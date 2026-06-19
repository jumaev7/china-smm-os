# Known Issues

> Agent memory file — bugs and limitations. Remove entries when resolved.

| Issue | Impact | Status | Workaround | Priority |
|-------|--------|--------|------------|----------|
| Tenant login redirect loop on `?next=` routes | Could not enter app after login when deep-linking to protected pages | **Fixed 2026-06-12** | Use `/dashboard` directly | — |
| `/briefs` 500 — missing `client_briefs.admin_feedback` column | Brief list crashed when migration drifted from ORM | **Fixed 2026-06-12** | Dev schema patch + `alembic upgrade head` | — |
| Workflow “Prepare Everything” progress is in-memory only | Progress lost on backend restart | Open | Re-run workflow after restart | Medium |
| `TELEGRAM_ADMIN_ID` empty | Buffer mode treats nobody as admin; group assembly blocked | Open | Set admin Telegram user IDs in env | High (if using Telegram) |
| Client approve ≠ admin approve | Two parallel approval tracks; checklist may not require client approval | Open | Manually verify both tracks before publish | Medium |
| Schedule timezone heuristic | “Tomorrow 18:00” stored as UTC, not local (e.g. Tashkent) | Open | Set schedules explicitly in UI/API | Low |
| Multi-photo posts | One ContentItem with refs; video pipeline uses primary media only | Open | Use primary media for video workflow | Low |
| Dev schema dual path | Alembic vs `create_tables()` + patches can drift | Open | Run `alembic upgrade head` before prod; use migrations for shared envs | High (prod) |
| Auto-publish to all platforms | Phase 2 — Instagram partial only | Open | Manual publish / queue review | Medium |
| AI-generated briefing content not localized | Executive Copilot / AI text stays in source language | Open | Use EN source; manual translation | Low |
| Backend dynamic strings in English | `safety_notice`, recommendation titles from API untranslated | Open | Frontend fallbacks; fix in backend i18n pass | Low |
| Non-priority pages partial RU/ZH | CRM, lead-intelligence standalone, marketplace “Open” KPI | Open | Use EN; expand locale keys | Low |
| Pilot metrics empty without seed | Validation/demo pages show zeros until pilot data seeded | Open | `POST /api/v1/pilot-execution/seed-pilot-data` (dev) | Low (dev/demo) |
| Production not deployed | No live environment; assessment tools only | Open | Follow `PRODUCTION_DEPLOYMENT_GUIDE.md` | High (go-live) |
| WhatsApp/WeChat live providers | Adapter placeholders; no hardcoded production credentials | By design | Configure provider credentials + adapter when ready | Medium |
| Client Brief Pipeline migrations | New migrations (`20260811`–`20260813`) may not be applied on all dev DBs | **Mitigated 2026-06-12** | Run `alembic upgrade head`; dev patch `_ensure_client_briefs_columns` | High (if using briefs) |
| Executive Copilot overview API slow | `/api/v1/executive-copilot/overview` can exceed 12s guard timeout under load | Open | Page renders via summary widget + partial error banner | Medium (demo) |
| Revenue Forecast API slow | `/api/v1/revenue-forecast/overview` can exceed endpoint timeout | Open | Admin-only route; page shows error after timeout | Medium (demo) |
| Pilot Readiness overview slow vs client timeout | `/api/v1/pilot-readiness/overview` ~17s; `adminApi` timeout 15s | Open | Page shows “loading took too long” until timeout raised or API optimized | High (demo) |

---

## Resolved (historical — do not re-add)

| Issue | Resolution |
|-------|------------|
| No auth on admin API | Admin + tenant JWT auth v1 implemented |
| Admin bootstrap/login failures | Admin Bootstrap/Login Fix sprint completed |
