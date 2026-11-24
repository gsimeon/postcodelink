"""Release Gate v6.1.8: Database-Level Verification Evidence Immutability

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-24 20:35:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        op.execute("""
        CREATE OR REPLACE FUNCTION prevent_verification_evidence_tampering()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'UPDATE') THEN
                RAISE EXCEPTION 'verification_evidence records are append-only immutable audit logs and cannot be updated';
            ELSIF (TG_OP = 'DELETE') THEN
                RAISE EXCEPTION 'verification_evidence records are append-only immutable audit logs and cannot be deleted';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_verification_evidence_immutable ON verification_evidence;")
        op.execute("""
        CREATE TRIGGER trg_verification_evidence_immutable
        BEFORE UPDATE OR DELETE ON verification_evidence
        FOR EACH ROW EXECUTE FUNCTION prevent_verification_evidence_tampering();
        """)
    elif dialect_name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_verification_evidence_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_verification_evidence_no_delete;")
        op.execute("""
        CREATE TRIGGER trg_verification_evidence_no_update
        BEFORE UPDATE ON verification_evidence
        BEGIN
            SELECT RAISE(ABORT, 'verification_evidence records are append-only immutable audit logs and cannot be updated');
        END;
        """)
        op.execute("""
        CREATE TRIGGER trg_verification_evidence_no_delete
        BEFORE DELETE ON verification_evidence
        BEGIN
            SELECT RAISE(ABORT, 'verification_evidence records are append-only immutable audit logs and cannot be deleted');
        END;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_verification_evidence_immutable ON verification_evidence;")
        op.execute("DROP FUNCTION IF EXISTS prevent_verification_evidence_tampering();")
    elif dialect_name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_verification_evidence_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_verification_evidence_no_delete;")
