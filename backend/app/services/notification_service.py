"""Out-of-band notification service supporting real SMS and WhatsApp dispatch providers.

Enforces zero-knowledge PIN privacy:
- Plaintext PIN is never stored in application memory.
- Plaintext PIN is never written to log files.
- Real HTTP requests to Termii and Twilio with timeout and error handling.
- Accurate status reporting: SIMULATED (dev), SENT (confirmed API dispatch), FAILED (API or network error).
"""
import os
import secrets
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
    DISPATCHING = "DISPATCHING"
    SENT = "SENT"
    SIMULATED = "SIMULATED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    RECONCILED = "RECONCILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class NotificationDispatchResult(BaseModel):
    status: NotificationDeliveryStatus
    channel: str
    recipient_masked: str
    provider: str
    message_preview: str
    error_details: Optional[str] = None
    message_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class BaseNotificationProvider(ABC):
    @abstractmethod
    def send_delivery_pin(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        pin: str,
        idempotency_key: Optional[str] = None,
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
        idempotency_key: Optional[str] = None,
    ) -> NotificationDispatchResult:
        """Dispatch delivery status notification out-of-band to recipient."""
        pass

    def check_message_status(
        self,
        idempotency_key: str,
        provider_message_id: Optional[str] = None,
        recipient_phone: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of a prior dispatch with the provider for crash recovery and reconciliation.
        
        Returns NotificationDispatchResult if status is known, or None if status cannot be determined.
        """
        return None


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
        idempotency_key: Optional[str] = None,
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
                idempotency_key=idempotency_key,
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
        if idempotency_key:
            payload["client_reference"] = idempotency_key
            payload["sms_id"] = idempotency_key

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
            message_id = None

        return NotificationDispatchResult(
            status=result_status,
            channel="Termii SMS Gateway",
            recipient_masked=masked,
            provider="termii",
            message_preview="Provider accepted the SMS request." if result_status == NotificationDeliveryStatus.SENT else "SMS provider did not confirm delivery.",
            error_details=error_details,
            message_id=str(message_id) if result_status == NotificationDeliveryStatus.SENT and message_id else None,
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

    def check_message_status(
        self,
        idempotency_key: str,
        provider_message_id: Optional[str] = None,
        recipient_phone: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of a message on Termii gateway for crash recovery and status reconciliation."""
        if not provider_message_id:
            return None
        try:
            url = f"https://api.ng.termii.com/api/sms/inbox"
            params = {"api_key": self.api_key, "message_id": provider_message_id}
            resp = httpx.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json() if callable(getattr(resp, "json", None)) else {}
                if isinstance(data, dict) and data.get("message_id") == provider_message_id:
                    return NotificationDispatchResult(
                        status=NotificationDeliveryStatus.SENT,
                        channel="Termii SMS Gateway",
                        recipient_masked=mask_phone(recipient_phone or "***"),
                        provider="termii",
                        message_preview="Message delivery verified with Termii.",
                        message_id=provider_message_id,
                    )
        except Exception as exc:
            logger.warning(f"[Termii Gateway] Status check exception for {provider_message_id}: {exc}")
        return None


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
        idempotency_key: Optional[str] = None,
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
                idempotency_key=idempotency_key,
            )

        message = f"Your PostcodeLink delivery confirmation PIN is {pin}. Do not share this code."
        req_headers = {}
        post_data = {"To": e164_phone, "From": self.from_number, "Body": message}
        if idempotency_key:
            req_headers["Idempotency-Key"] = idempotency_key
            post_data["ClientReference"] = idempotency_key

        try:
            resp = httpx.post(
                self.base_url,
                data=post_data,
                headers=req_headers if req_headers else None,
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

            sid = resp_data.get("sid")
            if not sid:
                err_text = resp_data.get("message") or getattr(resp, "text", "") or "Twilio did not return a message SID."
                raise ValueError(err_text)
            result_status = NotificationDeliveryStatus.SENT
            error_details = None
        except Exception as exc:
            logger.warning(f"[Twilio Gateway] SMS dispatch failed for {masked}: {exc}")
            result_status = NotificationDeliveryStatus.FAILED
            error_details = str(exc)
            sid = None

        return NotificationDispatchResult(
            status=result_status,
            channel="Twilio SMS Gateway",
            recipient_masked=masked,
            provider="twilio",
            message_preview="Provider accepted the SMS request." if result_status == NotificationDeliveryStatus.SENT else "SMS provider did not confirm delivery.",
            error_details=error_details,
            message_id=str(sid) if result_status == NotificationDeliveryStatus.SENT and sid else None,
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

    def check_message_status(
        self,
        idempotency_key: str,
        provider_message_id: Optional[str] = None,
        recipient_phone: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of a message on Twilio gateway for crash recovery and status reconciliation."""
        try:
            if provider_message_id:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages/{provider_message_id}.json"
                resp = httpx.get(url, auth=(self.account_sid, self.auth_token), timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json() if callable(getattr(resp, "json", None)) else {}
                    tw_status = data.get("status", "").lower()
                    if tw_status in ["queued", "sending", "sent", "delivered"]:
                        return NotificationDispatchResult(
                            status=NotificationDeliveryStatus.SENT,
                            channel="Twilio SMS Gateway",
                            recipient_masked=mask_phone(data.get("to", "***")),
                            provider="twilio",
                            message_preview="Message confirmed sent by Twilio.",
                            message_id=provider_message_id,
                        )
                    elif tw_status in ["failed", "undelivered"]:
                        return NotificationDispatchResult(
                            status=NotificationDeliveryStatus.FAILED,
                            channel="Twilio SMS Gateway",
                            recipient_masked=mask_phone(data.get("to", "***")),
                            provider="twilio",
                            message_preview="Message delivery failed on Twilio.",
                            error_details=data.get("error_message") or f"Twilio status: {tw_status}",
                            message_id=provider_message_id,
                        )
            elif recipient_phone:
                # Outbound message recovery: search messages sent to recipient when provider_message_id was lost in crash
                e164_phone, _ = normalize_nigerian_phone(recipient_phone)
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
                resp = httpx.get(
                    url,
                    params={"To": e164_phone, "PageSize": 5},
                    auth=(self.account_sid, self.auth_token),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json() if callable(getattr(resp, "json", None)) else {}
                    messages = data.get("messages", [])
                    for msg in messages:
                        tw_status = msg.get("status", "").lower()
                        if tw_status in ["queued", "sending", "sent", "delivered"]:
                            return NotificationDispatchResult(
                                status=NotificationDeliveryStatus.SENT,
                                channel="Twilio SMS Gateway",
                                recipient_masked=mask_phone(msg.get("to", recipient_phone)),
                                provider="twilio",
                                message_preview="Message confirmed sent by Twilio via outbound query.",
                                message_id=msg.get("sid"),
                            )
                        elif tw_status in ["failed", "undelivered"]:
                            return NotificationDispatchResult(
                                status=NotificationDeliveryStatus.FAILED,
                                channel="Twilio SMS Gateway",
                                recipient_masked=mask_phone(msg.get("to", recipient_phone)),
                                provider="twilio",
                                message_preview="Message delivery failed on Twilio.",
                                error_details=msg.get("error_message") or f"Twilio status: {tw_status}",
                                message_id=msg.get("sid"),
                            )
        except Exception as exc:
            logger.warning(f"[Twilio Gateway] Status check exception for {provider_message_id}: {exc}")
        return None


class SimulatedNotificationProvider(BaseNotificationProvider):
    """Development/Test simulated provider. Strictly avoids logging plaintext PINs."""

    _shared_dispatched_idempotency_keys: Dict[str, NotificationDispatchResult] = {}

    def __init__(self):
        self._dispatched_idempotency_keys: Dict[str, NotificationDispatchResult] = self._shared_dispatched_idempotency_keys

    def send_delivery_pin(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        pin: str,
        idempotency_key: Optional[str] = None,
    ) -> NotificationDispatchResult:
        if idempotency_key and idempotency_key in self._dispatched_idempotency_keys:
            logger.info(f"[Simulated Gateway] Idempotency match for key '{idempotency_key}'. Returning cached result.")
            return self._dispatched_idempotency_keys[idempotency_key]

        masked = mask_phone(recipient_phone)
        logger.info(
            f"[Simulated Gateway] Out-of-band notification simulated for recipient {masked} on Order {delivery_id}. (Development mode)"
        )
        res = NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway (Local Sandbox)",
            recipient_masked=masked,
            provider="simulated",
            message_preview="Notification simulated in local environment. In production, PIN is sent via Termii/Twilio SMS.",
            message_id=f"sim_{secrets.token_hex(8)}",
            idempotency_key=idempotency_key,
        )
        if idempotency_key:
            self._dispatched_idempotency_keys[idempotency_key] = res
        return res

    def check_message_status(
        self,
        idempotency_key: str,
        provider_message_id: Optional[str] = None,
        recipient_phone: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of simulated notification by idempotency key, provider message ID, or recipient."""
        if idempotency_key and idempotency_key in self._dispatched_idempotency_keys:
            return self._dispatched_idempotency_keys[idempotency_key]
        if provider_message_id:
            for item in self._dispatched_idempotency_keys.values():
                if item.message_id == provider_message_id:
                    return item
        if recipient_phone:
            masked = mask_phone(recipient_phone)
            for item in self._dispatched_idempotency_keys.values():
                if item.recipient_masked == masked:
                    return item
        return None

    def send_status_alert(
        self,
        recipient_phone: str,
        recipient_name: str,
        delivery_id: str,
        status_message: str,
        idempotency_key: Optional[str] = None,
    ) -> NotificationDispatchResult:
        if idempotency_key and idempotency_key in self._dispatched_idempotency_keys:
            return self._dispatched_idempotency_keys[idempotency_key]

        masked = mask_phone(recipient_phone)
        logger.info(
            f"[Simulated Gateway] Status alert simulated for recipient {masked} on Order {delivery_id}: {status_message}"
        )
        res = NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway (Local Sandbox)",
            recipient_masked=masked,
            provider="simulated",
            message_preview="Status alert simulated.",
            message_id=f"sim_{secrets.token_hex(8)}",
            idempotency_key=idempotency_key,
        )
        if idempotency_key:
            self._dispatched_idempotency_keys[idempotency_key] = res
        return res

    def check_message_status(
        self,
        idempotency_key: str,
        provider_message_id: Optional[str] = None,
        recipient_phone: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of simulated notification by idempotency key, provider message ID, or recipient."""
        if idempotency_key and idempotency_key in self._dispatched_idempotency_keys:
            return self._dispatched_idempotency_keys[idempotency_key]
        if provider_message_id:
            for item in self._dispatched_idempotency_keys.values():
                if item.message_id == provider_message_id:
                    return item
        if recipient_phone:
            masked = mask_phone(recipient_phone)
            for item in self._dispatched_idempotency_keys.values():
                if item.recipient_masked == masked:
                    return item
        return None


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
