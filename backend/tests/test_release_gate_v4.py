"""Focused regression tests for Release Gate v4 fixes."""
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from backend.app.models.enums import DeliveryStatus
from backend.app.services.delivery_service import adjust_operator_workload_count
from backend.app.services.notification_service import (
    NotificationDeliveryStatus,
    TermiiNotificationProvider,
)
from backend.app.services.postcode_service import cleanse_address


def test_conflicting_area_hint_is_not_accepted_because_it_appears_in_street_text():
    result = cleanse_address(
        address="15 Ikeja Road, Lagos",
        state_hint="Lagos",
        area_hint="Ikeja",
        postcode_hint="101241",  # Reference record is Lekki Phase 1.
    )

    assert result.postcode_status == "conflict"
    assert result.address_consistent is False
    assert result.matched_record.area == "Lekki Phase 1"


def test_operator_workload_decrements_only_when_leaving_active_state():
    operator = SimpleNamespace(active_deliveries_count=4)

    adjust_operator_workload_count(operator, DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.FAILED)
    assert operator.active_deliveries_count == 3

    # FAILED -> CANCELLED must not release the same workload slot twice.
    adjust_operator_workload_count(operator, DeliveryStatus.FAILED, DeliveryStatus.CANCELLED)
    assert operator.active_deliveries_count == 3


def test_operator_workload_increments_when_failed_delivery_is_retried():
    operator = SimpleNamespace(active_deliveries_count=2)

    adjust_operator_workload_count(operator, DeliveryStatus.FAILED, DeliveryStatus.OUT_FOR_DELIVERY)

    assert operator.active_deliveries_count == 3


def test_termii_reports_sent_only_after_provider_acceptance():
    provider = TermiiNotificationProvider(api_key="test-key")

    response = SimpleNamespace(
        status_code=200,
        json=lambda: {"code": "ok", "message_id": "msg-123"},
        raise_for_status=lambda: None,
    )
    with patch("backend.app.services.notification_service.httpx.post", return_value=response) as post:
        result = provider.send_delivery_pin("08012345678", "Recipient", "PL-TEST", "123456")

    assert result.status == NotificationDeliveryStatus.SENT
    assert post.call_args.kwargs["json"]["sms"].endswith("123456. Do not share this code.")


def test_termii_timeout_is_reported_as_failed_not_sent():
    provider = TermiiNotificationProvider(api_key="test-key")

    with patch(
        "backend.app.services.notification_service.httpx.post",
        side_effect=httpx.TimeoutException("timeout"),
    ):
        result = provider.send_delivery_pin("08012345678", "Recipient", "PL-TEST", "123456")

    assert result.status == NotificationDeliveryStatus.FAILED
