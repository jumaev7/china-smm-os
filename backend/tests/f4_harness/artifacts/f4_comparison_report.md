# F4 — Old vs New Backend Regression Report

Generated: `2026-09-17T10:34:18.051575+00:00`

## Identities

- Baseline (new): `d1ccee82e3106ea469ac086ed99bd5f840b75fe0`
- Old image: `sha256:34d2977e2d1de13fa8bf0ad2e79692e0f18c537609c6e66796dadbefafd8bff4`
- Old source-equivalent: `338d3f966fa7c5fd2795201e555512f1eebcadc9`

## Isolation

```json
{
  "ok": true,
  "database_url_sanitized": "127.0.0.1:54329/f4_old_vs_new_regression",
  "database_name": "f4_old_vs_new_regression",
  "host": "127.0.0.1",
  "port": 54329,
  "checks": [
    "host_loopback=127.0.0.1",
    "port=54329 (isolated test postgres)",
    "db_name_isolated=f4_old_vs_new_regression",
    "provider_env_absent:META_ACCESS_TOKEN",
    "provider_env_absent:TELEGRAM_BOT_TOKEN",
    "provider_env_absent:FACEBOOK_ACCESS_TOKEN",
    "provider_env_absent:INSTAGRAM_ACCESS_TOKEN",
    "provider_env_absent:TIKTOK_ACCESS_TOKEN",
    "provider_env_absent:LINKEDIN_ACCESS_TOKEN",
    "test_pg_tcp_reachable",
    "provider_adapters=mocked_counting_only",
    "no_production_registry_mutations_authorized",
    "no_production_migrations_authorized"
  ],
  "failures": []
}
```

## Schema compatibility

```json
{
  "A_historical": {
    "publication_intent_id_column": false,
    "registry_table": false,
    "note": "Historical schema has no intent column/registry. ORM new models expect R1; algorithm comparison uses in-memory/R1 fixtures for B/C."
  },
  "B_old_on_r1": {
    "null_intent_rows": 1,
    "registry_rows": 0,
    "fabricated_intents": 0
  },
  "C_new_on_r1": {
    "null_intent_rows": 1,
    "registry_rows": 0,
    "fabricated_intents": 0
  }
}
```

## Scenario matrix

| Scenario | Class | Verdict | Difference |
|---|---|---|---|
| `success_identity_response_only` | EQUIVALENT | PASS | none |
| `success_identity_durable_only` | INTENDED | PASS | suppression_decision: old='allow' new='suppress'; response_provider_id: old=None new='dur-1'; api.platform: old=None new |
| `success_identity_matching_ids` | EQUIVALENT | PASS | none |
| `success_identity_conflicting_ids` | INTENDED | PASS | suppression_decision: old='suppress' new='conflict'; identity_conflict: old=False new=True |
| `success_identity_missing_ids` | EQUIVALENT | PASS | none |
| `success_identity_mock_success` | EQUIVALENT | PASS | none |
| `success_identity_test_success` | EQUIVALENT | PASS | none |
| `success_identity_mock_with_durable` | EQUIVALENT | PASS | none |
| `success_identity_intentional_republish_empty_prior` | EQUIVALENT | PASS | none |
| `f1_find_live_mock_with_durable` | INTENDED | PASS | provider_calls: old=0 new=1; suppression_decision: old='suppress' new='allow' |
| `pub_fresh_success` | EQUIVALENT | PASS | none |
| `pub_response_only_suppress` | EQUIVALENT | PASS | none |
| `pub_durable_only` | INTENDED | PASS | none |
| `pub_conflict` | INTENDED | PASS | suppression_decision: old='suppress' new='conflict'; identity_conflict: old=False new=True |
| `pub_mock_with_durable` | INTENDED | PASS | provider_calls: old=0 new=1; suppression_decision: old='suppress' new='allow' |
| `dest_same_content_platform_account` | EQUIVALENT | PASS | none |
| `dest_cross_account_platform_keyed` | COMMON_MODE_SAFETY | PASS | none |
| `dest_different_platform` | EQUIVALENT | PASS | none |
| `dest_publish_version_change_platform_keyed` | COMMON_MODE_SAFETY | PASS | none |
| `registry_shadow_neutrality` | EQUIVALENT | PASS | none |
| `api_stranded_default_off` | INTENDED | PASS | api.default: old=None new=404; api.route: old='absent' new='present' |
| `failure_injection_bundle` | EQUIVALENT | PASS | none |
| `tenant_content_scope` | EQUIVALENT | PASS | none |

## Gates

```json
{
  "zero_unexplained_extra_provider_writes": true,
  "zero_unexpected_registry_mutations": true,
  "zero_unexpected_execution_activation": true,
  "zero_cross_tenant_leakage": true,
  "zero_unintended_differences": true,
  "zero_material_unresolved": true
}
```

## Verdicts

```json
{
  "f4_harness_implementation": "GO",
  "f4_behavioral_equivalence": "GO",
  "f4_safety_acceptance": "GO",
  "production_source_landing": "NO-GO",
  "production_image_build": "NO-GO",
  "runtime_deployment": "NO-GO",
  "shadow_enablement": "NO-GO",
  "registry_authority": "NO-GO",
  "provider_io_changes": "NO-GO",
  "claim_execution_activation": "NO-GO"
}
```

## Known common-mode safety concerns

- Platform-keyed _prior_live_successes suppresses cross-account republish on the same platform even when begin_attempt/find_live_success would allow a different account — present in both old and new.
- Old find_live_success treats durable external_post_id as live even when response is mock/test — pre-F1 hazard; new F1 refuses suppression.
- Platform-keyed prior reader ignores publish_version changes — both versions suppress republish after a prior live success on that platform.
