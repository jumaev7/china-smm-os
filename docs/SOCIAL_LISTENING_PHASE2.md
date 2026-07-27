# Social Listening Phase 2 — Trends, Competitor Intelligence & Executive Synthesis

## Boundary

Phase 2 transforms **normalized Phase 1 observations** into explainable, coverage-aware market intelligence.

It answers how observed mention volume is changing, which monitored subjects gain/lose attention, how own brands compare with configured competitors (Observed Share of Voice), which topics are emerging inside the observed dataset, which changes are unusual vs a valid baseline, what evidence supports each insight, and whether coverage is sufficient.

It is **descriptive decision support**. It is **not** forecasting, autonomous strategy execution, sentiment scoring, live-provider invention, or Business Health reweighting.

### Explicit guarantees

- No provider write operations (publish/reply/comment/react/message).
- No advertising campaign changes, CRM mutations, or outreach triggers.
- Fixture observations are excluded from production intelligence.
- Manual imports remain legitimate observed data with visible coverage limitations.
- Analyst review updates **internal** insight-review state only.
- Business Health v2 scores and domain weights remain **unchanged**.
- Sentiment remains **deferred**.

## Architecture

```
Observed mentions
  -> eligibility (listening_eligibility_v1)
  -> analysis windows (listening_windows_v1)
  -> coverage (listening_coverage_v1)
  -> time-series aggregation
  -> subject comparison + Observed SoV (listening_sov_v1, fractional_attribution_v1)
  -> emerging topics (listening_topics_v1)
  -> anomalies (listening_anomaly_v1)
  -> MarketInsight (listening_insights_v1)
  -> API / Listening UI / Executive Copilot read model
```

Analytics operate only on Phase 1 normalized rows. Request-time analytics never call providers.

## Eligibility (`listening_eligibility_v1`)

Production intelligence includes:

- tenant-scoped observations
- non-fixture origins (`manual_import`, and reserved `live_provider` / `webhook` when present)
- observations inside the requested window
- default review policy `default_exclude_irrelevant`:
  - exclude `irrelevant`
  - include `unreviewed`, `relevant`, `needs_follow_up`, `resolved`
  - expose unreviewed proportion in coverage

API may override with `include_all` or `relevant_only`.

### Timestamp policy

- Time-series / windowed metrics use `published_at` when present.
- Unknown `published_at` is **never** invented as now.
- Mentions without `published_at` are excluded from time-series and counted in data-quality reporting.

### Fixture policy

- Excluded from production intelligence and Executive Copilot.
- May be included only with explicit `include_fixture=true` for demo/dev displays.
- Never blended silently with manual/live observations.

## Windows (`listening_windows_v1`)

Supported keys: `7d`, `30d`, `90d`, `custom` (max 90 days).

Granularity: `hour` (≤3 days), `day`, `week`.

Comparison rules:

- previous period has equal duration
- identical filters
- both windows must meet minimum coverage for comparison metrics
- never divide by zero; never show `+∞%`
- zero baseline with current activity → `new_activity`

Buckets are half-open `[start, end)`.

## Coverage (`listening_coverage_v1`)

Statuses: `sufficient` | `partial` | `insufficient` | `unavailable`.

Assesses eligible counts, days with observations, freshness, failed/partial ingestion, subject comparability, origin composition, unreviewed proportion, missing timestamps, source imbalance.

Manual-import cadence completeness is **unknown** (not invented).

Failed ingestion reduces coverage and surfaces as **data-quality** anomalies — never as market decline.

## Observed Share of Voice (`listening_sov_v1`)

```
eligible mentions matched to subject
/ eligible mentions matched to all comparable configured subjects
* 100
```

- Labeled **Observed Share of Voice** (not total market share).
- Denominator and comparison set are visible.
- Subjects must share tenant/project scope.
- Insufficient denominators → unavailable (not zero).
- Multi-match policy `fractional_attribution_v1`: one mention matched to N comparable subjects contributes `1/N` to each.

## Emerging topics (`listening_topics_v1`)

Deterministic detection from Phase 1 match terms / aliases / query evidence. No unsupervised topic modeling.

Requires minimum current volume (≥3), multi-mention evidence, coverage, and (when comparison valid) growth vs baseline. Stop-word filtered.

## Anomalies (`listening_anomaly_v1`)

May detect volume spike/drop, new subject activity, emerging topic, source concentration shift, stale/interrupted coverage.

Market-signal anomalies are separated from data-quality anomalies. Severity is clamped deterministically. No forecast language.

## Analyst review

Table `tenant_listening_insight_reviews` stores append-only review transitions for deterministic `insight_key` identities.

States: `unreviewed` | `acknowledged` | `dismissed` | `monitoring` | `resolved`.

Does not modify source mentions or trigger providers/CRM/outreach.

## API

Prefix `/api/v1/listening/intelligence/*`:

- `GET overview|time-series|subjects|share-of-voice|topics|anomalies|insights|coverage`
- `GET insights/{insight_key}`
- `POST insights/{insight_key}/review` (owner/manager/operator)
- `GET insights/{insight_key}/reviews`

Phase 1 APIs remain compatible. No provider calls during analytics.

## Executive Copilot

Dedicated read service: `app.services.listening.executive_read`.

Section **Market Intelligence** consumes structured statements with evidence references. Conclusions are suppressed when coverage is insufficient. Data-quality warnings are visually distinct. Business Health remains unchanged.

## Persistence

Only insight-review rows are persisted. Aggregates are computed read models.

Migration: `20260915_listening_market_intelligence`  
Ensure helper: `_ensure_listening_tables` (create-only, includes insight reviews).

## Explicit non-goals retained

- Sentiment charts / classification
- Live social providers
- Business Health domain/weight changes
- Forecasting / autonomous strategy
- Whole-market coverage claims
