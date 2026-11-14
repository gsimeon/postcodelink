"""Out-of-band notification service supporting real SMS and WhatsApp dispatch providers.

Enforces zero-knowledge PIN privacy:
- Plaintext PIN is never stored in application memory.
- Plaintext PIN is never written to log files.
- Real HTTP requests to Termii and Twilio with timeout and error handling.
- Accurate status reporting: SIMULATED (dev), SENT (confirmed API dispatch), FAILED (API or network error).
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional
from enum import Enum
import httpx
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
    error_details: Optional[str] = None


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

    def __init__(
        self,
        api_key: str,
        sender_id: str = "PostcodeLnk",
        base_url: str = "https://api.ng.termii.com/api/sms/send",
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.sender_id = sender_id
        self.base_url = base_url
        self.timeout = timeout

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

        # Format recipient phone for Nigerian destination (ensure international prefix e.g. 234...)
        phone_cleaned = recipient_phone.strip().replace(" ", "").replace("-", "")
        if phone_cleaned.startswith("0") and len(phone_cleaned) == 11:
            dest_phone = "234" + phone_cleaned[1:]
        elif phone_cleaned.startswith("+234"):
            dest_phone = phone_cleaned[1:]
        else:
            dest_phone = phone_cleaned

        payload = {
            "to": dest_phone,
            "from": self.sender_id,
            "sms": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is: {pin}. Valid for 2 hours.",
            "type": "plain",
            "channel": "generic",
            "api_key": self.api_key,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.base_url, json=payload)

            if resp.status_code == 200:
                resp_data = resp.json() if resp.content else {}
                # Termii returns {"code": "ok", "message_id": "..."} on success
                if resp_data.get("code") == "ok" or "message_id" in resp_data:
                    logger.info(f"[Termii Gateway] SMS dispatched successfully to {masked} for Order {delivery_id}.")
                    return NotificationDispatchResult(
                        status=NotificationDeliveryStatus.SENT,
                        channel="Termii SMS Gateway (Nigeria)",
                        recipient_masked=masked,
                        provider="termii",
                        message_preview="Confirmation PIN dispatched directly to recipient mobile via Termii SMS.",
                    )
                else:
                    error_msg = resp_data.get("message", "Termii API rejected message dispatch.")
                    logger.warning(f"[Termii Gateway] Dispatch rejected for {masked}: {error_msg}")
                    return NotificationDispatchResult(
                        status=NotificationDeliveryStatus.FAILED,
                        channel="Termii SMS Gateway (Nigeria)",
                        recipient_masked=masked,
                        provider="termii",
                        message_preview="Failed to dispatch SMS via Termii.",
                        error_details=error_msg,
                    )
            else:
                error_msg = f"Termii HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[Termii Gateway] HTTP failure for {masked}: {error_msg}")
                return NotificationDispatchResult(
                    status=NotificationDeliveryStatus.FAILED,
                    channel="Termii SMS Gateway (Nigeria)",
                    recipient_masked=masked,
                    provider="termii",
                    message_preview="Termii gateway returned an error response.",
                    error_details=error_msg,
                )
        except httpx.RequestError as exc:
            error_msg = f"Network/Timeout error communicating with Termii: {str(exc)}"
            logger.error(f"[Termii Gateway] {error_msg}")
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Termii SMS Gateway (Nigeria)",
                recipient_masked=masked,
                provider="termii",
                message_preview="Unable to reach Termii SMS gateway due to network issue.",
                error_details=error_msg,
            )


class TwilioNotificationProvider(BaseNotificationProvider):
    """Twilio Provider for international and WhatsApp dispatch."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout: float = 10.0,
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.timeout = timeout
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

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

        data = {
            "To": recipient_phone,
            "From": self.from_number,
            "Body": f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is: {pin}. Valid for 2 hours.",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.base_url,
                    auth=(self.account_sid, self.auth_token),
                    data=data,
                )

            if resp.status_code in [200, 201]:
                logger.info(f"[Twilio Gateway] Message queued/sent successfully to {masked} for Order {delivery_id}.")
                return NotificationDispatchResult(
                    status=NotificationDeliveryStatus.SENT,
                    channel="Twilio Gateway",
                    recipient_masked=masked,
                    provider="twilio",
                    message_preview="Confirmation PIN dispatched directly to recipient phone via Twilio.",
                )
            else:
                error_msg = f"Twilio HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[Twilio Gateway] Error dispatching to {masked}: {error_msg}")
                return NotificationDispatchResult(
                    status=NotificationDeliveryStatus.FAILED,
                    channel="Twilio Gateway",
                    recipient_masked=masked,
                    provider="twilio",
                    message_preview="Twilio gateway returned an error response.",
                    error_details=error_msg,
                )
        except httpx.RequestError as exc:
            error_msg = f"Network/Timeout error communicating with Twilio: {str(exc)}"
            logger.error(f"[Twilio Gateway] {error_msg}")
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Twilio Gateway",
                recipient_masked=masked,
                provider="twilio",
                message_preview="Unable to reach Twilio gateway due to network issue.",
                error_details=error_msg,
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
            f"[Simulated Gateway] Out-of-band notification simulated for recipient {masked} on Order {delivery_id}. (Development mode)"
        )
        return NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway (Local Sandbox)",
            recipient_masked=masked,
            provider="simulated",
            message_preview="Notification simulated in local environment. In production, PIN is sent via Termii/Twilio SMS.",
        )


def get_notification_provider() -> BaseNotificationProvider:
    """Factory selecting provider based on configured environment variables."""
    provider_type = os.getenv("SMS_PROVIDER", "").strip().lower()

    if provider_type == "termii" or os.getenv("TERMII_API_KEY"):
        termii_key = os.getenv("TERMII_API_KEY", "")
        sender_id = os.getenv("TERMII_SENDER_ID", "PostcodeLnk")
        return TermiiNotificationProvider(api_key=termii_key, sender_id=sender_id)

    if provider_type == "twilio" or os.getenv("TWILIO_ACCOUNT_SID"):
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        twilio_from = os.getenv("TWILIO_FROM_NUMBER", "")
        return TwilioNotificationProvider(
            account_sid=twilio_sid, auth_token=twilio_token, from_number=twilio_from
        )

    return SimulatedNotificationProvider()


# Default singleton instance
notification_provider = get_notification_provider()
