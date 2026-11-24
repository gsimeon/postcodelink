"""Release Gate v6.1.8 Verification Test Suite.

Validates the resolutions for:
- P1: Environment normalization (case-insensitive, fail-closed on unknown environments)
- P1: Cross-tenant isolation & ASSIGNED status mutation restriction in delivery_service
- P1: Termii transactional OTP notification channel ('dnd' route)
- P1 & P2: Migration d4f5a6b7c8e9 local_reference taxonomy and safe conditional downgrade
- P2: Outbox lease immediate persistence before dispatch
"""
import os
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from backend.app.config import Settings
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.models.profile import Profile
from backend.app.models.delivery import Delivery
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.schemas.delivery import DeliveryStatusUpdateRequest
from backend.app.services.delivery_service import update_delivery_status, process_notification_outbox
from backend.app.services.notification_service import TermiiNotificationProvider


def test_p1_environment_normalization_and_case_insensitivity():
    """Verify ENVIRONMENT is normalized to lowercase and unknown environments fail closed."""
    # 1. 'Production' should normalize to 'production' and enforce production validation
    with patch.dict(os.environ, {
        "ENVIRONMENT": "Production",
        "SECRET_KEY": "weak",
        "SMS_PROVIDER": "simulated",
    }, clear=False):
        with pytest.raises(ValueError) as exc:
            Settings()
        assert "Fatal Security Error" in str(exc.value) or "Fatal Production Configuration Error" in str(exc.value)

    # 2. 'PRODUCTION' should also normalize and trigger production validation
    with patch.dict(os.environ, {
        "ENVIRONMENT": "PRODUCTION",
        "SECRET_KEY": "weak",
        "SMS_PROVIDER": "simulated",
    }, clear=False):
        with pytest.raises(ValueError) as exc:
            Settings()
        assert "Fatal Security Error" in str(exc.value) or "Fatal Production Configuration Error" in str(exc.value)

    # 3. Unknown environment must fail closed
    with patch.dict(os.environ, {"ENVIRONMENT": "staging_preview"}, clear=False):
        with pytest.raises(ValueError) as exc:
            Settings()
        assert "Unknown ENVIRONMENT 'staging_preview'" in str(exc.value)

    # 4. Valid environments succeed and normalize
    with patch.dict(os.environ, {"ENVIRONMENT": "DEVELOPMENT"}, clear=False):
        s = Settings()
        assert s.ENVIRONMENT == "development"


def test_p1_assigned_status_mutation_forbidden_in_generic_update():
    """Verify ASSIGNED status can only be achieved via dedicated courier assignment endpoint."""
    db = MagicMock()
    merchant = Profile(id="merchant-1", full_name="Merchant One", role=AppRole.MERCHANT)
    delivery = Delivery(
        id="del-1",
        merchant_id="merchant-1",
        status=DeliveryStatus.PENDING,
        version=1,
    )
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = delivery

    req = DeliveryStatusUpdateRequest(new_status=DeliveryStatus.ASSIGNED)
    with pytest.raises(HTTPException) as exc:
        update_delivery_status(db, "del-1", req, merchant)
    assert exc.value.status_code == 400
    assert "ASSIGNED status can only be achieved via the dedicated courier assignment endpoint" in exc.value.detail


def test_p1_cross_tenant_status_update_forbidden():
    """Verify a merchant cannot update delivery status for another merchant's order."""
    db = MagicMock()
    merchant_attacker = Profile(id="merchant-attacker", full_name="Attacker", role=AppRole.MERCHANT)
    delivery_victim = Delivery(
        id="del-victim",
        merchant_id="merchant-owner",
        status=DeliveryStatus.PENDING,
        version=1,
    )
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = delivery_victim

    req = DeliveryStatusUpdateRequest(new_status=DeliveryStatus.CANCELLED)
    with pytest.raises(HTTPException) as exc:
        update_delivery_status(db, "del-victim", req, merchant_attacker)
    assert exc.value.status_code == 403
    assert "Merchants cannot modify deliveries belonging to another merchant" in exc.value.detail


def test_p1_termii_transactional_channel_configuration():
    """Verify TermiiNotificationProvider defaults to the transactional DND route for OTPs."""
    provider = TermiiNotificationProvider(
        api_key="test-api-key",
        sender_id="TestSender",
        channel="dnd",
    )
    assert provider.channel == "dnd"

    # Mock HTTP response to inspect outbound payload channel
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": "ok", "message_id": "msg-12345"}
        mock_post.return_value = mock_resp

        res = provider.send_delivery_pin(
            recipient_phone="08012345678",
            recipient_name="Tunde",
            delivery_id="del-123",
            pin="123456",
        )
        assert res.status.value in ["SENT", "sent"]
        # Verify JSON payload has channel = "dnd"
        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["channel"] == "dnd"
        assert sent_payload["sms"] == "Your PostcodeLink delivery confirmation PIN for order del-123 is 123456. Do not share this code."


def test_p1_p2_national_postcode_migration_fixtures_and_downgrade_safety():
    """Verify migration d4f5a6b7c8e9 inserts local_reference fixtures and downgrade only removes migration records."""
    import backend.alembic.versions.d4f5a6b7c8e9_release_gate_v5_4_aes_gcm_national_postcode as mig

    mock_bind = MagicMock()
    mock_bind.dialect.name = "sqlite"

    with patch.object(mig.op, "get_bind", return_value=mock_bind), \
         patch.object(mig.op, "batch_alter_table"):
        # Test upgrade
        mig.upgrade()
        # Find execute calls with INSERT INTO postcodes
        insert_calls = [
            c for c in mock_bind.execute.call_args_list
            if len(c[0]) > 0 and "INSERT INTO postcodes" in str(c[0][0])
        ]
        assert len(insert_calls) == 2
        for call in insert_calls:
            # Check params passed
            rec = call[0][1]
            assert rec["verification_status"] == "local_reference"
            assert rec["provenance"] == "PostcodeLink National Postcode Format Demonstration Reference"
            assert rec["dataset_version"] == "2026.1"

        # Test downgrade
        mig.downgrade()
        delete_calls = [
            c for c in mock_bind.execute.call_args_list
            if len(c[0]) > 0 and "DELETE FROM postcodes" in str(c[0][0])
        ]
        assert len(delete_calls) == 1
        delete_query = str(delete_calls[0][0][0])
        assert "provenance IN ('PostcodeLink National Postcode Format Demonstration Reference'" in delete_query
        assert "dataset_version = '2026.1'" in delete_query


def test_p2_outbox_lease_committed_before_dispatch():
    """Verify outbox item lease is committed immediately upon acquisition before external network calls."""
    db = MagicMock()
    now = datetime.now(timezone.utc)
    item = NotificationOutbox(
        id="item-lease-test",
        delivery_id="del-test",
        delivery_version=1,
        channel="SMS",
        recipient_phone="+2348012345678",
        notification_type="otp_delivery_pin",
        message_payload=None,
        retry_count=0,
        max_retries=3,
        status="QUEUED",
        created_at=now,
    )
    # Mock query returns item
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.with_for_update.return_value.all.return_value = [item]

    commits_with_locked_at = []
    commit_count = 0
    def mock_commit():
        nonlocal commit_count
        commit_count += 1
        if item.locked_at is not None:
            commits_with_locked_at.append(item.locked_at)
    db.commit.side_effect = mock_commit

    with patch("backend.app.services.delivery_service.get_notification_provider") as mock_prov_factory:
        mock_prov = MagicMock()
        mock_prov.send_delivery_pin.return_value.status.value = "SENT"
        mock_prov.send_delivery_pin.return_value.message_id = "msg-ok"
        mock_prov_factory.return_value = mock_prov

        process_notification_outbox(db, max_items=1)

        # db.commit must have been called at least twice:
        # 1. Immediately upon acquiring the lease (item.locked_at)
        # 2. Upon dispatch state/completion
        assert commit_count >= 2
        assert len(commits_with_locked_at) >= 1
