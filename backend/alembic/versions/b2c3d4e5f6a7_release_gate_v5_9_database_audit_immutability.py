"""Release Gate v5.9: Database Audit Immutability Triggers

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-16 00:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        # PostgreSQL trigger function and row-level trigger preventing direct update or deletion of delivery_events
        op.execute("""
        CREATE OR REPLACE FUNCTION prevent_delivery_events_tampering()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'UPDATE') THEN
                RAISE EXCEPTION 'delivery_events records are append-only immutable audit logs and cannot be updated';
            ELSIF (TG_OP = 'DELETE') THEN
                -- Allow cascade deletion if parent delivery is deleted, but strictly prohibit direct deletion of audit records
                IF (current_query() ~* '^\\s*DELETE\\s+FROM\\s+(ONLY\\s+)?(public\\.)?delivery_events\\b') THEN
                    RAISE EXCEPTION 'delivery_events records are append-only immutable audit logs and cannot be deleted';
                END IF;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """)

        op.execute("""
        CREATE TRIGGER trg_delivery_events_immutable
        BEFORE UPDATE OR DELETE ON delivery_events
        FOR EACH ROW EXECUTE FUNCTION prevent_delivery_events_tampering();
        """)
    elif dialect_name == "sqlite":
        # SQLite triggers for local and test compatibility
        op.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_delivery_events_no_update
        BEFORE UPDATE ON delivery_events
        BEGIN
            SELECT RAISE(ABORT, 'delivery_events records are append-only immutable audit logs and cannot be updated');
        END;
        """)

        op.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_delivery_events_no_delete
        BEFORE DELETE ON delivery_events
        WHEN EXISTS (SELECT 1 FROM deliveries WHERE id = OLD.delivery_id)
        BEGIN
            SELECT RAISE(ABORT, 'delivery_events records are append-only immutable audit logs and cannot be deleted');
        END;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_immutable ON delivery_events;")
        op.execute("DROP FUNCTION IF EXISTS prevent_delivery_events_tampering();")
    elif dialect_name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_delete;")
