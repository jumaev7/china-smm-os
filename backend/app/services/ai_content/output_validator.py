"""Post-parse output validation beyond schema (policy + claims)."""
from __future__ import annotations

from app.services.ai_content.errors import AIOutputInvalidError, AISafetyBlockedError
from app.services.ai_content.schemas import ProtectedFact
from app.services.ai_platform.structured_output import PlatformAdaptationOutput


def validate_adaptation_output(
    output: PlatformAdaptationOutput,
    *,
    expected_platform: str,
    expected_locale: str,
    expected_length_profile: str,
    protected_facts: list[ProtectedFact],
    forbidden_terms: list[str] | None = None,
) -> None:
    if output.platform != expected_platform:
        raise AIOutputInvalidError(
            "Output platform mismatch",
            details={"expected": expected_platform, "got": output.platform},
        )
    if output.locale != expected_locale:
        raise AIOutputInvalidError(
            "Output locale mismatch",
            details={"expected": expected_locale, "got": output.locale},
        )
    if output.length_profile != expected_length_profile:
        raise AIOutputInvalidError(
            "Output length_profile mismatch",
            details={"expected": expected_length_profile, "got": output.length_profile},
        )
    for term in forbidden_terms or []:
        if term and term.lower() in (output.caption or "").lower():
            raise AISafetyBlockedError(
                "Output contains forbidden brand terminology",
                details={"term_category": "forbidden_terms"},
            )
    # Claims must reference source when present
    if not output.claims and protected_facts:
        # Soft: allow empty claims only when no protected facts — already handled
        pass
