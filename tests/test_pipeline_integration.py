from datetime import datetime, timedelta, timezone

from src.models import Event
from src.pipeline import IncidentInput, OutageRootPipeline
from src.scoring.causal_ranker import CausalRanker


class FakePrometheusClient:
    def fetch_events_from_query(self, query, start, end, incident_id):  # noqa: ANN001
        return [
            Event(
                event_id=f"{incident_id}-p-1",
                timestamp=start + timedelta(minutes=1),
                service="checkout",
                signal_type="alert",
                severity="warning",
                title=f"query:{query}",
                message="alert fired",
                source="prometheus",
                tags=["alert"],
            )
        ]


class FakeEnricher:
    def enrich_events(self, events):  # noqa: ANN001
        return events


def test_pipeline_runs_end_to_end_without_neo4j() -> None:
    start = datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=10)
    incident_input = IncidentInput(
        incident_id="inc-it",
        start_time=start,
        end_time=end,
        prometheus_queries=['ALERTS{alertstate="firing"}'],
        logs_text='2026-03-08T08:02:00Z service=checkout level=ERROR message="db timeout"',
        deploy_text='2026-03-08T07:58:00Z|checkout|v142|deploy',
    )

    pipeline = OutageRootPipeline(
        prometheus_client=FakePrometheusClient(),
        enricher=FakeEnricher(),
        ranker=CausalRanker(score_threshold=0.45),
        graph_store=None,
    )
    result = pipeline.run(incident_input)

    assert result.events
    assert result.summary
