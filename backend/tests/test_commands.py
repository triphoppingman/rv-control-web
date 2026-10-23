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
    def test_wled_form_configuration_rejects_invalid_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            field = {"param": "preset_id", "label": "Preset ID", "min": 1, "max": 250, "step": 1}
            control = {
                "id": "preset", "target": "strip", "action": "preset",
                "input": {"type": "form", "fields": [field]},
            }
            data = {"tabs": [{"id": "lighting", "root": {
                "type": "wled", "entity": "strip", "topic": "rv/wled/strip", "controls": [control],
            }}]}
            path.write_text(yaml.safe_dump(data))
            load_dashboard(path, root)
            for fields in ([], [field, field], [{**field, "step": 0}],
                           [{**field, "max": float("inf")}], [{**field, "param": "bad/name"}],
                           [{**field, "label": ""}], [{**field, "extra": True}]):
                control["input"]["fields"] = fields
                path.write_text(yaml.safe_dump(data))
                with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, "form"):
                    load_dashboard(path, root)
            control["input"]["fields"] = [field]
            control["params"] = {"preset_id": 1}
            path.write_text(yaml.safe_dump(data))
            with self.assertRaisesRegex(ValueError, "unique params"):
                load_dashboard(path, root)

    def test_wled_controls_bind_to_an_explicit_entity_not_the_raw_topic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            widget = {
                "type": "wled", "topic": "rv/wled/another-strip", "entity": "another_light",
                "controls": [{
                    "id": "strip_on", "target": "another_light", "action": "on",
                }],
            }
            data = {"tabs": [{"id": "lighting", "root": widget}]}
            path.write_text(yaml.safe_dump(data))
            loaded, topics = load_dashboard(path, root)
            self.assertEqual(topics["lighting"], {"rv/wled/another-strip"})
            self.assertEqual(
                dashboard_controls(loaded)["lighting"]["strip_on"]["target"], "another_light",
            )
            widget["controls"][0]["target"] = "other_light"
            path.write_text(yaml.safe_dump(data))
            with self.assertRaisesRegex(ValueError, "target must match"):
                load_dashboard(path, root)
            del widget["entity"]
            path.write_text(yaml.safe_dump(data))
            with self.assertRaisesRegex(ValueError, "require an entity binding"):
                load_dashboard(path, root)
            del widget["controls"]
            path.write_text(yaml.safe_dump(data))
            load_dashboard(path, root)
            for entity in ("", "bad/entity", 123, None):
                widget["entity"] = entity
                path.write_text(yaml.safe_dump(data))
                with self.subTest(entity=entity), self.assertRaisesRegex(ValueError, "entity must"):
                    load_dashboard(path, root)

    def test_front_and_rear_climate_controls_match_coach_actions(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for filename in ("dashboard.yaml", "dashboard.example.yaml"):
            dashboard, topics = load_dashboard(root / filename, root)
            controls = dashboard_controls(dashboard)["coach"]
            self.assertIn("rv/coach/entity/front_ac", topics["coach"])
            self.assertIn("rv/coach/entity/rear_ac", topics["coach"])
            self.assertEqual(
                {action for action in ("cool", "heat", "off", "fan_auto", "fan_high", "fan_low",
                                       "setpoint_down", "setpoint_up")
                 if f"front_ac_{action}" in controls},
                {"cool", "heat", "off", "fan_auto", "fan_high", "fan_low",
                 "setpoint_down", "setpoint_up"},
            )
            self.assertEqual(
                {action for action in ("cool", "heat", "off", "fan_auto", "fan_high", "fan_low",
                                       "setpoint_down", "setpoint_up")
                 if f"rear_ac_{action}" in controls},
                {"cool", "off", "fan_high", "fan_low", "setpoint_down", "setpoint_up"},
            )

    def test_generator_controls_require_confirmation_and_target_generator(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dashboard, _ = load_dashboard(root / "dashboard.yaml", root)
        controls = dashboard_controls(dashboard)["coach"]

        start = controls["generator_start"]
        stop = controls["generator_stop"]
        self.assertEqual((start["target"], start["action"], start["confirm"]),
                         ("generator", "start", True))
        self.assertEqual((stop["target"], stop["action"], stop["confirm"]),
                         ("generator", "stop", True))

    def test_fan_controls_match_coach_actions(self) -> None:
        root = Path(__file__).resolve().parents[2]
        expected = {
            "kitchen_fan": {
                ("kitchen_fan", "on"), ("kitchen_fan", "off"),
                ("kitchen_fan_lid", "open"), ("kitchen_fan_lid", "close"),
            },
            "mid_bath_fan": {("mid_bath_fan", "on"), ("mid_bath_fan", "off")},
            "rear_bath_fan": {("rear_bath_fan", "on"), ("rear_bath_fan", "off")},
        }
        for filename in ("dashboard.yaml", "dashboard.example.yaml"):
            dashboard, topics = load_dashboard(root / filename, root)
            controls = dashboard_controls(dashboard)["coach"]
            for fan, actions in expected.items():
                with self.subTest(filename=filename, fan=fan):
                    self.assertIn(f"rv/coach/entity/{fan}", topics["coach"])
                    actual = {
                        (control["target"], control["action"])
                        for control in controls.values()
                        if control["id"].startswith(f"{fan}_")
                    }
                    self.assertEqual(actual, actions)
            for action in ("raise", "lower"):
                with self.subTest(filename=filename, lid_action=action):
                    self.assertTrue(controls[f"kitchen_fan_lid_{action}"]["confirm"])
            for fan in expected:
                for action in ("start", "stop"):
                    self.assertFalse(controls[f"{fan}_{action}"]["confirm"])

    def test_fan_controls_can_target_only_its_configured_lid_entity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            fan = {
                "type": "fan",
                "topic": "rv/coach/entity/kitchen_fan",
                "payload_path": "state",
                "lid_topic": "rv/coach/entity/kitchen_fan_lid",
                "lid_payload_path": "state",
                "controls": [{
                    "id": "kitchen_fan_lid_raise",
                    "target": "kitchen_fan_lid",
                    "action": "open",
                    "label": "Raise lid",
                }],
            }
            path.write_text(yaml.safe_dump({"tabs": [{"id": "coach", "root": fan}]}))
            dashboard, _ = load_dashboard(path, root)
            self.assertEqual(
                dashboard_controls(dashboard)["coach"]["kitchen_fan_lid_raise"]["target"],
                "kitchen_fan_lid",
            )

            fan["controls"][0]["target"] = "rear_bath_fan"
            path.write_text(yaml.safe_dump({"tabs": [{"id": "coach", "root": fan}]}))
            with self.assertRaisesRegex(ValueError, "target must match"):
                load_dashboard(path, root)

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

    def test_slider_input_requires_a_finite_range_and_step(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            dashboard = {"tabs": [{"id": "coach", "root": {
                "type": "light",
                "topic": "rv/coach/entity/living_ceiling_light",
                "payload_path": "state",
                "controls": [{
                    "id": "living_ceiling_brightness",
                    "target": "living_ceiling_light",
                    "action": "brightness",
                    "input": {
                        "type": "slider", "param": "level", "value_field": "level",
                        "min": 0, "max": 100, "step": 1, "unit": "%",
                    },
                }],
            }}]}
            path.write_text(yaml.safe_dump(dashboard))
            loaded, _ = load_dashboard(path, root)
            action = dashboard_controls(loaded)["coach"]["living_ceiling_brightness"]
            self.assertEqual(action["input"]["param"], "level")
            self.assertEqual(action["input"]["value_field"], "level")

            dashboard["tabs"][0]["root"]["controls"][0]["input"]["step"] = 0
            path.write_text(yaml.safe_dump(dashboard))
            with self.assertRaisesRegex(ValueError, "input must define a valid slider"):
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

    async def test_kitchen_lid_controls_publish_only_after_confirmation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for filename in ("dashboard.yaml", "dashboard.example.yaml"):
            dashboard, _ = load_dashboard(root / filename, root)
            controls = dashboard_controls(dashboard)["coach"]
            with patch.object(main, "tab_controls", {"coach": controls}):
                for action, command in (("raise", "open"), ("lower", "close")):
                    with self.subTest(filename=filename, action=action):
                        self.broker.publish.reset_mock()
                        action_id = f"kitchen_fan_lid_{action}"
                        rejected = await main.submit_control(self.viewer, action_id, False)
                        self.assertEqual(rejected["code"], "confirmation_required")
                        self.broker.publish.assert_not_awaited()

                        result = await main.submit_control(self.viewer, action_id, True)
                        self.assertEqual(result["status"], "completed")
                        self.broker.publish.assert_awaited_once()
                        request = json.loads(self.broker.publish.await_args.args[1])
                        self.assertEqual(request["target"], "kitchen_fan_lid")
                        self.assertEqual(request["action"], command)
                        self.assertTrue(request["confirmed"])

    async def test_result_timeout_reports_unknown_without_retrying(self) -> None:
        self.broker.publish.side_effect = None
        with patch.object(main, "COMMAND_RESULT_TIMEOUT", 0.001):
            result = await main.submit_control(self.viewer, self.control["id"], False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["code"], "result_timeout")
        self.broker.publish.assert_awaited_once()
        self.broker.unsubscribe.assert_awaited_once()

    async def test_slider_value_is_sent_as_the_configured_action_parameter(self) -> None:
        self.control["input"] = {
            "type": "slider", "param": "level", "min": 0, "max": 100, "step": 1,
        }
        result = await main.submit_control(self.viewer, self.control["id"], False, 37)

        self.assertEqual(result["status"], "completed")
        request = json.loads(self.broker.publish.await_args.args[1])
        self.assertEqual(request["params"], {"level": 37})

    async def test_wled_actions_publish_to_the_configured_entity_with_native_brightness(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dashboard, _ = load_dashboard(root / "dashboard.example.yaml", root)
        controls = dashboard_controls(dashboard)["lighting"]
        with patch.object(main, "tab_controls", {"coach": controls}):
            for action in ("toggle", "on", "off", "brightness"):
                for value in ((0, 128, 255) if action == "brightness" else (None,)):
                    with self.subTest(action=action, value=value):
                        result = await main.submit_control(
                            self.viewer, f"wled_patio_{action}", False, value,
                        )
                        self.assertEqual(result["status"], "completed")
                        request = json.loads(self.broker.publish.await_args.args[1])
                        self.assertEqual(request["target"], "patio_light")
                        self.assertEqual(request["action"], action)
                        self.assertEqual(request["params"], {} if value is None else {"bri": value})
            self.broker.publish.reset_mock()
            for value in (-1, 256, 1.5, True, None):
                result = await main.submit_control(
                    self.viewer, "wled_patio_brightness", False, value,
                )
                self.assertEqual(result["code"], "invalid_params")
            self.broker.publish.assert_not_awaited()

    async def test_wled_forms_publish_typed_parameters_and_reject_invalid_values(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dashboard, _ = load_dashboard(root / "dashboard.example.yaml", root)
        controls = dashboard_controls(dashboard)["lighting"]
        expected = {
            "color": {"segment": 2, "red": 255, "green": 80, "blue": 20},
            "effect": {"segment": 2, "effect_id": 12},
            "palette": {"segment": 2, "palette_id": 5},
            "transition": {"duration": 10},
            "preset": {"preset_id": 1},
        }
        with patch.object(main, "tab_controls", {"coach": controls}):
            for action, params in expected.items():
                action_id = f"wled_patio_{action}"
                fields = controls[action_id]["input"]["fields"]
                for submitted in (
                    params, {field["param"]: field["min"] for field in fields},
                    {field["param"]: field["max"] for field in fields},
                ):
                    result = await main.submit_control(self.viewer, action_id, False, submitted)
                    self.assertEqual(result["status"], "completed")
                    request = json.loads(self.broker.publish.await_args.args[1])
                    self.assertEqual((request["target"], request["action"]), ("patio_light", action))
                    self.assertEqual(request["params"], submitted)
                self.broker.publish.reset_mock()
                invalid_values = [None, 1, [], {}, {**params, "extra": 1}]
                for field in fields:
                    for invalid in (
                        field["min"] - 1, field["max"] + 1, field["min"] + 0.5,
                        True, "1", None, {}, float("nan"), float("inf"),
                    ):
                        invalid_values.append({**params, field["param"]: invalid})
                for submitted in invalid_values:
                    with self.subTest(action=action, submitted=submitted):
                        result = await main.submit_control(self.viewer, action_id, False, submitted)
                        self.assertEqual(result["code"], "invalid_params")
                self.broker.publish.assert_not_awaited()

    async def test_slider_rejects_values_outside_range_or_off_step(self) -> None:
        self.control["input"] = {
            "type": "slider", "param": "level", "min": 0, "max": 100, "step": 5,
        }
        outside_range = await main.submit_control(self.viewer, self.control["id"], False, 102)
        off_step = await main.submit_control(self.viewer, self.control["id"], False, 37)

        self.assertEqual(outside_range["code"], "invalid_params")
        self.assertEqual(off_step["code"], "invalid_params")
        self.broker.publish.assert_not_awaited()

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


class RefreshResultParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_result_size_limit_allows_query_payloads_over_action_limit(self) -> None:
        request = {
            "version": 1, "client_id": "rv-control-web", "request_id": "req-1",
            "target": "coach", "action": "refresh_states",
        }
        future = asyncio.get_running_loop().create_future()
        result = {
            **request, "status": "completed", "code": "partial", "message": "Refreshed",
            "timestamp": "2026-10-17T12:00:00Z", "outcome": "not_started",
            "steps_completed": 0, "data": {"entities": [{"entity": "fan"}]},
        }
        raw = json.dumps({**result, "data": {"padding": "x" * 9000}}).encode()
        main._resolve_command_result(
            "rv/coach/result/rv-control-web/req-1", raw, (future, request), False,
        )
        self.assertTrue(future.done())
        self.assertEqual(future.result()["code"], "partial")


class RefreshStatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_publishes_all_active_tab_coach_entities(self) -> None:
        viewer = main.Viewer(AsyncMock())
        viewer.tab = "coach"
        broker = AsyncMock()
        operations: list[str] = []
        topics = {
            "rv/coach/entity/kitchen_fan",
            "rv/coach/entity/kitchen_fan_lid",
            "rv/coach/entity/rear_bath_fan",
            "rv/renogy",
        }

        async def subscribe(*_args: object, **_kwargs: object) -> None:
            operations.append("subscribe")

        async def publish(topic: str, payload: str, **_options: object) -> None:
            operations.append("publish")
            request = json.loads(payload)
            self.assertEqual(topic, "rv/coach/query")
            result_topic = f"rv/coach/result/{request['client_id']}/{request['request_id']}"
            future, _ = main.pending_command_results[result_topic]
            future.set_result({
                "version": 1, "client_id": request["client_id"],
                "request_id": request["request_id"], "target": "coach",
                "action": "refresh_states", "status": "completed", "code": "observed",
                "message": "Fresh state observed.", "timestamp": datetime.now(timezone.utc).isoformat(),
                "outcome": "not_started", "steps_completed": 0,
                "data": {"entities": [{"entity": "kitchen_fan", "status": "observed"}]},
            })

        broker.subscribe.side_effect = subscribe
        broker.publish.side_effect = publish
        with (
            patch.object(main, "mqtt_client", broker),
            patch.object(main, "mqtt_connected", True),
            patch.object(main, "queries_enabled", True),
            patch.object(main, "command_client_id", "rv-control-web"),
            patch.object(main, "tab_topics", {"coach": topics}),
            patch.object(main, "dashboard", {"tabs": [{
                "id": "coach",
                "root": {
                    "type": "flow",
                    "children": [
                        {"type": "fan", "topic": "rv/coach/entity/kitchen_fan",
                         "lid_topic": "rv/coach/entity/kitchen_fan_lid"},
                        {"type": "fan", "topic": "rv/coach/entity/rear_bath_fan"},
                        {"type": "light", "topic": "rv/coach/entity/patio_light",
                         "refreshable": False},
                    ],
                },
            }]}),
            patch.object(main, "pending_command_results", {}),
            patch.object(main, "active_command_id", None),
        ):
            result = await main.refresh_tab_states(viewer)

        self.assertEqual(operations, ["subscribe", "publish"])
        request = json.loads(broker.publish.await_args.args[1])
        self.assertEqual(request["target"], "coach")
        self.assertEqual(request["action"], "refresh_states")
        self.assertEqual(request["params"], {
            "entities": ["kitchen_fan", "kitchen_fan_lid", "rear_bath_fan"],
            "timeout_s": 5,
        })
        self.assertFalse(request["confirmed"])
        self.assertEqual(broker.publish.await_args.kwargs, {"qos": 1, "retain": False})
        self.assertEqual(result["type"], "refresh_result")
        self.assertEqual(result["code"], "observed")
        self.assertEqual(result["data"]["entities"][0]["status"], "observed")

    async def test_refresh_is_disabled_by_default_and_does_not_publish(self) -> None:
        viewer = main.Viewer(AsyncMock())
        viewer.tab = "coach"
        broker = AsyncMock()
        with (
            patch.object(main, "mqtt_client", broker),
            patch.object(main, "mqtt_connected", True),
            patch.object(main, "queries_enabled", False),
            patch.object(main, "tab_topics", {"coach": {"rv/coach/entity/kitchen_fan"}}),
        ):
            result = await main.refresh_tab_states(viewer)
        self.assertEqual(result["code"], "queries_disabled")
        broker.publish.assert_not_awaited()


class CommandWebSocketTests(unittest.TestCase):
    def test_unauthenticated_browser_command_uses_dashboard_action_and_returns_result(self) -> None:
        control = {
            "id": "living_ceiling_light_brightness", "target": "living_ceiling_light",
            "action": "brightness", "label": "Brightness", "params": {}, "confirm": False,
            "input": {"type": "slider", "param": "level", "min": 0, "max": 100, "step": 1},
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
            patch.object(main, "queries_enabled", True),
            patch.object(main, "command_client_id", "rv-control-web"),
            patch.object(main, "mqtt_client", broker),
            patch.object(main, "mqtt_connected", True),
            patch.object(main, "tab_topics", {"coach": {"rv/coach/entity/living_ceiling_light"}}),
            patch.object(main, "tab_controls", {"coach": {control["id"]: control}}),
            patch.object(main, "pending_command_results", {}),
            patch.object(main, "active_command_id", None),
        ):
            from fastapi.testclient import TestClient

            with TestClient(main.app, base_url=ORIGIN) as client:
                with client.websocket_connect("/ws") as socket:
                    config = socket.receive_json()
                    self.assertEqual(config["type"], "config")
                    self.assertTrue(config["config"]["query_controls_enabled"])
                    socket.send_json({"type": "subscribe", "tab": "coach"})
                    self.assertEqual(socket.receive_json()["type"], "snapshot")
                    socket.send_json({
                        "type": "command", "action_id": "living_ceiling_light_brightness",
                        "confirmed": False, "value": 37,
                    })
                    result = socket.receive_json()

        self.assertEqual(result["type"], "command_result")
        self.assertEqual(result["target"], "living_ceiling_light")
        self.assertEqual(result["action"], "brightness")
        request = json.loads(broker.publish.await_args.args[1])
        self.assertEqual(request["params"], {"level": 37})
        broker.publish.assert_awaited_once()
