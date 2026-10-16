"""MQTT-backed, read-only dashboard API."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, AsyncGenerator

import aiomqtt
import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import Auth, COOKIE_NAME, SESSION_SECONDS
from .dashboard import load_dashboard


CONFIG_PATH = Path(os.environ.get("RV_WEB_CONFIG", "config.yaml")).resolve()
settings = yaml.safe_load(CONFIG_PATH.read_text())
if not isinstance(settings, dict):
    raise ValueError("config.yaml must be a mapping")
dashboard_path = CONFIG_PATH.parent / settings.get("dashboard_file", "dashboard.yaml")
assets_dir = (CONFIG_PATH.parent / settings.get("assets_dir", "assets")).resolve()
dashboard, tab_topics = load_dashboard(dashboard_path, assets_dir)
dashboard_signature = dashboard_path.stat()
all_topics = set().union(*tab_topics.values())
stream_settings = settings.get("stream", {})
tick_hz = float(stream_settings.get("tick_hz", 12))
if tick_hz <= 0:
    raise ValueError("stream.tick_hz must be positive")
logging.basicConfig(level=settings.get("log_level", "INFO"))
logger = logging.getLogger(__name__)
auth = Auth(settings.get("auth"), CONFIG_PATH.parent)
if not auth.enabled:
    logger.warning("Authentication explicitly disabled: use only for local testing")
password_slots = asyncio.Semaphore(2)
values: dict[str, dict[str, Any]] = {}
clients: set["Viewer"] = set()
mqtt_connected = False


class Viewer:
    """Track the active tab and conflated pending updates for one browser."""

    def __init__(self, socket: WebSocket, token: str | None = None) -> None:
        """Initialize a disconnected viewer."""
        self.socket = socket
        self.tab: str | None = None
        self.pending: dict[str, dict[str, Any]] = {}
        self.send_lock = asyncio.Lock()
        self.token = token

    async def send(self, message: dict[str, Any]) -> None:
        """Serialize WebSocket sends from snapshot and ticker paths."""
        async with self.send_lock:
            if auth.enabled and auth.session(self.token) is None:
                await self.socket.close(code=4401)
                raise WebSocketDisconnect(code=4401)
            await self.socket.send_json(message)

    async def close(self) -> None:
        async with self.send_lock:
            await self.socket.close(code=4401)


async def receive_mqtt() -> None:
    """Reconnect to the broker and update the latest-value cache."""
    global mqtt_connected
    options = settings.get("mqtt", {})
    delay = 1
    while True:
        try:
            async with aiomqtt.Client(
                hostname=options.get("host", "127.0.0.1"),
                port=int(options.get("port", 1883)),
                username=options.get("username"),
                password=options.get("password"),
                identifier=options.get("client_id", "mqtt-dashboard"),
                keepalive=int(options.get("keepalive", 60)),
            ) as broker:
                mqtt_connected = True
                delay = 1
                for topic in sorted(all_topics):
                    await broker.subscribe(topic, qos=int(options.get("qos", 0)))
                async for message in broker.messages:
                    topic = str(message.topic)
                    if topic not in all_topics:
                        continue
                    try:
                        raw = bytes(message.payload).decode("utf-8")
                        payload = json.loads(raw)
                    except (UnicodeError, ValueError, TypeError):
                        logger.warning("Invalid MQTT JSON on %s", topic)
                        continue
                    if not isinstance(payload, dict):
                        payload = {"value": payload}
                    record = {"topic": topic, "payload": payload, "ts": time.time()}
                    values[topic] = record
                    for viewer in clients:
                        if viewer.tab and topic in tab_topics[viewer.tab]:
                            viewer.pending[topic] = record
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT unavailable: %s; retrying in %ss", exc, delay)
        finally:
            mqtt_connected = False
        await asyncio.sleep(delay)
        delay = min(delay * 2, 10)


async def flush_updates() -> None:
    """Send one conflated update batch per active viewer each tick."""
    while True:
        await asyncio.sleep(1 / tick_hz)
        for viewer in tuple(clients):
            if auth.enabled and auth.session(viewer.token) is None:
                clients.discard(viewer)
                try:
                    await viewer.close()
                except (WebSocketDisconnect, RuntimeError):
                    logger.debug("Expired viewer already disconnected")
                continue
            if viewer.pending:
                pending = list(viewer.pending.values())
                viewer.pending.clear()
                try:
                    await viewer.send({"type": "update", "values": pending})
                except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                    logger.info("Viewer send failed: %s", exc)
                    clients.discard(viewer)


async def watch_dashboard() -> None:
    """Reload valid dashboard edits and restart MQTT only when topics change."""
    global dashboard, tab_topics, all_topics, dashboard_signature
    mqtt_task = asyncio.create_task(receive_mqtt())
    previous_error = None
    try:
        while True:
            await asyncio.sleep(1)
            try:
                signature = dashboard_path.stat()
                if (signature.st_mtime_ns, signature.st_size, signature.st_ino) == (
                    dashboard_signature.st_mtime_ns,
                    dashboard_signature.st_size,
                    dashboard_signature.st_ino,
                ):
                    continue
                dashboard_signature = signature
                updated, updated_topics = load_dashboard(dashboard_path, assets_dir)
            except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
                message = f"Dashboard reload failed: {exc}. Keeping the last valid dashboard."
                if message == previous_error:
                    continue
                previous_error = message
                logger.error("%s", message)
                notification = {"type": "error", "code": "dashboard_reload", "message": message}
            else:
                previous_error = None
                topics = set().union(*updated_topics.values())
                changed_topics = topics != all_topics
                dashboard, tab_topics, all_topics = updated, updated_topics, topics
                for topic in list(values):
                    if topic not in all_topics:
                        del values[topic]
                for viewer in clients:
                    viewer.tab = None
                    viewer.pending.clear()
                if changed_topics:
                    mqtt_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await mqtt_task
                    mqtt_task = asyncio.create_task(receive_mqtt())
                logger.info("Reloaded dashboard from %s", dashboard_path)
                notification = {"type": "config", "config": {**dashboard, "stream": stream_settings}}
            for viewer in tuple(clients):
                try:
                    await viewer.send(notification)
                except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                    logger.info("Dashboard notification failed: %s", exc)
                    clients.discard(viewer)
    finally:
        mqtt_task.cancel()
        with suppress(asyncio.CancelledError):
            await mqtt_task


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Start and stop the broker listener and broadcast ticker."""
    tasks = [asyncio.create_task(watch_dashboard()), asyncio.create_task(flush_updates())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        clients.clear()
        auth.sessions.clear()


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def no_cache(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [(key, value) for key, value in headers if key.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        if auth.enabled and scope["type"] in {"http", "websocket"}:
            request = HTTPConnection(scope)
            path = scope["path"]
            if scope["type"] == "websocket":
                if request.headers.get("origin") not in auth.origins or auth.session(
                    request.cookies.get(COOKIE_NAME)
                ) is None:
                    await send({"type": "websocket.close", "code": 4401})
                    return
            elif (
                path == "/healthz" or path == "/assets" or path.startswith("/assets/")
                or path == "/api" or path.startswith("/api/")
            ) and path not in {"/api/auth/session", "/api/auth/login", "/api/auth/logout"}:
                if auth.session(request.cookies.get(COOKIE_NAME)) is None:
                    await JSONResponse(
                        {"detail": "Authentication required"}, status_code=401,
                        headers={"Cache-Control": "no-store"},
                    )(scope, receive, send)
                    return
        await self.app(scope, receive, no_cache if scope["type"] == "http" else send)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(AuthMiddleware)
app.mount("/assets", StaticFiles(directory=assets_dir, check_dir=False), name="assets")


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
    return JSONResponse({"detail": "Invalid request"}, status_code=422,
                        headers={"Cache-Control": "no-store"})


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


def check_origin(request: Request) -> None:
    if auth.enabled and request.headers.get("origin") not in auth.origins:
        raise HTTPException(status_code=403, detail="Request origin not allowed")


@app.get("/api/auth/session")
async def get_session(request: Request) -> JSONResponse:
    session = auth.session(request.cookies.get(COOKIE_NAME))
    return JSONResponse({
        "enabled": auth.enabled,
        "authenticated": not auth.enabled or session is not None,
        "username": session.username if session else None,
    }, headers={"Cache-Control": "no-store"})


@app.post("/api/auth/login")
async def login(credentials: Login, request: Request) -> JSONResponse:
    check_origin(request)
    if not auth.enabled:
        raise HTTPException(status_code=409, detail="Authentication is disabled")
    address = request.client.host if request.client else "unknown"
    if not auth.allow_attempt(address):
        raise HTTPException(status_code=429, detail="Too many login attempts; try again in a minute",
                            headers={"Retry-After": "60"})
    async with password_slots:
        valid = await asyncio.to_thread(auth.authenticate, credentials.username, credentials.password)
    if not valid:
        logger.warning("Login failed from %s", address)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth.revoke(request.cookies.get(COOKIE_NAME))
    token = auth.create_session(credentials.username)
    response = JSONResponse({"authenticated": True, "username": credentials.username},
                            headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=auth.secure_cookie, samesite="strict", path="/")
    return response


@app.post("/api/auth/logout")
async def logout(request: Request) -> Response:
    check_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    auth.revoke(token)
    for viewer in tuple(clients):
        if token is not None and viewer.token == token:
            clients.discard(viewer)
            try:
                await viewer.close()
            except (WebSocketDisconnect, RuntimeError):
                logger.debug("Logged-out viewer already disconnected")
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path="/", secure=auth.secure_cookie,
                           httponly=True, samesite="strict")
    return response


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    """Return the validated display tree and client timing settings."""
    return {**dashboard, "stream": stream_settings}


@app.get("/healthz")
async def health() -> dict[str, Any]:
    """Report broker state and resource counts."""
    return {"status": "ok" if mqtt_connected else "degraded", "mqtt_connected": mqtt_connected,
            "cached_topics": len(values), "connected_clients": len(clients)}


@app.websocket("/ws")
async def websocket(socket: WebSocket) -> None:
    """Deliver snapshots and active-tab updates to a browser."""
    await socket.accept()
    viewer = Viewer(socket, socket.cookies.get(COOKIE_NAME))
    clients.add(viewer)
    try:
        await viewer.send({"type": "config", "config": {**dashboard, "stream": stream_settings}})
        while True:
            if auth.enabled and auth.session(viewer.token) is None:
                await viewer.close()
                break
            try:
                message = await socket.receive_json()
            except ValueError:
                await viewer.send({"type": "error", "code": "invalid_message", "message": "Expected JSON."})
                continue
            if not isinstance(message, dict) or message.get("type") not in {"subscribe", "unsubscribe"}:
                await viewer.send({"type": "error", "code": "invalid_message", "message": "Expected subscribe or unsubscribe."})
                continue
            tab = message.get("tab")
            if tab not in tab_topics:
                await viewer.send({"type": "error", "code": "unknown_tab", "message": f"No tab with id {tab!r}."})
                continue
            if message["type"] == "unsubscribe":
                if viewer.tab == tab:
                    viewer.tab = None
                    viewer.pending.clear()
                continue
            viewer.tab = tab
            viewer.pending.clear()
            snapshot = [values[topic] for topic in sorted(tab_topics[tab]) if topic in values]
            await viewer.send({"type": "snapshot", "tab": tab, "values": snapshot})
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(viewer)


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")