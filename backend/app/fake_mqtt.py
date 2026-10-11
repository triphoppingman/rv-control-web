"""Publish configurable test telemetry for the selected dashboard."""

import argparse
import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiomqtt
import yaml

from .check_dashboard import MISSING, iter_bindings, iter_nodes, resolve_payload_path
from .dashboard import DashboardLoader, is_finite_number, load_dashboard


logger = logging.getLogger("rv_web.fake_mqtt")


@dataclass(frozen=True)
class TopicScenario:
    payload: Any
    interval_s: float
    qos: int
    retain: bool


def positive_number(value: Any, location: str) -> float:
    if not is_finite_number(value) or value <= 0:
        raise ValueError(f"{location}: must be a positive finite number")
    return float(value)


def validate_template(template: Any, location: str) -> None:
    """Validate static JSON payloads and explicitly marked value generators."""
    if isinstance(template, dict):
        if not all(isinstance(key, str) for key in template):
            raise ValueError(f"{location}: payload keys must be strings")
        if "generator" not in template:
            for key, value in template.items():
                validate_template(value, f"{location}.{key}")
            return
        generator = template["generator"]
        if not isinstance(generator, str):
            raise ValueError(f"{location}.generator: expected sine, ramp, or sequence")
        if generator == "sequence":
            allowed = {"generator", "values", "hold_s"}
            values = template.get("values")
            if not isinstance(values, list) or not values:
                raise ValueError(f"{location}.values: must be a non-empty list")
            for value in values:
                if isinstance(value, (dict, list)):
                    raise ValueError(f"{location}.values: expected scalar JSON values")
                validate_template(value, f"{location}.values")
            positive_number(template.get("hold_s"), f"{location}.hold_s")
        elif generator in {"sine", "ramp"}:
            allowed = {"generator", "min", "max", "period_s", "decimals"}
            minimum, maximum = template.get("min"), template.get("max")
            if (
                not is_finite_number(minimum)
                or not is_finite_number(maximum)
                or minimum >= maximum
                or not is_finite_number(maximum - minimum)
            ):
                raise ValueError(f"{location}: min and max must be finite with min < max")
            positive_number(template.get("period_s"), f"{location}.period_s")
            decimals = template.get("decimals", 1)
            if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 6:
                raise ValueError(f"{location}.decimals: must be an integer from 0 to 6")
        else:
            raise ValueError(f"{location}.generator: expected sine, ramp, or sequence")
        if set(template) - allowed:
            raise ValueError(f"{location}: unknown generator settings {sorted(set(template) - allowed)}")
    elif isinstance(template, list):
        for index, value in enumerate(template):
            validate_template(value, f"{location}[{index}]")
    elif template is not None and not isinstance(template, (str, bool)):
        if not is_finite_number(template):
            raise ValueError(f"{location}: expected a finite JSON value")


def render_payload(template: Any, elapsed_s: float) -> Any:
    """Evaluate generators using elapsed seconds, independent of publish rate."""
    if isinstance(template, list):
        return [render_payload(value, elapsed_s) for value in template]
    if not isinstance(template, dict):
        return template
    generator = template.get("generator")
    if generator is None:
        return {key: render_payload(value, elapsed_s) for key, value in template.items()}
    if generator == "sequence":
        values = template["values"]
        return values[int(elapsed_s / template["hold_s"]) % len(values)]
    fraction = (elapsed_s % template["period_s"]) / template["period_s"]
    if generator == "sine":
        fraction = (1 + math.sin(2 * math.pi * fraction)) / 2
    value = template["min"] + (template["max"] - template["min"]) * fraction
    decimals = template.get("decimals", 1)
    return int(round(value)) if decimals == 0 else round(value, decimals)


def sample_payloads(
    scenarios: dict[str, TopicScenario], elapsed_s: float = 0
) -> dict[str, Any]:
    return {topic: render_payload(scenario.payload, elapsed_s) for topic, scenario in scenarios.items()}


def load_scenarios(scenario_path: Path, dashboard_config: Path) -> dict[str, TopicScenario]:
    """Select only dashboard topics and reject missing or invalid bindings."""
    settings = yaml.safe_load(dashboard_config.read_text())
    if not isinstance(settings, dict):
        raise ValueError(f"{dashboard_config}: configuration must be a mapping")
    dashboard_file = settings.get("dashboard_file", "dashboard.yaml")
    assets_dir = settings.get("assets_dir", "assets")
    if not isinstance(dashboard_file, str) or not isinstance(assets_dir, str):
        raise ValueError(f"{dashboard_config}: dashboard_file and assets_dir must be paths")
    dashboard, tab_topics = load_dashboard(
        dashboard_config.parent / dashboard_file, dashboard_config.parent / assets_dir
    )
    expected_topics = set().union(*tab_topics.values())
    config = yaml.load(scenario_path.read_text(), Loader=DashboardLoader)
    if not isinstance(config, dict) or set(config) - {"interval_s", "topics"}:
        raise ValueError(f"{scenario_path}: expected interval_s and topics settings")
    topics = config.get("topics")
    if not isinstance(topics, dict) or not all(isinstance(topic, str) for topic in topics):
        raise ValueError(f"{scenario_path}: topics must be a mapping keyed by MQTT topic")
    missing = expected_topics - topics.keys()
    if missing:
        raise ValueError(f"{scenario_path}: missing dashboard topics: {', '.join(sorted(missing))}")
    default_interval = positive_number(config.get("interval_s", 1), "interval_s")
    scenarios: dict[str, TopicScenario] = {}
    for topic in sorted(expected_topics):
        entry = topics[topic]
        location = f"topics[{topic!r}]"
        if not topic or any(character in topic for character in ("+", "#", "\0")):
            raise ValueError(f"{location}: expected a concrete MQTT publish topic")
        if not isinstance(entry, dict) or "payload" not in entry:
            raise ValueError(f"{location}: payload is required")
        if set(entry) - {"payload", "interval_s", "qos", "retain"}:
            raise ValueError(f"{location}: unknown topic settings")
        interval = positive_number(entry.get("interval_s", default_interval), f"{location}.interval_s")
        qos = entry.get("qos", 0)
        if isinstance(qos, bool) or not isinstance(qos, int) or qos not in (0, 1, 2):
            raise ValueError(f"{location}.qos: expected 0, 1, or 2")
        retain = entry.get("retain", True)
        if not isinstance(retain, bool):
            raise ValueError(f"{location}.retain: expected true or false")
        validate_template(entry["payload"], f"{location}.payload")
        scenarios[topic] = TopicScenario(entry["payload"], interval, qos, retain)

    samples = sample_payloads(scenarios)
    errors: list[str] = []
    for index, tab in enumerate(dashboard["tabs"]):
        for node, location in iter_nodes(tab["root"], f"tabs[{index}].root"):
            for topic, path, numeric in iter_bindings(node):
                payload = samples[topic]
                value = resolve_payload_path(
                    payload if isinstance(payload, dict) else {"value": payload}, path
                )
                if value is MISSING or value is None:
                    errors.append(f"{location}: scenario {topic!r} has no value at {path!r}")
                elif numeric and node["type"] != "numeric" and not is_finite_number(value):
                    errors.append(f"{location}: scenario {topic!r} field {path!r} must be numeric")
                template = scenarios[topic].payload
                leaf = resolve_payload_path(
                    template if isinstance(template, dict) else {"value": template}, path
                )
                if isinstance(leaf, dict) and leaf.get("generator") == "sequence":
                    if any(
                        value is None or (
                            numeric and node["type"] != "numeric" and not is_finite_number(value)
                        )
                        for value in leaf["values"]
                    ):
                        errors.append(f"{location}: sequence at {topic!r} {path!r} has invalid binding values")
    if errors:
        raise ValueError("\n".join(errors))
    return scenarios


async def publish_forever(host: str, port: int, scenarios: dict[str, TopicScenario]) -> None:
    """Publish on per-topic schedules, retrying broker failures with backoff."""
    delay = 1
    started = time.monotonic()
    while True:
        try:
            async with aiomqtt.Client(
                hostname=host, port=port, identifier="rv-web-fake-telemetry", keepalive=30
            ) as broker:
                logger.info("Connected to %s:%s; publishing %s", host, port, ", ".join(scenarios))
                delay = 1
                due = {topic: time.monotonic() for topic in scenarios}
                while True:
                    now = time.monotonic()
                    for topic, scenario in scenarios.items():
                        if now >= due[topic]:
                            await broker.publish(
                                topic,
                                json.dumps(render_payload(scenario.payload, now - started), allow_nan=False),
                                qos=scenario.qos,
                                retain=scenario.retain,
                            )
                            due[topic] = now + scenario.interval_s
                    await asyncio.sleep(max(0, min(due.values()) - time.monotonic()))
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT unavailable: %s; retrying in %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("fake-mqtt.example.yaml"))
    parser.add_argument("--dashboard-config", type=Path, default=Path("config.test.yaml"))
    parser.add_argument("--host", default="127.0.0.1", help="test broker hostname")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--check", action="store_true", help="validate and print initial payloads without connecting")
    args = parser.parse_args(argv)
    if not args.host.strip():
        parser.error("--host must not be empty")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        scenarios = load_scenarios(args.scenario.resolve(), args.dashboard_config.resolve())
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    if args.check:
        print(json.dumps(sample_payloads(scenarios), indent=2, allow_nan=False))
        return
    if not scenarios:
        parser.error("selected dashboard has no MQTT topics to simulate")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(publish_forever(args.host, args.port, scenarios))
    except KeyboardInterrupt:
        logger.info("Stopped fake telemetry publisher")


if __name__ == "__main__":
    main()
