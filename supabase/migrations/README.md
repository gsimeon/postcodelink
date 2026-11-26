# Supabase Migrations — Reference DDL Architecture Notice

## Architectural Authority Notice

> [!IMPORTANT]
> **Authoritative Migration Authority:**
> As of Release Gate v6.1+, **SQLAlchemy & Alembic** ([backend/alembic/versions](file:///backend/alembic/versions)) constitute the **single authoritative database schema and migration authority** for PostcodeLink.

### Role of Files in this Directory

The `.sql` files in this directory are preserved strictly for:
1. **Reference DDL:** Quick inspection of PostgreSQL types and initial table structures.
2. **Managed Supabase Compatibility:** Establishing baseline RLS policies if direct Supabase Studio database access is configured.

### Schema Enforcement Rule
- **Never apply migrations in this directory independently from Alembic.**
- Production database schema migrations are executed exclusively via:
  ```bash
  alembic upgrade head
  ```
- All new tables, column modifications, indexes, and triggers must be authored as Alembic revisions in `backend/alembic/versions/` and exercised against PostgreSQL in CI.
