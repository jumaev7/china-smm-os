# Backup & Recovery Architecture

This document describes the backup and recovery architecture for China SMM OS. **No cloud backup is implemented yet** — this is the target design for production rollout.

## Components to Protect

| Asset | Location | Priority |
|-------|----------|----------|
| PostgreSQL database | `postgres` service / managed DB | Critical |
| Media files | `media_storage` volume or S3 bucket | High |
| Environment secrets | `.env` / secret manager | Critical |
| Alembic migrations | `backend/migrations/` | Medium (also in git) |

## Database Backup

### Recommended Approach (Production)

1. **Managed PostgreSQL** (AWS RDS, GCP Cloud SQL, Azure Database)
   - Enable automated daily snapshots (7–30 day retention)
   - Enable point-in-time recovery (PITR) where available
   - Store backups in a separate region/account

2. **Self-Hosted PostgreSQL**
   - Nightly `pg_dump` via cron:
     ```bash
     pg_dump -Fc -h localhost -U postgres china_smm_os > /backups/china_smm_os_$(date +%Y%m%d).dump
     ```
   - Encrypt dumps at rest (AES-256)
   - Copy to off-site storage (S3, GCS) within 1 hour
   - Retention: 7 daily, 4 weekly, 3 monthly

### Recovery Procedure (Database)

1. Stop backend services to prevent writes
2. Restore from snapshot or:
   ```bash
   pg_restore -h localhost -U postgres -d china_smm_os --clean /backups/china_smm_os_YYYYMMDD.dump
   ```
3. Verify migration version: `alembic current`
4. Run health check: `GET /api/v1/system/health`
5. Restart backend and frontend services
6. Verify tenant login and admin login

**RTO target**: 4 hours | **RPO target**: 24 hours (daily backup)

## Media Backup

### S3 Mode (`USE_S3=true`)

- Enable S3 versioning on the media bucket
- Configure cross-region replication for disaster recovery
- Lifecycle policy: transition old versions to Glacier after 90 days

### Local Volume Mode

- Nightly rsync or `tar` of `MEDIA_LOCAL_PATH` to backup storage:
  ```bash
  tar czf /backups/media_$(date +%Y%m%d).tar.gz ./media_storage
  ```
- Sync to off-site storage

### Recovery Procedure (Media)

1. Restore files to `MEDIA_LOCAL_PATH` or S3 bucket
2. Verify `MEDIA_BASE_URL` matches public URL
3. Test media URL from content item in UI

## Application State

- **In-memory error buffer**: Not backed up — resets on restart (acceptable)
- **Audit logs** (`platform_audit_logs`, `admin_audit_logs`): Included in DB backup
- **Pilot program data** (`pilot_factories`, `platform_feedback`): Included in DB backup

## Disaster Recovery Scenarios

| Scenario | Action |
|----------|--------|
| DB corruption | Restore latest pg_dump / snapshot |
| Full server loss | Provision new infra, restore DB + media, redeploy containers |
| Accidental tenant data delete | PITR to point before deletion (managed DB) |
| Secret compromise | Rotate keys, invalidate all JWTs (force re-login) |

## Implementation Status

| Item | Status |
|------|--------|
| Architecture documented | ✅ |
| Automated DB backup | ⏳ Not implemented — configure in production |
| Automated media backup | ⏳ Not implemented — configure in production |
| Restore runbook tested | ⏳ Test in staging before go-live |
| Off-site backup storage | ⏳ Configure with cloud provider |

## Next Steps for Production

1. Choose managed PostgreSQL with PITR
2. Configure S3 with versioning for media
3. Add backup monitoring alerts (backup job success/failure)
4. Run quarterly restore drills in staging
5. Document RTO/RPO in SLA with pilot factories
