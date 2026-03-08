from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request

from src.models import Event


class VertexEnricher:
    def __init__(self, project_id: str, location: str, model: str) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model

    def enrich_events(self, events: list[Event]) -> list[Event]:
        if not events:
            return events
        try:
            return self._enrich_with_vertex(events)
        except Exception:
            return [self._fallback_enrichment(ev) for ev in events]

    def _enrich_with_vertex(self, events: list[Event]) -> list[Event]:
        token = self._access_token()
        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{self.location}/publishers/google/models/{self.model}:generateContent"
        )

        compact_events = [
            {
                "event_id": e.event_id,
                "service": e.service,
                "signal_type": e.signal_type,
                "severity": e.severity,
                "message": e.message[:200],
                "title": e.title[:120],
            }
            for e in events
        ]

        prompt = (
            "You are an SRE enrichment engine. For each event, return JSON only as "
            '{"events":[{"event_id":"...","tags":["..."],"error_class":"...","component_hint":"..."}]} '
            f"for this input: {json.dumps(compact_events)}"
        )

        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        request = urllib.request.Request(
            url=url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))

        text = ""
        candidates = payload.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts and isinstance(parts[0], dict):
                text = parts[0].get("text", "")

        parsed = self._extract_json(text)
        event_updates = {entry.get("event_id"): entry for entry in parsed.get("events", []) if entry.get("event_id")}

        enriched: list[Event] = []
        for event in events:
            update = event_updates.get(event.event_id, {})
            tags = list(dict.fromkeys(event.tags + list(update.get("tags", []))))
            metadata = dict(event.metadata)
            if "error_class" in update:
                metadata["error_class"] = update["error_class"]
            if "component_hint" in update:
                metadata["component_hint"] = update["component_hint"]
            enriched.append(event.model_copy(update={"tags": tags, "metadata": metadata}))
        return enriched

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        if not text:
            return {"events": []}
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"events": []}

    @staticmethod
    def _fallback_enrichment(event: Event) -> Event:
        tags = list(event.tags)
        metadata = dict(event.metadata)
        message = (event.message or "").lower()
        title = (event.title or "").lower()
        blob = f"{message} {title}"

        if "oom" in blob or "memory" in blob:
            tags.append("memory")
            metadata["error_class"] = "resource_memory"
        if "timeout" in blob or "latency" in blob:
            tags.append("latency")
            metadata["error_class"] = metadata.get("error_class", "latency_timeout")
        if "connection" in blob or "db" in blob:
            tags.append("database")
            metadata["component_hint"] = "database"
        if event.signal_type == "deploy":
            tags.append("change_event")

        tags = list(dict.fromkeys(tags))
        return event.model_copy(update={"tags": tags, "metadata": metadata})

    @staticmethod
    def _access_token() -> str:
        result = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        token = result.strip()
        if not token:
            raise RuntimeError("Empty access token from gcloud")
        return token
