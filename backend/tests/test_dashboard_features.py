"""Tests for sample validation and derived dashboard bindings."""

import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from backend.app.check_dashboard import (
    MISSING,
    iter_nodes,
    main as check_dashboard,
    resolve_payload_path,
    validate_samples,
)
from backend.app.dashboard import load_dashboard


class DashboardFeatureTests(unittest.TestCase):
    def test_shipped_dashboard_example_uses_valid_feature_settings(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        dashboard, tab_topics = load_dashboard(
            repository / "dashboard.example.yaml", repository / "assets"
        )
        self.assertEqual(tab_topics["power"], {"rv/renogy"})
        self.assertEqual(tab_topics["shore"], {"rv/hughes"})
        nodes = list(iter_nodes(dashboard["tabs"][0]["root"], "tabs[0].root"))
        sparkline = next(node for node, _ in nodes if node.get("type") == "sparkline")
        self.assertEqual(sparkline["history_points"], 120)
        derived = next(node for node, _ in nodes if node.get("type") == "derived")
        self.assertEqual(derived["operation"], "difference")

    def test_payload_path_supports_prefixes_and_array_indices(self) -> None:
        payload = {"sensors": [{"temperature": 21.5}]}
        self.assertEqual(resolve_payload_path(payload, "$.sensors[0].temperature"), 21.5)
        self.assertIs(resolve_payload_path(payload, "sensors[1].temperature"), MISSING)

    def test_derived_inputs_are_included_in_tab_subscriptions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_path = root / "dashboard.yaml"
            dashboard_path.write_text(
                yaml.safe_dump(
                    {
                        "tabs": [
                            {
                                "id": "power",
                                "root": {
                                    "type": "derived",
                                    "operation": "difference",
                                    "inputs": [
                                        {"topic": "rv/battery", "payload_path": "current"},
                                        {"topic": "rv/load", "payload_path": "current"},
                                    ],
                                },
                            }
                        ]
                    }
                )
            )
            dashboard, tab_topics = load_dashboard(dashboard_path, root / "assets")
            self.assertEqual(tab_topics, {"power": {"rv/battery", "rv/load"}})
            self.assertEqual(dashboard["tabs"][0]["root"]["type"], "derived")

    def test_invalid_derived_arity_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_path = root / "dashboard.yaml"
            dashboard_path.write_text(
                yaml.safe_dump(
                    {
                        "tabs": [
                            {
                                "id": "power",
                                "root": {
                                    "type": "derived",
                                    "operation": "ratio",
                                    "inputs": [
                                        {"topic": "rv/a", "payload_path": "value"},
                                        {"topic": "rv/b", "payload_path": "value"},
                                        {"topic": "rv/c", "payload_path": "value"},
                                    ],
                                },
                            }
                        ]
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "ratio requires exactly two inputs"):
                load_dashboard(dashboard_path, root / "assets")

    def test_invalid_node_type_and_gauge_bounds_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_path = root / "dashboard.yaml"
            for node, expected in (
                ({"type": ["numeric"]}, "unknown type"),
                (
                    {
                        "type": "gauge",
                        "topic": "rv/a",
                        "payload_path": "value",
                        "min": "low",
                        "max": 100,
                    },
                    "finite numbers",
                ),
            ):
                dashboard_path.write_text(
                    yaml.safe_dump(
                        {"tabs": [{"id": "power", "root": node}]}
                    )
                )
                with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                    load_dashboard(dashboard_path, root / "assets")

    def test_sample_checker_rejects_zero_denominator(self) -> None:
        dashboard = {
            "tabs": [
                {
                    "id": "power",
                    "root": {
                        "type": "derived",
                        "operation": "ratio",
                        "inputs": [
                            {"topic": "rv/a", "payload_path": "value"},
                            {"topic": "rv/b", "payload_path": "value"},
                        ],
                    },
                }
            ]
        }
        errors = validate_samples(
            dashboard,
            {"rv/a": {"value": 12}, "rv/b": {"value": 0}},
            {"rv/a", "rv/b"},
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("non-finite value", errors[0])

    def test_dial_low_warning_validation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            for kind, warning, valid in (
                ("dial", 15, True),
                ("dial", 0, False),
                ("dial", 100, False),
                ("dial", -1, False),
                ("dial", 101, False),
                ("dial", True, False),
                ("dial", "15", False),
                ("dial", None, False),
                ("dial", float("nan"), False),
                ("dial", float("inf"), False),
                ("gauge", 15, False),
                ("numeric", 15, False),
            ):
                with self.subTest(kind=kind, warning=warning):
                    node = {
                        "type": kind, "topic": "rv/obd", "payload_path": "fuel",
                        "min": 0, "max": 100, "low_warning_below": warning,
                    }
                    path.write_text(yaml.safe_dump({"tabs": [{"id": "test", "root": node}]}))
                    if valid:
                        dashboard, _ = load_dashboard(path, root / "assets")
                        self.assertEqual(dashboard["tabs"][0]["root"]["low_warning_below"], 15)
                    else:
                        with self.assertRaisesRegex(ValueError, "low_warning_below"):
                            load_dashboard(path, root / "assets")

    def test_dial_warning_can_be_disabled(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            for kind, setting, valid in (
                ("dial", False, True), ("dial", True, True),
                ("dial", "false", False), ("dial", 0, False),
                ("numeric", False, False),
            ):
                with self.subTest(kind=kind, setting=setting):
                    node = {
                        "type": kind, "topic": "rv/hughes", "payload_path": "voltage_line_1",
                        "min": 90, "max": 150, "show_warning": setting,
                    }
                    path.write_text(yaml.safe_dump({"tabs": [{"id": "shore", "root": node}]}))
                    if valid:
                        dashboard, _ = load_dashboard(path, root)
                        self.assertEqual(dashboard["tabs"][0]["root"]["show_warning"], setting)
                    else:
                        with self.assertRaisesRegex(ValueError, "show_warning"):
                            load_dashboard(path, root)

    def test_only_example_fuel_dial_has_low_warning(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        dashboard, _ = load_dashboard(
            repository / "dashboard.example.yaml", repository / "assets"
        )
        configured = [
            node
            for tab in dashboard["tabs"]
            for node, _ in iter_nodes(tab["root"], "root")
            if "low_warning_below" in node
        ]
        self.assertEqual(len(configured), 1)
        self.assertEqual(configured[0]["payload_path"], "fuel")
        self.assertEqual(configured[0]["low_warning_below"], 15)

    def test_sample_check_validates_paths_types_and_topic_coverage(self) -> None:
        dashboard = {
            "tabs": [
                {
                    "id": "power",
                    "root": {
                        "type": "numeric",
                        "topic": "rv/battery",
                        "payload_path": "sensors[0].voltage",
                    },
                }
            ]
        }
        self.assertEqual(
            validate_samples(
                dashboard,
                {"rv/battery": {"sensors": [{"voltage": 13.4}]}},
                {"rv/battery"},
            ),
            [],
        )
        errors = validate_samples(
            dashboard,
            {"rv/battery": {"sensors": [{"voltage": "unknown"}]}},
            {"rv/battery", "rv/load"},
        )
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("finite number" in error for error in errors))
        self.assertTrue(any("missing sample payloads" in error for error in errors))

    def test_derived_sample_inputs_must_be_numeric(self) -> None:
        dashboard = {
            "tabs": [
                {
                    "id": "power",
                    "root": {
                        "type": "derived",
                        "operation": "sum",
                        "inputs": [
                            {"topic": "rv/a", "payload_path": "value"},
                            {"topic": "rv/b", "payload_path": "value"},
                        ],
                    },
                }
            ]
        }
        errors = validate_samples(
            dashboard,
            {"rv/a": {"value": 1}, "rv/b": {"value": True}},
            {"rv/a", "rv/b"},
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("finite number", errors[0])

    def test_cli_checks_config_and_sample_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dashboard.yaml").write_text(
                yaml.safe_dump(
                    {
                        "tabs": [
                            {
                                "id": "power",
                                "root": {
                                    "type": "numeric",
                                    "topic": "rv/battery",
                                    "payload_path": "voltage",
                                },
                            }
                        ]
                    }
                )
            )
            (root / "config.yaml").write_text("dashboard_file: dashboard.yaml\n")
            (root / "samples.json").write_text(
                json.dumps({"rv/battery": {"voltage": 13.4}})
            )
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(StringIO()):
                result = check_dashboard(
                    [
                        "--config",
                        str(root / "config.yaml"),
                        "--samples",
                        str(root / "samples.json"),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIn("1 bindings, 1 topics checked", output.getvalue())

    def test_map_widget_validation_and_subscription(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_path = root / "dashboard.yaml"
            dashboard_path.write_text(
                yaml.safe_dump(
                    {
                        "tabs": [
                            {
                                "id": "nav",
                                "root": {
                                    "type": "map",
                                    "topic": "rv/gpsd/TPV",
                                    "zoom": 15,
                                    "orientation": "north_up",
                                    "altitude_unit": "ft",
                                    "speed_unit": "mph",
                                },
                            }
                        ]
                    }
                )
            )
            dashboard, tab_topics = load_dashboard(dashboard_path, root / "assets")
            self.assertEqual(tab_topics, {"nav": {"rv/gpsd/TPV"}})
            self.assertEqual(dashboard["tabs"][0]["root"]["type"], "map")

    def test_map_widget_invalid_settings_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dashboard_path = root / "dashboard.yaml"
            for invalid_node, expected in (
                ({"type": "map"}, "topic is required"),
                ({"type": "map", "topic": "rv/gpsd", "zoom": 25}, "zoom must be a number between 1 and 20"),
                ({"type": "map", "topic": "rv/gpsd", "orientation": "bad"}, "orientation must be one of"),
                ({"type": "map", "topic": "rv/gpsd", "altitude_unit": "yard"}, "altitude_unit must be one of"),
                ({"type": "map", "topic": "rv/gpsd", "speed_unit": "furlong"}, "speed_unit must be one of"),
            ):
                dashboard_path.write_text(
                    yaml.safe_dump({"tabs": [{"id": "nav", "root": invalid_node}]})
                )
                with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                    load_dashboard(dashboard_path, root / "assets")

    def test_map_widget_sample_validation(self) -> None:
        dashboard = {
            "tabs": [
                {
                    "id": "nav",
                    "root": {
                        "type": "map",
                        "topic": "rv/gpsd/TPV",
                    },
                }
            ]
        }
        valid_samples = {
            "rv/gpsd/TPV": {
                "lat": 37.7749,
                "lon": -122.4194,
                "track": 90.0,
                "alt": 150.0,
                "speed": 25.0,
            }
        }
        self.assertEqual(validate_samples(dashboard, valid_samples, {"rv/gpsd/TPV"}), [])

        invalid_samples = {
            "rv/gpsd/TPV": {
                "lat": "not_a_number",
                "lon": -122.4194,
            }
        }
        errors = validate_samples(dashboard, invalid_samples, {"rv/gpsd/TPV"})
        self.assertEqual(len(errors), 1)
        self.assertIn("must resolve to a finite number", errors[0])


if __name__ == "__main__":
    unittest.main()
