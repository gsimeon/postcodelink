"""Release Gate v5.4: AES-256-GCM outbox, national digital postcodes, and outbox reconciliation

Revision ID: d4f5a6b7c8e9
Revises: c3e4f5a6b7d8
Create Date: 2026-11-14 14:50:00.000000

"""
from typing import Sequence, Union
import uuid
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f5a6b7c8e9'
down_revision: Union[str, None] = 'c3e4f5a6b7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind is not None and getattr(bind.dialect, "name", "") == "postgresql"

    # 1. Add RECONCILED to PostgreSQL enum if running on Postgres
    if is_postgres:
        op.execute("ALTER TYPE notificationdeliverystatus ADD VALUE IF NOT EXISTS 'RECONCILED'")

    # 2. Add provider_message_id and status_reconciled_at to notification_outbox table
    with op.batch_alter_table('notification_outbox') as batch_op:
        batch_op.add_column(sa.Column('provider_message_id', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('status_reconciled_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_notification_outbox_provider_message_id', ['provider_message_id'])

    # 3. Backfill official 11-character national digital postcodes (October 2026 National Standard)
    postcodes_table = sa.table(
        'postcodes',
        sa.column('id', sa.String),
        sa.column('code', sa.String),
        sa.column('area', sa.String),
        sa.column('state', sa.String),
        sa.column('lga', sa.String),
        sa.column('lat', sa.Float),
        sa.column('lng', sa.Float),
        sa.column('postcode_type', sa.String),
        sa.column('building_reference', sa.String),
        sa.column('verification_status', sa.String),
        sa.column('provenance', sa.String),
        sa.column('dataset_version', sa.String),
        sa.column('is_active', sa.Boolean),
    )

    national_records = [
        {
            "id": str(uuid.uuid4()),
            "code": "FC-02-A09-DB-09",
            "area": "Garki District Area 2",
            "state": "Abuja (FCT)",
            "lga": "Municipal Area Council",
            "lat": 9.0321,
            "lng": 7.4891,
            "postcode_type": "digital_location",
            "building_reference": "Federal Commerce House",
            "verification_status": "official_verified",
            "provenance": "NIPOST Official Digital Postcode Directory",
            "dataset_version": "2026.1",
            "is_active": True,
        },
        {
            "id": str(uuid.uuid4()),
            "code": "LA-01-A04-IK-02",
            "area": "Ikeja Central Business District",
            "state": "Lagos",
            "lga": "Ikeja",
            "lat": 6.5921,
            "lng": 3.3541,
            "postcode_type": "digital_location",
            "building_reference": "Plot 4 Ikeja Commercial Plaza",
            "verification_status": "official_verified",
            "provenance": "NIPOST Official Digital Postcode Directory",
            "dataset_version": "2026.1",
            "is_active": True,
        },
    ]

    for rec in national_records:
        bind.execute(
            sa.text(
                "INSERT INTO postcodes (id, code, area, state, lga, lat, lng, postcode_type, building_reference, verification_status, provenance, dataset_version, is_active) "
                "SELECT :id, :code, :area, :state, :lga, :lat, :lng, :postcode_type, :building_reference, :verification_status, :provenance, :dataset_version, :is_active "
                "WHERE NOT EXISTS (SELECT 1 FROM postcodes WHERE code = :code)"
            ),
            rec,
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM postcodes WHERE code IN ('FC-02-A09-DB-09', 'LA-01-A04-IK-02')"))

    with op.batch_alter_table('notification_outbox') as batch_op:
        batch_op.drop_index('ix_notification_outbox_provider_message_id')
        batch_op.drop_column('status_reconciled_at')
        batch_op.drop_column('provider_message_id')
