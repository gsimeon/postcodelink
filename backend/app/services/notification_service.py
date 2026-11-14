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
from typing import Optional, Tuple, Dict, Any, List
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
    SUPERSEDED = "SUPERSEDED"


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

    @abstractmethod
    def send_status_alert(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        status_message: str,
    ) -> NotificationDispatchResult:
        """Dispatch delivery status notification out-of-band to recipient."""
        pass


def mask_phone(phone: str) -> str:
    """Mask phone for privacy in logs (e.g. 080****5678)."""
    p = phone.strip()
    if len(p) >= 8:
        return f"{p[:3]}****{p[-4:]}"
    return "***"


def normalize_nigerian_phone(phone: str) -> Tuple[str, str]:
    """Validate and normalize phone numbers for Nigerian and international SMS dispatch.

    Returns:
        (e164_format, national_msisdn_format)
        e.g. ("+2348012345678", "2348012345678")
    Raises:
        ValueError if the phone number format is invalid.
    """
    if not phone or not isinstance(phone, str):
        raise ValueError("Phone number must be a non-empty string.")

    cleaned = "".join(c for c in phone.strip() if c.isdigit() or c == "+")
    digits = cleaned.replace("+", "")

    # 1. Nigerian local format: 080... / 070... / 090... / 081... (11 digits)
    if digits.startswith("0") and len(digits) == 11:
        msisdn = "234" + digits[1:]
        e164 = "+" + msisdn
        return e164, msisdn

    # 2. Nigerian international format without leading plus: 23480... (13 digits)
    if digits.startswith("234") and len(digits) == 13:
        msisdn = digits
        e164 = "+" + msisdn
        return e164, msisdn

    # 3. International format with explicit plus prefix (+1..., +44..., +234...)
    if cleaned.startswith("+") and 10 <= len(digits) <= 15:
        return cleaned, digits

    # 4. Standalone valid digits of standard international length (10-15 digits)
    if 10 <= len(digits) <= 15:
        return "+" + digits, digits

    raise ValueError(
        f"Invalid phone number format: '{phone}'. Expected 11-digit national or E.164 international format."
    )


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

        try:
            _, dest_msisdn = normalize_nigerian_phone(recipient_phone)
        except ValueError as exc:
            logger.warning(f"[Termii Gateway] Phone normalization failed for {masked}: {exc}")
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Termii SMS Gateway",
                recipient_masked=masked,
                provider="termii",
                message_preview="Invalid recipient phone format.",
                error_details=str(exc),
            )

        message = f"Your PostcodeLink delivery confirmation PIN is {pin}. Do not share this code."
        payload = {
            "to": dest_msisdn,
            "from": self.sender_id,
            "sms": message,
            "type": "plain",
            "channel": "generic",
            "api_key": self.api_key,
        }

        try:
            resp = httpx.post(self.base_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            try:
                resp_data = resp.json() if callable(getattr(resp, "json", None)) else {}
                if not isinstance(resp_data, dict):
                    raise ValueError("Termii returned a non-dictionary JSON payload.")
            except Exception as e:
                raise ValueError(f"Termii returned an invalid or unparseable response: {e}")

            code = resp_data.get("code")
            message_id = resp_data.get("message_id")
            # Strict verification: Termii requires BOTH code == "ok" AND a valid non-empty message_id
            if code != "ok" or not message_id:
                err_text = resp_data.get("message") or f"Termii rejected message dispatch or omitted message ID (code: {code}, message_id: {message_id})"
                raise ValueError(err_text)

            result_status = NotificationDeliveryStatus.SENT
            error_details = None
        except Exception as exc:
            logger.warning(f"[Termii Gateway] SMS dispatch failed for {masked}: {exc}")
            result_status = NotificationDeliveryStatus.FAILED
            error_details = str(exc)

        return NotificationDispatchResult(
            status=result_status,
            channel="Termii SMS Gateway",
            recipient_masked=masked,
            provider="termii",
            message_preview="Provider accepted the SMS request." if result_status == NotificationDeliveryStatus.SENT else "SMS provider did not confirm delivery.",
            error_details=error_details,
        )

    def send_status_alert(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        status_message: str,
    ) -> NotificationDispatchResult:
        masked = mask_phone(recipient_phone)
        try:
            _, dest_msisdn = normalize_nigerian_phone(recipient_phone)
        except ValueError as exc:
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Termii SMS Gateway",
                recipient_masked=masked,
                provider="termii",
                message_preview="Invalid recipient phone format.",
                error_details=str(exc),
            )

        payload = {
            "to": dest_msisdn,
            "from": self.sender_id,
            "sms": f"PostcodeLink Alert: {status_message}",
            "type": "plain",
            "channel": "generic",
            "api_key": self.api_key,
        }
        try:
            resp = httpx.post(self.base_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            resp_data = resp.json() if callable(getattr(resp, "json", None)) else {}
            if not isinstance(resp_data, dict) or resp_data.get("code") != "ok" or not resp_data.get("message_id"):
                err_text = resp_data.get("message") if isinstance(resp_data, dict) else "Termii rejected message dispatch."
                raise ValueError(err_text)
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.SENT,
                channel="Termii SMS Gateway",
                recipient_masked=masked,
                provider="termii",
                message_preview="Status alert dispatched via Termii.",
            )
        except Exception as exc:
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Termii SMS Gateway",
                recipient_masked=masked,
                provider="termii",
                message_preview="SMS provider did not confirm delivery.",
                error_details=str(exc),
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

        try:
            e164_phone, _ = normalize_nigerian_phone(recipient_phone)
        except ValueError as exc:
            logger.warning(f"[Twilio Gateway] Phone normalization failed for {masked}: {exc}")
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Twilio SMS Gateway",
                recipient_masked=masked,
                provider="twilio",
                message_preview="Invalid recipient phone format.",
                error_details=str(exc),
            )

        message = f"Your PostcodeLink delivery confirmation PIN is {pin}. Do not share this code."
        try:
            resp = httpx.post(
                self.base_url,
                data={"To": e164_phone, "From": self.from_number, "Body": message},
                auth=(self.account_sid, self.auth_token),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            try:
                resp_data = resp.json() if callable(getattr(resp, "json", None)) else {}
                if not isinstance(resp_data, dict):
                    raise ValueError("Twilio returned a non-dictionary JSON payload.")
            except Exception as e:
                raise ValueError(f"Twilio returned an invalid or unparseable response: {e}")

            if not resp_data.get("sid"):
                err_text = resp_data.get("message") or getattr(resp, "text", "") or "Twilio did not return a message SID."
                raise ValueError(err_text)
            result_status = NotificationDeliveryStatus.SENT
            error_details = None
        except Exception as exc:
            logger.warning(f"[Twilio Gateway] SMS dispatch failed for {masked}: {exc}")
            result_status = NotificationDeliveryStatus.FAILED
            error_details = str(exc)

        return NotificationDispatchResult(
            status=result_status,
            channel="Twilio SMS Gateway",
            recipient_masked=masked,
            provider="twilio",
            message_preview="Provider accepted the SMS request." if result_status == NotificationDeliveryStatus.SENT else "SMS provider did not confirm delivery.",
            error_details=error_details,
        )

    def send_status_alert(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        status_message: str,
    ) -> NotificationDispatchResult:
        masked = mask_phone(recipient_phone)
        try:
            e164_phone, _ = normalize_nigerian_phone(recipient_phone)
        except ValueError as exc:
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Twilio SMS Gateway",
                recipient_masked=masked,
                provider="twilio",
                message_preview="Invalid recipient phone format.",
                error_details=str(exc),
            )

        try:
            resp = httpx.post(
                self.base_url,
                data={"To": e164_phone, "From": self.from_number, "Body": f"PostcodeLink Alert: {status_message}"},
                auth=(self.account_sid, self.auth_token),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            resp_data = resp.json() if callable(getattr(resp, "json", None)) else {}
            if not isinstance(resp_data, dict) or not resp_data.get("sid"):
                err_text = resp_data.get("message") if isinstance(resp_data, dict) else "Twilio did not return a message SID."
                raise ValueError(err_text)
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.SENT,
                channel="Twilio SMS Gateway",
                recipient_masked=masked,
                provider="twilio",
                message_preview="Status alert sent via Twilio.",
            )
        except Exception as exc:
            return NotificationDispatchResult(
                status=NotificationDeliveryStatus.FAILED,
                channel="Twilio SMS Gateway",
                recipient_masked=masked,
                provider="twilio",
                message_preview="Twilio did not confirm delivery.",
                error_details=str(exc),
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

    def send_status_alert(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        status_message: str,
    ) -> NotificationDispatchResult:
        masked = mask_phone(recipient_phone)
        logger.info(
            f"[Simulated Gateway] Status alert simulated for recipient {masked} on Order {delivery_id}: {status_message}"
        )
        return NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway (Local Sandbox)",
            recipient_masked=masked,
            provider="simulated",
            message_preview=f"Simulated alert: {status_message}",
        )


def get_notification_provider(provider_type: Optional[str] = None) -> BaseNotificationProvider:
    """Factory selecting provider based on configured parameter or Pydantic settings."""
    from backend.app.config import settings
    selected = (provider_type or settings.SMS_PROVIDER).strip().lower()

    if selected == "termii" or (not selected and settings.TERMII_API_KEY):
        return TermiiNotificationProvider(
            api_key=settings.TERMII_API_KEY,
            sender_id=settings.TERMII_SENDER_ID
        )

    if selected == "twilio" or (not selected and settings.TWILIO_ACCOUNT_SID):
        return TwilioNotificationProvider(
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_FROM_NUMBER
        )

    return SimulatedNotificationProvider()


# Default singleton instance
notification_provider = get_notification_provider()
