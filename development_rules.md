# Development Rules

> Rules Cursor must follow before and after every implementation in China SMM OS.

---

## BEFORE ANY CODE CHANGE

### 1. Read (mandatory)

| File | Purpose |
|------|---------|
| `project_status.md` | Current platform state, modules, routes, RBAC, deployment |
| `architecture.md` | Frontend/backend structure, auth, pipelines, integrations |
| `current_task.md` | Active task, goals, blockers, files in scope |
| `known_issues.md` | Bugs and limitations to avoid or account for |
| `change_log.md` | Recent changes and affected areas |

Also consult when relevant:

- `PROJECT_STATUS.md` — detailed sprint history
- `PRODUCTION_DEPLOYMENT_GUIDE.md` — production constraints
- `backend/app/core/dependency_registry.py` — page ↔ API ↔ table map

### 2. Summarize understanding

Before editing, state (in the agent response):

- What the task requires
- Which modules/routes/services are affected
- Auth/RBAC implications (tenant vs admin vs public)
- Any known issues that apply

### 3. Identify affected modules

Map changes to:

- Frontend routes (`frontend/app/`, `frontend/lib/route-permissions.ts`)
- Backend routers (`backend/app/api/v1/`)
- Services (`backend/app/services/`)
- Models/schemas/migrations (`backend/app/models/`, `schemas/`, `migrations/`)
- Locales (`frontend/locales/`) if UI strings change

### 4. Make the smallest possible change

- Fix only what the task requires
- No drive-by refactors, renames, or formatting sweeps
- Prefer extending existing services over new abstractions
- Match existing naming, types, and patterns in the touched files

### 5. Do not refactor unrelated code

Unrelated improvements belong in a separate task.

### 6. Preserve (never break without explicit approval)

| Area | Constraint |
|------|------------|
| **Auth** | Separate tenant JWT (`/auth`, `TENANT_SECRET_KEY`) and admin JWT (`/admin-auth`, `ADMIN_SECRET_KEY`) |
| **RBAC** | Tenant roles in `tenant_permissions.py`; admin roles in `admin_permissions.py`; frontend gates in `route-permissions.ts` |
| **Tenant/admin separation** | No cross-tenant data access; pilot/platform routes admin-only |
| **Executive Copilot** | Read-only aggregation; preserve `executive.copilot.view` gate |
| **Brief Pipeline** | Status flow: `new → reviewing → changes_requested/approved → converted`; AI plan → content/task conversion |
| **Content Pipeline** | Kanban stages and `_ALLOWED_TRANSITIONS` in `content_pipeline_service.py`; publishing safety checks |

### 7. Update (before marking task complete)

| File | When |
|------|------|
| `current_task.md` | At task start (scope) and end (next task) |
| `change_log.md` | After every completed feature/fix with date, summary, files, result |

---

## AFTER EVERY COMPLETED TASK

1. **Update `project_status.md`** if platform state changed (new module, route, integration, milestone, RBAC rule, deployment status).
2. **Update `change_log.md`** with a dated entry.
3. **Remove resolved issues** from `known_issues.md` (move to Resolved section if useful).
4. **Update `current_task.md`** with the next active task and clear blockers.

---

## Safety defaults

- No autonomous messaging, payments, or external side effects unless the task explicitly requires it.
- Pilot/validation/deployment modules stay **read-only** unless task says otherwise.
- Do not commit secrets (`.env`, keys, credentials).
- Run migrations via Alembic for schema changes; add revision files under `backend/migrations/versions/`.
- Do not create git commits unless the user explicitly asks.

---

## Verification checklist (when applicable)

- [ ] Tenant and admin flows still authenticate separately
- [ ] Cross-tenant access still denied
- [ ] Affected frontend routes respect `route-permissions.ts`
- [ ] No unrelated files modified
- [ ] Governance files updated per this document
