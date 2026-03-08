from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    event_id: str
    timestamp: datetime
    service: str = "unknown"
    signal_type: str
    severity: str = "info"
    title: str = ""
    message: str = ""
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class CausalEdge(BaseModel):
    source_event_id: str
    target_event_id: str
    score: float
    reason: str


class RootCauseHypothesis(BaseModel):
    event_id: str
    service: str
    summary: str
    confidence: float
    evidence_event_ids: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)


class IncidentResult(BaseModel):
    incident_id: str
    events: list[Event]
    edges: list[CausalEdge]
    hypotheses: list[RootCauseHypothesis]
    summary: str
