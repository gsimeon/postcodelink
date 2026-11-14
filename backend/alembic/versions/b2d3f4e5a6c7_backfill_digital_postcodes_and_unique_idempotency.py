"""backfill digital postcodes metadata and add unique merchant idempotency constraint

Revision ID: b2d3f4e5a6c7
Revises: a1c2e3f4b5d6
Create Date: 2026-11-14 13:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d3f4e5a6c7'
down_revision: Union[str, None] = 'a1c2e3f4b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add unique composite constraint on (merchant_id, idempotency_key) to deliveries
    with op.batch_alter_table('deliveries') as batch_op:
        batch_op.create_unique_constraint('uq_merchant_idempotency_key', ['merchant_id', 'idempotency_key'])

    # 2. Backfill digital postcode metadata in database
    op.execute(
        sa.text("""
            UPDATE postcodes
            SET postcode_type = 'digital_location',
                building_reference = 'Plot 4 Ikeja Commercial Plaza',
                provenance = 'NIPOST Digital Address Register 2024',
                dataset_version = '2024.1'
            WHERE code = 'LAG-IKJ-0012'
        """)
    )
    op.execute(
        sa.text("""
            UPDATE postcodes
            SET postcode_type = 'digital_location',
                building_reference = 'Admiralty Mall & Tower',
                provenance = 'NIPOST Digital Address Register 2024',
                dataset_version = '2024.1'
            WHERE code = 'LAG-LEK-0045'
        """)
    )
    op.execute(
        sa.text("""
            UPDATE postcodes
            SET postcode_type = 'digital_location',
                building_reference = 'Federal Commerce House',
                provenance = 'NIPOST Digital Address Register 2024',
                dataset_version = '2024.1'
            WHERE code = 'ABJ-GAR-0101'
        """)
    )


def downgrade() -> None:
    with op.batch_alter_table('deliveries') as batch_op:
        batch_op.drop_constraint('uq_merchant_idempotency_key', type_='unique')
