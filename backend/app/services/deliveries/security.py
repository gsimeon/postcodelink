"""Delivery operator workload and transit PIN encryption helpers."""
import logging
from typing import Optional

from backend.app.config import settings
from backend.app.core.security import decrypt_authenticated_pin, encrypt_authenticated_pin
from backend.app.models.enums import DeliveryStatus
from backend.app.models.operator import Operator

logger = logging.getLogger("uvicorn")

ACTIVE_WORKLOAD_STATUSES = {
    DeliveryStatus.ASSIGNED,
    DeliveryStatus.PICKED_UP,
    DeliveryStatus.IN_TRANSIT,
    DeliveryStatus.OUT_FOR_DELIVERY,
}


def adjust_operator_workload_count(operator: Operator, old_status: DeliveryStatus, new_status: DeliveryStatus) -> None:
    """Change the active workload count only when a delivery crosses the active boundary."""
    was_active = old_status in ACTIVE_WORKLOAD_STATUSES
    is_active = new_status in ACTIVE_WORKLOAD_STATUSES
    if was_active and not is_active:
        operator.active_deliveries_count = max(0, operator.active_deliveries_count - 1)
    elif not was_active and is_active:
        operator.active_deliveries_count += 1


def encrypt_transit_pin(pin: str, secret_key: Optional[str] = None, delivery_id: Optional[str] = None) -> str:
    """Authenticated encryption for transit PIN using standard AES-256-GCM AEAD envelope."""
    key = secret_key or getattr(settings, "OUTBOX_ENCRYPTION_KEY", None) or settings.SECRET_KEY
    return encrypt_authenticated_pin(pin, master_key=key, delivery_id=delivery_id)


def decrypt_transit_pin(
    token: str,
    secret_key: Optional[str] = None,
    delivery_id: Optional[str] = None,
    allow_legacy: bool = False,
    allow_unbound: bool = False,
) -> Optional[str]:
    """Decrypts and verifies authenticated transit PIN envelope using AES-256-GCM and key rotation."""
    if not delivery_id and not allow_unbound:
        logger.warning("Decryption rejected: delivery_id context required for transit PIN decryption")
        return None

    if secret_key:
        res = decrypt_authenticated_pin(
            token, master_key=secret_key, delivery_id=delivery_id, allow_legacy=allow_legacy, allow_unbound=allow_unbound
        )
        if res is not None:
            return res
    outbox_key = getattr(settings, "OUTBOX_ENCRYPTION_KEY", None)
    if outbox_key and outbox_key != secret_key:
        res = decrypt_authenticated_pin(
            token, master_key=outbox_key, delivery_id=delivery_id, allow_legacy=allow_legacy, allow_unbound=allow_unbound
        )
        if res is not None:
            return res
    if settings.SECRET_KEY != secret_key and settings.SECRET_KEY != outbox_key:
        res = decrypt_authenticated_pin(
            token, master_key=settings.SECRET_KEY, delivery_id=delivery_id, allow_legacy=allow_legacy, allow_unbound=allow_unbound
        )
        if res is not None:
            return res
    return None
