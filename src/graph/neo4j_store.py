from __future__ import annotations

from datetime import datetime

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from src.models import CausalEdge, Event


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def healthcheck(self) -> bool:
        try:
            with self._driver.session() as session:
                result = session.run("RETURN 1 AS ok")
                return bool(result.single()["ok"])
        except Neo4jError:
            return False

    def ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.incident_id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE"
            )

    def write_incident_graph(self, incident_id: str, events: list[Event], edges: list[CausalEdge]) -> None:
        with self._driver.session() as session:
            session.run(
                """
                MERGE (i:Incident {incident_id: $incident_id})
                ON CREATE SET i.created_at = datetime()
                SET i.updated_at = datetime()
                """,
                incident_id=incident_id,
            )

            for event in events:
                session.run(
                    """
                    MERGE (e:Event {event_id: $event_id})
                    SET e.timestamp = datetime($timestamp),
                        e.service = $service,
                        e.signal_type = $signal_type,
                        e.severity = $severity,
                        e.title = $title,
                        e.message = $message,
                        e.source = $source,
                        e.tags = $tags
                    WITH e
                    MATCH (i:Incident {incident_id: $incident_id})
                    MERGE (i)-[:HAS_EVENT]->(e)
                    """,
                    incident_id=incident_id,
                    event_id=event.event_id,
                    timestamp=event.timestamp.isoformat(),
                    service=event.service,
                    signal_type=event.signal_type,
                    severity=event.severity,
                    title=event.title,
                    message=event.message,
                    source=event.source,
                    tags=event.tags,
                )

            for edge in edges:
                session.run(
                    """
                    MATCH (src:Event {event_id: $src})
                    MATCH (dst:Event {event_id: $dst})
                    MERGE (src)-[r:LIKELY_CAUSES]->(dst)
                    SET r.score = $score,
                        r.reason = $reason
                    """,
                    src=edge.source_event_id,
                    dst=edge.target_event_id,
                    score=edge.score,
                    reason=edge.reason,
                )

    def read_incident_graph(self, incident_id: str) -> dict[str, list[dict[str, object]]]:
        with self._driver.session() as session:
            node_result = session.run(
                """
                MATCH (i:Incident {incident_id: $incident_id})-[:HAS_EVENT]->(e:Event)
                RETURN e.event_id AS event_id,
                       e.timestamp AS timestamp,
                       e.service AS service,
                       e.signal_type AS signal_type,
                       e.severity AS severity,
                       e.title AS title
                ORDER BY e.timestamp
                """,
                incident_id=incident_id,
            )
            edge_result = session.run(
                """
                MATCH (:Incident {incident_id: $incident_id})-[:HAS_EVENT]->(src:Event)
                MATCH (:Incident {incident_id: $incident_id})-[:HAS_EVENT]->(dst:Event)
                MATCH (src)-[r:LIKELY_CAUSES]->(dst)
                RETURN src.event_id AS source_event_id,
                       dst.event_id AS target_event_id,
                       r.score AS score,
                       r.reason AS reason
                ORDER BY r.score DESC
                """,
                incident_id=incident_id,
            )

            nodes = []
            for row in node_result:
                ts = row["timestamp"]
                if isinstance(ts, datetime):
                    ts_text = ts.isoformat()
                else:
                    ts_text = str(ts)
                nodes.append(
                    {
                        "event_id": row["event_id"],
                        "timestamp": ts_text,
                        "service": row["service"],
                        "signal_type": row["signal_type"],
                        "severity": row["severity"],
                        "title": row["title"],
                    }
                )

            edges = [dict(row) for row in edge_result]
            return {"nodes": nodes, "edges": edges}
