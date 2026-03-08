from src.ingest.manual_parser import parse_deploy_events, parse_log_events


def test_parse_log_events_structured_format() -> None:
    text = (
        '2026-03-08T08:00:12Z service=checkout level=ERROR message="db timeout"\n'
        '2026-03-08T08:00:20Z service=payments level=WARN message="retry exhausted"'
    )
    events = parse_log_events(text, incident_id="inc-1")
    assert len(events) == 2
    assert events[0].service == "checkout"
    assert events[0].signal_type == "log_error"
    assert events[1].severity == "warning"


def test_parse_deploy_events_json_format() -> None:
    text = """
[
  {"timestamp":"2026-03-08T07:58:00Z","service":"checkout","version":"v142","action":"deploy"}
]
"""
    events = parse_deploy_events(text, incident_id="inc-2")
    assert len(events) == 1
    assert events[0].signal_type == "deploy"
    assert events[0].metadata["version"] == "v142"
