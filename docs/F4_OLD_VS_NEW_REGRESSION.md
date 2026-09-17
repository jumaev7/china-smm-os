# F4 — Old vs New Backend Regression Harness

**Status:** isolated testing infrastructure only.  
**Production source landing / image build / runtime deployment remain NO-GO.**

## Purpose

Reproducibly compare the **old production backend** against the **current
candidate HEAD**, while preserving immutable historical pins:

| Pin | Value | Role |
|--|--|--|
| Old image | `sha256:34d2977e2d1de13fa8bf0ad2e79692e0f18c537609c6e66796dadbefafd8bff4` | Production image evidence |
| Old source-equivalent | `338d3f966fa7c5fd2795201e555512f1eebcadc9` | Blob-hash identity of old algorithms |
| F1–F3 candidate (historical) | `d1ccee82e3106ea469ac086ed99bd5f840b75fe0` | Immutable baseline reference |
| F4 introduction | `72d8ab8d879fa8afaf2d2e64669e41bc98236aa4` | Harness introduction commit |
| Candidate under test | `git rev-parse HEAD` | Explicitly recorded in reports |

Image identity is established by R3.1 multi-file in-image hash match to the
source tip, plus git blob SHA256 pins in
`backend/tests/f4_harness/constants.py`. Git ancestry alone is not proof.

`test_00` verifies historical pins remain exact and that required commits are
ancestors of HEAD. It does **not** require HEAD to equal the F1–F3 baseline.

## Isolation

- Dedicated PostgreSQL: `127.0.0.1:54329` / database `f4_old_vs_new_regression`
  (override with `F4_REGRESSION_PG_URL`)
- Counting mock adapters only — no real provider credentials or API calls
- No production registry rows, migrations, workers, env files, or containers

## Schema modes

| Mode | Meaning |
|--|--|
| A_historical | Pre-R1: no `publication_intent_id`, no registry table |
| B_old_on_r1 | Old algorithms against R1 schema (nullable intents stay NULL) |
| C_new_on_r1 | New source against R1 schema |

## Run

```bash
cd backend
python -m pytest tests/test_f4_old_vs_new_regression.py -q
```

Artifacts:

- `backend/tests/f4_harness/artifacts/f4_comparison_report.json`
- `backend/tests/f4_harness/artifacts/f4_comparison_report.md`

Reports record both `candidate_sha` (HEAD under test) and
`historical_f1_f3_baseline_sha` / `pre_sha` (immutable F1–F3 pin). Do not treat
`pre_sha` as the code under test after later landings (e.g. I1).

## Classification

Every scenario is `INTENDED` / `UNINTENDED` / `UNRESOLVED` / `EQUIVALENT` /
`COMMON_MODE_SAFETY`.

Gates require zero unexplained extra provider writes, zero unexpected registry
mutations, zero unintended/material unresolved differences.

## Diff scope

Allowed: harness package, F4 tests, this doc.  
Forbidden: PublishService/business logic “fixes”, routes, flags, compose,
migrations, deployment helpers.
