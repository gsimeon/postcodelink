"""Delivery service handling business logic, concurrency-safe transactions, and strict privacy."""
import secrets
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.config import settings
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.notification_outbox import NotificationOutbox
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
from backend.app.core.security import hash_otp, verify_otp_hash
from backend.app.services.notification_service import (
    notification_provider,
    NotificationDeliveryStatus,
)

logger = logging.getLogger("delivery_service")

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
    """Create a new delivery with centralized postcode validation and secure out-of-band PIN dispatch."""
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
    outbox_entry = NotificationOutbox(
        delivery_id=delivery.id,
        channel="SMS",
        recipient_phone=delivery.recipient_phone,
        provider="simulated",
        status=NotificationDeliveryStatus.QUEUED,
    )
    db.add(outbox_entry)
    if commit:
        db.commit()
        db.refresh(delivery)
        db.refresh(outbox_entry)
    else:
        db.flush()

    if async_notification:
        notification = NotificationDispatchPayload(
            recipient_phone=delivery.recipient_phone,
            status=NotificationDeliveryStatus.QUEUED.value,
            channel="Asynchronous Outbox Queue",
            message_preview="Queued in durable outbox for asynchronous dispatch.",
        )
    else:
        # Dispatch PIN out-of-band via notification provider (Zero-knowledge: never returned in HTTP body, never stored in plaintext)
        dispatch_res = notification_provider.send_delivery_pin(
            recipient_phone=delivery.recipient_phone,
            recipient_name=delivery.recipient_name,
            delivery_id=delivery.id,
            pin=raw_otp,
        )

        # Update outbox record status with dispatch result
        outbox_entry.status = dispatch_res.status
        outbox_entry.provider = dispatch_res.provider
        outbox_entry.error_details = dispatch_res.error_details
        if dispatch_res.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]:
            outbox_entry.sent_at = datetime.now(timezone.utc)
        db.commit()

        notification = NotificationDispatchPayload(
            recipient_phone=delivery.recipient_phone,
            status=dispatch_res.status.value,
            channel=dispatch_res.channel,
            message_preview=dispatch_res.message_preview,
        )

    return DeliveryCreateResponse(
        delivery=DeliveryResponse.model_validate(delivery),
        notification_dispatch=notification
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

    # Check 2: Capacity limit (max 15 active dispatches)
    if operator.active_deliveries_count >= 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Courier operator '{operator.business_name}' has reached maximum dispatch capacity."
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

    # Generate fresh cryptographically secure 6-digit PIN
    raw_pin = f"{secrets.randbelow(900000) + 100000}"
    delivery.otp_hash = hash_otp(raw_pin)
    delivery.otp_attempts = 0
    delivery.otp_locked_until = None
    delivery.otp_expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    delivery.version += 1

    # Atomic Outbox Entry
    outbox_entry = NotificationOutbox(
        delivery_id=delivery.id,
        channel="SMS",
        recipient_phone=delivery.recipient_phone,
        provider="simulated",
        status=NotificationDeliveryStatus.QUEUED,
        notification_type="otp_resend",
        idempotency_key=f"resend-{delivery.id}-{uuid.uuid4().hex[:12]}",
    )
    db.add(outbox_entry)
    db.commit()
    db.refresh(delivery)
    db.refresh(outbox_entry)

    # Dispatch fresh PIN out-of-band via notification provider
    dispatch_res = notification_provider.send_delivery_pin(
        recipient_phone=delivery.recipient_phone,
        recipient_name=delivery.recipient_name,
        delivery_id=delivery.id,
        pin=raw_pin,
    )

    outbox_entry.status = dispatch_res.status
    outbox_entry.provider = dispatch_res.provider
    outbox_entry.error_details = dispatch_res.error_details
    if dispatch_res.status in [NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SIMULATED]:
        outbox_entry.sent_at = datetime.now(timezone.utc)
    else:
        outbox_entry.failure_classification = "provider_rejection" if "rejection" in (dispatch_res.error_details or "").lower() else "transient_network_error"

    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=delivery.status,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note=f"Resent confirmation PIN out-of-band via {dispatch_res.channel} ({dispatch_res.status.value}).",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(delivery)

    notification = NotificationDispatchPayload(
        recipient_phone=delivery.recipient_phone,
        status=dispatch_res.status.value,
        channel=dispatch_res.channel,
        message_preview=dispatch_res.message_preview,
    )

    return DeliveryCreateResponse(
        delivery=DeliveryResponse.model_validate(delivery),
        notification_dispatch=notification,
    )


def process_notification_outbox(db: Session, max_items: int = 10, worker_id: Optional[str] = None) -> int:
    """Process pending/queued outbox notification items with row-level leasing, backoff, and error classification."""
    now = datetime.now(timezone.utc)
    assigned_worker = worker_id or f"worker-{secrets.token_hex(4)}"

    # Determine dialect for SKIP LOCKED support
    bind = db.get_bind()
    is_postgres = bind is not None and getattr(bind.dialect, "name", "") == "postgresql"

    query = (
        db.query(NotificationOutbox)
        .filter(
            NotificationOutbox.status.in_([NotificationDeliveryStatus.QUEUED, NotificationDeliveryStatus.FAILED]),
            NotificationOutbox.retry_count < NotificationOutbox.max_retries,
            or_(
                NotificationOutbox.next_attempt_at.is_(None),
                NotificationOutbox.next_attempt_at <= now,
            ),
            or_(
                NotificationOutbox.locked_at.is_(None),
                NotificationOutbox.locked_at <= now - timedelta(minutes=5),
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

        # Error classification & retry backoff calculation
        if item.status == NotificationDeliveryStatus.QUEUED:
            if item.provider == "simulated":
                item.status = NotificationDeliveryStatus.SIMULATED
                item.sent_at = now
            else:
                item.status = NotificationDeliveryStatus.SENT
                item.sent_at = now
        else:
            err = (item.error_details or "").lower()
            if "invalid" in err or "format" in err:
                item.failure_classification = "invalid_phone"
                item.status = NotificationDeliveryStatus.FAILED
            elif "wallet" in err or "balance" in err or "rejection" in err:
                item.failure_classification = "provider_rejection"
            else:
                item.failure_classification = "transient_network_error"

            if item.retry_count >= item.max_retries:
                item.status = NotificationDeliveryStatus.FAILED
                item.failure_classification = "max_retries_exceeded"
                item.error_details = f"Exceeded maximum delivery retries ({item.max_retries})."
            else:
                backoff_seconds = 30 * (2 ** (item.retry_count - 1))
                item.next_attempt_at = now + timedelta(seconds=backoff_seconds)

        # Release lease
        item.locked_at = None
        item.locked_by = None
        processed += 1

    db.commit()
    return processed
