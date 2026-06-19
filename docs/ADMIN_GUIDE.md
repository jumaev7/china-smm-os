# Admin Guide — China SMM OS

## Overview

China SMM OS is a multi-tenant SaaS platform for Chinese factory export growth. Platform admins operate internal tools; tenant users (factory staff) use the business workspace.

## Access

| Console | URL | Credentials |
|---------|-----|-------------|
| Platform admin | `/admin-login` → dashboard | Admin JWT |
| Tenant workspace | `/login` | Tenant user JWT |

Admin sessions use separate JWT storage from tenant sessions. The active session determines which routes and APIs are available.

## Key Admin Areas

### Pilot Operations
- **Pilot Program** (`/pilot-program`) — Track real factory pilots (status, dates, success score)
- **Real Factory Pilot** (`/real-factory-pilot`) — Guided first-factory onboarding checklist
- **Pilot Success** (`/pilot-success`) — Adoption and customer success metrics
- **Launch Readiness** (`/launch-readiness`) — Pre-launch score (0–100)

### Tenant Management
- **Tenants** (`/tenants`) — Create tenants, link clients, isolation checks
- **Tenant Users** (`/tenant-users`) — Owner/manager user management
- **Factory Partners** (`/factory-partners`) — Review factory applications

### Operations & Monitoring
- **System Health** (`/system-health`) — API, DB, scheduler, integrations
- **System** (`/system`) — Deep diagnostics, demo seed/reset
- **Audit Logs** (`/audit-logs`) — Centralized activity log
- **Error Tracking** (`/error-tracking`) — Frontend/API/integration errors
- **Feedback Center** (`/feedback`) — Pilot factory submissions

### Billing
- **Billing** (`/billing`) — Tenant subscriptions and client-level billing

## Security Model

- **Platform admin RBAC**: `platform.full`, `tenants.read`, `tenants.manage`, `diagnostics.read`, `billing.read`
- **Tenant roles**: owner, manager, sales, operator, viewer
- **Tenant isolation**: Resources scoped by `tenant_id` or `client_id` via tenant's clients

## Recommended Admin Workflow for First Pilot

1. Review application in Factory Partners
2. Create tenant + owner user
3. Add factory to Pilot Program (status: Invited → Onboarding)
4. Complete Real Factory Pilot checklist
5. Monitor Pilot Success dashboard during active phase
6. Collect feedback via Feedback Center
7. Review Launch Readiness before commercial launch

## Support Escalation

- Check Error Tracking for recent API failures
- Review Audit Logs for user activity
- Run integrity audit at `/audit` for data issues
