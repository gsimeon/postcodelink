"""Release Gate v5.8: Provider Reconciliation, Production Resilience & Worker Lifecycle

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-11-15 23:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add lifecycle columns to worker_heartbeats
    op.add_column('worker_heartbeats', sa.Column('last_successful_process_at', sa.DateTime(), nullable=True))
    op.add_column('worker_heartbeats', sa.Column('stop_reason', sa.String(length=128), nullable=True))

    # 2. Add audit and evidence tracking columns to notification_outbox
    op.add_column('notification_outbox', sa.Column('reconciliation_request_id', sa.String(length=64), nullable=True))
    op.add_column('notification_outbox', sa.Column('evidence_type', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('notification_outbox', 'evidence_type')
    op.drop_column('notification_outbox', 'reconciliation_request_id')
    op.drop_column('worker_heartbeats', 'stop_reason')
    op.drop_column('worker_heartbeats', 'last_successful_process_at')
