"""Workflow definition validation — structural, type-safe, allowlisted."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.events.registry import event_registry
from app.models.automation import AUTOMATION_ACTION_TYPES
from app.models.workflow import (
    MAX_CONDITION_DEPTH,
    MAX_CONDITION_LIST_SIZE,
    MAX_CONDITION_STRING_LENGTH,
    MAX_CONDITIONS_PER_GROUP,
    MAX_TOTAL_CONDITIONS,
    MAX_WORKFLOW_STEPS,
    WORKFLOW_SCHEMA_VERSION,
    WORKFLOW_STEP_TYPES,
)
from app.services.automation_actions import validate_action_config
from app.services.workflow_field_catalog import (
    GROUP_OPERATORS,
    is_workflow_trigger_supported,
    get_field,
    operator_compatible,
)

_STEP_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
_SECRET_KEY_FRAGMENTS = ("token", "secret", "password", "authorization", "api_key", "bearer")


@dataclass
class ValidationErrorItem:
    code: str
    message: str
    path: str | None = None


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationErrorItem] = field(default_factory=list)
    normalized_definition: dict[str, Any] | None = None
    definition_hash: str | None = None

    def to_error_dicts(self) -> list[dict[str, Any]]:
        return [
            {"code": e.code, "message": e.message, "path": e.path}
            for e in self.errors
        ]


def definition_hash(definition: dict[str, Any]) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reject_secrets(obj: Any, path: str, errors: list[ValidationErrorItem]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SECRET_KEY_FRAGMENTS):
                errors.append(ValidationErrorItem(
                    "secret_not_allowed",
                    "Secret-bearing keys are not allowed in workflow definitions",
                    f"{path}.{key}",
                ))
            else:
                _reject_secrets(value, f"{path}.{key}", errors)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_secrets(item, f"{path}[{i}]", errors)


class WorkflowValidationService:
    """Validate Phase 1 workflow JSON definitions before publish/test."""

    @classmethod
    def validate(cls, definition: dict[str, Any] | None) -> ValidationResult:
        errors: list[ValidationErrorItem] = []
        if not isinstance(definition, dict):
            return ValidationResult(
                valid=False,
                errors=[ValidationErrorItem("invalid_definition", "Definition must be an object")],
            )

        _reject_secrets(definition, "definition", errors)

        schema_version = definition.get("schema_version")
        if schema_version != WORKFLOW_SCHEMA_VERSION:
            errors.append(ValidationErrorItem(
                "unsupported_schema_version",
                f"schema_version must be {WORKFLOW_SCHEMA_VERSION}",
                "schema_version",
            ))

        trigger = definition.get("trigger")
        if not isinstance(trigger, dict):
            errors.append(ValidationErrorItem("missing_trigger", "trigger is required", "trigger"))
            event_type = None
        else:
            event_type = trigger.get("event")
            if not isinstance(event_type, str) or not event_type:
                errors.append(ValidationErrorItem("missing_trigger_event", "trigger.event is required", "trigger.event"))
                event_type = None
            elif not event_registry.is_registered(event_type):
                errors.append(ValidationErrorItem(
                    "unknown_trigger_event",
                    "Trigger event is not a canonical Event Registry type",
                    "trigger.event",
                ))
            elif not is_workflow_trigger_supported(event_type):
                errors.append(ValidationErrorItem(
                    "unsupported_trigger_event",
                    "Trigger event is not in the workflow field catalog",
                    "trigger.event",
                ))

        conditions = definition.get("conditions")
        if conditions is not None and event_type:
            cls._validate_conditions(conditions, event_type, "conditions", errors, depth=1, counter={"n": 0})

        steps = definition.get("steps")
        if not isinstance(steps, list):
            errors.append(ValidationErrorItem("missing_steps", "steps must be a list", "steps"))
            steps = []
        elif len(steps) == 0:
            errors.append(ValidationErrorItem("empty_steps", "At least one action step is required", "steps"))
        elif len(steps) > MAX_WORKFLOW_STEPS:
            errors.append(ValidationErrorItem(
                "max_steps_exceeded",
                f"Maximum {MAX_WORKFLOW_STEPS} steps allowed",
                "steps",
            ))

        seen_ids: set[str] = set()
        normalized_steps: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            path = f"steps[{index}]"
            if not isinstance(step, dict):
                errors.append(ValidationErrorItem("invalid_step", "Step must be an object", path))
                continue
            step_id = step.get("id")
            if not isinstance(step_id, str) or not _STEP_ID_RE.match(step_id):
                errors.append(ValidationErrorItem(
                    "invalid_step_id",
                    "Step id must match [a-zA-Z][a-zA-Z0-9_]{0,63}",
                    f"{path}.id",
                ))
            elif step_id in seen_ids:
                errors.append(ValidationErrorItem("duplicate_step_id", "Step ids must be unique", f"{path}.id"))
            else:
                seen_ids.add(step_id)

            step_type = step.get("type")
            if step_type not in WORKFLOW_STEP_TYPES:
                errors.append(ValidationErrorItem(
                    "unsupported_step_type",
                    "Only type=action steps are supported in Phase 1 (branching deferred)",
                    f"{path}.type",
                ))
                continue

            action_type = step.get("action_type")
            if action_type not in AUTOMATION_ACTION_TYPES:
                errors.append(ValidationErrorItem(
                    "unsupported_action_type",
                    "Action type is not in the automation allowlist",
                    f"{path}.action_type",
                ))
                continue

            # Block recursive workflow triggers
            if action_type in {"trigger_workflow", "run_workflow", "execute_workflow"}:
                errors.append(ValidationErrorItem(
                    "recursive_workflow_forbidden",
                    "Recursive workflow actions are not allowed",
                    f"{path}.action_type",
                ))
                continue

            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            _reject_secrets(config, f"{path}.config", errors)
            try:
                normalized_config = validate_action_config(str(action_type), config)
            except ValueError as exc:
                errors.append(ValidationErrorItem(
                    "invalid_action_config",
                    str(exc),
                    f"{path}.config",
                ))
                normalized_config = dict(config)

            normalized_steps.append({
                "id": step_id if isinstance(step_id, str) else f"step_{index + 1}",
                "type": "action",
                "action_type": action_type,
                "config": normalized_config,
            })

        # Reject unsupported top-level keys that imply graphs/code
        for forbidden in ("edges", "graph", "code", "script", "imports", "cron", "webhook", "http"):
            if forbidden in definition:
                errors.append(ValidationErrorItem(
                    "unsupported_definition_key",
                    f"Key '{forbidden}' is not supported",
                    forbidden,
                ))

        failure_policy = definition.get("failure_policy", "stop_on_failure")
        if failure_policy != "stop_on_failure":
            errors.append(ValidationErrorItem(
                "unsupported_failure_policy",
                "Only stop_on_failure is supported in Phase 1",
                "failure_policy",
            ))

        if errors:
            return ValidationResult(valid=False, errors=errors)

        normalized = {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "trigger": {"event": event_type},
            "conditions": conditions if isinstance(conditions, dict) else {"operator": "all", "items": []},
            "steps": normalized_steps,
            "failure_policy": "stop_on_failure",
        }
        return ValidationResult(
            valid=True,
            errors=[],
            normalized_definition=normalized,
            definition_hash=definition_hash(normalized),
        )

    @classmethod
    def _validate_conditions(
        cls,
        node: Any,
        event_type: str,
        path: str,
        errors: list[ValidationErrorItem],
        *,
        depth: int,
        counter: dict[str, int],
    ) -> None:
        if depth > MAX_CONDITION_DEPTH:
            errors.append(ValidationErrorItem(
                "max_condition_depth_exceeded",
                f"Maximum condition depth is {MAX_CONDITION_DEPTH}",
                path,
            ))
            return
        if not isinstance(node, dict):
            errors.append(ValidationErrorItem("invalid_condition", "Condition must be an object", path))
            return

        operator = node.get("operator")
        if operator not in GROUP_OPERATORS:
            errors.append(ValidationErrorItem(
                "invalid_group_operator",
                "Condition group operator must be all|any|none",
                f"{path}.operator",
            ))
            return

        items = node.get("items")
        if not isinstance(items, list):
            errors.append(ValidationErrorItem(
                "invalid_group_items",
                "Condition group items must be a list",
                f"{path}.items",
            ))
            return
        if len(items) > MAX_CONDITIONS_PER_GROUP:
            errors.append(ValidationErrorItem(
                "max_conditions_per_group_exceeded",
                f"Maximum {MAX_CONDITIONS_PER_GROUP} conditions per group",
                f"{path}.items",
            ))

        for index, item in enumerate(items):
            item_path = f"{path}.items[{index}]"
            if not isinstance(item, dict):
                errors.append(ValidationErrorItem("invalid_condition_item", "Item must be an object", item_path))
                continue
            if "items" in item and "operator" in item:
                cls._validate_conditions(
                    item, event_type, item_path, errors, depth=depth + 1, counter=counter,
                )
                continue

            counter["n"] += 1
            if counter["n"] > MAX_TOTAL_CONDITIONS:
                errors.append(ValidationErrorItem(
                    "max_total_conditions_exceeded",
                    f"Maximum {MAX_TOTAL_CONDITIONS} conditions allowed",
                    item_path,
                ))
                return

            field_name = item.get("field")
            op = item.get("op") or item.get("operator")
            if not isinstance(field_name, str):
                errors.append(ValidationErrorItem("missing_field", "field is required", f"{item_path}.field"))
                continue
            if "." in field_name or "[" in field_name:
                errors.append(ValidationErrorItem(
                    "arbitrary_path_forbidden",
                    "Nested or arbitrary field paths are not allowed",
                    f"{item_path}.field",
                ))
                continue
            field_def = get_field(event_type, field_name)
            if field_def is None:
                errors.append(ValidationErrorItem(
                    "unknown_field",
                    "Field is not in the trigger field catalog",
                    f"{item_path}.field",
                ))
                continue
            if not isinstance(op, str) or not operator_compatible(field_def, op):
                errors.append(ValidationErrorItem(
                    "incompatible_operator",
                    "Operator is not compatible with field type",
                    f"{item_path}.op",
                ))
                continue

            value = item.get("value")
            if op in {"exists", "not_exists", "is_true", "is_false"}:
                continue
            if op in {"in", "not_in", "contains_any", "contains_all", "between"}:
                if not isinstance(value, list):
                    errors.append(ValidationErrorItem(
                        "value_must_be_list",
                        "This operator requires a list value",
                        f"{item_path}.value",
                    ))
                elif len(value) > MAX_CONDITION_LIST_SIZE:
                    errors.append(ValidationErrorItem(
                        "max_list_size_exceeded",
                        f"Maximum list size is {MAX_CONDITION_LIST_SIZE}",
                        f"{item_path}.value",
                    ))
                elif op == "between" and len(value) != 2:
                    errors.append(ValidationErrorItem(
                        "between_requires_two",
                        "between requires exactly two numbers",
                        f"{item_path}.value",
                    ))
            elif isinstance(value, str) and len(value) > MAX_CONDITION_STRING_LENGTH:
                errors.append(ValidationErrorItem(
                    "max_string_length_exceeded",
                    f"Maximum string length is {MAX_CONDITION_STRING_LENGTH}",
                    f"{item_path}.value",
                ))
            elif field_def.field_type in {"integer", "number"} and op in {
                "equals", "not_equals", "greater_than", "greater_than_or_equal",
                "less_than", "less_than_or_equal",
            }:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(ValidationErrorItem(
                        "type_mismatch",
                        "Numeric field requires a numeric value",
                        f"{item_path}.value",
                    ))
            elif field_def.field_type == "boolean" and op in {"equals", "not_equals"} and not isinstance(value, bool):
                errors.append(ValidationErrorItem(
                    "type_mismatch",
                    "Boolean field requires a boolean value",
                    f"{item_path}.value",
                ))
