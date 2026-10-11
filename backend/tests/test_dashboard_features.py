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


if __name__ == "__main__":
    unittest.main()
