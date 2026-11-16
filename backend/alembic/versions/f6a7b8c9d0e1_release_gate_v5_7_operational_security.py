"""Release Gate v5.7: Operational Security, Distributed Reliability, and Worker Heartbeats

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-15 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create worker_heartbeats table for cross-process heartbeat monitoring
    op.create_table(
        'worker_heartbeats',
        sa.Column('worker_id', sa.String(length=64), nullable=False),
        sa.Column('process_id', sa.Integer(), nullable=True),
        sa.Column('worker_role', sa.String(length=32), nullable=False, server_default='outbox_worker'),
        sa.Column('hostname', sa.String(length=64), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('active_jobs_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('worker_id'),
    )


def downgrade() -> None:
    op.drop_table('worker_heartbeats')
