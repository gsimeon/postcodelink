"""Verification evidence classification, validation, and transactional persistence."""
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn")


def classify_verification_evidence(
    evidence: Optional[Any],
    expected_code: Optional[str] = None,
) -> str:
    """Classifies NIPOST VerificationEvidence audit record into an exact integrity state.

    Returns one of: 'valid', 'expired', 'rejected', 'incomplete', 'invalid'.
    """
    if evidence is None:
        return "incomplete"

    is_active_val = getattr(evidence, "is_active", None)
    if is_active_val is False:
        return "rejected"
    if is_active_val is not True:
        return "incomplete"

    status_raw = getattr(evidence, "status", None)
    if not status_raw or not str(status_raw).strip():
        return "incomplete"
    status_val = str(status_raw).strip().lower()
    if status_val == "rejected":
        return "rejected"
    if status_val not in ("verified", "partial"):
        return "invalid"

    provider_raw = getattr(evidence, "provider", None)
    if not provider_raw or not str(provider_raw).strip():
        return "incomplete"
    if str(provider_raw).strip().upper() != "NIPOST":
        return "invalid"

    method_raw = getattr(evidence, "verification_method", None)
    if not method_raw or not str(method_raw).strip():
        return "incomplete"
    method = str(method_raw).strip().lower()
    if method not in ("validator_autofill_pipeline", "validator", "autofill"):
        return "invalid"

    if method == "validator_autofill_pipeline" and status_val != "verified":
        return "invalid"
    if method == "validator" and status_val != "partial":
        return "invalid"
    if method == "autofill":
        return "invalid"

    resp_hash_raw = getattr(evidence, "response_hash", None)
    if not resp_hash_raw or not str(resp_hash_raw).strip():
        return "incomplete"
    resp_hash = str(resp_hash_raw).strip()
    if len(resp_hash) != 64 or not all(c in "0123456789abcdefABCDEF" for c in resp_hash):
        return "invalid"

    valid_until = getattr(evidence, "valid_until", None)
    if valid_until is None:
        return "incomplete"

    now_utc = datetime.now(timezone.utc)
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if valid_until <= now_utc or getattr(evidence, "is_expired", False):
        return "expired"

    if expected_code:
        ev_code = str(getattr(evidence, "postcode", "") or "").strip().upper().replace("-", "").replace(" ", "")
        exp_code = str(expected_code).strip().upper().replace("-", "").replace(" ", "")
        if not ev_code or ev_code != exp_code:
            return "invalid"

    return "valid"


def validate_verification_evidence(
    evidence: Optional[Any],
    expected_code: Optional[str] = None,
) -> bool:
    """Canonical strict fail-closed validation rule for NIPOST VerificationEvidence audit records."""
    return classify_verification_evidence(evidence, expected_code) == "valid"


def record_verification_evidence(
    db: Optional[Session],
    code: str,
    live_res: Dict[str, Any],
    ver_method: str,
    upstream_version: Optional[str] = None,
    is_validator: bool = False,
    addr_metadata_source: Optional[str] = None,
    is_sandbox: bool = False,
) -> Tuple[bool, Optional[int], Optional[datetime]]:
    """Persist a NIPOST VerificationEvidence audit record within a transactional boundary."""
    if db is None:
        return False, None, None

    try:
        from backend.app.models.verification_evidence import VerificationEvidence, default_valid_until

        norm_code = str(live_res.get("code") or code or "").strip()
        raw_bytes = json.dumps(live_res or {}, sort_keys=True).encode("utf-8")
        resp_hash = hashlib.sha256(raw_bytes).hexdigest()
        ev_valid_until = default_valid_until()

        if is_sandbox:
            ev_status = "sandbox"
        elif ver_method == "validator_autofill_pipeline":
            ev_status = "verified"
        elif ver_method == "validator":
            ev_status = "partial"
        else:
            ev_status = "verified" if not is_validator else "partial"

        if addr_metadata_source is None:
            addr_metadata_source = "local_enrichment" if is_validator else "nipost_autofill"

        ev_rec = VerificationEvidence(
            postcode=norm_code,
            provider="NIPOST",
            provider_reference_id=live_res.get("reference_id") or live_res.get("transaction_id"),
            verification_method=ver_method,
            dataset_version=upstream_version or live_res.get("dataset_version"),
            response_hash=resp_hash,
            status=ev_status,
            address_metadata_source=addr_metadata_source,
            valid_until=ev_valid_until,
            is_active=True,
        )
        db.add(ev_rec)
        db.commit()
        db.refresh(ev_rec)
        return True, ev_rec.id, ev_valid_until
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"Failed to persist VerificationEvidence audit record: {exc}")
        return False, None, None
