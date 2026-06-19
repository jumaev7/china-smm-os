# Deployment Checklist

## Pre-Deploy

- [ ] All migrations applied (`alembic upgrade head`)
- [ ] `APP_ENV=production` set
- [ ] `DEMO_MODE=false` in production
- [ ] Strong `SECRET_KEY`, `ADMIN_SECRET_KEY`, `TENANT_SECRET_KEY`
- [ ] `OPENAI_API_KEY` configured (if AI features required)
- [ ] PostgreSQL backups scheduled (see BACKUP_RECOVERY_ARCHITECTURE.md)
- [ ] CORS origins restricted to production domains
- [ ] SSL/TLS terminated at load balancer or reverse proxy

## Infrastructure

- [ ] Docker Compose or K8s manifests reviewed
- [ ] Database connection pool sized for expected load
- [ ] Media storage: S3 or persistent volume configured
- [ ] `MEDIA_BASE_URL` points to public API domain

## Integrations

- [ ] Telegram: `TELEGRAM_BOT_TOKEN`, webhook URL registered
- [ ] WhatsApp: Meta Cloud API credentials + webhook verify token
- [ ] WeChat: Provider credentials (if live sync required)
- [ ] Email/notifications for admin alerts (recommended)

## Security

- [ ] Admin bootstrap credentials removed or rotated
- [ ] Admin security checks pass (`/admin-auth/security-checks`)
- [ ] Tenant isolation test script run
- [ ] Rate limiting on admin login verified

## Monitoring

- [ ] Health endpoint monitored (`GET /health`, `GET /api/v1/system/health`)
- [ ] System Health dashboard accessible (`/system-health`)
- [ ] Error Tracking reviewed (`/error-tracking`)
- [ ] External APM (Sentry) wired (recommended for production)
- [ ] Uptime alerts configured

## Post-Deploy Verification

- [ ] Tenant login flow works
- [ ] Admin login flow works
- [ ] Pilot Program CRUD works
- [ ] Feedback submission works
- [ ] Billing page loads for owner role
- [ ] Onboarding wizard completes
- [ ] Launch Readiness score ≥ target threshold

## Rollback Plan

- [ ] Previous Docker image tag documented
- [ ] Database restore procedure tested (see BACKUP_RECOVERY_ARCHITECTURE.md)
- [ ] Rollback decision owner identified
