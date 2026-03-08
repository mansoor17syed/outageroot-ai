from datetime import datetime, timedelta, timezone

from src.models import Event
from src.scoring.causal_ranker import CausalRanker


def test_ranker_generates_edges_and_hypotheses() -> None:
    start = datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc)
    events = [
        Event(
            event_id="e1",
            timestamp=start,
            service="checkout",
            signal_type="deploy",
            severity="info",
            title="deploy:checkout:v142",
            tags=["deploy", "change_event"],
        ),
        Event(
            event_id="e2",
            timestamp=start + timedelta(minutes=2),
            service="checkout",
            signal_type="log_error",
            severity="critical",
            title="log:checkout:error",
            message="db timeout observed",
            tags=["logs", "database", "latency"],
        ),
        Event(
            event_id="e3",
            timestamp=start + timedelta(minutes=3),
            service="checkout",
            signal_type="alert",
            severity="warning",
            title="HighErrorRate",
            tags=["alert", "latency"],
        ),
    ]

    ranker = CausalRanker(score_threshold=0.50)
    edges = ranker.score_edges(events)
    hypotheses = ranker.rank_root_causes(events, edges)

    assert edges, "Expected at least one causal edge"
    assert hypotheses, "Expected ranked hypotheses"
    assert hypotheses[0].confidence >= 0.5
