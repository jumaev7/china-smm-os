# Project Status

> Agent memory file — concise current platform state. Detailed sprint history lives in `PROJECT_STATUS.md`.

## Project

**China SMM OS** — AI-powered Sales + CRM + Communication operating system for Chinese factories, exporters, and international sales teams.

## Current Milestone

**Pilot Demo Mode v1** — admin-guided demonstration workflow with isolated demo data for factory presentations.

Previous milestone **Client Brief Pipeline v1** (stabilization) remains active for `/pilot-readiness` timeout fix.

---

## Stability Verification (2026-06-12)

| Check | Result |
|-------|--------|
| Docker Compose (postgres, backend, frontend) | **PASS** — 3/3 Up |
| Backend `GET /health` | **PASS** — 200 ok |
| Frontend `/login` | **PASS** — 200 |
| Demo login `demo@factory.local` | **PASS** |
| Admin login `admin@example.com` | **PASS** |
| `/pilot-demo-mode` | **PASS** — admin workflow 12/12 API verification |
| `/pilot-readiness` | **FAIL** — frontend `adminApi` 15s timeout; API needs ~17s |
| Build / runtime blockers | **PASS** — no ChunkLoadError, hydration mismatch, infinite access guard |
| **Overall** | **PASS** for pilot demo mode; pilot-readiness timeout remains open |

---

## Completed Modules

### Core SMM & Content

- Client management, media upload, AI caption generation (RU/UZ/EN/ZH)
- Content calendar, publishing queue, scheduled publish worker
- Content pipeline Kanban (`draft → internal_review → client_review → approved → scheduled → published`)
- Content factory, content planner, content studio, content repurpose
- Telegram ingestion (private chat, group buffer, admin NL instructions)
- Client review links (`/public/review/{token}`)
- Publishing checklist and publish safety

### Sales & CRM

- CRM pipeline (leads, deals, proposals, documents)
- Buyer intelligence, discovery, network, acquisition, acquisition engine, buyer finder
- Deal room v2, deal risk engine, revenue engine, revenue attribution, revenue forecast
- Sales agent, sales assistant, sales manager, sales playbooks, sales department v3
- Lead intelligence, communication intelligence, sales workflow automation
- Proposals, outreach, export agent, marketplace, landing pages, attribution links

### Communication

- **Communication Hub MVP** — dashboard, unified inbox, follow-ups, message templates (`/communications`, `/communications/inbox`, `/communications/followups`, `/communications/templates`)
- Unified inbox, communications hub, operator inbox
- WeChat / WhatsApp contact centers, sync, and provider integrations (adapter layer)
- Operator tasks, AI operator task engine

### Platform & Multi-Tenant

- Multi-tenant SaaS foundation, subscription & billing
- Factory platform v2, factory partner portal, factory profile
- Customer portal v1 + v2
- Tenant authentication & RBAC v1
- Admin authentication & RBAC v1, admin security hardening, audit logs

### AI & Executive

- Dashboard AI assistant, context AI, workflow “Prepare Everything”
- Executive Copilot v1 (read-only business command center)
- AI command center, multi-agent team
- Client Brief MVP + pipeline (submit, plan, review, convert)

### Pilot & Deployment Prep

- Pilot onboarding, launch, launch validation, execution, demo, sales demo
- **Pilot Readiness Dashboard** (`/pilot-readiness`) — demo tenant health, auth/RBAC, backend/DB status, content metrics, route stability audit
- **Pilot Demo Mode** (`/pilot-demo-mode`) — admin-guided 7-step demonstration workflow with isolated demo data, timeline, KPIs, workflow diagram, demo actions (brief → plan → tasks → publishing → revenue), full reset
- First pilot client, real factory pilot, production deployment assessment (read-only)

### Localization

- EN / RU / ZH locale files with priority-page parity (`frontend/locales/*.json`)
- Localization readiness audit (`frontend/docs/LOCALIZATION_READINESS.md`)

---

## Working Routes

### Public (no auth)

| Route | Purpose |
|-------|---------|
| `/login` | Tenant login |
| `/admin-login` | Admin login |
| `/factory-apply` | Factory partner application |
| `/review/[token]` | Client content review |
| `/public/review/{token}` | Backend public review API |
| `/public/landing/*` | Landing page leads |
| `/public/r/*` | Attribution redirect |

### Tenant business (~94 Next.js routes)

Key paths: `/dashboard`, `/clients`, `/content`, `/calendar`, `/pipeline`, `/publishing`, `/campaigns`, `/media-library`, `/content-studio`, `/content-planner`, `/content-factory`, `/briefs`, `/crm`, `/proposals`, `/executive-copilot`, `/sales-*`, `/buyer-*`, `/revenue-*`, `/deal-room`, `/communications`, `/communications/inbox`, `/communications/followups`, `/communications/templates`, `/unified-inbox`, `/wechat*`, `/whatsapp*`, `/billing`, `/tenant-users`, `/analytics`, `/tasks`, `/inbox`.

Route access: `frontend/lib/route-permissions.ts` (`TENANT_BUSINESS_PATHS`, role/permission gates).

### Admin / platform (admin JWT required)

| Area | Routes |
|------|--------|
| Platform console | `/admin-users`, `/admin-audit`, `/admin-settings` |
| Pilot & ops | `/pilot-readiness`, `/pilot-demo-mode`, `/pilot-*`, `/real-factory-pilot`, `/production-deployment`, `/factory-platform`, `/customer-portal*`, `/tenants`, `/ai-command-center`, `/operator-tasks`, `/audit`, `/system` |

### Backend API

- Authenticated: `/api/v1/*` (~90 routers in `backend/app/api/router.py`)
- Health: `GET /health`
- Docs: `/docs` (FastAPI)

---

## Integrations

| Integration | Status | Notes |
|-------------|--------|-------|
| OpenAI (GPT-4o) | Active | Captions, brief plans, assistant, context AI; `DEMO_MODE` for placeholders |
| Telegram Bot | Configurable | Webhook, group buffer, admin instructions |
| Instagram publisher | Partial | Publishing queue + safety checks |
| WeChat / WhatsApp | Adapter layer | Sync + provider stubs; no auto-messaging |
| PostgreSQL 16 | Active | Primary datastore |
| Local / S3 media | Active | `USE_S3` optional |
| Docker Compose | Dev default | postgres + backend (:8000) + frontend (:3000) |

---

## RBAC Status

### Tenant roles (`backend/app/core/tenant_permissions.py`)

`owner`, `manager`, `sales`, `operator`, `viewer` — permission sets enforced via `TenantAuthService.assert_permission`.

Notable gates:

- `/executive-copilot` → `executive.copilot.view` (owner)
- `/billing`, `/tenant-users` → owner or manager

### Admin roles (`backend/app/core/admin_permissions.py`)

`super_admin`, `platform_admin`, `support_admin`, `auditor` — platform-scoped permissions with audit logging.

Frontend guards: `TenantAuthGuard`, `DashboardRouteGuard`, `route-permissions.ts`.

---

## Tenant / Admin Access Status

| Layer | Mechanism | Separation |
|-------|-----------|------------|
| Tenant auth | JWT via `/api/v1/auth/*` + `/api/v1/tenant-auth/*` | `TENANT_SECRET_KEY`, tenant_id scoping |
| Admin auth | JWT via `/api/v1/admin-auth/*` | `ADMIN_SECRET_KEY`, separate session store |
| Route guards | Admin vs tenant session in localStorage (`session-sync`) | Pilot/platform routes admin-only |
| Cross-tenant | Blocked at service layer | `assert_tenant_access` |

Dev: `POST /api/v1/auth/create-demo-user` (development/test only).  
Prod checklist: `PRODUCTION_DEPLOYMENT_GUIDE.md`, `/production-deployment` assessment.

---

## Deployment Status

| Environment | Status |
|-------------|--------|
| Local Docker Compose | Working — 3 services, hot reload |
| Production | **Not deployed** — assessment-only tooling at `/production-deployment` |
| Migrations | Alembic (`backend/migrations/`); dev also uses `create_tables()` + schema patches |
| CI/CD | Not configured in repo |

Production blockers (from deployment guide): domain/SSL, secret keys, managed PostgreSQL, `DEMO_MODE=false`, backup/monitoring setup.

---

## Reference Files

- Detailed sprint log: `PROJECT_STATUS.md`
- Legacy context snapshot: `IRAY_CONTEXT.md`
- Production checklist: `PRODUCTION_DEPLOYMENT_GUIDE.md`
- Page → API mapping: `backend/app/core/dependency_registry.py`
