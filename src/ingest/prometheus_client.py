from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import Event


class PrometheusClient:
    def __init__(self, base_url: str, timeout_seconds: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def query_range(self, query: str, start: datetime, end: datetime, step: str = "30s") -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        return payload

    def query_instant(self, query: str, at: datetime | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"query": query}
        if at is not None:
            params["time"] = at.timestamp()

        response = requests.get(
            f"{self.base_url}/api/v1/query",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        return payload

    def fetch_events_from_query(
        self,
        query: str,
        start: datetime,
        end: datetime,
        incident_id: str,
        source_label: str = "prometheus",
    ) -> list[Event]:
        payload = self.query_range(query=query, start=start, end=end)
        results = payload.get("data", {}).get("result", [])
        events: list[Event] = []

        for series_idx, series in enumerate(results):
            metric = series.get("metric", {})
            values = series.get("values", [])
            service = metric.get("service") or metric.get("job") or "unknown"
            alert_name = metric.get("alertname", query[:60])

            for value_idx, point in enumerate(values):
                if not isinstance(point, list) or len(point) != 2:
                    continue
                ts, value_raw = point
                try:
                    val = float(value_raw)
                except (TypeError, ValueError):
                    continue
                if math.isclose(val, 0.0, abs_tol=1e-12):
                    continue

                ts_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                signal_type = "alert" if metric.get("alertname") else "metric_spike"
                severity = (metric.get("severity") or "warning").lower()
                event_id = f"{incident_id}-prom-{series_idx}-{value_idx}"

                events.append(
                    Event(
                        event_id=event_id,
                        timestamp=ts_dt,
                        service=service,
                        signal_type=signal_type,
                        severity=severity,
                        title=f"{alert_name} value={val:.3f}",
                        message=f"Prometheus query '{query}' produced non-zero value.",
                        source=source_label,
                        metadata={
                            "query": query,
                            "value": val,
                            "metric": metric,
                        },
                        tags=[metric.get("__name__", "metric"), signal_type],
                    )
                )
        return events
