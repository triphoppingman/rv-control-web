"""Coverage for configured Coach action publishing and result correlation."""

import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml

os.environ.setdefault("RV_WEB_CONFIG", str(Path(__file__).resolve().parents[2] / "config.test.yaml"))
from backend.app import main
from backend.app.dashboard import dashboard_controls, load_dashboard


ORIGIN = "http://127.0.0.1:8000"


class DashboardControlTests(unittest.TestCase):
    def test_actions_are_generic_but_targets_are_bound_to_coach_entities(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            path.write_text(yaml.safe_dump({
                "tabs": [{"id": "coach", "root": {
                    "type": "light",
                    "topic": "rv/coach/entity/kitchen_light",
                    "payload_path": "state",
                    "controls": [{
                        "id": "kitchen_brightness_30",
                        "target": "kitchen_light",
                        "action": "brightness",
                        "label": "30%",
                        "params": {"level": 30},
                    }],
                }}],
            }))
            dashboard, _ = load_dashboard(path, root)
            action = dashboard_controls(dashboard)["coach"]["kitchen_brightness_30"]
            self.assertEqual(action["action"], "brightness")
            self.assertEqual(action["params"], {"level": 30})
            self.assertFalse(action["confirm"])

            dashboard["tabs"][0]["root"]["controls"][0]["target"] = "other_light"
            path.write_text(yaml.safe_dump(dashboard))
            with self.assertRaisesRegex(ValueError, "target must match"):
                load_dashboard(path, root)


class CommandPublishingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.control = {
            "id": "kitchen_light_toggle",
            "target": "kitchen_light",
            "action": "toggle",
            "label": "Toggle",
            "params": {},
            "confirm": False,
        }
        self.viewer = main.Viewer(AsyncMock(), token="session")
        self.viewer.tab = "coach"
        self.broker = AsyncMock()
        self.operations: list[str] = []

        async def subscribe(*_args: object, **_kwargs: object) -> None:
            self.operations.append("subscribe")

        async def publish(topic: str, payload: str, **options: object) -> None:
            self.operations.append("publish")
            request = json.loads(payload)
            result_topic = f"rv/coach/result/{request['client_id']}/{request['request_id']}"
            future, _ = main.pending_command_results[result_topic]
            future.set_result({
                "version": 1,
                "client_id": request["client_id"],
                "request_id": request["request_id"],
                "target": request["target"],
                "action": request["action"],
                "status": "completed",
                "code": "executed",
                "message": "Action dispatched; physical state is not confirmed.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "outcome": "dispatched",
                "steps_completed": 1,
            })

        self.broker.subscribe.side_effect = subscribe
        self.broker.publish.side_effect = publish
        patches = (
            patch.object(main, "mqtt_client", self.broker),
            patch.object(main, "mqtt_connected", True),
            patch.object(main, "commands_enabled", True),
            patch.object(main, "command_client_id", "rv-control-web"),
            patch.object(main, "tab_controls", {"coach": {self.control["id"]: self.control}}),
            patch.object(main, "pending_command_results", {}),
            patch.object(main, "active_command_id", None),
        )
        for mock in patches:
            mock.start()
            self.addCleanup(mock.stop)

    async def test_publishes_v1_qos_one_request_after_result_subscription(self) -> None:
        result = await main.submit_control(self.viewer, self.control["id"], False)

        self.assertEqual(result["type"], "command_result")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outcome"], "dispatched")
        self.assertEqual(self.operations, ["subscribe", "publish"])
        self.broker.subscribe.assert_awaited_once()
        self.broker.publish.assert_awaited_once()
        topic, payload = self.broker.publish.await_args.args[:2]
        self.assertEqual(topic, "rv/coach/command")
        self.assertEqual(self.broker.publish.await_args.kwargs, {"qos": 1, "retain": False})
        request = json.loads(payload)
        self.assertEqual(request["client_id"], "rv-control-web")
        self.assertEqual(request["target"], "kitchen_light")
        self.assertEqual(request["action"], "toggle")
        self.assertEqual(request["params"], {})
        self.assertFalse(request["confirmed"])
        self.assertLessEqual(
            datetime.fromisoformat(request["expires_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(request["issued_at"].replace("Z", "+00:00")),
            timedelta(seconds=15),
        )

    async def test_confirmation_mismatch_and_unknown_action_never_publish(self) -> None:
        self.control["confirm"] = True
        confirmed = await main.submit_control(self.viewer, self.control["id"], False)
        unknown = await main.submit_control(self.viewer, "unconfigured", False)

        self.assertEqual(confirmed["code"], "confirmation_required")
        self.assertEqual(unknown["code"], "unknown_action")
        self.broker.publish.assert_not_awaited()

    async def test_result_timeout_reports_unknown_without_retrying(self) -> None:
        self.broker.publish.side_effect = None
        with patch.object(main, "COMMAND_RESULT_TIMEOUT", 0.001):
            result = await main.submit_control(self.viewer, self.control["id"], False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["code"], "result_timeout")
        self.broker.publish.assert_awaited_once()
        self.broker.unsubscribe.assert_awaited_once()

    async def test_result_parser_rejects_bad_correlation_and_retained_results(self) -> None:
        request = {
            "version": 1, "client_id": "rv-control-web", "request_id": "req-1",
            "target": "kitchen_light", "action": "toggle",
        }
        future = asyncio.get_running_loop().create_future()
        pending = {"unused": (future, request)}
        result = {
            **request, "status": "completed", "code": "executed", "message": "Done",
            "timestamp": "2026-10-17T12:00:00Z", "outcome": "dispatched", "steps_completed": 1,
        }
        wrong = {**result, "request_id": "other"}
        main._resolve_command_result("unused", json.dumps(wrong).encode(), pending["unused"], False)
        main._resolve_command_result("unused", json.dumps(result).encode(), pending["unused"], True)
        self.assertFalse(future.done())
        main._resolve_command_result("unused", json.dumps(result).encode(), pending["unused"], False)
        self.assertEqual(future.result()["status"], "completed")


class CommandWebSocketTests(unittest.TestCase):
    def test_unauthenticated_browser_command_uses_dashboard_action_and_returns_result(self) -> None:
        control = {
            "id": "kitchen_light_toggle", "target": "kitchen_light", "action": "toggle",
            "label": "Toggle", "params": {}, "confirm": False,
        }
        broker = AsyncMock()

        async def publish(_topic: str, payload: str, **_options: object) -> None:
            request = json.loads(payload)
            result_topic = f"rv/coach/result/{request['client_id']}/{request['request_id']}"
            future, _ = main.pending_command_results[result_topic]
            future.set_result({
                "version": 1, "client_id": request["client_id"],
                "request_id": request["request_id"], "target": request["target"],
                "action": request["action"], "status": "completed", "code": "executed",
                "message": "Action dispatched.", "timestamp": "2026-10-17T12:00:00Z",
                "outcome": "dispatched", "steps_completed": 1,
            })

        broker.publish.side_effect = publish
        auth = SimpleNamespace(
            enabled=False, origins=set(), sessions={}, session=lambda _token: None,
        )

        async def no_background_task() -> None:
            return

        with (
            patch.object(main, "auth", auth),
            patch.object(main, "watch_dashboard", no_background_task),
            patch.object(main, "flush_updates", no_background_task),
            patch.object(main, "commands_enabled", True),
            patch.object(main, "command_client_id", "rv-control-web"),
            patch.object(main, "mqtt_client", broker),
            patch.object(main, "mqtt_connected", True),
            patch.object(main, "tab_topics", {"coach": {"rv/coach/entity/kitchen_light"}}),
            patch.object(main, "tab_controls", {"coach": {control["id"]: control}}),
            patch.object(main, "pending_command_results", {}),
            patch.object(main, "active_command_id", None),
        ):
            from fastapi.testclient import TestClient

            with TestClient(main.app, base_url=ORIGIN) as client:
                with client.websocket_connect("/ws") as socket:
                    self.assertEqual(socket.receive_json()["type"], "config")
                    socket.send_json({"type": "subscribe", "tab": "coach"})
                    self.assertEqual(socket.receive_json()["type"], "snapshot")
                    socket.send_json({
                        "type": "command", "action_id": "kitchen_light_toggle",
                        "confirmed": False,
                    })
                    result = socket.receive_json()

        self.assertEqual(result["type"], "command_result")
        self.assertEqual(result["target"], "kitchen_light")
        self.assertEqual(result["action"], "toggle")
        broker.publish.assert_awaited_once()
