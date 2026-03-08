from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from src.models import CausalEdge, Event, RootCauseHypothesis


class CausalRanker:
    def __init__(
        self,
        time_decay_minutes: float = 30.0,
        score_threshold: float = 0.55,
        prior_deploy: float = 0.65,
        prior_log_error: float = 0.55,
        prior_alert: float = 0.40,
    ) -> None:
        self.time_decay_minutes = max(time_decay_minutes, 1.0)
        self.score_threshold = score_threshold
        self.priors = {
            "deploy": prior_deploy,
            "log_error": prior_log_error,
            "alert": prior_alert,
        }

    def _prior(self, signal_type: str) -> float:
        return self.priors.get(signal_type, 0.35)

    @staticmethod
    def _sigmoid(value: float) -> float:
        return 1.0 / (1.0 + math.exp(-value))

    def _time_decay(self, src_ts: datetime, dst_ts: datetime) -> float:
        delta_minutes = (dst_ts - src_ts).total_seconds() / 60.0
        if delta_minutes < 0:
            return 0.0
        return math.exp(-delta_minutes / self.time_decay_minutes)

    @staticmethod
    def _service_proximity(src: Event, dst: Event) -> float:
        if src.service == dst.service:
            return 1.0
        if src.service == "unknown" or dst.service == "unknown":
            return 0.5
        return 0.7

    @staticmethod
    def _semantic_overlap(src: Event, dst: Event) -> float:
        src_tags = set(src.tags)
        dst_tags = set(dst.tags)
        if not src_tags or not dst_tags:
            return 0.3
        intersection = len(src_tags.intersection(dst_tags))
        union = len(src_tags.union(dst_tags))
        return intersection / union if union else 0.3

    def score_edges(self, events: list[Event]) -> list[CausalEdge]:
        sorted_events = sorted(events, key=lambda ev: ev.timestamp)
        edges: list[CausalEdge] = []

        for src_idx, src in enumerate(sorted_events):
            for dst in sorted_events[src_idx + 1 :]:
                time_component = self._time_decay(src.timestamp, dst.timestamp)
                if time_component <= 0:
                    continue
                service_component = self._service_proximity(src, dst)
                semantic_component = self._semantic_overlap(src, dst)

                # Weighted log-odds style score.
                logit = (
                    1.5 * (self._prior(src.signal_type) - 0.5)
                    + 1.2 * (time_component - 0.5)
                    + 0.8 * (service_component - 0.5)
                    + 0.8 * (semantic_component - 0.5)
                )
                score = self._sigmoid(logit)
                if score < self.score_threshold:
                    continue

                reason = (
                    f"prior={self._prior(src.signal_type):.2f}, "
                    f"time={time_component:.2f}, "
                    f"service={service_component:.2f}, "
                    f"semantic={semantic_component:.2f}"
                )
                edges.append(
                    CausalEdge(
                        source_event_id=src.event_id,
                        target_event_id=dst.event_id,
                        score=round(score, 4),
                        reason=reason,
                    )
                )
        return sorted(edges, key=lambda edge: edge.score, reverse=True)

    def rank_root_causes(self, events: list[Event], edges: list[CausalEdge]) -> list[RootCauseHypothesis]:
        event_by_id = {event.event_id: event for event in events}
        outgoing_score = defaultdict(float)
        evidence = defaultdict(list)

        for edge in edges:
            outgoing_score[edge.source_event_id] += edge.score
            evidence[edge.source_event_id].append(edge.target_event_id)

        hypotheses: list[RootCauseHypothesis] = []
        for event_id, score_sum in outgoing_score.items():
            event = event_by_id.get(event_id)
            if event is None:
                continue

            confidence = min(0.99, score_sum / max(len(evidence[event_id]), 1))
            checks = self._recommended_checks(event)
            hypotheses.append(
                RootCauseHypothesis(
                    event_id=event.event_id,
                    service=event.service,
                    summary=f"{event.signal_type} on {event.service}: {event.title}",
                    confidence=round(confidence, 4),
                    evidence_event_ids=evidence[event_id][:5],
                    recommended_checks=checks,
                )
            )

        hypotheses.sort(key=lambda hyp: hyp.confidence, reverse=True)
        return hypotheses[:3]

    @staticmethod
    def _recommended_checks(event: Event) -> list[str]:
        checks = [f"Inspect service '{event.service}' around {event.timestamp.isoformat()}"]
        if event.signal_type == "deploy":
            checks.extend(
                [
                    f"Review deploy metadata: {event.metadata}",
                    f"Validate rollback strategy for {event.service}",
                ]
            )
        elif event.signal_type == "log_error":
            checks.extend(
                [
                    f"Search logs for repeated pattern: '{event.message[:80]}'",
                    "Check pod restart and OOM events in the same window",
                ]
            )
        else:
            checks.extend(
                [
                    "Verify alert rule threshold and recent baseline values",
                    "Cross-check dependency health for adjacent services",
                ]
            )
        return checks
