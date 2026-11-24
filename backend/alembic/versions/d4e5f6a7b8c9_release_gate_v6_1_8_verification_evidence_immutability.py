"""Release Gate v6.1.8: Verification Evidence Table & Database-Level Immutability

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-24 20:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "verification_evidence" not in existing_tables:
        op.create_table(
            "verification_evidence",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("postcode", sa.String(length=20), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False, server_default="NIPOST"),
            sa.Column("provider_reference_id", sa.String(length=128), nullable=True),
            sa.Column("verification_method", sa.String(length=64), nullable=False, server_default="validator_autofill_pipeline"),
            sa.Column("dataset_version", sa.String(length=32), nullable=True),
            sa.Column("verified_at", sa.DateTime(), nullable=False),
            sa.Column("valid_until", sa.DateTime(), nullable=False),
            sa.Column("response_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="verified"),
            sa.Column("address_metadata_source", sa.String(length=64), nullable=False, server_default="nipost_autofill"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1" if dialect_name == "sqlite" else "true")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_verification_evidence_postcode", "verification_evidence", ["postcode"])

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
    """VerificationEvidence is a permanent retained audit ledger.
    
    Database-level immutability triggers are intentionally preserved on downgrade
    while the verification_evidence table and its audit records remain retained.
    """
    pass
