"""MQTT-backed dashboard API with opt-in Coach command controls."""

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import uuid4

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
from .dashboard import dashboard_controls, load_dashboard


CONFIG_PATH = Path(os.environ.get("RV_WEB_CONFIG", "config.yaml")).resolve()
settings = yaml.safe_load(CONFIG_PATH.read_text())
if not isinstance(settings, dict):
    raise ValueError("config.yaml must be a mapping")
dashboard_path = CONFIG_PATH.parent / settings.get("dashboard_file", "dashboard.yaml")
assets_dir = (CONFIG_PATH.parent / settings.get("assets_dir", "assets")).resolve()
dashboard, tab_topics = load_dashboard(dashboard_path, assets_dir)
tab_controls = dashboard_controls(dashboard)
dashboard_signature = dashboard_path.stat()
all_topics = set().union(*tab_topics.values())
stream_settings = settings.get("stream", {})
tick_hz = float(stream_settings.get("tick_hz", 12))
if tick_hz <= 0:
    raise ValueError("stream.tick_hz must be positive")
logging.basicConfig(level=settings.get("log_level", "INFO"))
logger = logging.getLogger(__name__)
auth = Auth(settings.get("auth"), CONFIG_PATH.parent)
mqtt_settings = settings.get("mqtt", {})
commands_enabled = mqtt_settings.get("commands_enabled", False)
if not isinstance(commands_enabled, bool):
    raise ValueError("mqtt.commands_enabled must be a boolean")
command_client_id = mqtt_settings.get("command_client_id", "rv-control-web")
if not isinstance(command_client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", command_client_id):
    raise ValueError("mqtt.command_client_id must match [A-Za-z0-9_-]{1,64}")
COMMAND_RESULT_TIMEOUT = 14
if not auth.enabled:
    logger.warning(
        "Authentication disabled: every viewer can use configured controls when MQTT commands are enabled; "
        "use only on a trusted local test network"
    )
password_slots = asyncio.Semaphore(2)
values: dict[str, dict[str, Any]] = {}
clients: set["Viewer"] = set()
mqtt_connected = False
mqtt_client: aiomqtt.Client | None = None
pending_command_results: dict[str, tuple[asyncio.Future[dict[str, Any]], dict[str, Any]]] = {}
active_command_id: str | None = None


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


def _resolve_command_result(
    topic: str,
    raw: bytes,
    pending: tuple[asyncio.Future[dict[str, Any]], dict[str, Any]],
    retained: bool,
) -> None:
    future, request = pending
    if retained:
        logger.warning("Ignoring retained MQTT command result on %s", topic)
        return
    if future.done():
        return
    if len(raw) > 8192:
        logger.warning("Oversized MQTT command result on %s", topic)
        return

    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded:
                raise ValueError(f"duplicate result field {key}")
            decoded[key] = value
        return decoded

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    except (UnicodeError, ValueError):
        logger.warning("Invalid MQTT command result on %s", topic)
        return
    if (
        not isinstance(result, dict) or type(result.get("version")) is not int
        or type(result.get("steps_completed")) is not int or result["steps_completed"] < 0
        or not isinstance(result.get("timestamp"), str)
        or any(
            result.get(field) != request[field]
            for field in ("version", "client_id", "request_id", "target", "action")
        )
    ):
        logger.warning("Uncorrelated MQTT command result on %s", topic)
        return
    status = result.get("status")
    if status == "accepted":
        return
    if status not in {"completed", "rejected", "failed"}:
        logger.warning("Invalid MQTT command status on %s", topic)
        return
    if any(
        not isinstance(result.get(field), str) or len(result[field]) > 512
        for field in ("code", "message", "outcome")
    ) or result["outcome"] not in {"not_started", "dispatched", "partial", "unknown"}:
        logger.warning("Invalid MQTT command result fields on %s", topic)
        return
    future.set_result(result)


def _control_result(
    action_id: str,
    control: dict[str, Any] | None,
    status: str,
    code: str,
    message: str,
    outcome: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "command_result",
        "action_id": action_id,
        "request_id": request_id,
        "target": control.get("target") if control else None,
        "action": control.get("action") if control else None,
        "status": status,
        "code": code,
        "message": message,
        "outcome": outcome,
    }


async def submit_control(viewer: Viewer, action_id: str, confirmed: bool) -> dict[str, Any]:
    """Publish one configured action and wait for its correlated result."""
    global active_command_id
    control = tab_controls.get(viewer.tab, {}).get(action_id) if viewer.tab else None
    if control is None:
        return _control_result(
            action_id, None, "rejected", "unknown_action", "This control is not available on the active tab.",
            "not_started",
        )
    if not commands_enabled:
        return _control_result(
            action_id, control, "rejected", "writes_disabled", "Light controls are disabled by server configuration.",
            "not_started",
        )
    if confirmed is not control["confirm"]:
        return _control_result(
            action_id, control, "rejected", "confirmation_required",
            "The confirmation state did not match this control.", "not_started",
        )
    if active_command_id is not None:
        return _control_result(
            action_id, control, "rejected", "busy", "Another Coach command is in progress.",
            "not_started",
        )
    broker = mqtt_client
    if not mqtt_connected or broker is None:
        return _control_result(
            action_id, control, "failed", "broker_unavailable",
            "MQTT is unavailable; no command was sent.", "not_started",
        )

    request_id = str(uuid4())
    issued = datetime.now(timezone.utc).replace(microsecond=0)
    expires = issued + timedelta(seconds=15)
    request = {
        "version": 1,
        "client_id": command_client_id,
        "request_id": request_id,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "target": control["target"],
        "action": control["action"],
        "params": control["params"],
        "confirmed": control["confirm"],
    }
    result_topic = f"rv/coach/result/{command_client_id}/{request_id}"
    future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    pending_command_results[result_topic] = (future, request)
    active_command_id = request_id
    publish_attempted = False
    try:
        await broker.subscribe(result_topic, qos=1)
        publish_attempted = True
        await broker.publish(
            "rv/coach/command", json.dumps(request, separators=(",", ":"), allow_nan=False),
            qos=1, retain=False,
        )
        result = await asyncio.wait_for(future, timeout=COMMAND_RESULT_TIMEOUT)
        logger.info(
            "Coach command result request_id=%s client_id=%s target=%s action=%s status=%s outcome=%s",
            request_id, command_client_id, control["target"], control["action"],
            result["status"], result["outcome"],
        )
        return _control_result(
            action_id, control, result["status"], result["code"], result["message"],
            result["outcome"], request_id,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Coach command result timeout request_id=%s client_id=%s target=%s action=%s",
            request_id, command_client_id, control["target"], control["action"],
        )
        return _control_result(
            action_id, control, "failed", "result_timeout",
            "No correlated result arrived. The action outcome is unknown; check live state before retrying.",
            "unknown", request_id,
        )
    except aiomqtt.MqttError as exc:
        logger.warning("Coach command MQTT failure request_id=%s: %s", request_id, exc)
        outcome = "unknown" if publish_attempted else "not_started"
        return _control_result(
            action_id, control, "failed", "mqtt_unavailable",
            "MQTT command delivery failed; check live state before retrying."
            if publish_attempted else "MQTT subscription failed; no command was sent.",
            outcome, request_id,
        )
    finally:
        pending_command_results.pop(result_topic, None)
        if not future.done():
            future.cancel()
        try:
            await broker.unsubscribe(result_topic)
        except (aiomqtt.MqttError, OSError, RuntimeError) as exc:
            logger.warning("Could not unsubscribe from command result topic: %s", exc)
        active_command_id = None


async def receive_mqtt() -> None:
    """Reconnect to the broker and update the latest-value cache."""
    global mqtt_client, mqtt_connected
    options = settings.get("mqtt", {})
    delay = 1
    while True:
        try:
            async with aiomqtt.Client(
                hostname=options.get("host", "127.0.0.1"),
                port=int(options.get("port", 1883)),
                username=options.get("username"),
                password=options.get("password"),
                identifier=options.get("client_id", "rv-control-web"),
                keepalive=int(options.get("keepalive", 60)),
                clean_session=True,
            ) as broker:
                mqtt_client = broker
                mqtt_connected = True
                delay = 1
                for topic in sorted(all_topics):
                    await broker.subscribe(topic, qos=int(options.get("qos", 0)))
                async for message in broker.messages:
                    topic = str(message.topic)
                    pending = pending_command_results.get(topic)
                    if pending is not None:
                        _resolve_command_result(
                            topic, bytes(message.payload), pending, bool(getattr(message, "retain", False))
                        )
                        continue
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
            mqtt_client = None
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
    global dashboard, tab_topics, tab_controls, all_topics, dashboard_signature
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
                updated_controls = dashboard_controls(updated)
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
                dashboard, tab_topics, tab_controls, all_topics = (
                    updated, updated_topics, updated_controls, topics
                )
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
                notification = {
                    "type": "config",
                    "config": {
                        **dashboard, "stream": stream_settings,
                        "command_controls_enabled": commands_enabled,
                    },
                }
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
    return {
        **dashboard, "stream": stream_settings,
        "command_controls_enabled": commands_enabled,
    }


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
        await viewer.send({
            "type": "config",
            "config": {
                **dashboard, "stream": stream_settings,
                "command_controls_enabled": commands_enabled,
            },
        })
        while True:
            if auth.enabled and auth.session(viewer.token) is None:
                await viewer.close()
                break
            try:
                message = await socket.receive_json()
            except ValueError:
                await viewer.send({"type": "error", "code": "invalid_message", "message": "Expected JSON."})
                continue
            if not isinstance(message, dict):
                await viewer.send({"type": "error", "code": "invalid_message", "message": "Expected a JSON object."})
                continue
            if message.get("type") == "command":
                action_id = message.get("action_id")
                confirmed = message.get("confirmed")
                if (
                    not isinstance(action_id, str) or len(action_id) > 64
                    or not isinstance(confirmed, bool)
                ):
                    await viewer.send({
                        "type": "error", "code": "invalid_message",
                        "message": "Command messages require an action_id and boolean confirmed value.",
                    })
                    continue
                await viewer.send(await submit_control(viewer, action_id, confirmed))
                continue
            if message.get("type") not in {"subscribe", "unsubscribe"}:
                await viewer.send({"type": "error", "code": "invalid_message", "message": "Expected subscribe, unsubscribe, or command."})
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