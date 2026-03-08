from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    prometheus_base_url: str = os.getenv("PROMETHEUS_BASE_URL", "http://localhost:9090")
    prometheus_timeout_seconds: int = int(os.getenv("PROMETHEUS_TIMEOUT_SECONDS", "15"))

    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "outageroot")

    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "")
    gcp_location: str = os.getenv("GCP_LOCATION", "us-central1")
    gcp_vertex_model: str = os.getenv("GCP_VERTEX_MODEL", "gemini-2.0-flash")

    causal_time_decay_minutes: float = float(os.getenv("CAUSAL_TIME_DECAY_MINUTES", "30"))
    causal_score_threshold: float = float(os.getenv("CAUSAL_SCORE_THRESHOLD", "0.55"))
    causal_prior_deploy: float = float(os.getenv("CAUSAL_PRIOR_DEPLOY", "0.65"))
    causal_prior_log_error: float = float(os.getenv("CAUSAL_PRIOR_LOG_ERROR", "0.55"))
    causal_prior_alert: float = float(os.getenv("CAUSAL_PRIOR_ALERT", "0.40"))


def get_settings() -> Settings:
    return Settings()
