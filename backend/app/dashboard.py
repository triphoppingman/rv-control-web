"""Load dashboard YAML and derive topic subscriptions."""

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
STATIC = {"text", "image", "icon", "divider", "spacer"}


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
    if kind not in CONTAINERS | BOUND | STATIC:
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
        if kind in {"gauge", "dial", "sparkline"} and not node.get("min", 0) < node.get("max", 100):
            raise ValueError(f"{location}: min must be less than max")
        topics.add(node["topic"])
    else:
        if "topic" in node or "payload_path" in node:
            raise ValueError(f"{location}: static widgets cannot bind to a topic")
        if kind == "image":
            source = node.get("src")
            if not isinstance(source, str) or not source or not (assets_dir / source).resolve().is_relative_to(assets_dir.resolve()):
                raise ValueError(f"{location}: image src must be below assets_dir")