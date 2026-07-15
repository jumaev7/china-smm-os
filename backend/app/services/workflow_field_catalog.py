"""Safe typed field catalog for workflow condition evaluation.

Only allowlisted, non-secret top-level event fields may be referenced.
No nested path traversal, tokens, provider payloads, or database fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FieldType = Literal["string", "integer", "number", "boolean", "uuid", "enum", "string_list"]

COMMON_OPERATORS = frozenset({"equals", "not_equals", "exists", "not_exists"})
STRING_OPERATORS = frozenset({
    "contains", "not_contains", "starts_with", "ends_with", "in", "not_in",
})
NUMBER_OPERATORS = frozenset({
    "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal", "between",
})
BOOLEAN_OPERATORS = frozenset({"is_true", "is_false"})
LIST_OPERATORS = frozenset({"in", "not_in", "contains_any", "contains_all"})
ENUM_OPERATORS = frozenset({"in", "not_in"})

GROUP_OPERATORS = frozenset({"all", "any", "none"})


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    field_type: FieldType
    description: str = ""
    enum_values: frozenset[str] | None = None


def _ops_for_type(field_type: FieldType) -> frozenset[str]:
    if field_type == "string":
        return COMMON_OPERATORS | STRING_OPERATORS
    if field_type in {"integer", "number"}:
        return COMMON_OPERATORS | NUMBER_OPERATORS
    if field_type == "boolean":
        return COMMON_OPERATORS | BOOLEAN_OPERATORS
    if field_type == "uuid":
        return COMMON_OPERATORS | frozenset({"in", "not_in"})
    if field_type == "enum":
        return COMMON_OPERATORS | ENUM_OPERATORS
    if field_type == "string_list":
        return COMMON_OPERATORS | LIST_OPERATORS
    return COMMON_OPERATORS


# Canonical automation-enabled events only — must stay aligned with Event Registry.
_WORKFLOW_FIELD_CATALOG: dict[str, tuple[FieldDefinition, ...]] = {
    "tenant.content.publish_failed": (
        FieldDefinition("content_id", "uuid", "Content item id"),
        FieldDefinition("platform", "string", "Publishing platform"),
        FieldDefinition("failure_code", "string", "Structured failure code"),
        FieldDefinition("failure_category", "string", "Failure category"),
        FieldDefinition("retryable", "boolean", "Whether retry is advised"),
        FieldDefinition("attempt_number", "integer", "Publish attempt number"),
        FieldDefinition("source", "string", "Emitter source"),
        FieldDefinition("resource_name", "string", "Human-readable resource name"),
        FieldDefinition("channel", "string", "Channel alias"),
    ),
    "tenant.content.publish_partial_failed": (
        FieldDefinition("content_id", "uuid", "Content item id"),
        FieldDefinition("resource_name", "string", "Human-readable resource name"),
        FieldDefinition("success_count", "integer", "Successful platforms"),
        FieldDefinition("failure_count", "integer", "Failed platforms"),
        FieldDefinition("source", "string", "Emitter source"),
    ),
    "tenant.integration.disconnected": (
        FieldDefinition("provider", "string", "Integration provider"),
        FieldDefinition("platform", "string", "Platform alias"),
        FieldDefinition("disconnect_kind", "string", "Disconnect classification"),
        FieldDefinition("requires_reauthorization", "boolean", "Needs re-auth"),
        FieldDefinition("from_status", "string", "Previous status"),
        FieldDefinition("to_status", "string", "New status"),
        FieldDefinition("integration_name", "string", "Display name"),
        FieldDefinition("source", "string", "Emitter source"),
    ),
    "tenant.buyer.created": (
        FieldDefinition("buyer_id", "uuid", "Buyer id"),
        FieldDefinition("company_name", "string", "Company name"),
        FieldDefinition("company", "string", "Company alias"),
        FieldDefinition("country", "string", "Country"),
        FieldDefinition("industry", "string", "Industry"),
        FieldDefinition("source", "string", "Buyer source"),
        FieldDefinition("buyer_name", "string", "Buyer display name"),
    ),
    "tenant.crm.lead_created": (
        FieldDefinition("lead_id", "uuid", "Lead id"),
        FieldDefinition("lead_name", "string", "Lead name"),
        FieldDefinition("source", "string", "Lead source"),
        FieldDefinition("status", "string", "Lead status"),
        FieldDefinition("company_name", "string", "Company name"),
    ),
    "tenant.crm.deal_stage_changed": (
        FieldDefinition("deal_id", "uuid", "Deal id"),
        FieldDefinition("from_stage", "string", "Previous stage"),
        FieldDefinition("to_stage", "string", "New stage"),
        FieldDefinition("source", "string", "Emitter source"),
    ),
    "tenant.automation.triggered": (
        FieldDefinition("trigger_key", "string", "Trigger key"),
        FieldDefinition("source", "string", "Emitter source"),
        FieldDefinition("resource_name", "string", "Resource name"),
    ),
}


def list_workflow_trigger_events() -> list[str]:
    return sorted(_WORKFLOW_FIELD_CATALOG.keys())


def get_fields_for_event(event_type: str) -> dict[str, FieldDefinition]:
    fields = _WORKFLOW_FIELD_CATALOG.get(event_type)
    if not fields:
        return {}
    return {f.name: f for f in fields}


def is_workflow_trigger_supported(event_type: str) -> bool:
    return event_type in _WORKFLOW_FIELD_CATALOG


def get_field(event_type: str, field_name: str) -> FieldDefinition | None:
    return get_fields_for_event(event_type).get(field_name)


def operators_for_field(field: FieldDefinition) -> frozenset[str]:
    return _ops_for_type(field.field_type)


def operator_compatible(field: FieldDefinition, operator: str) -> bool:
    return operator in operators_for_field(field)


def extract_allowlisted_fields(event_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return only catalog fields present in the event payload (shallow)."""
    catalog = get_fields_for_event(event_type)
    if not catalog or not payload:
        return {}
    result: dict[str, Any] = {}
    for name in catalog:
        if name in payload:
            result[name] = payload[name]
    return result


def catalog_as_api() -> list[dict[str, Any]]:
    """Serialize catalog for frontend builder UI."""
    items: list[dict[str, Any]] = []
    for event_type, fields in sorted(_WORKFLOW_FIELD_CATALOG.items()):
        items.append({
            "event": event_type,
            "fields": [
                {
                    "name": f.name,
                    "type": f.field_type,
                    "description": f.description,
                    "operators": sorted(operators_for_field(f)),
                    "enum_values": sorted(f.enum_values) if f.enum_values else None,
                }
                for f in fields
            ],
        })
    return items
