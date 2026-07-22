"""Performance Intelligence package — analytics-facing read models."""
from app.services.performance_intelligence.content_performance import (
    classify_relative_performance,
    compute_tenant_baseline,
    generate_recommendations,
)

__all__ = [
    "compute_tenant_baseline",
    "classify_relative_performance",
    "generate_recommendations",
]
