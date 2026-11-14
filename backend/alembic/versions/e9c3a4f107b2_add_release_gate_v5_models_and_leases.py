"""add release gate v5 models and leases

Revision ID: e9c3a4f107b2
Revises: d8b2ddd3352d
Create Date: 2026-11-14 12:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9c3a4f107b2'
down_revision: Union[str, None] = 'd8b2ddd3352d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create login_attempts table
    op.create_table(
        'login_attempts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=False),
        sa.Column('attempted_at', sa.DateTime(), nullable=False),
        sa.Column('is_successful', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_attempts_email'), 'login_attempts', ['email'], unique=False)
    op.create_index(op.f('ix_login_attempts_ip_address'), 'login_attempts', ['ip_address'], unique=False)
    op.create_index(op.f('ix_login_attempts_attempted_at'), 'login_attempts', ['attempted_at'], unique=False)

    # 2. Add columns to notification_outbox
    op.add_column('notification_outbox', sa.Column('notification_type', sa.String(length=32), nullable=False, server_default='otp_delivery_pin'))
    op.add_column('notification_outbox', sa.Column('idempotency_key', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_notification_outbox_idempotency_key'), 'notification_outbox', ['idempotency_key'], unique=True)
    op.add_column('notification_outbox', sa.Column('next_attempt_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_notification_outbox_next_attempt_at'), 'notification_outbox', ['next_attempt_at'], unique=False)
    op.add_column('notification_outbox', sa.Column('locked_at', sa.DateTime(), nullable=True))
    op.add_column('notification_outbox', sa.Column('locked_by', sa.String(length=64), nullable=True))
    op.add_column('notification_outbox', sa.Column('failure_classification', sa.String(length=32), nullable=True))

    # 3. Add columns to postcodes
    op.add_column('postcodes', sa.Column('postcode_type', sa.String(length=24), nullable=False, server_default='conventional_area'))
    op.add_column('postcodes', sa.Column('building_reference', sa.String(length=64), nullable=True))
    op.add_column('postcodes', sa.Column('provenance', sa.String(length=128), nullable=False, server_default='NIPOST Official Digital Postcode Directory'))
    op.add_column('postcodes', sa.Column('dataset_version', sa.String(length=32), nullable=False, server_default='2024.2'))


def downgrade() -> None:
    # 3. Remove postcodes columns
    op.drop_column('postcodes', 'dataset_version')
    op.drop_column('postcodes', 'provenance')
    op.drop_column('postcodes', 'building_reference')
    op.drop_column('postcodes', 'postcode_type')

    # 2. Remove notification_outbox columns
    op.drop_column('notification_outbox', 'failure_classification')
    op.drop_column('notification_outbox', 'locked_by')
    op.drop_column('notification_outbox', 'locked_at')
    op.drop_index(op.f('ix_notification_outbox_next_attempt_at'), table_name='notification_outbox')
    op.drop_column('notification_outbox', 'next_attempt_at')
    op.drop_index(op.f('ix_notification_outbox_idempotency_key'), table_name='notification_outbox')
    op.drop_column('notification_outbox', 'idempotency_key')
    op.drop_column('notification_outbox', 'notification_type')

    # 1. Drop login_attempts table
    op.drop_index(op.f('ix_login_attempts_attempted_at'), table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_ip_address'), table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_email'), table_name='login_attempts')
    op.drop_table('login_attempts')
