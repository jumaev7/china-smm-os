# Social Listening Phase 1 — Observed Mentions Foundation

## Boundary

Phase 1 is an **observed-data foundation**. It answers what external content was observed, which monitored subjects/queries matched, when/where it was published, what evidence was retained, whether it was already ingested, how fresh coverage is, and which items need human review.

It is **not** a complete market-intelligence or autonomous-response system.

### Explicit guarantees

- Provider integrations may only retrieve permitted observed data (Phase 1: none live).
- No publish, reply, DM, comment, like, react, follow, block, report, or provider content mutation.
- No advertising campaign changes, CRM mutations, or automated outreach.
- Review-state changes update **internal** workflow state only.
- Business Health v2 scores and domain weights are **unchanged**.
- Coverage is limited to configured supported sources — **not** whole-market coverage.

## Supported sources

| Source | Capability status | Notes |
|--------|-------------------|-------|
| `manual_import` | `import_only` | Operator-supplied JSON observations. Never labeled as live provider data. |
| `fixture` | `fixture_only` | Deterministic demo rows for QA. Explicitly fixture/demo. |
| Live social/keyword providers | `unsupported` | Deferred. Do not invent capabilities. |

## Domain entities

- **ListeningProject** — tenant-scoped initiative (`active` / `paused` / `archived`). Pause stops future scheduled ingestion; history remains.
- **ListeningSubject** — own_brand / competitor / product / topic / other + aliases/handle/domain.
- **ListeningQuery** — inspectable include/exclude terms, source/language filters, optional subject link.
- **ListeningSource** — configured source with capability + freshness metadata.
- **ObservedMention** — normalized observation with provenance, fingerprints, review state.
- **MentionMatch** — why a mention matched (term, offsets/excerpt, matcher version).
- **MentionReview** — audited review transitions.
- **ListeningIngestionRun** — fetched/created/updated/duplicate/rejected/error/match counts, checkpoint, watermark.

## Provenance and timestamps

Distinct fields:

- `published_at` — when the source content was published (nullable; unknown stays null)
- `source_updated_at` — provider/source update time when supplied
- `observed_at` / `first_observed_at` / `last_observed_at` — observation lifecycle
- `created_at` / `updated_at` — local row timestamps

`observation_origin` is one of: `manual_import`, `fixture`, `live_provider`, `webhook`. Phase 1 only produces `manual_import` and `fixture`.

## Deduplication (`listening_dedupe_v1`)

Priority:

1. Tenant + source_type + provider_account_ref + provider_external_id
2. Canonicalized stable URL
3. Versioned normalized fingerprint (content + source/author/time/url components via `sha256`)

Rules:

- Tenant-safe uniqueness constraints
- Idempotent repeated ingestion
- Preserve `first_observed_at`; advance `last_observed_at`
- On content edit: update text/excerpt/fingerprint/engagement; do not invent timestamps
- No semantic near-duplicate clustering in Phase 1

## Matching (`listening_matcher_v1`)

Deterministic, explainable:

- Case-insensitive phrase / keyword / alias matching
- Boundary-aware matching for alphanumeric terms
- Exclude terms suppress matches
- Source and language filters
- Handle and domain matching when configured
- Evidence stored (term, excerpt, offsets, matcher version)
- Duplicate match rows prevented by unique constraint

Sentiment is deferred.

## API overview

Prefix: `/api/v1/listening`

- Overview / capabilities
- Projects, subjects, queries, sources CRUD (config writes: owner/manager)
- Mentions list/detail with filters
- Review updates (owner/manager/operator)
- Ingestion runs
- Manual import + fixture ingest (read-only observation)

Cross-tenant access resolves to 404. Pagination is bounded (`limit` ≤ 100).

## UI

Route group under `/listening`:

- Overview — counts, freshness, recent mentions, coverage notice
- Mention explorer — filters, search, evidence preview
- Mention detail — content, provenance, evidence, review controls
- Configuration — projects/subjects/queries/sources + import/fixture
- Ingestion runs — status and counts

## Privacy / retention

- Tenant isolation at query and persistence boundaries
- Minimize author data; no raw provider payload dumps
- Safe external links (`http`/`https` only; `javascript:` / `data:` rejected)
- No tokens in logs or API responses
- Manual import payloads are size-bounded (`MAX_IMPORT_PAYLOAD_BYTES`) and
  rate-limited per tenant (`MAX_IMPORT_REQUESTS_PER_TENANT_PER_HOUR`)
- Fixture/demo ingest is gated off when `APP_ENV` is `production` / `prod`
- Use existing tenant deletion/cascade conventions

## Schema ownership

Production schema changes use Alembic (`20260914_social_listening_foundation`).
`ensure_listening_schema()` is the established idempotent local/dev DDL helper
(same pattern as advertising/measurement). It must remain structurally aligned
with the Alembic revision and must not silently mutate columns on existing tables.
Production startup does **not** call ensure helpers — only `alembic upgrade head`.

## Phase 2+ extension points

Phase 2 (see `SOCIAL_LISTENING_PHASE2.md`) delivers:

- Trend / Observed Share of Voice analytics with coverage semantics
- Emerging topics + anomalies with evidence
- Executive Copilot market-intelligence read interface (not raw mention-table coupling)

Still deferred:

- Live provider adapters behind the same read-only contract
- Optional provisional sentiment with method/version/evidence
- Autonomous response planning/execution (explicitly out of scope until governed)
