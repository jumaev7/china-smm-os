"""Typed internal contracts for Business Health v2."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

AvailabilityStatus = Literal[
    "available",
    "unavailable",
    "not_configured",
    "error",
]

FreshnessStatus = Literal[
    "fresh",
    "aging",
    "stale",
    "unavailable",
    "mixed",
    "unknown",
]


@dataclass(frozen=True)
class HealthSignal:
    code: str
    domain: str
    severity: Literal["critical", "high", "medium", "low", "positive"]
    title: str
    explanation: str
    score_impact: int
    observed_value: Any = None
    threshold: Any = None
    entity_ref: dict[str, Any] | None = None
    observed_at: datetime | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.observed_at is not None:
            data["observed_at"] = self.observed_at.isoformat()
        return data


@dataclass
class DomainHealthAssessment:
    domain: str
    label: str
    weight: float
    effective_weight: float = 0.0
    availability: AvailabilityStatus = "unavailable"
    unavailable_reason: str | None = None
    score: int | None = None
    status: str | None = None
    summary: str = ""
    observed_metrics: dict[str, Any] = field(default_factory=dict)
    deductions: list[HealthSignal] = field(default_factory=list)
    positive_signals: list[HealthSignal] = field(default_factory=list)
    freshness: FreshnessStatus = "unknown"
    confidence: float = 0.0  # 0..1 coverage within domain

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "label": self.label,
            "weight": round(self.weight, 4),
            "effective_weight": round(self.effective_weight, 4),
            "availability": self.availability,
            "unavailable_reason": self.unavailable_reason,
            "score": self.score,
            "status": self.status,
            "summary": self.summary,
            "observed_metrics": self.observed_metrics,
            "deductions": [d.to_dict() for d in self.deductions],
            "positive_signals": [p.to_dict() for p in self.positive_signals],
            "freshness": self.freshness,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class BusinessHealthAssessment:
    score: int
    status: str
    calculated_at: datetime
    methodology_version: str
    data_confidence: float
    domains_evaluated: int
    domains_unavailable: int
    domains: list[DomainHealthAssessment] = field(default_factory=list)
    deductions: list[HealthSignal] = field(default_factory=list)
    positive_signals: list[HealthSignal] = field(default_factory=list)
    executive_summary: str = ""
    previous_score: int | None = None
    change: int | None = None
    history_available: bool = False
    disclaimer: str = ""
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": self.status,
            "calculated_at": self.calculated_at.isoformat(),
            "methodology_version": self.methodology_version,
            "data_confidence": round(self.data_confidence, 4),
            "domains_evaluated": self.domains_evaluated,
            "domains_unavailable": self.domains_unavailable,
            "domains": [d.to_dict() for d in self.domains],
            "deductions": [d.to_dict() for d in self.deductions],
            "positive_signals": [p.to_dict() for p in self.positive_signals],
            "executive_summary": self.executive_summary,
            "previous_score": self.previous_score,
            "change": self.change,
            "history_available": self.history_available,
            "disclaimer": self.disclaimer,
            "duration_ms": self.duration_ms,
        }
