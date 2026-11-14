"""add release gate v5.1 features: operator capacity, delivery idempotency, and outbox payloads

Revision ID: a1c2e3f4b5d6
Revises: e9c3a4f107b2
Create Date: 2026-11-14 12:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c2e3f4b5d6'
down_revision: Union[str, None] = 'e9c3a4f107b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add max_active_deliveries to operators
    op.add_column('operators', sa.Column('max_active_deliveries', sa.Integer(), nullable=False, server_default='15'))

    # 2. Add idempotency_key to deliveries
    op.add_column('deliveries', sa.Column('idempotency_key', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_deliveries_idempotency_key'), 'deliveries', ['idempotency_key'], unique=False)

    # 3. Add recipient_name and message_payload to notification_outbox
    op.add_column('notification_outbox', sa.Column('recipient_name', sa.String(length=128), nullable=True))
    op.add_column('notification_outbox', sa.Column('message_payload', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('notification_outbox', 'message_payload')
    op.drop_column('notification_outbox', 'recipient_name')
    op.drop_index(op.f('ix_deliveries_idempotency_key'), table_name='deliveries')
    op.drop_column('deliveries', 'idempotency_key')
    op.drop_column('operators', 'max_active_deliveries')
