"""Tests for configurable dashboard-driven fake MQTT telemetry."""

import asyncio
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import yaml

from backend.app.fake_mqtt import (
    TopicScenario,
    load_scenarios,
    main,
    publish_forever,
    render_payload,
    sample_payloads,
    validate_template,
)
from backend.app.check_dashboard import calculate_derived


REPOSITORY = Path(__file__).resolve().parents[2]


class FakeMqttTests(unittest.TestCase):
    def test_example_scenario_selects_only_dashboard_topics(self) -> None:
        scenarios = load_scenarios(
            REPOSITORY / "fake-mqtt.example.yaml", REPOSITORY / "config.test.yaml"
        )
        self.assertEqual(set(scenarios), {"rv/renogy", "rv/hughes"})
        first = sample_payloads(scenarios)
        later = sample_payloads(scenarios, 30)
        self.assertEqual(first["rv/renogy"]["battery_percentage"], 72)
        self.assertEqual(later["rv/renogy"]["battery_percentage"], 80)
        self.assertEqual(later["rv/renogy"]["charging_status"], "idle")

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
        self.assertEqual(set(json.loads(output.getvalue())), {"rv/renogy", "rv/hughes"})

    def test_invalid_config_exits_with_explicit_error(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            main(["--scenario", "/nonexistent/rv-web-test-scenario.yaml", "--check"])
        self.assertEqual(error.exception.code, 2)


class FakePublisherTests(unittest.IsolatedAsyncioTestCase):
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
