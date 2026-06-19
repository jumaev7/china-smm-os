# Change Log

> Agent memory file — significant project changes only. Newest first.

---

## 2026-06-14 — Communication Hub MVP

**Feature:** Centralized Communication Hub integrated into existing platform — dashboard, unified inbox, follow-ups, message templates, AI-ready service layer.

**Approach:** Extended existing `CommunicationContact` / `CommunicationThread` / `CommunicationMessage` models (no duplicate Communication table). Added tenant-scoped `CommunicationFollowUp` and `CommunicationMessageTemplate`. Communication records exposed as unified DTO over messages + threads.

**API:** `/api/v1/communications/dashboard`, `/inbox`, `/records`, `/followups`, `/templates`, `/ai/capabilities`

**Frontend routes:** `/communications` (dashboard), `/communications/inbox`, `/communications/followups`, `/communications/templates`

**Verification:** Lint pass (pre-existing warnings only), frontend build pass, dashboard API returns KPIs for demo tenant.

---

## 2026-06-12 — Frontend CSS recovery (stale .next cache)

**Fix:** Dashboard unstyled/raw HTML — no CSS/layout code changes

**Root cause:** Stale/corrupt `frontend/.next` dev cache after compile errors (`lib/api.ts` syntax error caused 500 on static chunks). HTML returned 200 but `/_next/static/css/app/layout.css` and JS chunks returned 404.

**Action:** `rm -rf frontend/.next` + `docker compose restart frontend`. Verified CSS/JS 200; lint + build pass.

**Files:** `scripts/verify_frontend_css.py` (verification helper). No changes to `globals.css`, `layout.tsx`, Tailwind, or auth.

---

## 2026-06-12 — Pilot Demo Mode v1

**Feature:** Admin-guided demonstration mode for presenting China SMM OS to Chinese factories

**Files changed:**

- `backend/app/schemas/pilot_demo_mode.py`, `services/pilot_demo_mode_service.py`, `api/v1/pilot_demo_mode.py`, `api/router.py`
- `backend/app/core/dependency_registry.py`, `services/api_health_service.py`
- `frontend/app/(dashboard)/pilot-demo-mode/page.tsx`
- `frontend/lib/api.ts`, `route-permissions.ts`, `components/layout/DashboardShell.tsx`, `locales/*.json`
- `frontend/app/(dashboard)/pilot-readiness/page.tsx` — PageHeader `subtitle` prop fix (build)
- `scripts/verify_pilot_demo_mode.py`
- Governance: `project_status.md`, `known_issues.md`, `current_task.md`

**Result:** `/pilot-demo-mode` provides 7-step guided workflow (brief → AI plan → approve → tasks → QA → publishing → revenue) with isolated `[PILOT_DEMO_MODE_V1]` demo data, timeline/KPI/diagram visuals, EN/RU/ZH i18n, admin-only RBAC. API verification 12/12 pass; production build includes route.

---

## 2026-06-12 — Final stability verification (post-recovery)

**Verification:** Docker health, tenant/admin login, demo routes — no code changes

**Result:** Core stack stable (3/3 containers, health 200, logins <1s, dashboard/briefs/content/tasks/executive-copilot OK). **FAIL:** `/pilot-readiness` frontend error — `adminApi` 15s timeout vs API ~17s. No ChunkLoadError, hydration mismatch, infinite access guard, or login timeout observed.

---

## 2026-06-12 — Pilot Readiness Dashboard + route stability audit

**Feature:** Admin Pilot Readiness Dashboard and route stability fixes for pilot demo prep

**Files changed:**

- `backend/app/schemas/pilot_readiness.py`, `services/pilot_readiness_service.py`, `api/v1/pilot_readiness.py`, `api/router.py`
- `backend/app/core/database.py` — `_ensure_client_briefs_columns` dev patch
- `frontend/app/(dashboard)/pilot-readiness/page.tsx`
- `frontend/lib/api.ts`, `route-permissions.ts`, `components/auth/AdminAuthGuard.tsx`
- `frontend/next.config.js` — redirects `/buyer-search` → `/buyer-finder`, `/revenue-analytics` → `/analytics`
- `frontend/components/layout/DashboardShell.tsx`, `locales/*.json`
- `scripts/final_route_audit.py`, `scripts/pilot_route_audit.py`
- Governance: `project_status.md`, `known_issues.md`, `current_task.md`

**Result:** `/pilot-readiness` shows demo tenant health, auth/RBAC, backend/DB status, brief/content counts, open issues, readiness score, and route audit table. AdminAuthGuard resolves within 3s (no infinite “Checking admin session…”). `/briefs` API fixed after schema patch. Alembic migrations applied on dev DB.

---

## 2026-06-12 — Tenant login redirect loop fix

**Feature:** Fix post-login redirect loop on `/login?next=/deal-risk`

**Files changed:**

- `frontend/lib/route-permissions.ts` — `isEffectivelyTenantAuthenticated` in access checks; `resolveTenantPostLoginPath`
- `frontend/lib/auth-store.tsx` — `isAuthenticated` honors active tenant session during hydration
- `frontend/components/auth/DashboardRouteGuard.tsx` — prevent login redirect when tenant token present
- `frontend/app/login/page.tsx` — safe `next` resolution after auth

**Result:** Tenant login no longer loops through `/login?next=…` when navigating to protected routes like `/deal-risk`.

---

## 2026-06-12 — Project governance files

**Feature:** Agent memory / governance documentation

**Files changed:**

- `project_status.md` (new)
- `architecture.md` (new)
- `current_task.md` (new)
- `known_issues.md` (new)
- `change_log.md` (new)
- `development_rules.md` (new)

**Result:** Cursor agents have a concise, mandatory context layer separate from the detailed `PROJECT_STATUS.md` sprint log.

---

## 2026-08-13 — Client Brief Pipeline

**Feature:** Admin feedback field, `changes_requested` status workflow

**Files changed:**

- `backend/migrations/versions/20260813_client_brief_pipeline.py`
- `backend/app/services/client_brief_service.py`
- `backend/app/api/v1/client_briefs.py`
- `frontend/app/(dashboard)/briefs/*`

**Result:** Brief review loop supports admin feedback and change requests before approval/conversion.

---

## 2026-08-12 — Client Brief MVP

**Feature:** Brief fields (product description, notes, languages), status rename (`new` / `reviewing` / `approved` / `converted`)

**Files changed:**

- `backend/migrations/versions/20260812_client_brief_mvp.py`
- `backend/app/models/client_brief.py`
- `backend/app/schemas/client_brief.py`

**Result:** Tenant brief intake aligned with pipeline statuses and richer campaign metadata.

---

## 2026-06 — RU/ZH Business Localization v2

**Feature:** Priority page i18n, B2B terminology, pipeline stage labels, sidebar polish

**Files changed:**

- `frontend/locales/en.json`, `ru.json`, `zh.json`
- `frontend/docs/LOCALIZATION_READINESS.md`
- Multiple dashboard / executive / pilot pages

**Result:** Priority routes translate in EN/RU/ZH; production build passes (~94 routes).

---

## 2026-06 — Pilot Launch Validation v1

**Feature:** Read-only end-to-end pilot readiness assessment

**Files changed:**

- `backend/app/services/pilot_launch_validation_service.py`
- `backend/app/api/v1/pilot_launch_validation.py`
- `frontend/app/(dashboard)/pilot-launch-validation/page.tsx`

**Result:** Admin/tenant flow probes, data completeness scoring, blockers/next-actions aggregation.

---

## 2026-06 — Admin Authentication & RBAC v1

**Feature:** Separate admin JWT, roles, permissions, audit logs, platform console

**Files changed:**

- `backend/app/api/v1/admin_auth.py`
- `backend/app/core/admin_permissions.py`, `admin_access.py`
- `frontend/app/(admin)/*`, `frontend/lib/route-permissions.ts`

**Result:** Platform admin separated from tenant users; pilot routes admin-gated.

---

## 2026-06 — Multi-Tenant SaaS Foundation v1

**Feature:** Tenants, tenant users, subscription billing, tenant-scoped data

**Files changed:**

- `backend/app/models/tenant.py`, `tenant_user.py`
- `backend/app/services/tenant_service.py`, `tenant_auth_service.py`
- `backend/app/api/v1/tenant_auth.py`, `auth.py`, `billing.py`

**Result:** Cross-tenant isolation enforced; tenant login and RBAC operational.

---

## 2026-06 — Executive Copilot v1

**Feature:** Read-only executive command center aggregating sales, revenue, pilot, comms health

**Files changed:**

- `backend/app/services/executive_copilot_service.py`
- `backend/app/api/v1/executive_copilot.py`
- `frontend/app/(dashboard)/executive-copilot/page.tsx`

**Result:** Owner-facing `/executive-copilot` with permission gate `executive.copilot.view`.

---

## 2026-05 — Content Pipeline Kanban

**Feature:** Pipeline board with stage transitions and publishing integration

**Files changed:**

- `backend/app/services/content_pipeline_service.py`
- `backend/app/api/v1/content_pipeline.py`
- `frontend/app/(dashboard)/pipeline/page.tsx`

**Result:** Visual content workflow from draft through published/failed.

---

## Phase 1 — Core SMM (baseline)

**Feature:** Clients, media, AI captions, calendar, Telegram ingestion, client review

**Result:** Foundation documented in `README.md` and `IRAY_CONTEXT.md`.
