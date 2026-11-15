"""Release Gate v5.5: Integration Integrity, Atomic Monthly Quotas, and Postcode Provenance

Revision ID: e5f6a7b8c9d0
Revises: d4f5a6b7c8e9
Create Date: 2026-11-15 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4f5a6b7c8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind is not None and getattr(bind.dialect, "name", "") == "postgresql"

    # 1. Add DISPATCHING and RECONCILIATION_REQUIRED to PostgreSQL enum if running on Postgres
    if is_postgres:
        op.execute("ALTER TYPE notificationdeliverystatus ADD VALUE IF NOT EXISTS 'DISPATCHING'")
        op.execute("ALTER TYPE notificationdeliverystatus ADD VALUE IF NOT EXISTS 'RECONCILIATION_REQUIRED'")

    # 2. Add period-based quota and revocation columns to api_keys table
    with op.batch_alter_table('api_keys') as batch_op:
        batch_op.add_column(sa.Column('current_period', sa.String(length=7), nullable=False, server_default='2026-11'))
        batch_op.add_column(sa.Column('period_usage_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('rate_limit_per_minute', sa.Integer(), nullable=False, server_default='60'))
        batch_op.add_column(sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default=sa.false()))

    # 3. Postcode provenance audit: Reclassify local demonstration postcodes to local_reference
    # Strictly target demonstration fixtures and local reference records, preserving legitimate NIPOST records
    op.execute(
        sa.text(
            "UPDATE postcodes "
            "SET verification_status = 'local_reference', "
            "    provenance = 'PostcodeLink National Postcode Format Demonstration Reference' "
            "WHERE code IN ('FC-02-A09-DB-09', 'LA-01-A04-IK-02') "
            "   OR provenance LIKE '%Demonstration%' "
            "   OR provenance LIKE '%Local Reference%' "
            "   OR provenance LIKE '%Pilot%' "
            "   OR (verification_status = 'official_verified' AND provenance NOT LIKE '%NIPOST Official%')"
        )
    )
    # Ensure any legitimate NIPOST verified record retains official_verified status
    op.execute(
        sa.text(
            "UPDATE postcodes "
            "SET verification_status = 'official_verified' "
            "WHERE provenance LIKE '%NIPOST Official%' "
            "  AND (verification_status IS NULL OR verification_status = 'local_reference')"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table('api_keys') as batch_op:
        batch_op.drop_column('is_revoked')
        batch_op.drop_column('rate_limit_per_minute')
        batch_op.drop_column('period_usage_count')
        batch_op.drop_column('current_period')
