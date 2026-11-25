# Verification Evidence Lifecycle & Audit Retention Policy

## 1. Immutability Model (Append-Only Ledger)
`VerificationEvidence` (`verification_evidence` table) is an **append-only immutable audit ledger**:
- **Application layer**: SQLAlchemy `before_update` and `before_delete` listeners in `backend/app/models/verification_evidence.py` raise `ValueError` on any mutation or deletion attempt.
- **Database layer**: Alembic migration `d4e5f6a7b8c9` installs `BEFORE UPDATE` and `BEFORE DELETE` triggers in both SQLite and PostgreSQL.
- **Forward-only schema**: Migration `d4e5f6a7b8c9` intentionally preserves `verification_evidence` and its audit triggers on `downgrade()` so historical proof cannot be silently dropped.

## 2. Supersession, Revocation & Expiry
Because committed rows cannot be mutated:
- **Expiry**: Each record carries `verified_at` and `valid_until` (default 30 days). Consumers and `postcode_service` evaluate `is_expired` at read time (`now > valid_until`). Expired records remain in the ledger for historical auditability and fail closed to `verification_unavailable` / `local_reference` until re-verified.
- **Supersession & Correction**: When a postcode is re-verified or corrected, a **new** `VerificationEvidence` row is appended with a new `id`, `verified_at`, `valid_until`, `response_hash`, and `status`. Queries order by `VerificationEvidence.verified_at.desc()` so the latest valid record takes precedence while preserving full history.
- **Revocation**: Erroneous or revoked verifications are superseded by appending a new `VerificationEvidence` record with `status="rejected"` and `address_metadata_source="unverified"`, rather than updating `is_active` on the historical row.

## 3. Retention, Access Control & Recovery
- **Retention**: Evidence rows are retained for at least 7 years (or the governing NIPOST commercial agreement retention window, whichever is shorter/required).
- **Access Control**: Only authenticated backend services persist `VerificationEvidence`; public/merchant API responses expose sanitized provenance metadata (`evidence_id`, `verified_at`, `valid_until`, `provider`, `address_metadata_source`).
- **Backup & Recovery**:
  1. Take and verify a database snapshot (`pg_dump` / managed snapshot) before any Alembic upgrade.
  2. Never attempt to `UPDATE` or `DELETE` `verification_evidence` rows in production.
  3. Use forward-fix migrations for schema evolution; restore from a verified snapshot if an upgrade must be reverted.
