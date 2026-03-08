from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.models import Event


LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\S+)\s+service=(?P<service>[^\s]+)\s+level=(?P<level>[^\s]+)\s+message=\"?(?P<message>.*)\"?$"
)


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _severity_from_level(level: str) -> str:
    lvl = level.lower()
    if lvl in {"error", "critical", "fatal"}:
        return "critical"
    if lvl in {"warn", "warning"}:
        return "warning"
    return "info"


def parse_log_events(log_text: str, incident_id: str) -> list[Event]:
    events: list[Event] = []
    for idx, line in enumerate(log_text.splitlines()):
        line = line.strip()
        if not line:
            continue

        match = LOG_PATTERN.match(line)
        if match:
            timestamp = _parse_timestamp(match.group("timestamp"))
            service = match.group("service")
            level = match.group("level")
            message = match.group("message")
        else:
            # Fallback parser for free-form lines:
            # timestamp | service | level | message
            parts = [x.strip() for x in line.split("|")]
            if len(parts) < 4:
                continue
            timestamp = _parse_timestamp(parts[0])
            service = parts[1] or "unknown"
            level = parts[2] or "info"
            message = "|".join(parts[3:])

        events.append(
            Event(
                event_id=f"{incident_id}-log-{idx}",
                timestamp=timestamp,
                service=service,
                signal_type="log_error" if _severity_from_level(level) != "info" else "log",
                severity=_severity_from_level(level),
                title=f"log:{service}:{level.lower()}",
                message=message,
                source="manual_logs",
                metadata={"level": level.lower()},
                tags=["logs", level.lower()],
            )
        )
    return events


def _parse_deploy_json(payload: Any, incident_id: str) -> list[Event]:
    if not isinstance(payload, list):
        return []

    events: list[Event] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        ts_raw = str(item.get("timestamp", "")).strip()
        if not ts_raw:
            continue
        timestamp = _parse_timestamp(ts_raw)
        service = str(item.get("service", "unknown"))
        version = str(item.get("version", "unknown"))
        action = str(item.get("action", "deploy"))

        events.append(
            Event(
                event_id=f"{incident_id}-dep-{idx}",
                timestamp=timestamp,
                service=service,
                signal_type="deploy",
                severity="info",
                title=f"{action}:{service}:{version}",
                message=f"Deploy action '{action}' applied for service {service}",
                source="manual_deploy",
                metadata={"version": version, "action": action},
                tags=["deploy", action.lower()],
            )
        )
    return events


def parse_deploy_events(deploy_text: str, incident_id: str) -> list[Event]:
    stripped = deploy_text.strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None:
        json_events = _parse_deploy_json(parsed, incident_id=incident_id)
        if json_events:
            return json_events

    events: list[Event] = []
    for idx, line in enumerate(stripped.splitlines()):
        line = line.strip()
        if not line:
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 4:
            continue
        timestamp = _parse_timestamp(parts[0])
        service = parts[1] or "unknown"
        version = parts[2] or "unknown"
        action = parts[3] or "deploy"

        events.append(
            Event(
                event_id=f"{incident_id}-dep-{idx}",
                timestamp=timestamp,
                service=service,
                signal_type="deploy",
                severity="info",
                title=f"{action}:{service}:{version}",
                message=f"Deploy action '{action}' applied for service {service}",
                source="manual_deploy",
                metadata={"version": version, "action": action},
                tags=["deploy", action.lower()],
            )
        )
    return events
