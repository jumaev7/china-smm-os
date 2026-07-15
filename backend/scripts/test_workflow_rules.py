"""Unit checks for the safe workflow rules engine."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from app.services.workflow_field_catalog import extract_allowlisted_fields, get_field
    from app.services.workflow_rule_engine import WorkflowRuleEngine
    from app.services.workflow_validation_service import WorkflowValidationService

    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    # Field catalog — no arbitrary paths
    record("catalog_has_publish_failed", get_field("tenant.content.publish_failed", "platform") is not None)
    record("catalog_rejects_nested", get_field("tenant.content.publish_failed", "payload.token") is None)
    record("catalog_rejects_secret", get_field("tenant.content.publish_failed", "access_token") is None)
    extracted = extract_allowlisted_fields(
        "tenant.content.publish_failed",
        {"platform": "instagram", "access_token": "SECRET", "nested": {"a": 1}},
    )
    record("extract_allowlisted_only", extracted == {"platform": "instagram"}, str(extracted))

    # Empty conditions match
    empty = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "instagram"},
        conditions={"operator": "all", "items": []},
    )
    record("empty_conditions_match", empty.matched and empty.status == "matched")

    # all / any / none
    cond_all = {
        "operator": "all",
        "items": [
            {"id": "c1", "field": "platform", "op": "equals", "value": "instagram"},
            {"id": "c2", "field": "retryable", "op": "is_true"},
        ],
    }
    r_all = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "instagram", "retryable": True},
        conditions=cond_all,
    )
    record("all_group_match", r_all.matched)

    r_all_fail = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "instagram", "retryable": False},
        conditions=cond_all,
    )
    record("all_group_not_match", not r_all_fail.matched and "c2" in r_all_fail.failed_condition_ids)

    r_any = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "tiktok", "retryable": True},
        conditions={"operator": "any", "items": cond_all["items"]},
    )
    record("any_group_match", r_any.matched)

    r_none = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "tiktok", "retryable": False},
        conditions={"operator": "none", "items": cond_all["items"]},
    )
    record("none_group_match", r_none.matched)

    # String operators
    r_contains = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"failure_code": "auth_or_permission"},
        conditions={
            "operator": "all",
            "items": [{"id": "s1", "field": "failure_code", "op": "contains", "value": "auth"}],
        },
    )
    record("string_contains", r_contains.matched)

    r_in = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "facebook"},
        conditions={
            "operator": "all",
            "items": [{"id": "s2", "field": "platform", "op": "in", "value": ["instagram", "facebook"]}],
        },
    )
    record("string_in", r_in.matched)

    # Numeric
    r_gt = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"attempt_number": 3},
        conditions={
            "operator": "all",
            "items": [{"id": "n1", "field": "attempt_number", "op": "greater_than", "value": 1}],
        },
    )
    record("numeric_gt", r_gt.matched)

    r_between = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"attempt_number": 2},
        conditions={
            "operator": "all",
            "items": [{"id": "n2", "field": "attempt_number", "op": "between", "value": [1, 3]}],
        },
    )
    record("numeric_between", r_between.matched)

    # Type mismatch
    r_type = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"attempt_number": "three"},
        conditions={
            "operator": "all",
            "items": [{"id": "t1", "field": "attempt_number", "op": "greater_than", "value": 1}],
        },
    )
    record("type_mismatch_fails", not r_type.matched and r_type.status in {"not_matched", "invalid_input"})

    # Missing field
    r_missing = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={},
        conditions={
            "operator": "all",
            "items": [{"id": "m1", "field": "platform", "op": "equals", "value": "instagram"}],
        },
    )
    record("missing_field_not_match", not r_missing.matched)

    # Exists
    r_exists = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "instagram"},
        conditions={
            "operator": "all",
            "items": [{"id": "e1", "field": "platform", "op": "exists"}],
        },
    )
    record("exists_op", r_exists.matched)

    # Depth limit
    deep = {"operator": "all", "items": []}
    node = deep
    for i in range(6):
        child = {"operator": "all", "items": []}
        node["items"] = [child]
        node = child
    r_depth = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={},
        conditions=deep,
    )
    record("depth_limit", r_depth.status == "invalid_input", r_depth.diagnostics.get("error", ""))

    # Deterministic ordering of failed ids
    r1 = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "x", "retryable": False},
        conditions=cond_all,
    )
    r2 = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "x", "retryable": False},
        conditions=cond_all,
    )
    record("deterministic", r1.failed_condition_ids == r2.failed_condition_ids)

    # Diagnostics scrub — no secrets
    dirty = WorkflowRuleEngine.evaluate(
        event_type="tenant.content.publish_failed",
        payload={"platform": "instagram", "access_token": "SECRET"},
        conditions={"operator": "all", "items": []},
    )
    diag_text = str(dirty.diagnostics)
    record("diagnostics_no_secret", "SECRET" not in diag_text and "access_token" not in diag_text, diag_text)

    # Validation: reject arbitrary path / unsupported action / invalid trigger
    bad_trigger = WorkflowValidationService.validate({
        "schema_version": 1,
        "trigger": {"event": "tenant.user.login"},
        "conditions": {"operator": "all", "items": []},
        "steps": [{"id": "step_1", "type": "action", "action_type": "create_notification", "config": {"title": "x"}}],
    })
    record("reject_unsupported_trigger", not bad_trigger.valid)

    bad_field = WorkflowValidationService.validate({
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {
            "operator": "all",
            "items": [{"field": "payload.secret", "op": "equals", "value": "x"}],
        },
        "steps": [{"id": "step_1", "type": "action", "action_type": "create_notification", "config": {"title": "x"}}],
    })
    record("reject_arbitrary_path", not bad_field.valid)

    bad_action = WorkflowValidationService.validate({
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {"operator": "all", "items": []},
        "steps": [{"id": "step_1", "type": "action", "action_type": "run_shell", "config": {}}],
    })
    record("reject_unsupported_action", not bad_action.valid)

    good = WorkflowValidationService.validate({
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {
            "operator": "all",
            "items": [{"id": "c1", "field": "platform", "op": "equals", "value": "instagram"}],
        },
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "action_type": "create_notification",
                "config": {"title": "Hi {resource_name}", "category": "automation"},
            },
            {
                "id": "step_2",
                "type": "action",
                "action_type": "record_activity",
                "config": {"title": "Logged"},
            },
        ],
        "failure_policy": "stop_on_failure",
    })
    record("valid_definition", good.valid, str(good.to_error_dicts()))

    branch = WorkflowValidationService.validate({
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {"operator": "all", "items": []},
        "steps": [{"id": "step_1", "type": "condition", "condition": {}}],
    })
    record("branch_steps_deferred", not branch.valid)

    if failures:
        print(f"\nFAILED {len(failures)}")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nAll workflow rules checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
