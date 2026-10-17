"""Load dashboard YAML and derive topic subscriptions."""

import math
import re
from pathlib import Path
from typing import Any

import yaml


class DashboardLoader(yaml.SafeLoader):
    """Preserve MQTT field names such as 'on' while parsing true/false values."""


DashboardLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
DashboardLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.IGNORECASE), list("tTfF")
)


CONTAINERS = {"grid", "row", "column", "stack", "card", "flow"}
BOUND = {
    "gauge", "dial", "numeric", "boolean", "sparkline", "tank", "light", "fan",
    "generator", "thermostat",
}
DERIVED_OPERATIONS = {"sum", "difference", "product", "ratio", "average"}
STATIC = {"text", "image", "icon", "divider", "spacer"}
MAP_ORIENTATIONS = {"north_up", "heading_up"}
ALTITUDE_UNITS = {"ft", "m"}
SPEED_UNITS = {"mph", "km/h", "kt"}
COACH_ENTITY_PREFIX = "rv/coach/entity/"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_finite_number(value: Any) -> bool:
    """Return whether a value is a finite JSON-compatible number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def load_dashboard(path: Path, assets_dir: Path) -> tuple[dict[str, Any], dict[str, set[str]]]:
    """Validate a display tree and return its configuration and tab topics."""
    data = yaml.load(path.read_text(), Loader=DashboardLoader)
    if not isinstance(data, dict) or not isinstance(data.get("tabs"), list) or not data["tabs"]:
        raise ValueError("dashboard: tabs must be a non-empty list")
    seen_tabs: set[str] = set()
    seen_nodes: set[str] = set()
    seen_controls: set[str] = set()
    tab_topics: dict[str, set[str]] = {}
    for index, tab in enumerate(data["tabs"]):
        location = f"tabs[{index}]"
        if not isinstance(tab, dict) or not isinstance(tab.get("id"), str) or not tab["id"]:
            raise ValueError(f"{location}: id is required")
        if tab["id"] in seen_tabs:
            raise ValueError(f"{location}: duplicate tab id {tab['id']}")
        seen_tabs.add(tab["id"])
        topics: set[str] = set()
        validate_node(
            tab.get("root"), f"{location}.root", topics, seen_nodes, seen_controls, assets_dir
        )
        tab_topics[tab["id"]] = topics
    return data, tab_topics


def validate_node(
    node: Any,
    location: str,
    topics: set[str],
    seen_nodes: set[str],
    seen_controls: set[str],
    assets_dir: Path,
) -> None:
    """Validate one node and recursively validate its children."""
    if not isinstance(node, dict):
        raise ValueError(f"{location}: expected a node")
    kind = node.get("type")
    if not isinstance(kind, str) or kind not in CONTAINERS | BOUND | {"derived", "map"} | STATIC:
        raise ValueError(f"{location}: unknown type {kind!r}")
    if "low_warning_below" in node and kind != "dial":
        raise ValueError(f"{location}: low_warning_below is only supported for dial widgets")
    if "show_warning" in node:
        if kind != "dial" or not isinstance(node["show_warning"], bool):
            raise ValueError(f"{location}: show_warning must be a boolean on a dial widget")
    if "lid_topic" in node or "lid_payload_path" in node:
        if kind != "fan":
            raise ValueError(f"{location}: lid bindings are only supported for fan widgets")
        for field in ("lid_topic", "lid_payload_path"):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise ValueError(f"{location}: {field} is required for a lid binding")
        topics.add(node["lid_topic"])
    controls = node.get("controls")
    if controls is not None:
        if kind not in BOUND or not isinstance(controls, list) or not controls:
            raise ValueError(f"{location}: controls must be a non-empty list on a bound widget")
        allowed_targets = {
            topic[len(COACH_ENTITY_PREFIX):]
            for topic in (node.get("topic"),)
            if isinstance(topic, str) and topic.startswith(COACH_ENTITY_PREFIX)
        }
        for index, control in enumerate(controls):
            control_location = f"{location}.controls[{index}]"
            if not isinstance(control, dict) or set(control) - {
                "id", "target", "action", "label", "params", "confirm", "input"
            }:
                raise ValueError(
                    f"{control_location}: expected id, target, action, label, params, confirm, and input fields"
                )
            control_id = control.get("id")
            if (
                not isinstance(control_id, str) or not IDENTIFIER.fullmatch(control_id)
                or control_id in seen_controls
            ):
                raise ValueError(f"{control_location}: id must be unique and match [A-Za-z0-9_-]{{1,64}}")
            seen_controls.add(control_id)
            target = control.get("target")
            if (
                not isinstance(target, str) or not IDENTIFIER.fullmatch(target)
                or target not in allowed_targets
            ):
                raise ValueError(f"{control_location}: target must match this widget's Coach entity topic")
            action = control.get("action")
            if not isinstance(action, str) or not IDENTIFIER.fullmatch(action):
                raise ValueError(f"{control_location}: action must match [A-Za-z0-9_-]{{1,64}}")
            label = control.get("label", action.replace("_", " ").title())
            if not isinstance(label, str) or not label.strip() or len(label) > 64:
                raise ValueError(f"{control_location}: label must be a non-empty string of at most 64 characters")
            params = control.get("params", {})
            if not isinstance(params, dict) or any(
                not isinstance(name, str) or not IDENTIFIER.fullmatch(name)
                or isinstance(value, (dict, list)) or value is None
                or not isinstance(value, (str, int, float, bool))
                or isinstance(value, float) and not math.isfinite(value)
                for name, value in params.items()
            ):
                raise ValueError(f"{control_location}: params must contain only finite scalar values")
            control_input = control.get("input")
            if control_input is not None:
                required_input_fields = {"type", "param", "min", "max", "step"}
                if (
                    not isinstance(control_input, dict)
                    or not required_input_fields.issubset(control_input)
                    or set(control_input) - required_input_fields - {"value_field", "unit"}
                    or control_input.get("type") != "slider"
                    or not isinstance(control_input.get("param"), str)
                    or not IDENTIFIER.fullmatch(control_input["param"])
                    or control_input["param"] in params
                    or (
                        "value_field" in control_input
                        and (
                            not isinstance(control_input["value_field"], str)
                            or not IDENTIFIER.fullmatch(control_input["value_field"])
                        )
                    )
                    or (
                        "unit" in control_input
                        and (
                            not isinstance(control_input["unit"], str)
                            or len(control_input["unit"]) > 16
                        )
                    )
                    or not is_finite_number(control_input.get("min"))
                    or not is_finite_number(control_input.get("max"))
                    or not is_finite_number(control_input.get("step"))
                    or control_input["min"] >= control_input["max"]
                    or control_input["step"] <= 0
                    or not is_finite_number(control_input["max"] - control_input["min"])
                    or not is_finite_number(
                        (control_input["max"] - control_input["min"]) / control_input["step"]
                    )
                    or not math.isclose(
                        (control_input["max"] - control_input["min"]) / control_input["step"],
                        round((control_input["max"] - control_input["min"]) / control_input["step"]),
                    )
                ):
                    raise ValueError(
                        f"{control_location}: input must define a valid slider param, min, max, and step"
                    )
            confirm = control.get("confirm", False)
            if not isinstance(confirm, bool):
                raise ValueError(f"{control_location}: confirm must be a boolean")
            control.setdefault("label", label)
            control.setdefault("params", params)
            control.setdefault("confirm", confirm)
            if control_input is not None:
                control.setdefault("input", control_input)
    node_id = node.get("id")
    if node_id is not None:
        if not isinstance(node_id, str) or not node_id or node_id in seen_nodes:
            raise ValueError(f"{location}: invalid or duplicate node id {node_id!r}")
        seen_nodes.add(node_id)
    if kind in CONTAINERS:
        if "topic" in node or "payload_path" in node:
            raise ValueError(f"{location}: containers cannot bind to a topic")
        if not isinstance(node.get("children"), list):
            raise ValueError(f"{location}: children must be a list")
        for index, child in enumerate(node["children"]):
            validate_node(
                child, f"{location}.children[{index}]", topics, seen_nodes, seen_controls, assets_dir
            )
    elif kind in BOUND:
        for field in ("topic", "payload_path"):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise ValueError(f"{location}: {field} is required")
        if kind in {"gauge", "dial", "sparkline", "tank"}:
            minimum = node.get("min", 0)
            maximum = node.get("max", 100)
            if (
                not is_finite_number(minimum)
                or not is_finite_number(maximum)
                or minimum >= maximum
            ):
                raise ValueError(f"{location}: min and max must be finite numbers with min < max")
            if "low_warning_below" in node:
                warning = node["low_warning_below"]
                if not is_finite_number(warning) or not minimum < warning < maximum:
                    raise ValueError(f"{location}: low_warning_below must be a finite number between min and max")
        if kind == "tank":
            segments = node.get("segments", 3)
            if isinstance(segments, bool) or not isinstance(segments, int) or not 1 <= segments <= 20:
                raise ValueError(f"{location}: segments must be an integer from 1 to 20")
        if kind == "sparkline":
            history_points = node.get("history_points", 60)
            if isinstance(history_points, bool) or not isinstance(history_points, int) or not 2 <= history_points <= 1000:
                raise ValueError(f"{location}: history_points must be an integer from 2 to 1000")
            sample_interval_ms = node.get("sample_interval_ms", 1000)
            if (
                isinstance(sample_interval_ms, bool)
                or not isinstance(sample_interval_ms, int)
                or not 0 <= sample_interval_ms <= 60000
            ):
                raise ValueError(f"{location}: sample_interval_ms must be an integer from 0 to 60000")
        topics.add(node["topic"])
    elif kind == "derived":
        if "topic" in node or "payload_path" in node:
            raise ValueError(f"{location}: derived widgets use inputs, not topic or payload_path")
        operation = node.get("operation")
        if not isinstance(operation, str) or operation not in DERIVED_OPERATIONS:
            raise ValueError(f"{location}: operation must be one of {', '.join(sorted(DERIVED_OPERATIONS))}")
        inputs = node.get("inputs")
        if not isinstance(inputs, list) or len(inputs) < 2:
            raise ValueError(f"{location}: inputs must contain at least two bindings")
        if operation in {"difference", "ratio"} and len(inputs) != 2:
            raise ValueError(f"{location}: {operation} requires exactly two inputs")
        for index, binding in enumerate(inputs):
            input_location = f"{location}.inputs[{index}]"
            if not isinstance(binding, dict):
                raise ValueError(f"{input_location}: expected a binding")
            for field in ("topic", "payload_path"):
                if not isinstance(binding.get(field), str) or not binding[field].strip():
                    raise ValueError(f"{input_location}: {field} is required")
            topics.add(binding["topic"])
    elif kind == "map":
        topic = node.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError(f"{location}: topic is required")
        for path_field in ("lat_path", "lon_path", "track_path", "alt_path", "speed_path", "mode_path"):
            val = node.get(path_field)
            if val is not None and (not isinstance(val, str) or not val.strip()):
                raise ValueError(f"{location}: {path_field} must be a non-empty string if specified")
        zoom = node.get("zoom", 14)
        if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not 1 <= zoom <= 20:
            raise ValueError(f"{location}: zoom must be a number between 1 and 20")
        orientation = node.get("orientation", "north_up")
        if not isinstance(orientation, str) or orientation not in MAP_ORIENTATIONS:
            raise ValueError(f"{location}: orientation must be one of {', '.join(sorted(MAP_ORIENTATIONS))}")
        alt_unit = node.get("altitude_unit", "ft")
        if not isinstance(alt_unit, str) or alt_unit not in ALTITUDE_UNITS:
            raise ValueError(f"{location}: altitude_unit must be one of {', '.join(sorted(ALTITUDE_UNITS))}")
        speed_unit = node.get("speed_unit", "mph")
        if not isinstance(speed_unit, str) or speed_unit not in SPEED_UNITS:
            raise ValueError(f"{location}: speed_unit must be one of {', '.join(sorted(SPEED_UNITS))}")
        tile_url = node.get("tile_url")
        if tile_url is not None and (not isinstance(tile_url, str) or not tile_url.strip()):
            raise ValueError(f"{location}: tile_url must be a non-empty string if specified")
        topics.add(topic)
    else:
        if "topic" in node or "payload_path" in node:
            raise ValueError(f"{location}: static widgets cannot bind to a topic")
        if controls is not None:
            raise ValueError(f"{location}: controls are only supported on Coach entity widgets")
        if kind == "image":
            source = node.get("src")
            if not isinstance(source, str) or not source or not (assets_dir / source).resolve().is_relative_to(assets_dir.resolve()):
                raise ValueError(f"{location}: image src must be below assets_dir")


def dashboard_controls(data: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Return validated control definitions grouped by tab and control ID."""
    controls: dict[str, dict[str, dict[str, Any]]] = {}

    def visit(node: dict[str, Any], tab_controls: dict[str, dict[str, Any]]) -> None:
        for control in node.get("controls", []):
            tab_controls[control["id"]] = control
        for child in node.get("children", []):
            visit(child, tab_controls)

    for tab in data["tabs"]:
        tab_controls: dict[str, dict[str, Any]] = {}
        visit(tab["root"], tab_controls)
        controls[tab["id"]] = tab_controls
    return controls