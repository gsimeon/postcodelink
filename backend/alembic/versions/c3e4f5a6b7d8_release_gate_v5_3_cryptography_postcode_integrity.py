"""Release Gate v5.3: Cryptography, queue integrity, postcode taxonomy, and api keys

Revision ID: c3e4f5a6b7d8
Revises: b2d3f4e5a6c7
Create Date: 2026-11-14 14:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e4f5a6b7d8'
down_revision: Union[str, None] = 'b2d3f4e5a6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind is not None and getattr(bind.dialect, "name", "") == "postgresql"

    # 1. Add SUPERSEDED to PostgreSQL enum if running on Postgres
    if is_postgres:
        op.execute("ALTER TYPE notificationdeliverystatus ADD VALUE IF NOT EXISTS 'SUPERSEDED'")

    # 2. Add delivery_version to notification_outbox table
    with op.batch_alter_table('notification_outbox') as batch_op:
        batch_op.add_column(sa.Column('delivery_version', sa.Integer(), nullable=True, server_default='1'))

    # 3. Add verification_status and verified_at to postcodes table
    with op.batch_alter_table('postcodes') as batch_op:
        batch_op.add_column(sa.Column('verification_status', sa.String(length=32), nullable=True, server_default='local_reference'))
        batch_op.add_column(sa.Column('verified_at', sa.DateTime(), nullable=True))

    # 4. Create api_keys foundation table
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('merchant_id', sa.String(length=36), sa.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, server_default='Default API Key'),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('hashed_key', sa.String(length=128), nullable=False, unique=True),
        sa.Column('monthly_quota', sa.Integer(), nullable=False, server_default='10000'),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table('api_keys') as batch_op:
        batch_op.create_index('ix_api_keys_merchant_id', ['merchant_id'])
        batch_op.create_index('ix_api_keys_key_prefix', ['key_prefix'])


def downgrade() -> None:
    op.drop_table('api_keys')
    with op.batch_alter_table('postcodes') as batch_op:
        batch_op.drop_column('verified_at')
        batch_op.drop_column('verification_status')
    with op.batch_alter_table('notification_outbox') as batch_op:
        batch_op.drop_column('delivery_version')
