"""Tests for configurable dashboard-driven fake MQTT telemetry."""

import asyncio
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml

from backend.app.fake_mqtt import (
    FanActionSimulator,
    TopicScenario,
    consume_simulated_commands,
    load_scenarios,
    main,
    publish_forever,
    render_payload,
    sample_payloads,
    validate_template,
)
from backend.app.check_dashboard import calculate_derived, iter_nodes, validate_samples
from backend.app.dashboard import load_dashboard


REPOSITORY = Path(__file__).resolve().parents[2]


class FakeMqttTests(unittest.TestCase):
    def test_fan_action_simulator_updates_fan_and_lid_telemetry(self) -> None:
        simulator = FanActionSimulator()
        initial = simulator.payloads(0)
        self.assertFalse(initial["rv/coach/entity/kitchen_fan"]["state"]["on"])
        self.assertEqual(
            initial["rv/coach/entity/kitchen_fan_lid"]["state"],
            {"open_active": False, "close_active": False},
        )

        request = {
            "version": 1, "client_id": "rv-control-web", "request_id": "req-1",
            "target": "kitchen_fan", "action": "on",
        }
        result, topic = simulator.handle(request, 1)
        self.assertEqual(topic, "rv/coach/entity/kitchen_fan")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(simulator.payloads(1)[topic]["state"], {"on": True})

        request.update(request_id="req-2", target="kitchen_fan_lid", action="open")
        result, topic = simulator.handle(request, 2)
        self.assertEqual(topic, "rv/coach/entity/kitchen_fan_lid")
        self.assertEqual(result["outcome"], "dispatched")
        self.assertEqual(
            simulator.payloads(3)[topic]["state"],
            {"open_active": True, "close_active": False, "open_remaining": 14},
        )
        self.assertEqual(
            simulator.payloads(18)[topic]["state"],
            {"open_active": False, "close_active": False},
        )

        request.update(request_id="req-3", target="front_ac", action="cool")
        result, topic = simulator.handle(request, 19)
        self.assertIsNone(topic)
        self.assertEqual(result["status"], "rejected")

    def test_fan_action_simulator_ignores_malformed_requests(self) -> None:
        simulator = FanActionSimulator()
        self.assertEqual(simulator.handle({"version": 1}, 0), (None, None))

    def test_tank_scenario_generates_independent_discrete_levels(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_path = root / "dashboard.yaml"
            dashboard_path.write_text(yaml.safe_dump({
                "tabs": [{"id": "tanks", "root": {
                    "type": "flow",
                    "children": [
                        {"type": "tank", "label": label, "topic": "rv/tanks",
                         "payload_path": field, "min": 0, "max": 3, "segments": 3}
                        for label, field in (
                            ("Fresh water", "fresh_level"),
                            ("Gray water", "gray_level"),
                            ("Black water", "black_level"),
                        )
                    ],
                }}],
            }))
            config = root / "config.yaml"
            config.write_text("dashboard_file: dashboard.yaml\n")
            scenarios = load_scenarios(REPOSITORY / "fake-mqtt.example.yaml", config)
            dashboard, _ = load_dashboard(dashboard_path, root)
            self.assertEqual(set(scenarios), {"rv/tanks"})
            self.assertEqual(scenarios["rv/tanks"].interval_s, 2)
            self.assertTrue(scenarios["rv/tanks"].retain)
            expected = {
                0: (3, 0, 0), 10: (2, 0, 0), 15: (2, 1, 0),
                20: (1, 1, 1), 30: (0, 2, 1), 40: (3, 2, 2),
                60: (1, 0, 3), 80: (3, 1, 0),
            }
            for elapsed, levels in expected.items():
                with self.subTest(elapsed=elapsed):
                    samples = sample_payloads(scenarios, elapsed)
                    self.assertEqual(tuple(samples["rv/tanks"].values()), levels)
                    self.assertTrue(all(type(value) is int for value in samples["rv/tanks"].values()))
                    self.assertEqual(validate_samples(dashboard, samples, {"rv/tanks"}), [])
            output = StringIO()
            with redirect_stdout(output), patch("backend.app.fake_mqtt.aiomqtt.Client") as client:
                main(["--scenario", str(REPOSITORY / "fake-mqtt.example.yaml"),
                      "--dashboard-config", str(config), "--check"])
            client.assert_not_called()
            self.assertEqual(json.loads(output.getvalue()), sample_payloads(scenarios))

    def test_tank_scenario_rejects_invalid_later_sequence_values(self) -> None:
        for invalid in ("full", None, True):
            with self.subTest(invalid=invalid), TemporaryDirectory() as directory:
                paths = self.make_config(Path(directory), {
                    "sensors": [{"value": {
                        "generator": "sequence", "values": [0, invalid], "hold_s": 10,
                    }}],
                }, node_type="tank")
                with self.assertRaisesRegex(ValueError, "invalid binding values"):
                    load_scenarios(*paths)

    def test_obd_example_matches_active_pid_payload(self) -> None:
        dashboard, tab_topics = load_dashboard(
            REPOSITORY / "dashboard.example.yaml", REPOSITORY / "assets"
        )
        self.assertEqual(tab_topics["obd2"], {"rv/obd"})
        obd = next(tab for tab in dashboard["tabs"] if tab["id"] == "obd2")
        nodes = [node for node, _ in iter_nodes(obd["root"], "root")]
        self.assertEqual(
            {node["payload_path"] for node in nodes if "payload_path" in node},
            {"rpm", "coolant_temp", "tft", "baro", "load", "iat",
             "speed", "fuel", "volt", "gear", "ambient", "tcc"},
        )
        payload = {
            "rpm": 600.0, "coolant_temp": 174.2, "tft": 170.9375,
            "baro": 0.98, "load": 10.588235, "iat": 31, "speed": 0.0,
            "fuel": 89.41248, "volt": 14.76, "gear": 1, "ambient": 24, "tcc": 70,
        }
        self.assertEqual(
            validate_samples({"tabs": [obd]}, {"rv/obd": payload}, {"rv/obd"}), []
        )
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(yaml.safe_dump({
                "dashboard_file": str(REPOSITORY / "dashboard.example.yaml"),
                "assets_dir": str(REPOSITORY / "assets"),
            }))
            samples = sample_payloads(load_scenarios(
                REPOSITORY / "fake-mqtt.example.yaml", config
            ))
        self.assertEqual(
            validate_samples(dashboard, samples, set().union(*tab_topics.values())), []
        )

    def test_example_scenario_selects_only_dashboard_topics(self) -> None:
        scenarios = load_scenarios(
            REPOSITORY / "fake-mqtt.example.yaml", REPOSITORY / "config.test.yaml"
        )
        self.assertEqual(
            set(scenarios),
            {"rv/renogy", "rv/hughes", "rv/gpsd/TPV", "rv/gpsd/SKY", "rv/obd"},
        )
        first = sample_payloads(scenarios)
        later = sample_payloads(scenarios, 30)
        self.assertEqual(first["rv/renogy"]["battery_percentage"], 72)
        self.assertEqual(later["rv/renogy"]["battery_percentage"], 80)
        self.assertEqual(later["rv/renogy"]["charging_status"], "idle")

    def test_action_mode_allows_dashboard_topics_without_telemetry_scenarios(self) -> None:
        scenarios = load_scenarios(
            REPOSITORY / "fake-mqtt.example.yaml",
            REPOSITORY / "config.test.yaml",
            allow_missing_topics=True,
        )
        self.assertTrue(scenarios)
        self.assertTrue(all(topic in scenarios for topic in (
            "rv/renogy", "rv/hughes", "rv/obd",
        )))

    def test_generators_follow_elapsed_time_and_wrap(self) -> None:
        ramp = {"generator": "ramp", "min": 0, "max": 10, "period_s": 20, "decimals": 0}
        self.assertEqual(render_payload(ramp, 10), 5)
        self.assertEqual(render_payload(ramp, 20), 0)
        self.assertIsInstance(render_payload(ramp, 10), int)
        sequence = {"generator": "sequence", "values": [True, False], "hold_s": 5}
        self.assertIs(render_payload(sequence, 0), True)
        self.assertIs(render_payload(sequence, 5), False)
        self.assertIs(render_payload(sequence, 10), True)

    def test_nested_payloads_and_arrays_preserve_static_fields(self) -> None:
        template = {"sensors": [{"temp": {"generator": "sequence", "values": [20, 21], "hold_s": 2}}],
                    "name": "Demo", "on": True}
        self.assertEqual(
            render_payload(template, 2),
            {"sensors": [{"temp": 21}], "name": "Demo", "on": True},
        )

    def test_shared_sample_checker_evaluates_generated_product_inputs(self) -> None:
        payload = render_payload(
            {"voltage": 12, "current": {"generator": "sequence", "values": [2, 3], "hold_s": 1}},
            1,
        )
        self.assertEqual(calculate_derived("product", [payload["voltage"], payload["current"]]), 36)

    def make_config(self, root: Path, payload: object, node_type: str = "gauge") -> tuple[Path, Path]:
        (root / "config.yaml").write_text("dashboard_file: dashboard.yaml\n")
        (root / "dashboard.yaml").write_text(yaml.safe_dump({
            "tabs": [{"id": "test", "root": {"type": node_type, "topic": "custom/sensor",
                                         "payload_path": "sensors[0].value"}}],
        }))
        (root / "scenario.yaml").write_text(yaml.safe_dump({
            "interval_s": 1,
            "topics": {"custom/sensor": {"payload": payload, "interval_s": 0.25, "qos": 1, "retain": False}},
        }))
        return root / "scenario.yaml", root / "config.yaml"

    def test_custom_dashboard_topics_and_characteristics_are_not_hardcoded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_config(root, {"sensors": [{"value": 12}]})
            scenarios = load_scenarios(*paths)
            self.assertEqual(set(scenarios), {"custom/sensor"})
            self.assertEqual(scenarios["custom/sensor"].interval_s, 0.25)
            self.assertEqual(scenarios["custom/sensor"].qos, 1)
            self.assertFalse(scenarios["custom/sensor"].retain)

    def test_missing_topics_and_paths_fail_before_connecting(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_config(root, {"wrong_field": 10})
            with self.assertRaisesRegex(ValueError, "has no value"):
                load_scenarios(*paths)
            paths[0].write_text("topics: {}\n")
            with self.assertRaisesRegex(ValueError, "missing dashboard topics: custom/sensor"):
                load_scenarios(*paths)

    def test_all_sequence_values_must_match_numeric_bindings(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.make_config(Path(directory), {
                "sensors": [{"value": {"generator": "sequence", "values": [1, "bad"], "hold_s": 1}}],
            })
            with self.assertRaisesRegex(ValueError, "invalid binding values"):
                load_scenarios(*paths)

    def test_invalid_generators_report_location(self) -> None:
        invalid = [
            {"generator": "sine", "min": 0, "max": 1, "period_s": 0},
            {"generator": "ramp", "min": 0, "max": 1, "period_s": 1, "decimals": True},
            {"generator": "sine", "min": 1, "max": 0, "period_s": 1},
            {"generator": "sequence", "values": [], "hold_s": 1},
            {"generator": "unknown"},
            {"generator": []},
            float("nan"),
        ]
        for template in invalid:
            with self.subTest(template=template), self.assertRaisesRegex(ValueError, "payload.test"):
                validate_template(template, "payload.test")

    def test_invalid_topic_options_are_rejected(self) -> None:
        for field, value in [("interval_s", 0), ("qos", True), ("retain", "yes"), ("typo", 3)]:
            with self.subTest(field=field), TemporaryDirectory() as directory:
                paths = self.make_config(Path(directory), {"sensors": [{"value": 12}]})
                config = yaml.safe_load(paths[0].read_text())
                config["topics"]["custom/sensor"][field] = value
                paths[0].write_text(yaml.safe_dump(config))
                with self.assertRaisesRegex(ValueError, "topics"):
                    load_scenarios(*paths)

    def test_check_mode_prints_selected_payloads_without_connecting(self) -> None:
        output = StringIO()
        with redirect_stdout(output), patch("backend.app.fake_mqtt.aiomqtt.Client") as client:
            main(["--scenario", str(REPOSITORY / "fake-mqtt.example.yaml"),
                  "--dashboard-config", str(REPOSITORY / "config.test.yaml"), "--check"])
        client.assert_not_called()
        self.assertEqual(
            set(json.loads(output.getvalue())),
            {"rv/renogy", "rv/hughes", "rv/gpsd/TPV", "rv/gpsd/SKY", "rv/obd"},
        )

    def test_invalid_config_exits_with_explicit_error(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            main(["--scenario", "/nonexistent/rv-web-test-scenario.yaml", "--check"])
        self.assertEqual(error.exception.code, 2)


class FakePublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulated_command_publishes_state_and_correlated_result(self) -> None:
        broker = AsyncMock()
        request = {
            "version": 1, "client_id": "rv-control-web", "request_id": "req-1",
            "target": "mid_bath_fan", "action": "on",
        }

        async def messages():
            yield SimpleNamespace(
                topic="rv/coach/command",
                payload=json.dumps(request).encode(),
            )

        broker.messages = messages()
        await consume_simulated_commands(broker, FanActionSimulator())

        calls = broker.publish.await_args_list
        self.assertEqual(calls[0].args[0], "rv/coach/entity/mid_bath_fan")
        self.assertEqual(json.loads(calls[0].args[1]), {"state": {"on": True}})
        self.assertEqual(calls[0].kwargs, {"qos": 0, "retain": False})
        self.assertEqual(calls[1].args[0], "rv/coach/result/rv-control-web/req-1")
        result = json.loads(calls[1].args[1])
        self.assertEqual((result["status"], result["outcome"]), ("completed", "dispatched"))
        self.assertEqual(calls[1].kwargs, {"qos": 1, "retain": False})

    async def test_action_mode_subscribes_and_publishes_initial_fan_states(self) -> None:
        client = AsyncMock()
        client.__aenter__.return_value = client
        clock = [0.0]

        async def empty_messages():
            await asyncio.Event().wait()
            yield None

        client.messages = empty_messages()

        async def stop_after_first_tick(delay: float) -> None:
            clock[0] += delay
            raise asyncio.CancelledError

        with patch("backend.app.fake_mqtt.aiomqtt.Client", return_value=client), \
             patch("backend.app.fake_mqtt.time", SimpleNamespace(monotonic=lambda: clock[0])), \
             patch("backend.app.fake_mqtt.asyncio.sleep", side_effect=stop_after_first_tick):
            with self.assertRaises(asyncio.CancelledError):
                await publish_forever(
                    "localhost", 1883, {"sample": TopicScenario({"value": 1}, 1, 0, False)},
                    simulate_actions=True,
                )

        client.subscribe.assert_awaited_once_with("rv/coach/command", qos=1)
        published_topics = [call.args[0] for call in client.publish.await_args_list]
        self.assertIn("rv/coach/entity/kitchen_fan", published_topics)
        self.assertIn("rv/coach/entity/kitchen_fan_lid", published_topics)

    async def test_per_topic_intervals_qos_and_retain(self) -> None:
        scenarios = {
            "fast": TopicScenario({"value": 1}, 1, 1, True),
            "slow": TopicScenario({"value": 2}, 2, 0, False),
        }
        client = AsyncMock()
        client.__aenter__.return_value = client
        clock = [0.0]

        async def advance(delay: float) -> None:
            clock[0] += delay
            if clock[0] >= 3:
                raise asyncio.CancelledError

        with patch("backend.app.fake_mqtt.aiomqtt.Client", return_value=client), \
             patch("backend.app.fake_mqtt.time.monotonic", side_effect=lambda: clock[0]), \
             patch("backend.app.fake_mqtt.asyncio.sleep", side_effect=advance):
            with self.assertRaises(asyncio.CancelledError):
                await publish_forever("localhost", 1883, scenarios)
        calls = client.publish.await_args_list
        self.assertEqual([call.args[0] for call in calls], ["fast", "slow", "fast", "fast", "slow"])
        self.assertEqual(calls[0].kwargs, {"qos": 1, "retain": True})
        self.assertEqual(calls[1].kwargs, {"qos": 0, "retain": False})


if __name__ == "__main__":
    unittest.main()
