"""Release Gate v6.0: Permanent Audit Retention, Soft Deletion & Requeue Tracking

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-16 02:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    # Drop existing triggers and tmp tables first so SQLite table rename during batch_alter_table doesn't encounter schema conflicts
    if dialect_name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_delete;")
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_update;")
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_deliveries;")
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_notification_outbox;")

    # 1. Add soft-deletion columns to deliveries table
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.add_column(sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect_name == "sqlite" else "false")))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_deliveries_is_deleted", ["is_deleted"])

    # 2. Add dispatch attempt, original idempotency, and previous provider message ID tracking to notification_outbox
    with op.batch_alter_table("notification_outbox") as batch_op:
        batch_op.add_column(sa.Column("dispatch_attempt", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("original_idempotency_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_failed_provider_message_id", sa.String(length=128), nullable=True))

    # 3. Unconditional Database Triggers for permanent audit immutability
    if dialect_name == "postgresql":
        # Unconditional rejection of any UPDATE or DELETE on delivery_events
        op.execute("""
        CREATE OR REPLACE FUNCTION prevent_delivery_events_tampering()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'UPDATE') THEN
                RAISE EXCEPTION 'delivery_events records are append-only immutable audit logs and cannot be updated';
            ELSIF (TG_OP = 'DELETE') THEN
                RAISE EXCEPTION 'delivery_events records are append-only immutable audit logs and cannot be deleted';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """)

        # Drop existing trigger if present, recreate unconditional trigger
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_immutable ON delivery_events;")
        op.execute("""
        CREATE TRIGGER trg_delivery_events_immutable
        BEFORE UPDATE OR DELETE ON delivery_events
        FOR EACH ROW EXECUTE FUNCTION prevent_delivery_events_tampering();
        """)

        # Restrict parent deletion if audit records exist (fail-closed without silent suppression)
        op.execute("""
        ALTER TABLE delivery_events DROP CONSTRAINT IF EXISTS delivery_events_delivery_id_fkey;
        ALTER TABLE delivery_events ADD CONSTRAINT delivery_events_delivery_id_fkey
            FOREIGN KEY (delivery_id) REFERENCES deliveries(id) ON DELETE RESTRICT;
        """)
    elif dialect_name == "sqlite":
        # SQLite unconditional triggers
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_delete;")
        op.execute("DROP TRIGGER IF EXISTS trg_deliveries_no_delete_with_audit_events;")

        op.execute("""
        CREATE TRIGGER trg_delivery_events_no_update
        BEFORE UPDATE ON delivery_events
        BEGIN
            SELECT RAISE(ABORT, 'delivery_events records are append-only immutable audit logs and cannot be updated');
        END;
        """)

        op.execute("""
        CREATE TRIGGER trg_delivery_events_no_delete
        BEFORE DELETE ON delivery_events
        BEGIN
            SELECT RAISE(ABORT, 'delivery_events records are append-only immutable audit logs and cannot be deleted');
        END;
        """)

        op.execute("""
        CREATE TRIGGER trg_deliveries_no_delete_with_audit_events
        BEFORE DELETE ON deliveries
        FOR EACH ROW
        WHEN EXISTS (SELECT 1 FROM delivery_events WHERE delivery_id = OLD.id)
        BEGIN
            SELECT RAISE(ABORT, 'Cannot delete delivery with existing audit events; use soft deletion');
        END;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_deliveries_no_delete_with_audit_events;")
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_no_delete;")
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_deliveries;")
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_notification_outbox;")

    inspector = sa.inspect(bind)
    outbox_cols = [c["name"] for c in inspector.get_columns("notification_outbox")]
    delivery_cols = [c["name"] for c in inspector.get_columns("deliveries")]

    with op.batch_alter_table("notification_outbox") as batch_op:
        if "last_failed_provider_message_id" in outbox_cols:
            batch_op.drop_column("last_failed_provider_message_id")
        if "original_idempotency_key" in outbox_cols:
            batch_op.drop_column("original_idempotency_key")
        if "dispatch_attempt" in outbox_cols:
            batch_op.drop_column("dispatch_attempt")

    with op.batch_alter_table("deliveries") as batch_op:
        if "ix_deliveries_is_deleted" in [ix["name"] for ix in inspector.get_indexes("deliveries")]:
            batch_op.drop_index("ix_deliveries_is_deleted")
        if "deleted_at" in delivery_cols:
            batch_op.drop_column("deleted_at")
        if "is_deleted" in delivery_cols:
            batch_op.drop_column("is_deleted")

    if dialect_name == "sqlite":
        # Fully restore original Release Gate v5.9 SQLite triggers AFTER batch alterations
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
    elif dialect_name == "postgresql":
        # Fully restore original Release Gate v5.9 PostgreSQL trigger and function
        op.execute("""
        CREATE OR REPLACE FUNCTION prevent_delivery_events_tampering()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'UPDATE') THEN
                RAISE EXCEPTION 'delivery_events records are append-only immutable audit logs and cannot be updated';
            ELSIF (TG_OP = 'DELETE') THEN
                IF (current_query() ~* 'delivery_events' AND current_query() !~* 'deliveries') OR EXISTS (SELECT 1 FROM deliveries WHERE id = OLD.delivery_id) THEN
                    RAISE EXCEPTION 'delivery_events records are append-only immutable audit logs and cannot be deleted';
                END IF;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """)

        op.execute("DROP TRIGGER IF EXISTS trg_delivery_events_immutable ON delivery_events;")
        op.execute("""
        CREATE TRIGGER trg_delivery_events_immutable
        BEFORE UPDATE OR DELETE ON delivery_events
        FOR EACH ROW EXECUTE FUNCTION prevent_delivery_events_tampering();
        """)

        op.execute("""
        ALTER TABLE delivery_events DROP CONSTRAINT IF EXISTS delivery_events_delivery_id_fkey;
        ALTER TABLE delivery_events ADD CONSTRAINT delivery_events_delivery_id_fkey
            FOREIGN KEY (delivery_id) REFERENCES deliveries(id) ON DELETE CASCADE;
        """)
