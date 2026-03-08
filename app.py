from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

import streamlit as st

from src.ai.vertex_enricher import VertexEnricher
from src.config import get_settings
from src.ingest.prometheus_client import PrometheusClient
from src.pipeline import IncidentInput, OutageRootPipeline
from src.scoring.causal_ranker import CausalRanker


def _datetime_picker(label: str, default_value: datetime, key_prefix: str) -> datetime:
    date_col, time_col = st.columns(2)
    with date_col:
        selected_date = st.date_input(
            f"{label} date (UTC)",
            value=default_value.date(),
            key=f"{key_prefix}_date",
        )
    with time_col:
        selected_time = st.time_input(
            f"{label} time (UTC)",
            value=default_value.time().replace(microsecond=0),
            key=f"{key_prefix}_time",
        )
    return datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)


def _build_dot(result) -> str:
    lines = ["digraph causalGraph {"]
    lines.append('rankdir="LR";')
    for event in result.events:
        label = f"{event.service}\\n{event.signal_type}\\n{event.severity}"
        lines.append(f'"{event.event_id}" [label="{label}"];')
    for edge in result.edges[:50]:
        lines.append(f'"{edge.source_event_id}" -> "{edge.target_event_id}" [label="{edge.score:.2f}"];')
    lines.append("}")
    return "\n".join(lines)


def _markdown_report(result) -> str:
    lines = [f"# OutageRoot Incident Report: {result.incident_id}", "", result.summary, ""]
    lines.append("## Top Hypotheses")
    if not result.hypotheses:
        lines.append("- No strong hypothesis found.")
    else:
        for idx, hyp in enumerate(result.hypotheses, start=1):
            lines.append(f"{idx}. **{hyp.summary}** (confidence: {hyp.confidence:.2f})")
            for check in hyp.recommended_checks:
                lines.append(f"   - {check}")
    lines.append("")
    lines.append("## Causal Edges")
    if not result.edges:
        lines.append("- No causal edges above threshold.")
    else:
        for edge in result.edges[:20]:
            lines.append(
                f"- `{edge.source_event_id}` -> `{edge.target_event_id}` "
                f"(score={edge.score:.2f}) | {edge.reason}"
            )
    lines.append("")
    lines.append(f"Total events analyzed: {len(result.events)}")
    return "\n".join(lines)


def _build_debug_summary(result) -> dict:
    by_source = Counter()
    by_signal = Counter()
    prom_by_query = defaultdict(int)

    for event in result.events:
        by_source[event.source or "unknown"] += 1
        by_signal[event.signal_type] += 1
        if event.source == "prometheus":
            query = str(event.metadata.get("query", "unknown"))
            prom_by_query[query] += 1

    return {
        "by_source": dict(by_source),
        "by_signal": dict(by_signal),
        "prom_by_query": dict(prom_by_query),
    }


def main() -> None:
    settings = get_settings()
    st.set_page_config(page_title="OutageRoot", layout="wide")
    st.title("OutageRoot")
    st.caption("From alert noise to causal graph in seconds")

    with st.sidebar:
        st.subheader("Environment")
        st.write(f"Prometheus: `{settings.prometheus_base_url}`")
        st.write(f"Neo4j: `{settings.neo4j_uri}`")
        st.write(f"Vertex model: `{settings.gcp_vertex_model}`")
        auto_last_15m = st.checkbox("Auto use last 15m (UTC)", value=True)
        if st.button("Load Kind Lab query pack"):
            st.session_state["prom_queries_text"] = "\n".join(
                [
                    "outageroot_error_rate",
                    "outageroot_latency_ms",
                    "outageroot_cpu_burst",
                    'up{job="pushgateway"}',
                    "up",
                ]
            )

    default_start = datetime.now(tz=timezone.utc) - timedelta(minutes=20)
    default_end = datetime.now(tz=timezone.utc)
    default_incident_id = f"inc-{uuid.uuid4().hex[:8]}"

    left, right = st.columns(2)
    with left:
        incident_id = st.text_input("Incident ID", value=default_incident_id)
        start_time = _datetime_picker("Start", default_start, "start")
    with right:
        end_time = _datetime_picker("End", default_end, "end")
        prom_queries_text = st.text_area(
            "Prometheus queries (one per line)",
            key="prom_queries_text",
            value='ALERTS{alertstate="firing"}\nrate(container_cpu_usage_seconds_total[5m])',
            height=100,
        )

    logs_text = st.text_area(
        "Manual logs",
        value=(
            "2026-03-08T08:00:12Z service=checkout level=ERROR "
            'message="db timeout during checkout"\n'
            "2026-03-08T08:00:20Z service=payments level=WARN "
            'message="retry budget exhausted"'
        ),
        height=140,
    )
    deploy_text = st.text_area(
        "Manual deploy events (JSON array or pipe-delimited)",
        value=json.dumps(
            [
                {
                    "timestamp": "2026-03-08T07:58:00Z",
                    "service": "checkout",
                    "version": "v142",
                    "action": "deploy",
                }
            ],
            indent=2,
        ),
        height=140,
    )

    run_clicked = st.button("Run OutageRoot Analysis", type="primary")
    if not run_clicked:
        return

    prom_client = PrometheusClient(
        base_url=settings.prometheus_base_url,
        timeout_seconds=settings.prometheus_timeout_seconds,
    )
    enricher = VertexEnricher(
        project_id=settings.gcp_project_id,
        location=settings.gcp_location,
        model=settings.gcp_vertex_model,
    )
    ranker = CausalRanker(
        time_decay_minutes=settings.causal_time_decay_minutes,
        score_threshold=settings.causal_score_threshold,
        prior_deploy=settings.causal_prior_deploy,
        prior_log_error=settings.causal_prior_log_error,
        prior_alert=settings.causal_prior_alert,
    )

    graph_store = None
    try:
        from src.graph.neo4j_store import Neo4jStore

        graph_store = Neo4jStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
    except ModuleNotFoundError as exc:
        st.warning(
            "Neo4j Python package is not installed in this runtime. "
            "Run `python -m pip install -r requirements.txt` from the outageroot venv."
        )
        st.caption(f"Details: {exc}")
    except Exception as exc:
        st.warning(f"Neo4j unavailable, running without persistence: {exc}")

    pipeline = OutageRootPipeline(
        prometheus_client=prom_client,
        enricher=enricher,
        ranker=ranker,
        graph_store=graph_store,
    )

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    if auto_last_15m:
        end_time = datetime.now(tz=timezone.utc)
        start_time = end_time - timedelta(minutes=15)
        st.info(
            f"Auto window applied: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC -> "
            f"{end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    incident_input = IncidentInput(
        incident_id=incident_id.strip() or default_incident_id,
        start_time=start_time,
        end_time=end_time,
        prometheus_queries=[line for line in prom_queries_text.splitlines() if line.strip()],
        logs_text=logs_text,
        deploy_text=deploy_text,
    )
    with st.spinner("Building causal graph..."):
        result = pipeline.run(incident_input)

    st.success(result.summary)

    top_col, graph_col = st.columns([1, 1])
    with top_col:
        st.subheader("Top root-cause hypotheses")
        if not result.hypotheses:
            st.info("No strong hypotheses found.")
        else:
            for hyp in result.hypotheses:
                with st.container(border=True):
                    st.write(f"**{hyp.summary}**")
                    st.write(f"Confidence: `{hyp.confidence:.2f}`")
                    if hyp.recommended_checks:
                        st.write("Recommended checks:")
                        for item in hyp.recommended_checks:
                            st.write(f"- {item}")

    with graph_col:
        st.subheader("Causal graph snapshot")
        if result.edges:
            st.graphviz_chart(_build_dot(result))
        else:
            st.info("No edges above score threshold.")

    st.subheader("Causal chain table")
    if result.edges:
        st.dataframe(
            [
                {
                    "source_event_id": edge.source_event_id,
                    "target_event_id": edge.target_event_id,
                    "score": edge.score,
                    "reason": edge.reason,
                }
                for edge in result.edges
            ],
            use_container_width=True,
        )
    else:
        st.write("No causal edges generated.")

    st.subheader("Normalized events")
    st.dataframe(
        [
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "service": event.service,
                "signal_type": event.signal_type,
                "severity": event.severity,
                "title": event.title,
                "tags": ", ".join(event.tags),
            }
            for event in result.events
        ],
        use_container_width=True,
    )

    st.subheader("Debug details")
    debug = _build_debug_summary(result)
    d1, d2 = st.columns(2)
    with d1:
        st.write("Events by source")
        st.json(debug["by_source"])
        st.write("Events by signal type")
        st.json(debug["by_signal"])
    with d2:
        st.write("Prometheus events by query")
        st.json(debug["prom_by_query"])
        if not debug["prom_by_query"]:
            st.warning(
                "No Prometheus events were generated from current queries/time window. "
                "Check UTC window, query names, and whether values are non-zero."
            )

    report_md = _markdown_report(result)
    st.download_button(
        label="Download incident report (.md)",
        data=report_md,
        file_name=f"{result.incident_id}_outageroot_report.md",
        mime="text/markdown",
    )

    if graph_store is not None:
        graph_store.close()


if __name__ == "__main__":
    main()
