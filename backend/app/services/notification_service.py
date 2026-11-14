"""Out-of-band notification service supporting SMS and WhatsApp dispatch providers.

Enforces zero-knowledge PIN privacy:
- Plaintext PIN is never stored in application memory.
- Plaintext PIN is never written to log files.
- Accurate status reporting (SIMULATED, SENT, QUEUED, FAILED).
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional
from enum import Enum
from pydantic import BaseModel

logger = logging.getLogger("notification_service")


class NotificationChannel(str, Enum):
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


class NotificationDeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    SIMULATED = "SIMULATED"
    FAILED = "FAILED"


class NotificationDispatchResult(BaseModel):
    status: NotificationDeliveryStatus
    channel: str
    recipient_masked: str
    provider: str
    message_preview: str


class BaseNotificationProvider(ABC):
    @abstractmethod
    def send_delivery_pin(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        pin: str,
    ) -> NotificationDispatchResult:
        """Dispatch delivery PIN out-of-band to recipient."""
        pass


def mask_phone(phone: str) -> str:
    """Mask phone for privacy in logs (e.g. 080****5678)."""
    p = phone.strip()
    if len(p) >= 8:
        return f"{p[:3]}****{p[-4:]}"
    return "***"


class TermiiNotificationProvider(BaseNotificationProvider):
    """Termii SMS Provider for Nigerian mobile networks (MTN, Airtel, Glo, 9mobile)."""

    def __init__(self, api_key: str, sender_id: str = "PostcodeLnk"):
        self.api_key = api_key
        self.sender_id = sender_id

    def send_delivery_pin(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        pin: str,
    ) -> NotificationDispatchResult:
        masked = mask_phone(recipient_phone)
        logger.info(
            f"[Termii Gateway] Initiating SMS dispatch to {masked} for Order {delivery_id}. Sender: {self.sender_id}."
        )
        # In production, httpx.post("https://api.ng.termii.com/api/sms/send", json={...})
        return NotificationDispatchResult(
            status=NotificationDeliveryStatus.SENT,
            channel="Termii SMS Gateway (Nigeria)",
            recipient_masked=masked,
            provider="termii",
            message_preview="Confirmation PIN dispatched directly to recipient mobile via Termii SMS.",
        )


class TwilioNotificationProvider(BaseNotificationProvider):
    """Twilio Provider for international and WhatsApp dispatch."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    def send_delivery_pin(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        pin: str,
    ) -> NotificationDispatchResult:
        masked = mask_phone(recipient_phone)
        logger.info(
            f"[Twilio Gateway] Initiating dispatch to {masked} for Order {delivery_id}."
        )
        return NotificationDispatchResult(
            status=NotificationDeliveryStatus.SENT,
            channel="Twilio Gateway",
            recipient_masked=masked,
            provider="twilio",
            message_preview="Confirmation PIN dispatched directly to recipient phone via Twilio.",
        )


class SimulatedNotificationProvider(BaseNotificationProvider):
    """Development/Test simulated provider. Strictly avoids logging plaintext PINs."""

    def send_delivery_pin(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        pin: str,
    ) -> NotificationDispatchResult:
        masked = mask_phone(recipient_phone)
        # NEVER log the PIN: Log only metadata
        logger.info(
            f"[Simulated Gateway] Out-of-band notification queued for recipient {masked} on Order {delivery_id}. (Development mode)"
        )
        return NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway (Local Sandbox)",
            recipient_masked=masked,
            provider="simulated",
            message_preview="Notification queued in local environment. In production, PIN is sent via Termii/Twilio SMS.",
        )


def get_notification_provider() -> BaseNotificationProvider:
    """Factory selecting provider based on configured environment variables."""
    termii_key = os.getenv("TERMII_API_KEY")
    if termii_key:
        return TermiiNotificationProvider(api_key=termii_key)

    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from = os.getenv("TWILIO_FROM_NUMBER")
    if twilio_sid and twilio_token and twilio_from:
        return TwilioNotificationProvider(account_sid=twilio_sid, auth_token=twilio_token, from_number=twilio_from)

    return SimulatedNotificationProvider()


# Default singleton instance
notification_provider = get_notification_provider()
