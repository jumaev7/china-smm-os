"""Deterministic safe workflow rules engine — no eval, no DB, no side effects."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.workflow import (
    MAX_CONDITION_DEPTH,
    MAX_CONDITION_LIST_SIZE,
    MAX_CONDITION_STRING_LENGTH,
    MAX_CONDITIONS_PER_GROUP,
    MAX_TOTAL_CONDITIONS,
)
from app.services.workflow_field_catalog import (
    GROUP_OPERATORS,
    extract_allowlisted_fields,
    get_field,
    operator_compatible,
)


@dataclass
class ConditionEvalRecord:
    condition_id: str
    matched: bool | None
    reason: str | None = None


@dataclass
class RulesEvaluationResult:
    matched: bool
    status: str  # matched | not_matched | invalid_input
    evaluated_conditions: list[ConditionEvalRecord] = field(default_factory=list)
    failed_condition_ids: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value)


def _coerce_uuid_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class WorkflowRuleEngine:
    """Pure condition-tree evaluator over allowlisted event fields."""

    @classmethod
    def evaluate(
        cls,
        *,
        event_type: str,
        payload: dict[str, Any] | None,
        conditions: dict[str, Any] | None,
    ) -> RulesEvaluationResult:
        records: list[ConditionEvalRecord] = []
        failed: list[str] = []

        if not conditions:
            return RulesEvaluationResult(
                matched=True,
                status="matched",
                evaluated_conditions=records,
                failed_condition_ids=failed,
                diagnostics={"empty_conditions": True},
            )

        if not isinstance(conditions, dict):
            return RulesEvaluationResult(
                matched=False,
                status="invalid_input",
                diagnostics={"error": "conditions_must_be_object"},
            )

        allowlisted = extract_allowlisted_fields(event_type, payload)
        counter = {"n": 0}

        try:
            matched = cls._eval_group(
                event_type=event_type,
                allowlisted=allowlisted,
                node=conditions,
                depth=1,
                records=records,
                failed=failed,
                counter=counter,
            )
        except _RulesLimitError as exc:
            return RulesEvaluationResult(
                matched=False,
                status="invalid_input",
                evaluated_conditions=records,
                failed_condition_ids=failed,
                diagnostics={"error": str(exc)},
            )
        except _RulesTypeError as exc:
            return RulesEvaluationResult(
                matched=False,
                status="invalid_input",
                evaluated_conditions=records,
                failed_condition_ids=failed,
                diagnostics={"error": str(exc)},
            )

        return RulesEvaluationResult(
            matched=bool(matched),
            status="matched" if matched else "not_matched",
            evaluated_conditions=records,
            failed_condition_ids=failed,
            diagnostics={
                "condition_count": counter["n"],
                "field_count": len(allowlisted),
            },
        )

    @classmethod
    def _eval_group(
        cls,
        *,
        event_type: str,
        allowlisted: dict[str, Any],
        node: dict[str, Any],
        depth: int,
        records: list[ConditionEvalRecord],
        failed: list[str],
        counter: dict[str, int],
    ) -> bool:
        if depth > MAX_CONDITION_DEPTH:
            raise _RulesLimitError("max_condition_depth_exceeded")

        operator = node.get("operator")
        if operator not in GROUP_OPERATORS:
            raise _RulesTypeError("invalid_group_operator")

        items = node.get("items")
        if not isinstance(items, list):
            raise _RulesTypeError("group_items_must_be_list")
        if len(items) > MAX_CONDITIONS_PER_GROUP:
            raise _RulesLimitError("max_conditions_per_group_exceeded")

        results: list[bool] = []
        for item in items:
            if not isinstance(item, dict):
                raise _RulesTypeError("condition_item_must_be_object")
            if "operator" in item and "items" in item:
                results.append(
                    cls._eval_group(
                        event_type=event_type,
                        allowlisted=allowlisted,
                        node=item,
                        depth=depth + 1,
                        records=records,
                        failed=failed,
                        counter=counter,
                    )
                )
            else:
                results.append(
                    cls._eval_leaf(
                        event_type=event_type,
                        allowlisted=allowlisted,
                        node=item,
                        records=records,
                        failed=failed,
                        counter=counter,
                    )
                )

        if operator == "all":
            return all(results) if results else True
        if operator == "any":
            return any(results) if results else False
        # none — no child matches
        return not any(results) if results else True

    @classmethod
    def _eval_leaf(
        cls,
        *,
        event_type: str,
        allowlisted: dict[str, Any],
        node: dict[str, Any],
        records: list[ConditionEvalRecord],
        failed: list[str],
        counter: dict[str, int],
    ) -> bool:
        counter["n"] += 1
        if counter["n"] > MAX_TOTAL_CONDITIONS:
            raise _RulesLimitError("max_total_conditions_exceeded")

        condition_id = str(node.get("id") or f"cond_{counter['n']}")
        field_name = node.get("field")
        operator = node.get("op") or node.get("operator")
        expected = node.get("value")

        if not isinstance(field_name, str) or not field_name:
            records.append(ConditionEvalRecord(condition_id, False, "missing_field"))
            failed.append(condition_id)
            return False

        field_def = get_field(event_type, field_name)
        if field_def is None:
            records.append(ConditionEvalRecord(condition_id, False, "field_not_allowlisted"))
            failed.append(condition_id)
            return False

        if not isinstance(operator, str) or not operator_compatible(field_def, operator):
            records.append(ConditionEvalRecord(condition_id, False, "operator_incompatible"))
            failed.append(condition_id)
            return False

        exists = field_name in allowlisted
        actual = allowlisted.get(field_name) if exists else None

        try:
            matched = cls._apply_operator(
                field_type=field_def.field_type,
                operator=operator,
                exists=exists,
                actual=actual,
                expected=expected,
            )
        except _RulesTypeError:
            records.append(ConditionEvalRecord(condition_id, False, "type_mismatch"))
            failed.append(condition_id)
            return False

        records.append(ConditionEvalRecord(condition_id, matched, None if matched else "not_matched"))
        if not matched:
            failed.append(condition_id)
        return matched

    @classmethod
    def _apply_operator(
        cls,
        *,
        field_type: str,
        operator: str,
        exists: bool,
        actual: Any,
        expected: Any,
    ) -> bool:
        if operator == "exists":
            return exists and actual is not None
        if operator == "not_exists":
            return (not exists) or actual is None

        if not exists:
            return False

        if operator == "is_true":
            if not isinstance(actual, bool):
                raise _RulesTypeError("boolean_required")
            return actual is True
        if operator == "is_false":
            if not isinstance(actual, bool):
                raise _RulesTypeError("boolean_required")
            return actual is False

        if operator in {"equals", "not_equals"}:
            ok = cls._values_equal(field_type, actual, expected)
            return ok if operator == "equals" else not ok

        if field_type in {"string", "uuid", "enum"}:
            return cls._string_ops(operator, actual, expected)

        if field_type in {"integer", "number"}:
            return cls._number_ops(operator, actual, expected)

        if field_type == "string_list":
            return cls._list_ops(operator, actual, expected)

        if field_type == "boolean":
            if operator in {"equals", "not_equals"}:
                if not isinstance(actual, bool) or not isinstance(expected, bool):
                    raise _RulesTypeError("boolean_required")
                return (actual == expected) if operator == "equals" else (actual != expected)

        raise _RulesTypeError("unsupported_operator")

    @classmethod
    def _values_equal(cls, field_type: str, actual: Any, expected: Any) -> bool:
        if field_type == "boolean":
            if not isinstance(actual, bool) or not isinstance(expected, bool):
                raise _RulesTypeError("boolean_required")
            return actual is expected
        if field_type in {"integer", "number"}:
            if not _is_number(actual) or not _is_number(expected):
                raise _RulesTypeError("number_required")
            return float(actual) == float(expected)
        if field_type == "string_list":
            if not isinstance(actual, list) or not isinstance(expected, list):
                raise _RulesTypeError("list_required")
            return [str(x) for x in actual] == [str(x) for x in expected]
        left = _as_str(actual) if field_type != "uuid" else _coerce_uuid_str(actual)
        right = _as_str(expected) if field_type != "uuid" else _coerce_uuid_str(expected)
        if left is None or right is None:
            raise _RulesTypeError("string_required")
        return left == right

    @classmethod
    def _string_ops(cls, operator: str, actual: Any, expected: Any) -> bool:
        left = _as_str(actual)
        if left is None:
            raise _RulesTypeError("string_required")
        if len(left) > MAX_CONDITION_STRING_LENGTH:
            raise _RulesLimitError("max_string_length_exceeded")

        if operator in {"in", "not_in"}:
            if not isinstance(expected, list):
                raise _RulesTypeError("list_required")
            if len(expected) > MAX_CONDITION_LIST_SIZE:
                raise _RulesLimitError("max_list_size_exceeded")
            members = {_as_str(x) for x in expected}
            ok = left in members
            return ok if operator == "in" else not ok

        right = _as_str(expected)
        if right is None:
            raise _RulesTypeError("string_required")
        if len(right) > MAX_CONDITION_STRING_LENGTH:
            raise _RulesLimitError("max_string_length_exceeded")

        if operator == "contains":
            return right in left
        if operator == "not_contains":
            return right not in left
        if operator == "starts_with":
            return left.startswith(right)
        if operator == "ends_with":
            return left.endswith(right)
        raise _RulesTypeError("unsupported_string_operator")

    @classmethod
    def _number_ops(cls, operator: str, actual: Any, expected: Any) -> bool:
        if not _is_number(actual):
            raise _RulesTypeError("number_required")
        value = float(actual)

        if operator == "between":
            if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                raise _RulesTypeError("between_requires_two_numbers")
            if not _is_number(expected[0]) or not _is_number(expected[1]):
                raise _RulesTypeError("number_required")
            low, high = float(expected[0]), float(expected[1])
            return low <= value <= high

        if not _is_number(expected):
            raise _RulesTypeError("number_required")
        target = float(expected)
        if operator == "greater_than":
            return value > target
        if operator == "greater_than_or_equal":
            return value >= target
        if operator == "less_than":
            return value < target
        if operator == "less_than_or_equal":
            return value <= target
        raise _RulesTypeError("unsupported_number_operator")

    @classmethod
    def _list_ops(cls, operator: str, actual: Any, expected: Any) -> bool:
        if not isinstance(actual, list):
            raise _RulesTypeError("list_required")
        if len(actual) > MAX_CONDITION_LIST_SIZE:
            raise _RulesLimitError("max_list_size_exceeded")
        actual_set = {str(x) for x in actual}

        if operator in {"in", "not_in"}:
            # For string_list field: "in" means actual list equals membership check against expected list
            # Treat as: any overlap with expected for contains_any; here in = expected is member of actual? 
            # Spec: list operators contains_any/contains_all; in/not_in compare scalar membership.
            # For string_list, in/not_in compare the list as a whole equality set membership of expected list items.
            if not isinstance(expected, list):
                # scalar membership: expected string is in actual list
                right = _as_str(expected)
                if right is None:
                    raise _RulesTypeError("string_required")
                ok = right in actual_set
                return ok if operator == "in" else not ok
            expected_set = {str(x) for x in expected}
            ok = actual_set == expected_set
            return ok if operator == "in" else not ok

        if not isinstance(expected, list):
            raise _RulesTypeError("list_required")
        if len(expected) > MAX_CONDITION_LIST_SIZE:
            raise _RulesLimitError("max_list_size_exceeded")
        expected_set = {str(x) for x in expected}

        if operator == "contains_any":
            return bool(actual_set & expected_set)
        if operator == "contains_all":
            return expected_set.issubset(actual_set)
        raise _RulesTypeError("unsupported_list_operator")


class _RulesLimitError(ValueError):
    pass


class _RulesTypeError(ValueError):
    pass
