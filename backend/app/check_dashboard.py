"""Validate a dashboard and its bindings against captured MQTT payloads."""

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from .dashboard import BOUND, CONTAINERS, is_finite_number, load_dashboard


MISSING = object()
NUMERIC_WIDGETS = {"gauge", "dial", "numeric", "sparkline", "tank"}


def resolve_payload_path(payload: Any, path: str) -> Any:
    """Resolve the same dotted and indexed paths used by the frontend."""
    normalized = re.sub(r"^\$\.?", "", path)
    if not normalized:
        return payload
    parts = re.sub(r"\[(\d+)\]", r".\1", normalized).split(".")
    current = payload
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return MISSING
            current = current[part]
        elif isinstance(current, list):
            if not part.isdecimal() or (len(part) > 1 and part.startswith("0")):
                return MISSING
            index = int(part)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def iter_nodes(node: dict[str, Any], location: str):
    """Yield a node and its children with stable dashboard locations."""
    yield node, location
    if node.get("type") in CONTAINERS:
        for index, child in enumerate(node["children"]):
            yield from iter_nodes(child, f"{location}.children[{index}]")


def iter_bindings(node: dict[str, Any]):
    """Yield topic/path bindings for regular, derived, and map widgets."""
    if node.get("type") == "derived":
        for binding in node["inputs"]:
            yield binding["topic"], binding["payload_path"], True
    elif node.get("type") == "map":
        topic = node["topic"]
        lat_path = node.get("lat_path", "lat")
        lon_path = node.get("lon_path", "lon")
        yield topic, lat_path, True
        yield topic, lon_path, True
        for opt_field in ("track_path", "alt_path", "speed_path", "mode_path"):
            if opt_field in node:
                yield topic, node[opt_field], True
    elif node.get("type") == "weather":
        yield node["topic"], "$", False
    elif node.get("type") in BOUND:
        yield node["topic"], node["payload_path"], node["type"] in NUMERIC_WIDGETS
        if node["type"] == "fan" and "lid_topic" in node:
            yield node["lid_topic"], node["lid_payload_path"], False


def calculate_derived(operation: str, inputs: list[int | float]) -> int | float | None:
    """Evaluate a validated derived operation without accepting invalid output."""
    if operation == "sum":
        value = sum(inputs)
    elif operation == "difference":
        value = inputs[0] - inputs[1]
    elif operation == "product":
        value = math.prod(inputs)
    elif operation == "ratio":
        if inputs[1] == 0:
            return None
        value = inputs[0] / inputs[1]
    else:
        value = sum(inputs) / len(inputs)
    return value if is_finite_number(value) else None


def validate_samples(
    dashboard: dict[str, Any], samples: dict[str, Any], expected_topics: set[str]
) -> list[str]:
    """Return binding errors found when checking sample payloads."""
    errors: list[str] = []
    missing_topics = expected_topics - samples.keys()
    extra_topics = samples.keys() - expected_topics
    if missing_topics:
        errors.append(f"missing sample payloads for topics: {', '.join(sorted(missing_topics))}")
    if extra_topics:
        errors.append(f"samples contain unconfigured topics: {', '.join(sorted(extra_topics))}")

    for tab_index, tab in enumerate(dashboard["tabs"]):
        root_location = f"tabs[{tab_index}].root"
        for node, location in iter_nodes(tab["root"], root_location):
            derived_inputs: list[int | float] = []
            derived_valid = node.get("type") == "derived"
            for topic, path, numeric in iter_bindings(node):
                if topic not in samples:
                    derived_valid = False
                    continue
                payload = samples[topic]
                if not isinstance(payload, dict) and node.get("type") != "weather":
                    payload = {"value": payload}
                value = resolve_payload_path(payload, path)
                if value is MISSING:
                    derived_valid = False
                    errors.append(
                        f"{location}: topic {topic!r} sample has no value at payload_path {path!r}"
                    )
                elif node.get("type") == "weather" and not isinstance(value, dict):
                    derived_valid = False
                    errors.append(
                        f"{location}: topic {topic!r} weather payload must be an object"
                    )
                elif numeric and not is_finite_number(value):
                    derived_valid = False
                    errors.append(
                        f"{location}: topic {topic!r} payload_path {path!r} must resolve to a finite number"
                    )
                elif node.get("type") == "generator":
                    valid = (
                        isinstance(value, dict)
                        and any(value.get(field) is not None for field in (
                            "status", "run_hours", "starting", "stopping"
                        ))
                        and (
                            value.get("status") is None
                            or (isinstance(value["status"], str) and bool(value["status"].strip()))
                            or is_finite_number(value["status"])
                        )
                        and (
                            value.get("run_hours") is None
                            or (is_finite_number(value["run_hours"]) and value["run_hours"] >= 0)
                        )
                        and all(value.get(field) is None or isinstance(value[field], bool)
                                for field in ("starting", "stopping"))
                        and not (value.get("starting") is True and value.get("stopping") is True)
                    )
                    if not valid:
                        errors.append(
                            f"{location}: topic {topic!r} payload_path {path!r} must resolve "
                            "to a generator state with status, nonnegative run_hours, or boolean "
                            "starting/stopping (not both active)"
                        )
                elif node.get("type") == "fan":
                    if topic == node.get("lid_topic") and path == node.get("lid_payload_path"):
                        valid = (
                            isinstance(value, dict)
                            and isinstance(value.get("open_active"), bool)
                            and isinstance(value.get("close_active"), bool)
                            and not (value["open_active"] and value["close_active"])
                            and all(
                                value.get(field) is None or (
                                    is_finite_number(value[field]) and value[field] >= 0
                                )
                                for field in ("open_remaining", "close_remaining")
                            )
                        )
                        requirement = "a lid state with boolean open_active/close_active and nonnegative remaining times"
                    else:
                        valid = isinstance(value, bool) or (
                            isinstance(value, dict) and isinstance(value.get("on"), bool)
                        )
                        requirement = "a boolean or a fan state with boolean on"
                    if not valid:
                        errors.append(
                            f"{location}: topic {topic!r} payload_path {path!r} must resolve to {requirement}"
                        )
                elif node.get("type") == "light":
                    valid = isinstance(value, bool) or (
                        isinstance(value, dict)
                        and isinstance(value.get("on"), bool)
                        and (
                            value.get("level") is None
                            or (
                                is_finite_number(value["level"])
                                and 0 <= value["level"] <= 100
                            )
                        )
                    )
                    if not valid:
                        errors.append(
                            f"{location}: topic {topic!r} payload_path {path!r} must resolve "
                            "to a boolean or a light state with boolean on and optional level from 0 to 100"
                        )
                elif node.get("type") == "derived":
                    derived_inputs.append(value)
            if derived_valid and calculate_derived(node["operation"], derived_inputs) is None:
                errors.append(
                    f"{location}: derived {node['operation']} produces a non-finite value"
                )
    return errors


def load_samples(path: Path) -> dict[str, Any]:
    """Load a JSON object mapping MQTT topics to representative payloads."""
    samples = json.loads(path.read_text())
    if not isinstance(samples, dict) or not all(isinstance(topic, str) for topic in samples):
        raise ValueError("sample file must be a JSON object mapping MQTT topics to payloads")
    return samples


def main(argv: list[str] | None = None) -> int:
    """Run the dashboard/sample checker as a command-line tool."""
    parser = argparse.ArgumentParser(
        description="Check dashboard bindings against captured MQTT JSON payloads."
    )
    parser.add_argument(
        "--config", type=Path, default=Path(os.environ.get("RV_WEB_CONFIG", "config.yaml"))
    )
    parser.add_argument("--samples", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        config_path = args.config.resolve()
        settings = yaml.safe_load(config_path.read_text())
        if not isinstance(settings, dict):
            raise ValueError(f"{config_path}: configuration must be a mapping")
        dashboard_file = settings.get("dashboard_file", "dashboard.yaml")
        assets_directory = settings.get("assets_dir", "assets")
        if not isinstance(dashboard_file, str) or not isinstance(assets_directory, str):
            raise ValueError("dashboard_file and assets_dir must be paths")
        dashboard_path = config_path.parent / dashboard_file
        assets_path = (config_path.parent / assets_directory).resolve()
        dashboard, tab_topics = load_dashboard(dashboard_path, assets_path)
        samples = load_samples(args.samples)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"Dashboard check failed: {exc}", file=sys.stderr)
        return 1

    expected_topics = set().union(*tab_topics.values())
    errors = validate_samples(dashboard, samples, expected_topics)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    binding_count = sum(
        1
        for tab_index, tab in enumerate(dashboard["tabs"])
        for node, _ in iter_nodes(tab["root"], f"tabs[{tab_index}].root")
        for _ in iter_bindings(node)
    )
    print(
        f"Dashboard OK: {len(dashboard['tabs'])} tabs, {binding_count} bindings, "
        f"{len(expected_topics)} topics checked against samples."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
