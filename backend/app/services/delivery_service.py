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
from backend.app.models.enums import DeliveryStatus, PostcodeStatus
from backend.app.schemas.delivery import (
    DeliveryCreateRequest,
    DeliveryStatusUpdateRequest,
    DeliveryAssignRequest,
    DeliveryVerifyOTPRequest,
    DeliveryPublicTrackingResponse,
)
from backend.app.services.state_machine import can_transition
from backend.app.services.postcode_service import OFFICIAL_POSTCODES, normalize_string


def generate_reference(db: Session) -> str:
    """Generate a unique, collision-resistant delivery reference."""
    year = datetime.now(timezone.utc).year
    for _ in range(10):
        random_suffix = secrets.token_hex(3).upper()
        ref = f"PL-{year}-{random_suffix}"
        existing = db.query(Delivery).filter(Delivery.id == ref).first()
        if not existing:
            return ref
    # Fallback with timestamp microsecond
    micro = int(datetime.now(timezone.utc).timestamp() * 1000) % 1000000
    return f"PL-{year}-{micro:06X}"


def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit delivery OTP."""
    return f"{secrets.randbelow(900000) + 100000}"


def create_delivery(db: Session, request: DeliveryCreateRequest) -> Delivery:
    """Create a new delivery with strict postcode verification and immutable event tracking."""
    ref_id = generate_reference(db)
    otp_code = generate_otp()
    
    # Authoritative postcode verification check
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
        merchant_id=request.merchant_id,
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
        otp=otp_code,
        otp_attempts=0,
        otp_max_attempts=settings.OTP_MAX_ATTEMPTS,
        pod_verified=False,
    )
    
    db.add(delivery)
    db.flush()

    # Create initial immutable event
    init_event = DeliveryEvent(
        delivery_id=delivery.id,
        status=DeliveryStatus.PENDING,
        actor_name="Merchant Dispatch",
        actor_role="merchant",
        note=f"Order created with status PENDING. Postcode status: {postcode_status.value}.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(init_event)
    db.commit()
    db.refresh(delivery)
    return delivery


def assign_operator(db: Session, delivery_id: str, request: DeliveryAssignRequest) -> Delivery:
    """Assign an operator to a delivery and advance status to ASSIGNED."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")
        
    operator = db.query(Operator).filter(Operator.id == request.operator_id).first()
    if not operator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Courier operator not found.")

    allowed, reason = can_transition(delivery.status, DeliveryStatus.ASSIGNED)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    delivery.operator_id = operator.id
    delivery.status = DeliveryStatus.ASSIGNED
    operator.active_deliveries_count += 1
    
    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=DeliveryStatus.ASSIGNED,
        actor_name=request.actor_name,
        actor_role="dispatcher",
        note=f"Dispatched to courier fleet '{operator.business_name}' ({operator.phone}).",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(delivery)
    return delivery


def update_delivery_status(db: Session, delivery_id: str, request: DeliveryStatusUpdateRequest) -> Delivery:
    """Transition delivery state according to lifecycle rules."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    allowed, reason = can_transition(delivery.status, request.new_status)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    # If transitioning to DELIVERED, OTP verification must have succeeded
    if request.new_status == DeliveryStatus.DELIVERED and not delivery.pod_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot mark as DELIVERED without secure recipient OTP confirmation."
        )

    old_status = delivery.status
    delivery.status = request.new_status

    # Update operator active count if terminal state
    if delivery.operator_id and request.new_status in [DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED]:
        op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
        if op:
            op.active_deliveries_count = max(0, op.active_deliveries_count - 1)
            if request.new_status == DeliveryStatus.DELIVERED:
                op.completed_deliveries += 1

    event = DeliveryEvent(
        delivery_id=delivery.id,
        status=request.new_status,
        actor_name=request.actor_name,
        actor_role=request.actor_role,
        note=request.note or f"Status updated from {old_status.value} to {request.new_status.value}.",
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(delivery)
    return delivery


def verify_delivery_otp(db: Session, delivery_id: str, request: DeliveryVerifyOTPRequest) -> Delivery:
    """Verify delivery PIN with recipient phone challenge and 3-attempt brute-force protection."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery order not found.")

    now = datetime.now(timezone.utc)

    # 1. Check if already delivered
    if delivery.pod_verified and delivery.status == DeliveryStatus.DELIVERED:
        return delivery

    # 2. Check if locked out
    if delivery.otp_locked_until:
        # Convert or ensure tz aware
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
            # Lockout expired, reset attempts
            delivery.otp_attempts = 0
            delivery.otp_locked_until = None

    # 3. Optional recipient phone check
    if request.recipient_phone:
        clean_input_phone = request.recipient_phone.replace(" ", "").replace("-", "")
        clean_target_phone = delivery.recipient_phone.replace(" ", "").replace("-", "")
        if not clean_target_phone.endswith(clean_input_phone[-4:]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security challenge failed: phone number does not match recipient on file."
            )

    # 4. Check PIN match
    if request.otp.strip() == delivery.otp.strip():
        # SUCCESS!
        delivery.pod_verified = True
        delivery.status = DeliveryStatus.DELIVERED
        delivery.otp_attempts = 0
        delivery.otp_locked_until = None
        delivery.pod_note = request.note or "Verified via recipient 6-digit confirmation PIN."

        # Operator stats update
        if delivery.operator_id:
            op = db.query(Operator).filter(Operator.id == delivery.operator_id).first()
            if op:
                op.active_deliveries_count = max(0, op.active_deliveries_count - 1)
                op.completed_deliveries += 1

        event = DeliveryEvent(
            delivery_id=delivery.id,
            status=DeliveryStatus.DELIVERED,
            actor_name="Recipient / Courier POD",
            actor_role="recipient",
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
    """Format delivery for public recipient tracking, masking private OTP and phone numbers."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery tracking reference not found.")

    # Mask phone: e.g. "08012345678" -> "080****5678"
    phone = delivery.recipient_phone
    if len(phone) >= 7:
        masked_phone = f"{phone[:3]}****{phone[-4:]}"
    else:
        masked_phone = "***"

    # Mask OTP: e.g. "492812" -> "***812"
    masked_otp = f"***{delivery.otp[-3:]}"

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
        fee=delivery.fee,
        status=delivery.status,
        lat=delivery.lat,
        lng=delivery.lng,
        otp_masked=masked_otp,
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

