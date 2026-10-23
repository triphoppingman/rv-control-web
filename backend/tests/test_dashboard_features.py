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
    iter_bindings,
    iter_nodes,
    main as check_dashboard,
    resolve_payload_path,
    validate_samples,
)
from backend.app.dashboard import load_dashboard


class DashboardFeatureTests(unittest.TestCase):
    def test_temperature_unit_defaults_to_fahrenheit_and_can_be_overridden(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            dashboard_data = {"tabs": [{"id": "weather", "root": {"type": "text"}}]}

            path.write_text(yaml.safe_dump(dashboard_data))
            dashboard, _ = load_dashboard(path, root)
            self.assertEqual(dashboard["units"]["temperature"], "F")

            dashboard_data["units"] = {"temperature": "C"}
            path.write_text(yaml.safe_dump(dashboard_data))
            dashboard, _ = load_dashboard(path, root)
            self.assertEqual(dashboard["units"]["temperature"], "C")

            dashboard_data["units"]["temperature"] = "K"
            path.write_text(yaml.safe_dump(dashboard_data))
            with self.assertRaisesRegex(ValueError, "dashboard.units.temperature must be C or F"):
                load_dashboard(path, root)

    def test_weather_widget_binds_to_the_full_topic_payload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            path.write_text(yaml.safe_dump({
                "tabs": [{"id": "weather", "root": {"type": "weather", "topic": "rv/weather"}}],
            }))
            dashboard, topics = load_dashboard(path, root)
            self.assertEqual(topics, {"weather": {"rv/weather"}})
            weather = dashboard["tabs"][0]["root"]
            self.assertEqual(weather["provider"], "open-meteo")
            self.assertEqual(validate_samples(
                dashboard, {"rv/weather": {"current": {"temperature_2m": 20.8}}},
                {"rv/weather"},
            ), [])
            self.assertTrue(validate_samples(dashboard, {"rv/weather": 20.8}, {"rv/weather"}))

            weather["provider"] = "custom"
            weather["bindings"] = {"current_temperature": "conditions.temp"}
            path.write_text(yaml.safe_dump(dashboard))
            custom_dashboard, _ = load_dashboard(path, root)
            self.assertEqual(
                custom_dashboard["tabs"][0]["root"]["bindings"]["current_temperature"],
                "conditions.temp",
            )

            dashboard["tabs"][0]["root"].pop("topic")
            path.write_text(yaml.safe_dump(dashboard))
            with self.assertRaisesRegex(ValueError, "topic is required"):
                load_dashboard(path, root)

    def test_wled_widget_binds_and_validates_full_state_payload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            path.write_text(yaml.safe_dump({
                "tabs": [{"id": "lighting", "root": {"type": "wled", "topic": "rv/wled/patio"}}],
            }))
            dashboard, topics = load_dashboard(path, root)
            self.assertEqual(topics, {"lighting": {"rv/wled/patio"}})
            state = {
                "on": True, "bri": 128,
                "seg": [{"id": 0, "on": True, "fx": 12, "pal": 4, "col": [[255, 96, 32]]}],
            }
            self.assertEqual(validate_samples(
                dashboard, {"rv/wled/patio": state}, {"rv/wled/patio"},
            ), [])
            for invalid in (
                None, [], {"on": 1}, {"on": True, "bri": 256},
                {"on": True, "seg": {}},
                {"on": True, "seg": [{"fx": -1}]},
                {"on": True, "seg": [{"col": [[256, 0, 0]]}]},
            ):
                with self.subTest(invalid=invalid):
                    self.assertTrue(validate_samples(
                        dashboard, {"rv/wled/patio": invalid}, {"rv/wled/patio"},
                    ))
            self.assertTrue(validate_samples(
                dashboard, {"rv/wled/patio": {"on": True}}, {"rv/wled/patio"},
            ) == [])
            dashboard["tabs"][0]["root"]["payload_path"] = "state"
            path.write_text(yaml.safe_dump(dashboard))
            with self.assertRaisesRegex(ValueError, "WLED widgets consume the full payload"):
                load_dashboard(path, root)

        repository = Path(__file__).resolve().parents[2]
        example, topics = load_dashboard(
            repository / "dashboard.example.yaml", repository / "assets"
        )
        lighting = next(tab for tab in example["tabs"] if tab["id"] == "lighting")
        widget = lighting["root"]["children"][0]["children"][0]
        self.assertEqual(widget["type"], "wled")
        self.assertEqual(topics["lighting"], {"rv/wled/patio"})
        self.assertEqual(validate_samples(
            {"tabs": [lighting]},
            {"rv/wled/patio": {
                "on": True, "bri": 128,
                "seg": [{"id": 0, "on": True, "fx": 12, "pal": 4,
                         "col": [[255, 96, 32], [0, 0, 0], [0, 0, 0]]}],
            }},
            {"rv/wled/patio"},
        ), [])

    def test_generator_configuration_and_samples(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        for filename in ("dashboard.example.yaml", "dashboard.yaml"):
            path = repository / filename
            if not path.exists():
                continue
            dashboard, topics = load_dashboard(path, repository / "assets")
            coach = next(tab for tab in dashboard["tabs"] if tab["id"] == "coach")
            group = next(item for item in coach["root"]["children"] if item.get("title") == "Generator")
            self.assertEqual(group["title"], "Generator")
            node = group["children"][0]
            self.assertEqual(node["type"], "generator")
            self.assertEqual(node["payload_path"], "state")
            self.assertEqual(node["topic"], "rv/coach/entity/generator")
            self.assertIn(node["topic"], topics["coach"])
            for state in (
                {"starting": False, "stopping": False, "status": "stopped", "run_hours": 148.2},
                {"status": "running", "run_hours": 0},
                {"starting": True}, {"stopping": True}, {"run_hours": 148.2},
                {"status": 5}, {"status": "warming_up"}, {"status": None, "starting": False},
            ):
                with self.subTest(filename=filename, state=state):
                    self.assertEqual(validate_samples(
                        {"tabs": [{"root": node}]}, {node["topic"]: {"state": state}},
                        {node["topic"]},
                    ), [])
            for state in (
                None, {}, [], True, {"status": ""}, {"status": True},
                {"run_hours": -1}, {"run_hours": "148.2"}, {"run_hours": float("inf")},
                {"starting": 1}, {"stopping": "false"}, {"starting": True, "stopping": True},
            ):
                with self.subTest(filename=filename, state=state):
                    self.assertTrue(validate_samples(
                        {"tabs": [{"root": node}]}, {node["topic"]: {"state": state}},
                        {node["topic"]},
                    ))

    def test_solar_input_voltage_and_current(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        for filename in ("dashboard.example.yaml", "dashboard.yaml"):
            path = repository / filename
            if not path.exists():
                continue
            with self.subTest(filename=filename):
                dashboard, _ = load_dashboard(path, repository / "assets")
                solar = dashboard["tabs"][0]
                card = next(node for node in solar["root"]["children"]
                            if node.get("title") == "Solar input")
                voltage, current, power = card["children"]
                self.assertEqual(
                    (voltage["type"], voltage["payload_path"], voltage["unit"],
                     voltage["min"], voltage["max"]),
                    ("dial", "pv_voltage", "V", 0, 150),
                )
                self.assertEqual(
                    (current["type"], current["payload_path"], current["unit"]),
                    ("numeric", "pv_current", "A"),
                )
                self.assertEqual(power["payload_path"], "pv_power")
                self.assertTrue(all(node["topic"] == "rv/renogy"
                                    for node in card["children"]))
                self.assertEqual(validate_samples(
                    {"tabs": [{"root": card}]},
                    {"rv/renogy": {"pv_voltage": 13.4, "pv_current": 0.0, "pv_power": 0}},
                    {"rv/renogy"},
                ), [])

    def test_coach_fans_and_lid_subscription(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        dashboard, topics = load_dashboard(
            repository / "dashboard.example.yaml", repository / "assets"
        )
        coach = next(tab for tab in dashboard["tabs"] if tab["id"] == "coach")
        group = coach["root"]["children"][2]
        self.assertEqual(group["title"], "Fans")
        fans = group["children"][0]["children"]
        self.assertEqual([node["label"] for node in fans], ["Kitchen", "Mid Bath", "Rear Bath"])
        self.assertEqual(
            [node["topic"] for node in fans],
            [f"rv/coach/entity/{name}_fan" for name in ("kitchen", "mid_bath", "rear_bath")],
        )
        kitchen = fans[0]
        self.assertEqual(list(iter_bindings(kitchen)), [
            ("rv/coach/entity/kitchen_fan", "state", False),
            ("rv/coach/entity/kitchen_fan_lid", "state", False),
        ])
        self.assertIn(kitchen["lid_topic"], topics["coach"])
        self.assertTrue(all(node["type"] == "fan" for node in fans))

    def test_fan_and_lid_configuration_and_samples(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            node = {
                "type": "fan", "topic": "fan", "payload_path": "state",
                "lid_topic": "lid", "lid_payload_path": "state",
            }
            path.write_text(yaml.safe_dump({"tabs": [{"id": "coach", "root": node}]}))
            dashboard, topics = load_dashboard(path, root)
            self.assertEqual(topics["coach"], {"fan", "lid"})
            idle = {"open_active": False, "close_active": False}
            for fan in (True, False, {"on": True}, {"on": False, "level": 100}):
                for lid in (
                    idle,
                    {"open_active": True, "close_active": False, "open_remaining": 15},
                    {"open_active": False, "close_active": True, "close_remaining": 0},
                    {**idle, "open_remaining": None, "close_remaining": None},
                ):
                    with self.subTest(fan=fan, lid=lid):
                        self.assertEqual(validate_samples(dashboard, {
                            "fan": {"state": fan}, "lid": {"state": lid},
                        }, {"fan", "lid"}), [])
            for lid in (
                None, {}, {"open_active": True}, {"open_active": 1, "close_active": False},
                {"open_active": True, "close_active": True},
                {**idle, "open_remaining": -1}, {**idle, "close_remaining": "15"},
                {**idle, "open_remaining": True}, {**idle, "open_remaining": float("inf")},
            ):
                with self.subTest(lid=lid):
                    self.assertTrue(validate_samples(dashboard, {
                        "fan": {"state": {"on": True}}, "lid": {"state": lid},
                    }, {"fan", "lid"}))
            for fan in (None, 1, "on", [], {}, {"on": 1}):
                with self.subTest(fan=fan):
                    self.assertTrue(validate_samples(dashboard, {
                        "fan": {"state": fan}, "lid": {"state": idle},
                    }, {"fan", "lid"}))
            for settings in (
                {"lid_topic": None}, {"lid_payload_path": ""}, {"type": "light"},
            ):
                path.write_text(yaml.safe_dump({"tabs": [{"id": "coach", "root": {
                    **node, **settings,
                }}]}))
                with self.subTest(settings=settings), self.assertRaises(ValueError):
                    load_dashboard(path, root)

    def test_coach_light_groups(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        expected = {
            "Entry": [
                ("Cargo", "cargo"), ("Step", "step"), ("Awning", "awning"),
            ],
            "Main": [
                ("Living Ceiling", "living_ceiling"), ("Hall", "hall"),
                ("Dinette", "dinette"), ("Kitchen", "kitchen"),
                ("Sofa", "sofa"), ("Accent", "accent"),
            ],
            "Rear": [
                ("Bedroom ceiling", "bedroom_ceiling"), ("Rear Bath", "rear_bath"),
                ("Mid Bath", "mid_bath"), ("Vanity", "vanity"),
            ],
        }
        for filename in ("dashboard.example.yaml", "dashboard.yaml"):
            path = repository / filename
            if not path.exists():
                continue
            with self.subTest(filename=filename):
                dashboard, topics = load_dashboard(path, repository / "assets")
                coach = next(tab for tab in dashboard["tabs"] if tab["id"] == "coach")
                groups = coach["root"]["children"]
                self.assertEqual(
                    [group["title"] for group in groups],
                    ["Tank Levels", "Lights", "Fans", "Generator", "Climate"],
                )
                self.assertTrue(all(group["type"] == "card" for group in groups))
                layout = groups[1]["children"][0]
                self.assertEqual(layout["type"], "grid")
                self.assertEqual(layout["cols"], 3)
                self.assertEqual([card["title"] for card in layout["children"]], list(expected))
                for card in layout["children"]:
                    self.assertEqual(card["type"], "card")
                    lights = card["children"]
                    expected_lights = expected[card["title"]]
                    if filename == "dashboard.yaml" and card["title"] == "Entry":
                        expected_lights = [*expected_lights, ("Patio strip", "patio")]
                    self.assertEqual(
                        [(node["label"], node["topic"]) for node in lights],
                        [(label, f"rv/coach/entity/{entity}_light")
                         for label, entity in expected_lights],
                    )
                    for node in lights:
                        self.assertEqual(node["type"], "light")
                        self.assertEqual(node["payload_path"], "state")
                        self.assertIn(node["topic"], topics["coach"])
                tanks = groups[0]["children"][0]["children"]
                self.assertEqual(len(tanks), 5)
                self.assertTrue(all(node["type"] == "tank" for node in tanks))

    def test_light_configuration_and_samples(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            path.write_text(yaml.safe_dump({"tabs": [{"id": "coach", "root": {
                "type": "light", "topic": "rv/coach/entity/light", "payload_path": "state",
            }}]}))
            dashboard, topics = load_dashboard(path, root)
            self.assertEqual(topics, {"coach": {"rv/coach/entity/light"}})
            for value in (
                True, False, {"on": True}, {"on": False, "level": 75},
                {"on": True, "level": 0}, {"on": True, "level": 100},
                {"on": True, "level": None},
            ):
                with self.subTest(value=value):
                    self.assertEqual(validate_samples(
                        dashboard, {"rv/coach/entity/light": {"state": value}},
                        topics["coach"],
                    ), [])
            for value in (
                None, 1, "on", {}, [], {"on": 1}, {"on": "false"},
                {"on": True, "level": True}, {"on": True, "level": "50"},
                {"on": True, "level": -1}, {"on": True, "level": 101},
                {"on": True, "level": float("inf")},
            ):
                with self.subTest(value=value):
                    self.assertTrue(validate_samples(
                        dashboard, {"rv/coach/entity/light": {"state": value}},
                        topics["coach"],
                    ))

    def test_tank_configuration_and_numeric_samples(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            node = {
                "type": "tank", "topic": "rv/tanks", "payload_path": "fresh",
                "min": 0, "max": 3, "segments": 3,
            }
            path.write_text(yaml.safe_dump({"tabs": [{"id": "tanks", "root": node}]}))
            dashboard, topics = load_dashboard(path, root)
            self.assertEqual(topics, {"tanks": {"rv/tanks"}})
            for value in (0, 1, 2, 3):
                self.assertEqual(validate_samples(
                    dashboard, {"rv/tanks": {"fresh": value}}, {"rv/tanks"}
                ), [])
            for value in ("2", None, True, float("inf")):
                with self.subTest(value=value):
                    self.assertTrue(validate_samples(
                        dashboard, {"rv/tanks": {"fresh": value}}, {"rv/tanks"}
                    ))

    def test_tank_rejects_invalid_segments_and_ranges(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "dashboard.yaml"
            for settings in (
                {"segments": 0}, {"segments": 21}, {"segments": 2.5},
                {"segments": True}, {"segments": "3"}, {"segments": None},
                {"min": 3, "max": 3}, {"min": 4, "max": 3},
                {"min": float("nan")}, {"max": float("inf")},
            ):
                with self.subTest(settings=settings):
                    node = {"type": "tank", "topic": "rv/tanks", "payload_path": "fresh", **settings}
                    path.write_text(yaml.safe_dump({"tabs": [{"id": "tanks", "root": node}]}))
                    with self.assertRaises(ValueError):
                        load_dashboard(path, root)
            for settings in ({}, {"segments": 1}, {"segments": 4}, {"segments": 20}):
                node = {"type": "tank", "topic": "rv/tanks", "payload_path": "fresh", **settings}
                path.write_text(yaml.safe_dump({"tabs": [{"id": "tanks", "root": node}]}))
                load_dashboard(path, root)

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
