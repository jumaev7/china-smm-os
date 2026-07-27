# Current Task

> Agent memory file — active work only. Update at task start and completion.

## Task

**Social Listening Phase 3 — Governed Live Read-Only Sources** (DoD complete)

## Goals

- [x] Baseline `93a5b6c` confirmed; Phase 1/2 regression gate attempted
- [x] Capability discovery vs official Meta / repo integrations
- [x] Implement Facebook Page comments + mentions live read-only adapters
- [x] Credential reuse, tenant-safe binding, checkpoint/lock/scheduling
- [x] Capability/migration safeguards (separate caps, sanitized states, DB lock, create-only ensure, fixtures)
- [x] API/UI + Executive Copilot live coverage honesty
- [x] Full DoD verification matrix + focused commit

## Selected scope

- **Adapters:** `facebook_page_comments`, `facebook_page_mentions` (independent capabilities)
- **Scopes:** reuse Meta OAuth; `pages_read_user_content` necessary but not sufficient — live probes required
- **Deferred:** Instagram comments, global keyword, TikTok/LinkedIn

## Safeguards completed

- Separate owned comments vs tagged mentions; official docs matrix in `meta_capability_matrix.py` + `docs/SOCIAL_LISTENING_PHASE3.md`
- Access layers documented; sanitized health codes; capability-specific probes
- Tokens never persisted on ListeningSource; DB atomic source lock with commit-before-work
- `ensure_listening_schema()` create-only; Alembic retains ALTER
- Contract fixtures + two-session lock tests in `scripts/test_listening_live_sources.py`
- Ordinary read paths make zero Graph calls
- Product copy (en/zh/ru) and overview/capabilities honesty for Phase 3 limits

## Blockers

Production Live mode requires Meta App Review + Advanced Access beyond app roles.

## Next Active Task

None — Phase 3 DoD complete. Ready for next phase when scheduled.
