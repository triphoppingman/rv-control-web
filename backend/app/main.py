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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .dashboard import load_dashboard


CONFIG_PATH = Path(os.environ.get("RV_WEB_CONFIG", "config.yaml")).resolve()
settings = yaml.safe_load(CONFIG_PATH.read_text())
if not isinstance(settings, dict):
    raise ValueError("config.yaml must be a mapping")
dashboard_path = CONFIG_PATH.parent / settings.get("dashboard_file", "dashboard.yaml")
assets_dir = (CONFIG_PATH.parent / settings.get("assets_dir", "assets")).resolve()
dashboard, tab_topics = load_dashboard(dashboard_path, assets_dir)
all_topics = set().union(*tab_topics.values())
stream_settings = settings.get("stream", {})
tick_hz = float(stream_settings.get("tick_hz", 12))
if tick_hz <= 0:
    raise ValueError("stream.tick_hz must be positive")
logging.basicConfig(level=settings.get("log_level", "INFO"))
logger = logging.getLogger(__name__)
values: dict[str, dict[str, Any]] = {}
clients: set["Viewer"] = set()
mqtt_connected = False


class Viewer:
    """Track the active tab and conflated pending updates for one browser."""

    def __init__(self, socket: WebSocket) -> None:
        """Initialize a disconnected viewer."""
        self.socket = socket
        self.tab: str | None = None
        self.pending: dict[str, dict[str, Any]] = {}
        self.send_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        """Serialize WebSocket sends from snapshot and ticker paths."""
        async with self.send_lock:
            await self.socket.send_json(message)


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
            if viewer.pending:
                pending = list(viewer.pending.values())
                viewer.pending.clear()
                try:
                    await viewer.send({"type": "update", "values": pending})
                except Exception:
                    clients.discard(viewer)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Start and stop the broker listener and broadcast ticker."""
    tasks = [asyncio.create_task(receive_mqtt()), asyncio.create_task(flush_updates())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        clients.clear()


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=assets_dir, check_dir=False), name="assets")


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
    viewer = Viewer(socket)
    clients.add(viewer)
    try:
        while True:
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