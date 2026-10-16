"""Dashboard file watching, validation, and viewer notification coverage."""

import asyncio
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import yaml

os.environ.setdefault("RV_WEB_CONFIG", str(Path(__file__).resolve().parents[2] / "config.test.yaml"))
from backend.app import main
from backend.app.auth import Auth
from backend.app.dashboard import load_dashboard


class DashboardReloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "dashboard.yaml"
        self.write_dashboard("power", "rv/old")
        dashboard, topics = load_dashboard(self.path, self.root)
        self.messages = asyncio.Queue()
        socket = AsyncMock()
        socket.send_json.side_effect = self.messages.put
        self.viewer = main.Viewer(socket)
        self.viewer.tab = "power"
        self.viewer.pending["rv/old"] = {"topic": "rv/old"}
        self.mqtt = AsyncMock(side_effect=self.wait_for_cancel)
        patches = {
            "dashboard_path": self.path,
            "dashboard_signature": self.path.stat(),
            "assets_dir": self.root,
            "dashboard": dashboard,
            "tab_topics": topics,
            "all_topics": {"rv/old"},
            "values": {"rv/old": {"topic": "rv/old"}},
            "clients": {self.viewer},
            "auth": Auth({"enabled": False}, self.root),
            "receive_mqtt": self.mqtt,
        }
        for name, value in patches.items():
            mock = patch.object(main, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.task = asyncio.create_task(main.watch_dashboard())

    async def asyncTearDown(self) -> None:
        self.task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.task

    async def wait_for_cancel(self) -> None:
        await asyncio.Event().wait()

    def write_dashboard(self, tab: str, topic: str, label: str = "Reading") -> None:
        self.path.write_text(yaml.safe_dump({
            "tabs": [{"id": tab, "root": {
                "type": "numeric", "label": label, "topic": topic, "payload_path": "value",
            }}],
        }))

    async def notification(self) -> dict:
        return await asyncio.wait_for(self.messages.get(), timeout=4)

    async def test_topic_and_tab_changes_update_config_and_restart_mqtt(self) -> None:
        self.write_dashboard("shore", "rv/new")
        message = await self.notification()
        await asyncio.sleep(0)
        self.assertEqual(message["type"], "config")
        self.assertEqual(message["config"]["tabs"][0]["id"], "shore")
        self.assertEqual(main.tab_topics, {"shore": {"rv/new"}})
        self.assertEqual(main.all_topics, {"rv/new"})
        self.assertEqual(main.values, {})
        self.assertIsNone(self.viewer.tab)
        self.assertEqual(self.viewer.pending, {})
        self.assertEqual(self.mqtt.await_count, 2)
        self.assertEqual((await main.get_config())["tabs"], message["config"]["tabs"])

    async def test_layout_only_edit_preserves_mqtt_and_cache(self) -> None:
        self.write_dashboard("power", "rv/old", "New label")
        message = await self.notification()
        self.assertEqual(message["config"]["tabs"][0]["root"]["label"], "New label")
        self.assertEqual(self.mqtt.await_count, 1)
        self.assertIn("rv/old", main.values)

    async def test_invalid_edit_keeps_dashboard_and_recovers_after_correction(self) -> None:
        self.path.write_text("tabs: [")
        with self.assertLogs(main.logger, level="ERROR"):
            message = await self.notification()
        self.assertEqual(message["code"], "dashboard_reload")
        self.assertEqual(main.dashboard["tabs"][0]["id"], "power")
        self.assertEqual(main.all_topics, {"rv/old"})
        self.assertEqual(self.viewer.tab, "power")
        self.assertEqual(self.mqtt.await_count, 1)
        self.write_dashboard("power", "rv/old", "Corrected")
        message = await self.notification()
        self.assertEqual(message["type"], "config")
        self.assertEqual(message["config"]["tabs"][0]["root"]["label"], "Corrected")

    async def test_atomic_file_replacement_is_detected(self) -> None:
        replacement = self.root / "replacement.yaml"
        replacement.write_text(yaml.safe_dump({
            "tabs": [{"id": "empty", "root": {"type": "text", "content": "Static"}}],
        }))
        replacement.replace(self.path)
        message = await self.notification()
        self.assertEqual(message["config"]["tabs"][0]["id"], "empty")
        self.assertEqual(main.all_topics, set())
