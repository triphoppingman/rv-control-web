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


CONTAINERS = {"grid", "row", "column", "stack", "card"}
BOUND = {"gauge", "dial", "numeric", "boolean", "sparkline"}
DERIVED_OPERATIONS = {"sum", "difference", "product", "ratio", "average"}
STATIC = {"text", "image", "icon", "divider", "spacer"}


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
    tab_topics: dict[str, set[str]] = {}
    for index, tab in enumerate(data["tabs"]):
        location = f"tabs[{index}]"
        if not isinstance(tab, dict) or not isinstance(tab.get("id"), str) or not tab["id"]:
            raise ValueError(f"{location}: id is required")
        if tab["id"] in seen_tabs:
            raise ValueError(f"{location}: duplicate tab id {tab['id']}")
        seen_tabs.add(tab["id"])
        topics: set[str] = set()
        validate_node(tab.get("root"), f"{location}.root", topics, seen_nodes, assets_dir)
        tab_topics[tab["id"]] = topics
    return data, tab_topics


def validate_node(
    node: Any, location: str, topics: set[str], seen_nodes: set[str], assets_dir: Path
) -> None:
    """Validate one node and recursively validate its children."""
    if not isinstance(node, dict):
        raise ValueError(f"{location}: expected a node")
    kind = node.get("type")
    if not isinstance(kind, str) or kind not in CONTAINERS | BOUND | {"derived"} | STATIC:
        raise ValueError(f"{location}: unknown type {kind!r}")
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
            validate_node(child, f"{location}.children[{index}]", topics, seen_nodes, assets_dir)
    elif kind in BOUND:
        for field in ("topic", "payload_path"):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise ValueError(f"{location}: {field} is required")
        if kind in {"gauge", "dial", "sparkline"}:
            minimum = node.get("min", 0)
            maximum = node.get("max", 100)
            if (
                not is_finite_number(minimum)
                or not is_finite_number(maximum)
                or minimum >= maximum
            ):
                raise ValueError(f"{location}: min and max must be finite numbers with min < max")
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
    else:
        if "topic" in node or "payload_path" in node:
            raise ValueError(f"{location}: static widgets cannot bind to a topic")
        if kind == "image":
            source = node.get("src")
            if not isinstance(source, str) or not source or not (assets_dir / source).resolve().is_relative_to(assets_dir.resolve()):
                raise ValueError(f"{location}: image src must be below assets_dir")