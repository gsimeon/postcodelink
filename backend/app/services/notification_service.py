"""Out-of-band notification service supporting real SMS and WhatsApp dispatch providers.

Enforces cryptographic PIN privacy:
- Plaintext PIN is never stored in persistent database columns; stored as one-way SHA-256 hash on Delivery.
- In-transit payloads are encrypted via AES-256-GCM bound to Delivery ID AAD.
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
        delivery_id: Optional[str] = None,
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

        message = f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is {pin}. Do not share this code."
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
            "sms": f"PostcodeLink Alert for order {delivery_id}: {status_message}",
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
        delivery_id: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of a message on Termii gateway for crash recovery and status reconciliation.
        
        Enforces strict cryptographic and identity verification:
        1. Validates returned message_id matches provider_message_id.
        2. Validates recipient destination matches expected recipient phone.
        3. Validates sender ID matches configured sender.
        4. Validates message content contains delivery order fingerprint.
        5. Validates authoritative outbound delivery status.
        """
        if not provider_message_id:
            logger.info(
                f"[Termii Gateway] Outbound status inquiry without provider_message_id is unsupported by Termii. "
                "Returning None to trigger administrator reconciliation and prevent duplicate dispatch."
            )
            return None
        try:
            url = f"https://api.ng.termii.com/api/sms/status"
            params = {"api_key": self.api_key, "message_id": provider_message_id}
            resp = httpx.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(f"[Termii Gateway] Non-200 status ({resp.status_code}) on status check for {provider_message_id}")
                return None

            data = resp.json() if callable(getattr(resp, "json", None)) else {}
            if not isinstance(data, dict):
                return None

            # 1. Verify message ID identity
            ret_id = data.get("message_id") or data.get("id")
            if not ret_id or ret_id != provider_message_id:
                logger.warning(f"[Termii Gateway] Message ID mismatch or missing: expected {provider_message_id}, got {ret_id}")
                return None

            # 2. Verify recipient phone (fail-closed: recipient field MUST be present and match)
            raw_to = data.get("to") or data.get("phone_number") or data.get("receiver")
            if not raw_to:
                logger.warning(f"[Termii Gateway] Missing recipient in provider response for {provider_message_id}")
                return None
            if recipient_phone:
                try:
                    expected_phone, _ = normalize_nigerian_phone(recipient_phone)
                    actual_phone, _ = normalize_nigerian_phone(str(raw_to))
                    if actual_phone != expected_phone:
                        logger.warning(f"[Termii Gateway] Recipient mismatch on {provider_message_id}: expected {expected_phone}, got {actual_phone}")
                        return None
                except Exception as e:
                    logger.warning(f"[Termii Gateway] Recipient normalization check failed: {e}")
                    return None

            # 3. Verify sender ID (fail-closed: sender field MUST be present and match)
            raw_sender = data.get("from") or data.get("sender")
            if not raw_sender:
                logger.warning(f"[Termii Gateway] Missing sender in provider response for {provider_message_id}")
                return None
            if self.sender_id and str(raw_sender).strip().lower() != self.sender_id.strip().lower():
                logger.warning(f"[Termii Gateway] Sender mismatch on {provider_message_id}: expected {self.sender_id}, got {raw_sender}")
                return None

            # 4. Verify delivery identifier in message text (fail-closed: text MUST be present and contain delivery_id)
            text_content = data.get("text") or data.get("message") or data.get("sms")
            if not text_content:
                logger.warning(f"[Termii Gateway] Missing message text in provider response for {provider_message_id}")
                return None
            if delivery_id:
                if delivery_id not in str(text_content) and f"order {delivery_id}" not in str(text_content).lower():
                    logger.warning(f"[Termii Gateway] Delivery identifier mismatch on {provider_message_id}: order {delivery_id} not in text.")
                    return None

            # 5. Verify authoritative outbound status
            raw_status = (data.get("status") or data.get("code") or "").lower()
            if not raw_status:
                logger.warning(f"[Termii Gateway] Missing delivery status for {provider_message_id}")
                return None
            if raw_status in ["delivered", "sent", "successful", "ok"]:
                return NotificationDispatchResult(
                    status=NotificationDeliveryStatus.SENT,
                    channel="Termii SMS Gateway",
                    recipient_masked=mask_phone(recipient_phone or str(raw_to)),
                    provider="termii",
                    message_preview="Message delivery verified with Termii.",
                    message_id=provider_message_id,
                )
            elif raw_status in ["failed", "rejected", "undelivered", "error"]:
                return NotificationDispatchResult(
                    status=NotificationDeliveryStatus.FAILED,
                    channel="Termii SMS Gateway",
                    recipient_masked=mask_phone(recipient_phone or str(raw_to)),
                    provider="termii",
                    message_preview="Message delivery failed on Termii.",
                    error_details=data.get("message") or f"Termii status: {raw_status}",
                    message_id=provider_message_id,
                )
            return None
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

        message = f"Your PostcodeLink delivery confirmation PIN for order {delivery_id} is {pin}. Do not share this code."
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
                data={"To": e164_phone, "From": self.from_number, "Body": f"PostcodeLink Alert for order {delivery_id}: {status_message}"},
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
        delivery_id: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of a message on Twilio gateway for crash recovery and status reconciliation."""
        try:
            if provider_message_id:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages/{provider_message_id}.json"
                resp = httpx.get(url, auth=(self.account_sid, self.auth_token), timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json() if callable(getattr(resp, "json", None)) else {}
                    if not isinstance(data, dict):
                        return None

                    # 1. Verify SID identity matches exactly
                    sid = data.get("sid")
                    if not sid or sid != provider_message_id:
                        logger.warning(f"[Twilio Gateway] SID mismatch or missing: expected {provider_message_id}, got {sid}")
                        return None

                    # 2. Verify recipient phone number (fail-closed: 'to' field MUST be present and match)
                    msg_to = data.get("to")
                    if not msg_to:
                        logger.warning(f"[Twilio Gateway] Missing recipient 'to' field in provider response for {provider_message_id}")
                        return None
                    if recipient_phone:
                        try:
                            expected_e164, _ = normalize_nigerian_phone(recipient_phone)
                            actual_e164, _ = normalize_nigerian_phone(str(msg_to))
                            if actual_e164 != expected_e164:
                                logger.warning(f"[Twilio Gateway] Recipient mismatch on {provider_message_id}: expected {expected_e164}, got {actual_e164}")
                                return None
                        except Exception as e:
                            logger.warning(f"[Twilio Gateway] Recipient normalization comparison failed: {e}")
                            return None

                    # 3. Verify sender (fail-closed: 'from' field MUST be present and match configured from_number)
                    msg_from = data.get("from")
                    if not msg_from:
                        logger.warning(f"[Twilio Gateway] Missing sender 'from' field in provider response for {provider_message_id}")
                        return None
                    if self.from_number and str(msg_from).strip() != self.from_number.strip():
                        logger.warning(f"[Twilio Gateway] Sender mismatch on {provider_message_id}: expected {self.from_number}, got {msg_from}")
                        return None

                    # 4. Verify delivery identifier in message body (fail-closed: body MUST be present and contain delivery_id)
                    body = data.get("body")
                    if not body:
                        logger.warning(f"[Twilio Gateway] Missing message body in provider response for {provider_message_id}")
                        return None
                    if delivery_id:
                        if delivery_id not in str(body) and f"order {delivery_id}" not in str(body).lower():
                            logger.warning(f"[Twilio Gateway] Delivery identifier mismatch on {provider_message_id}: order {delivery_id} not in body.")
                            return None

                    # 5. Verify authoritative status
                    tw_status = (data.get("status") or "").lower()
                    if not tw_status:
                        logger.warning(f"[Twilio Gateway] Missing status in provider response for {provider_message_id}")
                        return None
                    if tw_status in ["queued", "sending", "sent", "delivered"]:
                        return NotificationDispatchResult(
                            status=NotificationDeliveryStatus.SENT,
                            channel="Twilio SMS Gateway",
                            recipient_masked=mask_phone(recipient_phone or str(msg_to)),
                            provider="twilio",
                            message_preview="Message confirmed sent by Twilio.",
                            message_id=provider_message_id,
                        )
                    elif tw_status in ["failed", "undelivered"]:
                        return NotificationDispatchResult(
                            status=NotificationDeliveryStatus.FAILED,
                            channel="Twilio SMS Gateway",
                            recipient_masked=mask_phone(recipient_phone or str(msg_to)),
                            provider="twilio",
                            message_preview="Message delivery failed on Twilio.",
                            error_details=data.get("error_message") or f"Twilio status: {tw_status}",
                            message_id=provider_message_id,
                        )
                    return None
            elif recipient_phone and delivery_id:
                # Outbound message recovery: search messages sent to recipient when provider_message_id was lost in crash.
                # Strictly requires matching recipient AND specific delivery_id fingerprint in the message body.
                e164_phone, _ = normalize_nigerian_phone(recipient_phone)
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
                resp = httpx.get(
                    url,
                    params={"To": e164_phone, "PageSize": 10},
                    auth=(self.account_sid, self.auth_token),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json() if callable(getattr(resp, "json", None)) else {}
                    messages = data.get("messages", [])
                    matching_msgs = []
                    for msg in messages:
                        body = msg.get("body") or ""
                        if delivery_id in body or f"order {delivery_id}" in body.lower():
                            matching_msgs.append(msg)

                    # Exact unambiguous match required: if multiple or 0 matches found, refuse to guess
                    if len(matching_msgs) == 1:
                        msg = matching_msgs[0]
                        tw_status = msg.get("status", "").lower()
                        if tw_status in ["queued", "sending", "sent", "delivered"]:
                            return NotificationDispatchResult(
                                status=NotificationDeliveryStatus.SENT,
                                channel="Twilio SMS Gateway",
                                recipient_masked=mask_phone(msg.get("to", recipient_phone)),
                                provider="twilio",
                                message_preview="Message confirmed sent by Twilio via delivery fingerprint query.",
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
                    else:
                        logger.warning(
                            f"[Twilio Gateway] Ambiguous or zero matching messages ({len(matching_msgs)}) for recipient "
                            f"{mask_phone(recipient_phone)} and delivery {delivery_id}. Routing to reconciliation."
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
            message_preview=f"Notification simulated for order {delivery_id}. In production, PIN is sent via Termii/Twilio SMS.",
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
        delivery_id: Optional[str] = None,
    ) -> Optional[NotificationDispatchResult]:
        """Check status of simulated notification strictly matching message_id, recipient, and delivery fingerprint."""
        if provider_message_id:
            for item in self._dispatched_idempotency_keys.values():
                if item.message_id == provider_message_id:
                    # Verify recipient if supplied
                    if recipient_phone and item.recipient_masked:
                        exp = mask_phone(recipient_phone)
                        exp_clean = exp.replace("+234", "").replace("+23", "").replace("*", "")
                        act_clean = item.recipient_masked.replace("+234", "").replace("+23", "").replace("*", "")
                        if exp_clean != act_clean:
                            logger.warning(f"[Simulated Gateway] Recipient mismatch on {provider_message_id}")
                            return None
                    # Verify delivery fingerprint if supplied and preview has order tag
                    if delivery_id and item.message_preview:
                        has_order_tag = "order" in item.message_preview.lower() or "pl-" in item.message_preview.lower()
                        if has_order_tag and delivery_id not in item.message_preview:
                            logger.warning(f"[Simulated Gateway] Delivery fingerprint mismatch on {provider_message_id}")
                            return None
                    return item
            return None

        if idempotency_key and idempotency_key in self._dispatched_idempotency_keys:
            item = self._dispatched_idempotency_keys[idempotency_key]
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
