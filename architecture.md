# Architecture

> Agent memory file — technical architecture overview for China SMM OS.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14 App Router, TypeScript, Tailwind CSS, React Query, react-hot-toast |
| Backend | FastAPI, Python 3.12, SQLAlchemy 2 (async), Pydantic v2 |
| Database | PostgreSQL 16 |
| Migrations | Alembic (prod) + dev `create_tables()` / `ensure_dev_schema_patches()` |
| Storage | Local filesystem (`./media_storage`) or S3-compatible |
| AI | OpenAI API (`gpt-4o` default) |
| Infra | Docker Compose (postgres, backend, frontend) |

---

## Frontend Structure

```
frontend/
├── app/
│   ├── (dashboard)/          # Main tenant + admin-in-dashboard shell
│   ├── (admin)/              # Admin console layout (users, audit, settings)
│   ├── login/                # Tenant login
│   ├── admin-login/          # Admin login
│   └── review/[token]/       # Public client review
├── components/
│   ├── auth/                 # TenantAuthGuard, DashboardRouteGuard
│   ├── content/              # Modals, checklist, generation UI
│   ├── assistant/            # Floating AI assistant
│   └── ui/design-system/     # Shared DataTable, HealthIndicator, PageStates
├── lib/
│   ├── api.ts                # Typed API client (all backend calls)
│   ├── route-permissions.ts  # RBAC + nav visibility (single source of truth)
│   ├── nav-access.ts         # Re-exports route-permissions
│   ├── session-sync.ts       # Admin vs tenant JWT session
│   ├── I18nProvider.tsx      # EN/RU/ZH
│   └── usePostAuthNavigation.ts
└── locales/                  # en.json, ru.json, zh.json
```

**Routing model:** App Router with route groups. Access enforced client-side via guards + `evaluateRouteAccess()`. API calls attach Bearer token from active session (tenant or admin).

---

## Backend Structure

```
backend/app/
├── api/
│   ├── router.py             # Aggregates all /api/v1 routers
│   ├── v1/                   # ~90 domain routers (clients, crm, executive_copilot, …)
│   └── public/               # review, landing, redirect (no JWT)
├── core/
│   ├── config.py             # Settings / env
│   ├── database.py           # Async engine, sessions, dev table creation
│   ├── tenant_access.py      # get_current_tenant_user, require_role
│   ├── admin_access.py       # get_current_admin, require_admin_permission
│   ├── tenant_permissions.py # Tenant RBAC matrix
│   ├── admin_permissions.py  # Admin RBAC matrix
│   ├── executive_access.py   # Executive Copilot actor resolution
│   ├── dependency_registry.py# Page → endpoint → service → table map
│   └── admin_route_registry.py
├── models/                   # SQLAlchemy ORM (~80+ entities)
├── schemas/                  # Pydantic request/response
├── services/                 # Business logic (~100+ services)
└── main.py                   # FastAPI app, CORS, lifespan, /media mount
```

**Pattern:** Router → Service → Model. Cross-cutting: `endpoint_guard`, pagination helpers, audit logging for admin actions.

---

## Database

- **Engine:** PostgreSQL via `asyncpg`
- **Key entity groups:**
  - **SMM:** `clients`, `media_files`, `content_items`, `calendar_entries`, `campaigns`, `publish_attempts`
  - **CRM:** `crm_leads`, `crm_deals`, `crm_proposals`, `crm_documents`, `crm_activities`
  - **Tenant SaaS:** `tenants`, `tenant_users`, `subscriptions`, `plans`, `invoices`
  - **Admin:** `admin_users`, `admin_sessions`, `admin_audit_logs`
  - **Factory:** factory profile, products, certificates, export markets, media
  - **Comms:** `communication_threads`, `communication_messages`, WeChat/WhatsApp account tables
  - **Briefs:** `client_briefs` (status workflow, AI plan JSON, media refs)
  - **Telegram:** buffer messages, processed updates, instruction JSON on content
- **Dev vs prod:** Dev auto-creates/patches schema on startup; production must run `alembic upgrade head`.

---

## Auth Flow

### Tenant

```
POST /api/v1/auth/login { email, password }
  → TenantAuthService.login
  → JWT access + refresh (signed with TENANT_SECRET_KEY)
  → Frontend stores token, session type = "tenant"
GET /api/v1/auth/me
  → resolve user + tenant_id + role + permissions
Protected routes → Depends(get_current_tenant_user)
  → validate JWT → load TenantUser → assert tenant active
  → assert_permission / assert_tenant_access as needed
```

### Admin

```
POST /api/v1/admin-auth/login
  → AdminAuthService.login (rate limit, lockout, session record)
  → JWT (ADMIN_SECRET_KEY) + session_id + access_nonce
Frontend session type = "admin"
Protected routes → Depends(get_current_admin)
  → AdminRbacService.resolve_current_admin
  → require_admin_permission / require_admin_role + audit log
```

### Public

- Review tokens, landing leads, attribution redirects — no JWT; token/slug validation in service layer.

---

## RBAC Flow

### Tenant (business users)

1. Role assigned on `tenant_users.role`
2. Permissions derived from `ROLE_PERMISSIONS` in `tenant_permissions.py`
3. API: `TenantAuthService.assert_permission(user, "leads.manage")`
4. Frontend: `TENANT_ROUTE_ROLE_REQUIREMENTS`, `TENANT_ROUTE_PERMISSION_REQUIREMENTS` in `route-permissions.ts`
5. **Isolation:** every query scoped by `tenant_id`; cross-tenant returns 403

### Admin (platform operators)

1. Role on `admin_users.role` — super_admin has `platform.full`
2. Permissions from `admin_permissions.py`; route matrix in `admin_route_registry.py`
3. API: `require_admin_permission("tenants.manage")` with audit trail
4. Frontend: `PLATFORM_CONSOLE_PATHS` + `PLATFORM_PILOT_PATHS` require admin session

### Executive Copilot

- Dual actor: tenant owner/manager with `executive.copilot.view`, or admin for platform overview
- Resolved in `executive_access.py` → read-only aggregation across services

---

## Content Pipeline Flow

### Kanban pipeline (`/pipeline`)

Stages: `draft` → `internal_review` → `client_review` → `approved` → `scheduled` → `published` (+ `failed`)

```
ContentPipelineService.board()
  → maps content_items.status + client_review_status → pipeline stage
PATCH /content-pipeline/items/{id}/stage
  → validates _ALLOWED_TRANSITIONS
  → updates content status, review flags, scheduling
PublishingQueueService / ScheduledPublishService
  → queue → publish attempts → Instagram adapter (with PublishSafetyService)
```

### Legacy content workflow

- Statuses: draft, ready, ready_for_approval, approved, scheduled, published, failed, changes_requested
- Telegram → ContentItem (source: telegram, telegram_group, tg_group_buffer)
- AI generation: `/generate`, `/content/{id}/generate`
- Client review: token link sets `client_approved_at` / changes_requested (parallel to admin approve)
- Workflow “Prepare Everything”: in-memory progress (`workflow_service`) — subtitles, voice, export

### Client Brief → Content (`/briefs`)

```
Tenant submits brief (ClientBriefService.submit)
  → status: new
Admin/operator generates AI plan (7 posts, multilingual captions)
  → status: reviewing
Request changes / approve
  → changes_requested / approved
Convert to content + operator tasks
  → status: converted → ContentItems + OperatorTasks
```

---

## AI Integrations

| Feature | Service | Endpoint(s) |
|---------|---------|-------------|
| Caption generation | `ai_service`, `content_service` | `/generate`, `/content/{id}/generate` |
| Dashboard assistant | `assistant_service` | `/assistant/chat`, `/assistant/apply` |
| Context AI | `context_ai_service` | Used in generation + workflow |
| Client brief plans | `client_brief_service` | `/client-briefs/{id}/generate-plan` |
| Executive Copilot | `executive_copilot_service` | `/executive-copilot/*` (heuristic, read-only) |
| Sales / operator AI | `sales_assistant_service`, `operator_task_engine_service` | Various |
| Lead / comm intelligence | `lead_classification_service`, `communication_intelligence_service` | Classification endpoints |

**Safety:** `DEMO_MODE` returns placeholders without API key. Assistant `suggested_patch` limited to caption/hashtag/notes fields. Executive Copilot and pilot validation modules are read-only aggregators.

---

## External Integrations

| System | Integration point | Behavior |
|--------|-------------------|----------|
| OpenAI | `ai_service`, brief/assistant services | GPT-4o JSON + text generation |
| Telegram | `telegram_service`, webhook router | Ingest media/text; group buffer; admin NL |
| Instagram | `instagram_publisher`, publishing queue | Scheduled publish with safety checks |
| WeChat | `wechat_*_service` | Account registry, sync adapters, contact center |
| WhatsApp | `whatsapp_*_service` | Same pattern as WeChat |
| S3 | `core/storage.py` | Optional media backend |
| Public web | `public/landing`, `public/review`, `public/redirect` | Lead capture, client review, attribution |

**Explicit non-goals:** No autonomous outbound messaging, no auto CRM lead creation from sync, no payment execution in assessment modules.

---

## Key Configuration (`backend/app/core/config.py`)

- `DATABASE_URL`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`
- `ADMIN_SECRET_KEY`, `TENANT_SECRET_KEY`, `SECRET_KEY`
- `PUBLIC_APP_URL`, `MEDIA_BASE_URL`, `CORS_ORIGINS`
- `USE_S3`, `DEMO_MODE`, `SCHEDULED_PUBLISH_ENABLED`, `HEALTH_SNAPSHOT_ENABLED`

---

## Observability

- `/system` — component health (DB, scheduler, AI, Telegram)
- `/system/stability` — API route probes
- `HealthSnapshotService` — background probes (disable in dev via env)
- `dependency_registry.py` — developer page → backend dependency map
