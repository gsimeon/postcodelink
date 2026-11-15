"""Delivery service handling business logic, concurrency-safe transactions, and strict privacy."""
import secrets
import logging
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from backend.app.config import settings
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.worker_heartbeat import WorkerHeartbeat
from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole
from backend.app.schemas.delivery import (
    DeliveryCreateRequest,
    DeliveryCreateResponse,
    DeliveryStatusUpdateRequest,
    DeliveryAssignRequest,
    DeliveryVerifyOTPRequest,
    DeliveryPublicTrackingResponse,
    NotificationDispatchPayload,
    DeliveryResponse,
    PublicTrackingEvent,
)
from backend.app.services.state_machine import can_transition
from backend.app.services.postcode_service import cleanse_address, normalize_string
from backend.app.core.security import (
    hash_otp,
    verify_otp_hash,
    encrypt_authenticated_pin,
    decrypt_authenticated_pin,
    migrate_legacy_transit_pin,
)
from backend.app.services.notification_service import (
    notification_provider,
    get_notification_provider,
    NotificationDeliveryStatus,
)

logger = logging.getLogger("delivery_service")

WORKER_LAST_HEARTBEAT: Optional[datetime] = None

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
    """Decrypts and verifies authenticated transit PIN envelope using AES-256-GCM and key rotation.
    
    Strictly requires context-bound delivery AAD (delivery_id) for active delivery decryption.
    Legacy v1 and unversioned envelopes are strictly rejected unless allow_legacy=True.
    Unbound envelopes are strictly rejected unless allow_unbound=True.
    """
    if not delivery_id and not allow_unbound:
        logger.warning("Decryption rejected: delivery_id context required for transit PIN decryption")
        return None

    if secret_key:
        res = decrypt_authenticated_pin(token, master_key=secret_key, delivery_id=delivery_id, allow_legacy=allow_legacy, allow_unbound=allow_unbound)
        if res is not None:
            return res
    outbox_key = getattr(settings, "OUTBOX_ENCRYPTION_KEY", None)
    if outbox_key and outbox_key != secret_key:
        res = decrypt_authenticated_pin(token, master_key=outbox_key, delivery_id=delivery_id, allow_legacy=allow_legacy, allow_unbound=allow_unbound)
        if res is not None:
            return res
    if settings.SECRET_KEY != secret_key and settings.SECRET_KEY != outbox_key:
        res = decrypt_authenticated_pin(token, master_key=settings.SECRET_KEY, delivery_id=delivery_id, allow_legacy=allow_legacy, allow_unbound=allow_unbound)
        if res is not None:
            return res
    return None


def generate_reference(db: Session) -> str:
    """Generate a unique, collision-resistant delivery reference."""
    year = datetime.now(timezone.utc).year
    for _ in range(10):
        random_suffix = secrets.token_hex(3).upper()
        ref = f"PL-{year}-{random_suffix}"
        existing = db.query(Delivery).filter(Delivery.id == ref).first()
        if not existing:
            return ref
    micro = int(datetime.now(timezone.utc).timestamp() * 1000) % 1000000
    return f"PL-{year}-{micro:06X}"


def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit delivery OTP."""
    return f"{secrets.randbelow(900000) + 100000}"


def create_delivery(
    db: Session,
    request: DeliveryCreateRequest,
    current_user: Profile,
    async_notification: bool = False,
    commit: bool = True,
) -> DeliveryCreateResponse:
    """Create a new delivery with centralized postcode validation, idempotency guards, and secure out-of-band PIN dispatch."""
    # 1. Idempotency Guard: prevent duplicate orders on network retries
    if getattr(request, "idempotency_key", None):
        clean_key = request.idempotency_key.strip()
        existing = db.query(Delivery).filter(
            Delivery.merchant_id == current_user.id,
            Delivery.idempotency_key == clean_key,
        ).first()
        if existing:
            return DeliveryCreateResponse(
                delivery=DeliveryResponse.model_validate(existing),
                notification_dispatch=NotificationDispatchPayload(
                    recipient_phone=existing.recipient_phone,
                    status="IDEMPOTENT_REPLAY",
                    channel="Idempotency Cache",
                    message_preview=f"Idempotent replay: Delivery {existing.id} already created.",
                ),
            )

    ref_id = generate_reference(db)
    raw_otp = generate_otp()
    otp_hash_val = hash_otp(raw_otp)
    otp_expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.OTP_EXPIRE_HOURS)
    tracking_token = secrets.token_urlsafe(24)

    # CRITICAL FIX: Centralized postcode validation through cleanse_address with area consistency check
    cleanse_res = cleanse_address(
        address=request.destination_address,
        state_hint=request.destination_state,
        area_hint=request.destination_area,
        postcode_hint=request.postcode_input,
        db=db,
    )

    # Only mark VERIFIED if exact postcode match was confirmed AND address is consistent
    input_code = request.postcode_input.strip()
    if cleanse_res.postcode_status == "verified" and cleanse_res.postcode == input_code and cleanse_res.address_consistent:
        postcode_status = PostcodeStatus.VERIFIED
        verified_code = cleanse_res.postcode
    elif cleanse_res.postcode_status in ["estimated", "conflict"]:
        postcode_status = PostcodeStatus.ESTIMATED
        verified_code = cleanse_res.postcode if cleanse_res.postcode else None
    else:
        postcode_status = PostcodeStatus.UNVERIFIED
        verified_code = None

    delivery = Delivery(
        id=ref_id,
        idempotency_key=request.idempotency_key.strip() if getattr(request, "idempotency_key", None) else None,
        tracking_token=tracking_token,
        merchant_id=current_user.id,  # Strictly derived from authenticated merchant
        recipient_name=request.recipient_name.strip(),
        recipient_phone=request.recipient_phone.strip(),
        destination_address=request.destination_address.strip(),
        destination_landmark=request.destination_landmark.strip() if request.destination_landmark else None,
        destination_area=request.destination_area.strip(),
        destination_state=request.destination_state.strip(),
        postcode_input=input_code,
        postcode_status=postcode_status,
        verified_postcode=verified_code,
        package_description=request.package_description.strip(),
        fee=request.fee,
        pickup_address=request.pickup_address.strip() if request.pickup_address else "Merchant Fulfillment Hub, Lagos",
        status=DeliveryStatus.PENDING,
        otp_hash=otp_hash_val,
        otp_expires_at=otp_expires_at,
        otp_attempts=0,
        otp_max_attempts=settings.OTP_MAX_ATTEMPTS,
        pod_verified=False,
        version=1,
    )
    
    db.add(delivery)
    db.flush()

    # Initial audit log
    init_event = DeliveryEvent(
        delivery_id=delivery.id,
        status=DeliveryStatus.PENDING,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note=f"Order created with status PENDING. Postcode status: {postcode_status.value}.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(init_event)

    # Persistent notification outbox record (QUEUED) created atomically with delivery
    # Transit PIN is securely encrypted with dedicated OUTBOX_ENCRYPTION_KEY and bound to delivery.id via AEAD AAD
    encrypted_pin = encrypt_transit_pin(raw_otp, settings.OUTBOX_ENCRYPTION_KEY, delivery_id=delivery.id)
    outbox_entry = NotificationOutbox(
        delivery_id=delivery.id,
        channel="SMS",
        recipient_phone=delivery.recipient_phone,
        recipient_name=delivery.recipient_name,
        message_payload=encrypted_pin,
        provider=settings.SMS_PROVIDER,
        notification_type="otp_delivery_pin",
        delivery_version=delivery.version,
        status=NotificationDeliveryStatus.QUEUED,
        idempotency_key=f"outbox-{delivery.id}-{uuid.uuid4().hex[:12]}",
    )
    db.add(outbox_entry)

    try:
        if commit:
            db.commit()
            db.refresh(delivery)
            db.refresh(outbox_entry)
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        # Concurrency race on (merchant_id, idempotency_key): return the existing delivery safely
        if getattr(request, "idempotency_key", None) and request.idempotency_key.strip():
            existing = (
                db.query(Delivery)
                .filter(
                    Delivery.merchant_id == current_user.id,
                    Delivery.idempotency_key == request.idempotency_key.strip(),
                )
                .first()
            )
            if existing:
                return DeliveryCreateResponse(
                    delivery=DeliveryResponse.model_validate(existing),
                    notification_dispatch=NotificationDispatchPayload(
                        recipient_phone=existing.recipient_phone,
                        status="IDEMPOTENT_REPLAY",
                        channel="Idempotency Cache",
                        message_preview=f"Idempotent replay: Delivery {existing.id} already created.",
                    ),
                )
        raise

    notification = NotificationDispatchPayload(
        recipient_phone=delivery.recipient_phone,
        status=NotificationDeliveryStatus.QUEUED.value,
        channel="Transactional Outbox Queue",
        message_preview="Queued in durable outbox for asynchronous dispatch by notification worker.",
    )

    return DeliveryCreateResponse(
        delivery=DeliveryResponse.model_validate(delivery),
        notification_dispatch=notification,
    )


def assign_operator(db: Session, delivery_id: str, request: DeliveryAssignRequest, current_user: Profile) -> Delivery:
    """Assign an operator with availability, capacity, and service area checks."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).with_for_update().first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    if current_user.role != AppRole.ADMIN and delivery.merchant_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to assign this delivery.")

    # Idempotency: if already assigned to the same operator, return without incrementing counters
    if delivery.operator_id == request.operator_id:
        return delivery

    operator = db.query(Operator).filter(Operator.id == request.operator_id).with_for_update().first()
    if not operator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Courier operator not found.")

    # Check 1: Availability
    if not operator.is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Courier operator '{operator.business_name}' is currently unavailable for new dispatches."
        )

    # Check 2: Capacity limit (configurable max active dispatches)
    max_cap = getattr(operator, "max_active_deliveries", 15)
    if operator.active_deliveries_count >= max_cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Courier operator '{operator.business_name}' has reached maximum dispatch capacity ({max_cap})."
        )

    # Check 3: Service area coverage (supports state-level or area-level fleet tags)
    op_areas = [normalize_string(a) for a in (operator.service_areas or [])]
    dest_area = normalize_string(delivery.destination_area)
    dest_state = normalize_string(delivery.destination_state)
    has_coverage = (
        not op_areas
        or "all areas" in op_areas
        or any(a in dest_area or dest_area in a or a in dest_state or dest_state in a for a in op_areas)
    )
    if not has_coverage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operator '{operator.business_name}' does not cover '{delivery.destination_area}'. Covered zones: {', '.join(operator.service_areas)}."
        )

    allowed, reason = can_transition(delivery.status, DeliveryStatus.ASSIGNED)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    # Reassignment: decrement previous operator
    if delivery.operator_id and delivery.operator_id != operator.id:
        old_op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
        if old_op:
            old_op.active_deliveries_count = max(0, old_op.active_deliveries_count - 1)

    delivery.operator_id = operator.id
    delivery.status = DeliveryStatus.ASSIGNED
    delivery.version += 1
    operator.active_deliveries_count += 1
    
    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=DeliveryStatus.ASSIGNED,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note=f"Dispatched to courier fleet '{operator.business_name}' ({operator.phone}).",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(delivery)
    return delivery


def update_delivery_status(db: Session, delivery_id: str, request: DeliveryStatusUpdateRequest, current_user: Profile) -> Delivery:
    """Transition delivery state enforcing comprehensive role-specific transition authority and exact operator counter adjustments."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).with_for_update().first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    # Idempotency check: no duplicate event if status is unchanged
    if delivery.status == request.new_status:
        return delivery

    is_merchant_owner = delivery.merchant_id == current_user.id
    is_assigned_operator = False
    if current_user.role == AppRole.OPERATOR and delivery.operator_id:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if op and op.id == delivery.operator_id:
            is_assigned_operator = True

    # ROLE PERMISSION MATRIX (Enforce authorization prior to state progression)
    # 1. DELIVERED: Rejection rule - DELIVERED status requires PIN verification endpoint
    if request.new_status == DeliveryStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DELIVERED status can only be achieved via the recipient PIN verification endpoint."
        )

    # 2. PENDING (Unassign courier back to pending pool): Merchant owner or Admin only
    if request.new_status == DeliveryStatus.PENDING:
        if not is_merchant_owner and current_user.role != AppRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only the merchant owner or admin can unassign a delivery back to pending."
            )

    # 3. PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY: Assigned Operator or Admin only
    if request.new_status in [DeliveryStatus.PICKED_UP, DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY]:
        if not is_assigned_operator and current_user.role != AppRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Only the assigned courier operator can advance delivery to '{request.new_status.value}'."
            )

    # 4. FAILED: Assigned Operator or Admin only
    if request.new_status == DeliveryStatus.FAILED:
        if not is_assigned_operator and current_user.role != AppRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only the assigned courier operator or admin can report delivery failure."
            )

    # 5. CANCELLED:
    # - If pending or assigned: Merchant owner or Admin
    # - If already picked up or in transit: Admin only (cannot be cancelled unilaterally by merchant once in transit)
    if request.new_status == DeliveryStatus.CANCELLED:
        if delivery.status in [DeliveryStatus.PICKED_UP, DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY]:
            if current_user.role != AppRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Deliveries in transit can only be cancelled by platform administrators."
                )
        elif not is_merchant_owner and current_user.role != AppRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only the merchant owner or admin can cancel this order."
            )

    # Validate state machine allows the transition
    allowed, reason = can_transition(delivery.status, request.new_status)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    old_status = delivery.status
    delivery.status = request.new_status
    delivery.version += 1

    # OPERATOR COUNTER ACCOUNTING (Atomic & exact)
    if delivery.operator_id:
        op = db.query(Operator).filter(Operator.id == delivery.operator_id).with_for_update().first()
        if op:
            adjust_operator_workload_count(op, old_status, request.new_status)

    # When unassigned back to pending, clear the operator assignment
    if request.new_status == DeliveryStatus.PENDING:
        delivery.operator_id = None

    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=request.new_status,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note=request.note or f"Status updated from {old_status.value} to {request.new_status.value}.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(delivery)
    return delivery


def verify_delivery_otp(db: Session, delivery_id: str, request: DeliveryVerifyOTPRequest, current_user: Profile) -> Delivery:
    """Verify delivery PIN with row-level locking, expiry, and atomic 3-attempt lockout."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).with_for_update().first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    is_owner = delivery.merchant_id == current_user.id
    is_assigned = False
    if current_user.role == AppRole.OPERATOR and delivery.operator_id:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if op and op.id == delivery.operator_id:
            is_assigned = True

    if current_user.role != AppRole.ADMIN and not is_owner and not is_assigned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to confirm delivery for this order.")

    now = datetime.now(timezone.utc)

    # 1. Single-use guard: Cannot verify an already finalized/delivered order
    if delivery.pod_verified or delivery.status == DeliveryStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delivery order has already been verified and delivered."
        )

    # 2. Strict Delivery Stage Guard: Proof of delivery PIN can only be verified when OUT_FOR_DELIVERY
    if delivery.status != DeliveryStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delivery PIN can only be verified when the order is out for delivery."
        )

    # 3. Check lockout
    if delivery.otp_locked_until:
        locked_until = delivery.otp_locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
            
        if now < locked_until:
            rem_secs = int((locked_until - now).total_seconds())
            rem_mins = max(1, (rem_secs + 59) // 60)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"PIN verification is locked due to multiple failed attempts. Try again in {rem_mins} minute(s)."
            )
        else:
            delivery.otp_attempts = 0
            delivery.otp_locked_until = None

    # 3. Check OTP Expiry
    if delivery.otp_expires_at:
        expires_at = delivery.otp_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery confirmation PIN has expired. A new delivery order must be issued."
            )

    # 4. Check PIN Match
    if verify_otp_hash(request.otp, delivery.otp_hash):
        delivery.pod_verified = True
        delivery.status = DeliveryStatus.DELIVERED
        delivery.otp_attempts = 0
        delivery.otp_locked_until = None
        # Single-use revocation
        delivery.otp_hash = "REVOKED_AND_VERIFIED"
        delivery.pod_note = request.note or "Verified via recipient confirmation PIN."
        delivery.version += 1

        if delivery.operator_id:
            op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
            if op:
                adjust_operator_workload_count(op, DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.DELIVERED)
                op.completed_deliveries += 1

        event = DeliveryEvent(
            delivery_id=delivery.id,
            status=DeliveryStatus.DELIVERED,
            actor_name=current_user.full_name,
            actor_role=current_user.role.value,
            note=delivery.pod_note,
            occurred_at=now,
        )
        db.add(event)
        db.commit()
        db.refresh(delivery)
        return delivery

    # MISMATCH: Increment attempt counter atomically
    delivery.otp_attempts += 1
    delivery.version += 1
    remaining = delivery.otp_max_attempts - delivery.otp_attempts
    
    if remaining <= 0:
        delivery.otp_locked_until = now + timedelta(minutes=settings.OTP_LOCKOUT_MINUTES)
        lock_event = DeliveryEvent(
            delivery_id=delivery.id,
            status=delivery.status,
            actor_name="Security Guard",
            actor_role="system",
            note=f"Brute force protection triggered: 3 failed PIN attempts. Locked for {settings.OTP_LOCKOUT_MINUTES} minutes.",
            occurred_at=now,
        )
        db.add(lock_event)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Invalid delivery PIN. Maximum attempts exceeded. Verification locked for {settings.OTP_LOCKOUT_MINUTES} minutes."
        )

    db.commit()
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Invalid delivery PIN. {remaining} attempt(s) remaining."
    )


def mask_recipient_name(name: str) -> str:
    parts = name.strip().split()
    masked_parts = []
    for p in parts:
        if len(p) <= 2:
            masked_parts.append(p[0] + "*")
        else:
            masked_parts.append(p[0] + "*" * (len(p) - 1))
    return " ".join(masked_parts)


def get_public_tracking(db: Session, identifier: str) -> DeliveryPublicTrackingResponse:
    """Format delivery for public recipient tracking strictly by cryptographically random tracking token.
    
    Enforces strict privacy:
    - Rejects lookup by predictable human-readable delivery ID (returns 404).
    - Masks recipient name and phone.
    - Hides exact street address, coordinates, parcel description, fees, and internal actor notes.
    """
    token = identifier.strip()
    if token.startswith("PL-") or len(token) < 20:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public tracking requires a valid 32-character tracking token. Human-readable delivery IDs cannot be used for public tracking."
        )

    delivery = db.query(Delivery).filter(Delivery.tracking_token == token).first()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery tracking record not found. Please provide a valid 32-character tracking token."
        )

    phone = delivery.recipient_phone
    masked_phone = f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "***"
    masked_name = mask_recipient_name(delivery.recipient_name)
    general_location = f"{delivery.destination_area}, {delivery.destination_state}"

    now = datetime.now(timezone.utc)
    is_locked = False
    lockout_rem = None

    if delivery.otp_locked_until:
        locked_until = delivery.otp_locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if now < locked_until:
            is_locked = True
            lockout_rem = max(1, int((locked_until - now).total_seconds() + 59) // 60)

    operator_name = delivery.assigned_operator.business_name if delivery.assigned_operator else None

    # Public timeline (no internal actor notes or IDs)
    public_timeline = [
        PublicTrackingEvent(status=e.status, occurred_at=e.occurred_at)
        for e in delivery.events
    ]

    return DeliveryPublicTrackingResponse(
        id=delivery.id,
        recipient_name_masked=masked_name,
        recipient_phone_masked=masked_phone,
        destination_general_location=general_location,
        postcode_status=delivery.postcode_status,
        verified_postcode=delivery.verified_postcode,
        status=delivery.status,
        requires_pin_confirmation=True,
        otp_attempts=delivery.otp_attempts,
        otp_max_attempts=delivery.otp_max_attempts,
        is_locked=is_locked,
        lockout_remaining_minutes=lockout_rem,
        pod_verified=delivery.pod_verified,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
        assigned_operator_name=operator_name,
        timeline=public_timeline,
    )


def regenerate_tracking_token(db: Session, delivery_id: str, current_user: Profile) -> Delivery:
    """Regenerate a cryptographically secure tracking token (Merchant owner or Admin only)."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).with_for_update().first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    if current_user.role != AppRole.ADMIN and delivery.merchant_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Not authorized to regenerate tracking token for this order."
        )

    new_token = secrets.token_urlsafe(24)
    delivery.tracking_token = new_token
    delivery.version += 1

    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=delivery.status,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note="Regenerated public tracking URL token. Previous tracking link revoked.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(delivery)
    return delivery


def resend_delivery_pin(db: Session, delivery_id: str, current_user: Profile) -> DeliveryCreateResponse:
    """Securely regenerate and dispatch a fresh proof-of-delivery PIN out-of-band."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).with_for_update().first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    if current_user.role != AppRole.ADMIN and delivery.merchant_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Not authorized to resend PIN for this delivery."
        )

    if delivery.status in [DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resend PIN: delivery order is already in '{delivery.status.value}' terminal status."
        )

    # 1. Atomically supersede all prior queued or retrying PIN notifications for this delivery
    prior_pin_items = (
        db.query(NotificationOutbox)
        .filter(
            NotificationOutbox.delivery_id == delivery.id,
            NotificationOutbox.status.in_([NotificationDeliveryStatus.QUEUED, NotificationDeliveryStatus.FAILED]),
            NotificationOutbox.notification_type.in_(["otp_delivery_pin", "otp", "otp_resend"]),
        )
        .all()
    )
    for prior in prior_pin_items:
        prior.status = NotificationDeliveryStatus.SUPERSEDED
        prior.error_details = f"Superseded by fresh PIN generation at delivery version {delivery.version + 1}."
        prior.locked_at = None
        prior.locked_by = None

    # 2. Generate fresh cryptographically secure 6-digit PIN
    raw_pin = f"{secrets.randbelow(900000) + 100000}"
    delivery.otp_hash = hash_otp(raw_pin)
    delivery.otp_attempts = 0
    delivery.otp_locked_until = None
    delivery.otp_expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.OTP_EXPIRE_HOURS)
    delivery.version += 1

    encrypted_pin = encrypt_transit_pin(raw_pin, settings.OUTBOX_ENCRYPTION_KEY, delivery_id=delivery.id)

    # Atomic Outbox Entry: strictly queued for asynchronous worker dispatch
    outbox_entry = NotificationOutbox(
        delivery_id=delivery.id,
        channel="SMS",
        recipient_phone=delivery.recipient_phone,
        recipient_name=delivery.recipient_name,
        provider=settings.SMS_PROVIDER,
        status=NotificationDeliveryStatus.QUEUED,
        notification_type="otp_resend",
        delivery_version=delivery.version,
        message_payload=encrypted_pin,
        idempotency_key=f"resend-{delivery.id}-{uuid.uuid4().hex[:12]}",
    )
    db.add(outbox_entry)

    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=delivery.status,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note="Queued confirmation PIN resend in outbox for asynchronous worker dispatch.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)

    db.commit()
    db.refresh(delivery)
    db.refresh(outbox_entry)

    notification = NotificationDispatchPayload(
        recipient_phone=delivery.recipient_phone,
        status=NotificationDeliveryStatus.QUEUED.value,
        channel="Transactional Outbox Queue",
        message_preview="Queued in durable outbox for asynchronous dispatch by worker.",
    )

    return DeliveryCreateResponse(
        delivery=DeliveryResponse.model_validate(delivery),
        notification_dispatch=notification,
    )


def record_worker_heartbeat(
    db: Session,
    worker_id: str,
    status: str = "active",
    processed_count: int = 0,
    worker_role: str = "outbox_worker",
    stop_reason: Optional[str] = None,
) -> None:
    """Record or update persistent worker heartbeat in the database for cross-process health monitoring."""
    import os
    import socket
    now = datetime.now(timezone.utc)
    try:
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
        if not hb:
            hb = WorkerHeartbeat(
                worker_id=worker_id,
                process_id=os.getpid(),
                worker_role=worker_role,
                hostname=socket.gethostname(),
                last_heartbeat_at=now,
                status=status,
                active_jobs_count=0,
                processed_count=processed_count,
                last_successful_process_at=now if processed_count > 0 else None,
                stop_reason=stop_reason,
                created_at=now,
                updated_at=now,
            )
            db.add(hb)
        else:
            hb.process_id = os.getpid()
            hb.last_heartbeat_at = now
            hb.status = status
            hb.hostname = socket.gethostname()
            hb.processed_count += processed_count
            if processed_count > 0:
                hb.last_successful_process_at = now
            if stop_reason:
                hb.stop_reason = stop_reason
            hb.updated_at = now
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(f"Failed to record worker heartbeat: {exc}")


def record_worker_shutdown(
    db: Session,
    worker_id: str,
    reason: str = "graceful_shutdown",
) -> None:
    """Record clean worker termination in worker_heartbeats."""
    now = datetime.now(timezone.utc)
    try:
        hb = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
        if hb:
            hb.status = "stopped"
            hb.stop_reason = reason
            hb.last_heartbeat_at = now
            hb.updated_at = now
            db.commit()
            logger.info(f"[Worker Heartbeat] Recorded graceful shutdown for worker '{worker_id}' (reason: {reason}).")
    except Exception as exc:
        db.rollback()
        logger.warning(f"Failed to record worker shutdown: {exc}")


def process_notification_outbox(db: Session, max_items: int = 10, worker_id: Optional[str] = None) -> int:
    """Process pending/queued outbox notification items with row-level leasing, backoff, and error classification."""
    global WORKER_LAST_HEARTBEAT
    now = datetime.now(timezone.utc)
    WORKER_LAST_HEARTBEAT = now
    assigned_worker = worker_id or f"worker-{secrets.token_hex(4)}"
    record_worker_heartbeat(db, assigned_worker, status="active", processed_count=0)

    # Determine dialect for SKIP LOCKED support
    bind = db.get_bind()
    is_postgres = bind is not None and getattr(bind.dialect, "name", "") == "postgresql"

    lease_timeout_minutes = getattr(settings, "OUTBOX_LEASE_TIMEOUT_MINUTES", 5)
    query = (
        db.query(NotificationOutbox)
        .filter(
            NotificationOutbox.status.in_([
                NotificationDeliveryStatus.QUEUED,
                NotificationDeliveryStatus.FAILED,
                NotificationDeliveryStatus.DISPATCHING,
            ]),
            NotificationOutbox.retry_count < NotificationOutbox.max_retries,
            or_(
                NotificationOutbox.next_attempt_at.is_(None),
                NotificationOutbox.next_attempt_at <= now,
            ),
            or_(
                NotificationOutbox.locked_at.is_(None),
                NotificationOutbox.locked_at <= now - timedelta(minutes=lease_timeout_minutes),
            ),
        )
        .order_by(NotificationOutbox.created_at.asc())
        .limit(max_items)
    )

    if is_postgres:
        queued = query.with_for_update(skip_locked=True).all()
    else:
        queued = query.with_for_update().all()

    processed = 0
    for item in queued:
        # Acquire processing lease
        item.locked_at = now
        item.locked_by = assigned_worker
        item.retry_count += 1
        item.updated_at = now

        # Select provider based on item configuration early for idempotent cache checks
        provider_name = item.provider if item.provider in ["termii", "twilio", "simulated"] else settings.SMS_PROVIDER
        active_provider = get_notification_provider(provider_name)

        # Ensure unique idempotency key is assigned for provider deduplication
        if not getattr(item, "idempotency_key", None):
            item.idempotency_key = f"outbox_{item.id}_{item.delivery_version}_{item.retry_count}"

        # Idempotent reconciliation guard:
        # If the item already has a provider_message_id recorded (e.g. from previous dispatch attempt
        # where the provider accepted the SMS), reconcile to SENT immediately without re-dispatching.
        if getattr(item, "provider_message_id", None):
            logger.info(
                f"[Outbox Worker] Item {item.id} already has provider_message_id '{item.provider_message_id}'. "
                "Reconciling to SENT without duplicate dispatch."
            )
            item.status = NotificationDeliveryStatus.SENT
            item.status_reconciled_at = now
            item.sent_at = item.sent_at or now
            item.locked_at = None
            item.locked_by = None
            db.commit()
            processed += 1
            continue

        # Crash-window recovery: if worker crashed while actively dispatching (DISPATCHING state)
        if item.status == NotificationDeliveryStatus.DISPATCHING and item.retry_count > 1:
            logger.warning(
                f"[Outbox Worker] Item {item.id} found in DISPATCHING state from prior worker crash. "
                "Checking provider status for crash recovery."
            )
            # 1. Attempt automated provider reconciliation
            reconciled_res = None
            if active_provider and hasattr(active_provider, "check_message_status"):
                try:
                    reconciled_res = active_provider.check_message_status(
                        idempotency_key=item.idempotency_key,
                        provider_message_id=getattr(item, "provider_message_id", None),
                        recipient_phone=getattr(item, "recipient_phone", None),
                        delivery_id=getattr(item, "delivery_id", None),
                    )
                except Exception as exc:
                    logger.warning(f"[Outbox Worker] Provider status check failed for item {item.id}: {exc}")

            if reconciled_res and reconciled_res.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]:
                logger.info(f"[Outbox Worker] Item {item.id} confirmed accepted/sent by provider during crash recovery.")
                item.status = reconciled_res.status
                item.provider_message_id = reconciled_res.message_id or item.provider_message_id
                item.status_reconciled_at = now
                item.sent_at = item.sent_at or now
                item.locked_at = None
                item.locked_by = None
                db.commit()
                processed += 1
                continue
            elif reconciled_res and reconciled_res.status == NotificationDeliveryStatus.FAILED:
                logger.info(f"[Outbox Worker] Item {item.id} confirmed rejected/failed by provider during crash recovery.")
                item.status = NotificationDeliveryStatus.FAILED
                item.failure_classification = "provider_rejection"
                item.error_details = reconciled_res.error_details or "Provider rejected message."
                item.locked_at = None
                item.locked_by = None
                db.commit()
                processed += 1
                continue

            # 2. If unconfirmed whether provider accepted or sent the SMS, route to RECONCILIATION_REQUIRED
            # to prevent duplicate SMS (at-least-once dispatch with duplicate prevention)
            item.status = NotificationDeliveryStatus.RECONCILIATION_REQUIRED
            item.failure_classification = "unconfirmed_crash_window"
            item.error_details = "Worker crashed during HTTP dispatch; provider status could not be verified automatically. Flagged for administrator reconciliation."
            item.locked_at = None
            item.locked_by = None
            db.commit()
            processed += 1
            continue

        dispatch_res = None
        # Handle PIN notification types
        if item.notification_type in ["otp_delivery_pin", "otp", "otp_resend"]:
            if item.status == NotificationDeliveryStatus.SUPERSEDED:
                item.locked_at = None
                item.locked_by = None
                processed += 1
                continue

            deliv = db.query(Delivery).filter(Delivery.id == item.delivery_id).first()
            if not deliv or deliv.status in [DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED]:
                item.status = NotificationDeliveryStatus.FAILED
                item.failure_classification = "terminal_order"
                item.error_details = "Delivery is in terminal status (delivered/cancelled) or not found."
                item.locked_at = None
                item.locked_by = None
                db.commit()
                processed += 1
                continue

            target_pin = None
            if item.message_payload:
                target_pin = decrypt_transit_pin(
                    item.message_payload,
                    settings.OUTBOX_ENCRYPTION_KEY,
                    delivery_id=item.delivery_id,
                    allow_legacy=False,
                )
                if not target_pin and (item.message_payload.startswith("v1:") or not item.message_payload.startswith("v2:")):
                    # Explicit controlled migration path for unmigrated legacy outbox items
                    migrated_pin, upgraded_envelope = migrate_legacy_transit_pin(
                        item.message_payload,
                        delivery_id=item.delivery_id,
                        master_key=settings.OUTBOX_ENCRYPTION_KEY,
                    )
                    if migrated_pin and upgraded_envelope:
                        target_pin = migrated_pin
                        item.message_payload = upgraded_envelope
                        db.flush()

                if not target_pin:
                    item.status = NotificationDeliveryStatus.FAILED
                    item.failure_classification = "invalid_pin_payload"
                    item.error_details = "PIN payload could not be decrypted or failed authentication verification."
                    item.locked_at = None
                    item.locked_by = None
                    db.commit()
                    processed += 1
                    continue

                # Stale PIN guard: verify decrypted PIN matches current active delivery OTP hash
                if not verify_otp_hash(target_pin, deliv.otp_hash):
                    item.status = NotificationDeliveryStatus.SUPERSEDED
                    item.failure_classification = "stale_pin_superseded"
                    item.error_details = f"PIN payload does not match current delivery OTP hash (delivery version: {deliv.version}); superseded."
                    item.locked_at = None
                    item.locked_by = None
                    db.commit()
                    processed += 1
                    continue
            else:
                # Fresh PIN generation when payload is absent (e.g. dynamic PIN rotation on dispatch)
                target_pin = generate_otp()
                deliv.otp_hash = hash_otp(target_pin)
                deliv.otp_attempts = 0
                deliv.otp_locked_until = None
                deliv.otp_expires_at = now + timedelta(hours=settings.OTP_EXPIRE_HOURS)
                deliv.version += 1
                item.message_payload = encrypt_transit_pin(target_pin, settings.OUTBOX_ENCRYPTION_KEY, delivery_id=deliv.id)
                db.flush()

            # Persist DISPATCHING intent state to disk before executing external HTTP network call
            item.status = NotificationDeliveryStatus.DISPATCHING
            item.updated_at = now
            db.commit()

            dispatch_res = active_provider.send_delivery_pin(
                recipient_phone=item.recipient_phone,
                recipient_name=item.recipient_name or deliv.recipient_name,
                delivery_id=item.delivery_id,
                pin=target_pin,
                idempotency_key=item.idempotency_key,
            )
        else:
            status_text = item.message_payload or f"Update for delivery {item.delivery_id}"
            item.status = NotificationDeliveryStatus.DISPATCHING
            item.updated_at = now
            db.commit()

            dispatch_res = active_provider.send_status_alert(
                recipient_phone=item.recipient_phone,
                recipient_name=item.recipient_name or "Recipient",
                delivery_id=item.delivery_id,
                status_message=status_text,
                idempotency_key=item.idempotency_key,
            )

        # Inspect provider response
        item.status = dispatch_res.status
        item.provider = dispatch_res.provider
        if getattr(dispatch_res, "message_id", None):
            item.provider_message_id = dispatch_res.message_id
            item.status_reconciled_at = datetime.now(timezone.utc)

        if dispatch_res.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]:
            item.sent_at = now
            item.error_details = None
            item.failure_classification = None
        else:
            item.status = NotificationDeliveryStatus.FAILED
            item.error_details = dispatch_res.error_details
            err = (dispatch_res.error_details or "").lower()
            if "invalid" in err or "format" in err or "phone" in err:
                item.failure_classification = "invalid_phone"
                # Permanent failure: do not retry
                item.retry_count = item.max_retries
            elif "wallet" in err or "balance" in err or "rejection" in err or "unauthorized" in err:
                item.failure_classification = "provider_rejection"
            else:
                item.failure_classification = "transient_network_error"

            if item.retry_count >= item.max_retries:
                item.status = NotificationDeliveryStatus.FAILED
                item.failure_classification = "max_retries_exceeded"
                item.error_details = f"Exceeded maximum delivery retries ({item.max_retries}). Last error: {dispatch_res.error_details}"
            else:
                backoff_seconds = 30 * (2 ** (item.retry_count - 1))
                item.next_attempt_at = now + timedelta(seconds=backoff_seconds)

        # Release lease and persist immediately per item to eliminate crash window
        item.locked_at = None
        item.locked_by = None
        db.commit()
        processed += 1
    record_worker_heartbeat(db, assigned_worker, status="idle" if processed == 0 else "active", processed_count=processed)
    return processed
