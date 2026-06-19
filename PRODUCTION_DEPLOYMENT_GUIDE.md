# Production Deployment Guide

Read-only preparation checklist for China SMM OS production launch. This guide supports the `/production-deployment` assessment dashboard — it does not execute deployment steps.

## Safety

- **Assessment only** — no DNS changes, SSL generation, cloud provisioning, or deployment execution
- All checks are read-only aggregations over existing configuration and services
- POST `/api/v1/production-deployment/refresh` recomputes scores only (no data writes)

---

## Domain Checklist

- [ ] Register production domain (e.g. `app.yourcompany.com`)
- [ ] Point DNS A/AAAA or CNAME records to your load balancer or hosting provider
- [ ] Set `PUBLIC_APP_URL` to the production frontend origin (HTTPS)
- [ ] Set `MEDIA_BASE_URL` to the production backend/media origin (HTTPS)
- [ ] Verify review links (`/public/review/{token}`) resolve to the correct frontend
- [ ] Remove `localhost` from `CORS_ORIGINS` in production

---

## SSL Checklist

- [ ] Obtain TLS certificates (Let's Encrypt, cloud provider ACM, or commercial CA)
- [ ] Terminate TLS at load balancer or reverse proxy (nginx, Caddy, Cloudflare)
- [ ] Ensure `PUBLIC_APP_URL` uses `https://`
- [ ] Ensure `MEDIA_BASE_URL` uses `https://`
- [ ] Enable HSTS on the public frontend (optional but recommended)
- [ ] Verify mixed-content warnings are absent (HTTP media on HTTPS pages)

---

## Production Environment Checklist

| Variable | Requirement |
|----------|-------------|
| `APP_ENV` | Must be `production` |
| `ADMIN_SECRET_KEY` | Long random string; must differ from tenant key |
| `TENANT_SECRET_KEY` | Long random string; must differ from admin key |
| `SECRET_KEY` | Change from default `change-me` |
| `DATABASE_URL` | Managed PostgreSQL (not localhost) |
| `CORS_ORIGINS` | Production frontend origin(s) only |
| `DEMO_MODE` | Must be `false` |
| `ADMIN_BOOTSTRAP_*` | Empty / unset in production |
| `OPENAI_API_KEY` | Real key if AI features required |

JWT settings:

- `JWT_ALGORITHM=HS256` (default)
- Review `ACCESS_TOKEN_EXPIRE_MINUTES` and `REFRESH_TOKEN_EXPIRE_DAYS` for your security policy

---

## Backup Checklist

- [ ] Enable automated PostgreSQL backups (provider snapshot or `pg_dump` cron)
- [ ] Define retention policy (minimum 7 daily, 4 weekly recommended)
- [ ] Document restore procedure and test on staging
- [ ] Back up `media_storage` volume or configure S3 (`USE_S3=true`)
- [ ] Store backup credentials separately from application secrets
- [ ] Verify Alembic migration history is tracked in git before go-live

Restore test (staging):

1. Restore database snapshot to a test instance
2. Run `alembic upgrade head`
3. Verify admin login and tenant isolation
4. Confirm media files accessible

---

## Monitoring Checklist

- [ ] Review `/system/stability` — API health probes should be green
- [ ] Review `/system` — database, scheduler, AI, Telegram status
- [ ] Register production deployment in dependency registry (`/production-deployment`)
- [ ] Wire external uptime monitoring (Pingdom, UptimeRobot, cloud provider)
- [ ] Configure error alerting (Sentry, email, PagerDuty)
- [ ] Monitor disk usage for PostgreSQL and media storage
- [ ] Set up log aggregation for backend (uvicorn) and frontend

Key API probes (via `api_health_service`):

- `production_deployment` → `/api/v1/production-deployment/overview`
- `admin_auth` → `/api/v1/admin-auth/security-checks`
- `dashboard`, `billing`, `tenants`, `executive_copilot`

---

## Launch Checklist

Complete before directing real factory clients to the platform:

1. **Admin security** — `/admin-audit` security status score ≥ 80, zero open admin routes
2. **Tenant isolation** — run isolation check on `/tenants` for each active tenant
3. **Billing** — subscription plans configured on `/billing`
4. **First pilot client** — `/first-pilot-client` launch_ready = true
5. **Pilot launch QA** — `/pilot-launch` smoke tests passing
6. **Production deployment** — `/production-deployment` readiness score ≥ 80, zero blockers
7. **Run migrations** — `alembic upgrade head` on production database
8. **Docker / hosting** — backend `:8000`, frontend `:3000` or reverse-proxied equivalents
9. **Telegram** — `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ADMIN_ID` configured if using bot workflow
10. **Post-launch** — monitor `/production-deployment/summary` for regressions

---

## Related Pages

| Page | Purpose |
|------|---------|
| `/production-deployment` | Full deployment readiness dashboard |
| `/admin-audit` | Admin security hardening status |
| `/first-pilot-client` | First real client launch readiness |
| `/pilot-launch` | Pilot QA, demo data, smoke tests |
| `/system/stability` | API health and dependency registry |
| `/executive-copilot` | Executive rollup including production readiness |

---

## API Endpoints

| Method | Path |
|--------|------|
| GET | `/api/v1/production-deployment/overview` |
| GET | `/api/v1/production-deployment/readiness` |
| GET | `/api/v1/production-deployment/environment` |
| GET | `/api/v1/production-deployment/checklist` |
| GET | `/api/v1/production-deployment/backups` |
| GET | `/api/v1/production-deployment/monitoring` |
| GET | `/api/v1/production-deployment/security` |
| GET | `/api/v1/production-deployment/summary` |
| GET | `/api/v1/production-deployment/summary-widget` |
| POST | `/api/v1/production-deployment/refresh` |

All endpoints require admin JWT with `platform.settings` permission.

---

## Migrations

None — read-only aggregation over existing tables and configuration.
