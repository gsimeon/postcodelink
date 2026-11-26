# PostcodeLink Deployment, Worker & Disaster Recovery Runbook

## 1. Pre-Deployment Requirements
1. **Schema Authority**: SQLAlchemy + Alembic (`backend/alembic/`) is the sole schema authority. Automatic `Base.metadata.create_all()` is disabled in `staging` and `production`.
2. **Environment Variables**:
   - `ENVIRONMENT=production` (or `staging`)
   - `SECRET_KEY`, `OTP_SECRET_KEY`, `OUTBOX_ENCRYPTION_KEY` (each >= 32 chars, cryptographically random, distinct per domain)
   - `DATABASE_URL=postgresql+psycopg2://...`
   - `REDIS_URL=redis://...` (`REDIS_REQUIRED_IN_PRODUCTION=true`)
   - `CORS_ORIGINS=["https://app.postcodelink.ng"]`
   - `TRUSTED_PROXIES` (explicitly set to reverse-proxy IPs/CIDRs; defaults to `[]` in `staging`/`production`)
   - `OUTBOX_WORKER_ENABLED=true`
   - `SEED_DEMO_DATA=false`, `SEED_DEMO_ACCOUNTS=false` (enforced; startup fails if `true` in `staging`/`production`)

## 2. Release & Migration Sequence
1. **Take & verify a PostgreSQL snapshot** before running migrations:
   ```bash
   pg_dump "$DATABASE_URL" --format=custom --file="backup_$(date -u +%Y%m%dT%H%M%SZ).dump"
   ```
2. **Apply Alembic migrations**:
   ```bash
   python -m alembic upgrade head
   ```
3. **Start API service** (`PROCESS_ROLE=api`):
   ```bash
   PROCESS_ROLE=api uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
   ```
4. **Start Outbox Worker** (`PROCESS_ROLE=worker` as an independent process):
   ```bash
   PROCESS_ROLE=worker python -m backend.app.workers.outbox_worker
   ```

## 3. Health & Readiness Verification
- **Liveness** (public): `GET /health/live` → `200 OK`
- **Worker / Rate Limiter / Integrations** (require `ADMIN` auth in `production`):
  - `GET /health/worker`
  - `GET /health/rate-limiter`
  - `GET /health/integrations`

## 4. Backup & Restore Drill Procedure
Because `verification_evidence` is an append-only immutable ledger (forward-only migration `d4e5f6a7b8c9`):
1. Never run manual `UPDATE` or `DELETE` against `verification_evidence`.
2. To test recovery, restore the `.dump` snapshot into a staging/scratch PostgreSQL database:
   ```bash
   pg_restore --clean --if-exists --dbname="$SCRATCH_DATABASE_URL" backup_YYYYMMDDTHHMMSSZ.dump
   python -m alembic current
   ```
3. If a production release must be reverted, restore from the pre-migration snapshot or apply a forward-fix Alembic migration.
