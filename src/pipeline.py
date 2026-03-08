from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.ai.vertex_enricher import VertexEnricher
from src.graph.neo4j_store import Neo4jStore
from src.ingest.manual_parser import parse_deploy_events, parse_log_events
from src.ingest.prometheus_client import PrometheusClient
from src.models import IncidentResult
from src.scoring.causal_ranker import CausalRanker


@dataclass
class IncidentInput:
    incident_id: str
    start_time: datetime
    end_time: datetime
    prometheus_queries: list[str]
    logs_text: str
    deploy_text: str


class OutageRootPipeline:
    def __init__(
        self,
        prometheus_client: PrometheusClient,
        enricher: VertexEnricher,
        ranker: CausalRanker,
        graph_store: Neo4jStore | None = None,
    ) -> None:
        self.prometheus_client = prometheus_client
        self.enricher = enricher
        self.ranker = ranker
        self.graph_store = graph_store

    def run(self, incident_input: IncidentInput) -> IncidentResult:
        events = []
        for query in [q.strip() for q in incident_input.prometheus_queries if q.strip()]:
            try:
                events.extend(
                    self.prometheus_client.fetch_events_from_query(
                        query=query,
                        start=incident_input.start_time,
                        end=incident_input.end_time,
                        incident_id=incident_input.incident_id,
                    )
                )
            except Exception as exc:
                # Continue incident flow even if a query fails.
                events.extend(
                    parse_log_events(
                        log_text=(
                            f"{incident_input.start_time.isoformat()} service=prometheus level=ERROR "
                            f"message=\"query failed for '{query}': {exc}\""
                        ),
                        incident_id=incident_input.incident_id,
                    )
                )

        events.extend(parse_log_events(incident_input.logs_text, incident_input.incident_id))
        events.extend(parse_deploy_events(incident_input.deploy_text, incident_input.incident_id))

        # Keep deterministic ordering and remove potential duplicates by event_id.
        dedup = {event.event_id: event for event in sorted(events, key=lambda event: event.timestamp)}
        ordered_events = list(dedup.values())

        enriched_events = self.enricher.enrich_events(ordered_events)
        edges = self.ranker.score_edges(enriched_events)
        hypotheses = self.ranker.rank_root_causes(enriched_events, edges)
        summary = self._build_summary(hypotheses, total_events=len(enriched_events))

        if self.graph_store is not None:
            try:
                self.graph_store.ensure_constraints()
                self.graph_store.write_incident_graph(
                    incident_id=incident_input.incident_id,
                    events=enriched_events,
                    edges=edges,
                )
            except Exception:
                # Neo4j persistence is best-effort for MVP.
                pass

        return IncidentResult(
            incident_id=incident_input.incident_id,
            events=enriched_events,
            edges=edges,
            hypotheses=hypotheses,
            summary=summary,
        )

    @staticmethod
    def _build_summary(hypotheses, total_events: int) -> str:
        if not hypotheses:
            return (
                f"Processed {total_events} events. No strong root-cause hypothesis crossed "
                "the configured confidence threshold."
            )
        top = hypotheses[0]
        return (
            f"Processed {total_events} events. Top likely root cause: {top.summary} "
            f"(confidence={top.confidence:.2f})."
        )
