"""Delivery service handling business logic, state transitions, and secure OTP verification."""
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
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
)
from backend.app.services.state_machine import can_transition
from backend.app.services.postcode_service import OFFICIAL_POSTCODES, normalize_string
from backend.app.core.security import hash_otp, verify_otp_hash


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


def create_delivery(db: Session, request: DeliveryCreateRequest, current_user: Profile) -> DeliveryCreateResponse:
    """Create a new delivery scoped strictly to the authenticated merchant."""
    ref_id = generate_reference(db)
    raw_otp = generate_otp()
    otp_hash_val = hash_otp(raw_otp)
    otp_expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.OTP_EXPIRE_HOURS)
    
    # Authoritative reference postcode check
    verified_code = None
    postcode_status = PostcodeStatus.UNVERIFIED
    
    norm_area = normalize_string(request.destination_area)
    norm_state = normalize_string(request.destination_state)
    input_code = request.postcode_input.strip()

    for rec in OFFICIAL_POSTCODES:
        if (rec["code"] == input_code or normalize_string(rec["area"]) == norm_area) and normalize_string(rec["state"]) == norm_state:
            postcode_status = PostcodeStatus.VERIFIED
            verified_code = rec["code"]
            break

    delivery = Delivery(
        id=ref_id,
        merchant_id=current_user.id,  # Strictly derived from authenticated user
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
    )
    
    db.add(delivery)
    db.flush()

    # Create initial immutable event with verified actor identity
    init_event = DeliveryEvent(
        delivery_id=delivery.id,
        status=DeliveryStatus.PENDING,
        actor_name=current_user.full_name,
        actor_role=current_user.role.value,
        note=f"Order created with status PENDING. Postcode status: {postcode_status.value}.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(init_event)
    db.commit()
    db.refresh(delivery)

    # Simulated outbound SMS/WhatsApp notification payload
    dispatch_msg = (
        f"Hello {delivery.recipient_name}, your package '{delivery.package_description}' is registered for delivery "
        f"with tracking {delivery.id}. Your delivery confirmation PIN is: {raw_otp}."
    )
    notification = NotificationDispatchPayload(
        recipient_phone=delivery.recipient_phone,
        delivery_pin=raw_otp,
        channel="SMS / WhatsApp Gateway",
        message_preview=dispatch_msg
    )

    return DeliveryCreateResponse(
        delivery=DeliveryResponse.model_validate(delivery),
        notification_dispatch=notification
    )


def assign_operator(db: Session, delivery_id: str, request: DeliveryAssignRequest, current_user: Profile) -> Delivery:
    """Assign an operator to a delivery with validation on availability, service area, and capacity."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    # Tenant check: only delivery owner merchant or admin can assign
    if current_user.role != AppRole.ADMIN and delivery.merchant_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to assign this delivery.")

    operator = db.query(Operator).filter(Operator.id == request.operator_id).first()
    if not operator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Courier operator not found.")

    # Operational Check 1: Operator availability
    if not operator.is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Courier operator '{operator.business_name}' is currently unavailable for new dispatches."
        )

    # Operational Check 2: Service area coverage
    op_areas = [normalize_string(a) for a in (operator.service_areas or [])]
    dest_area = normalize_string(delivery.destination_area)
    if op_areas and "all areas" not in op_areas and not any(a in dest_area or dest_area in a for a in op_areas):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operator '{operator.business_name}' does not cover '{delivery.destination_area}'. Covered zones: {', '.join(operator.service_areas)}."
        )

    # Lifecycle state transition check
    allowed, reason = can_transition(delivery.status, DeliveryStatus.ASSIGNED)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    # Atomic counter adjustment: if previously assigned to a different operator, decrement old count
    if delivery.operator_id and delivery.operator_id != operator.id:
        old_op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
        if old_op:
            old_op.active_deliveries_count = max(0, old_op.active_deliveries_count - 1)

    delivery.operator_id = operator.id
    delivery.status = DeliveryStatus.ASSIGNED
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
    """Transition delivery state according to lifecycle rules and authenticated permissions."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    # Authorization check
    is_owner = delivery.merchant_id == current_user.id
    is_assigned = False
    if current_user.role == AppRole.OPERATOR and delivery.operator_id:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if op and op.id == delivery.operator_id:
            is_assigned = True

    if current_user.role != AppRole.ADMIN and not is_owner and not is_assigned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update status of this delivery.")

    allowed, reason = can_transition(delivery.status, request.new_status)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    # Guard: Cannot mark as DELIVERED without verified PIN
    if request.new_status == DeliveryStatus.DELIVERED and not delivery.pod_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot mark as DELIVERED without secure recipient OTP confirmation."
        )

    old_status = delivery.status
    delivery.status = request.new_status

    # Operator active counters update
    if delivery.operator_id and request.new_status in [DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED]:
        op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
        if op:
            op.active_deliveries_count = max(0, op.active_deliveries_count - 1)
            if request.new_status == DeliveryStatus.DELIVERED:
                op.completed_deliveries += 1

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
    """Verify delivery PIN with hash validation, expiry checks, and atomic 3-attempt lockout."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    # Authorization check
    is_owner = delivery.merchant_id == current_user.id
    is_assigned = False
    if current_user.role == AppRole.OPERATOR and delivery.operator_id:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if op and op.id == delivery.operator_id:
            is_assigned = True

    if current_user.role != AppRole.ADMIN and not is_owner and not is_assigned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to confirm delivery for this order.")

    now = datetime.now(timezone.utc)

    # 1. Already delivered
    if delivery.pod_verified and delivery.status == DeliveryStatus.DELIVERED:
        return delivery

    # 2. Check lockout
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

    # 4. Check PIN Match via secure hash comparison
    if verify_otp_hash(request.otp, delivery.otp_hash):
        delivery.pod_verified = True
        delivery.status = DeliveryStatus.DELIVERED
        delivery.otp_attempts = 0
        delivery.otp_locked_until = None
        # Single-use enforcement: invalidate hash so it can never be used again
        delivery.otp_hash = "REVOKED_AND_VERIFIED"
        delivery.pod_note = request.note or "Verified via recipient 6-digit confirmation PIN."

        if delivery.operator_id:
            op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
            if op:
                op.active_deliveries_count = max(0, op.active_deliveries_count - 1)
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

    # MISMATCH: Increment attempt counter
    delivery.otp_attempts += 1
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


def get_public_tracking(db: Session, delivery_id: str) -> DeliveryPublicTrackingResponse:
    """Format delivery for public recipient tracking. No OTP digits exposed."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery tracking reference not found.")

    # Mask recipient phone: e.g. "080****5678"
    phone = delivery.recipient_phone
    masked_phone = f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "***"

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

    return DeliveryPublicTrackingResponse(
        id=delivery.id,
        recipient_name=delivery.recipient_name,
        recipient_phone_masked=masked_phone,
        destination_address=delivery.destination_address,
        destination_landmark=delivery.destination_landmark,
        destination_area=delivery.destination_area,
        destination_state=delivery.destination_state,
        postcode_status=delivery.postcode_status,
        verified_postcode=delivery.verified_postcode,
        package_description=delivery.package_description,
        fee=float(delivery.fee),
        status=delivery.status,
        lat=delivery.lat,
        lng=delivery.lng,
        requires_pin_confirmation=True,
        otp_attempts=delivery.otp_attempts,
        otp_max_attempts=delivery.otp_max_attempts,
        is_locked=is_locked,
        lockout_remaining_minutes=lockout_rem,
        pod_verified=delivery.pod_verified,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
        assigned_operator_name=operator_name,
        events=delivery.events,
    )
