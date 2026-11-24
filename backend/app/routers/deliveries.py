"""Deliveries router with authentication, tenant isolation, and RBAC."""
import uuid
import secrets
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.database import get_db
from backend.app.config import settings
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.services.notification_service import NotificationDeliveryStatus, mask_phone
from backend.app.schemas.delivery import (
    DeliveryCreateRequest,
    DeliveryCreateResponse,
    DeliveryStatusUpdateRequest,
    DeliveryAssignRequest,
    DeliveryVerifyOTPRequest,
    DeliveryResponse,
    DeliveryPublicTrackingResponse,
    DeliveryBulkCreateResponse,
    BulkItemResult,
    RecipientVerifyChallengeRequest,
    RecipientVerifyChallengeResponse,
)
from backend.app.services.delivery_service import (
    create_delivery,
    assign_operator,
    update_delivery_status,
    verify_delivery_otp,
    get_public_tracking,
    regenerate_tracking_token,
    resend_delivery_pin,
    verify_recipient_challenge,
)
from backend.app.core.auth_deps import (
    get_current_user,
    require_roles,
    get_current_actor,
    get_authenticated_merchant_or_api_key,
)

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post("/", response_model=DeliveryCreateResponse, status_code=status.HTTP_201_CREATED)
def api_create_delivery(
    request: DeliveryCreateRequest,
    current_user: Profile = Depends(get_authenticated_merchant_or_api_key),
    db: Session = Depends(get_db),
):
    """Create a new delivery record scoped strictly to the authenticated merchant (Bearer JWT or x-api-key)."""
    return create_delivery(db, request, current_user)


@router.post("/bulk", response_model=DeliveryBulkCreateResponse, status_code=status.HTTP_201_CREATED)
def api_bulk_create_deliveries(
    items: List[DeliveryCreateRequest],
    batch_id: Optional[str] = Query(None),
    current_user: Profile = Depends(get_authenticated_merchant_or_api_key),
    db: Session = Depends(get_db),
):
    """Batch import delivery orders into the authenticated merchant's account with atomic per-item reporting."""
    batch_identifier = batch_id or f"batch-{secrets.token_hex(6)}"
    results: List[BulkItemResult] = []
    success_count = 0
    failure_count = 0

    for idx, item in enumerate(items):
        try:
            with db.begin_nested():
                res = create_delivery(db, item, current_user, async_notification=True, commit=False)
                results.append(
                    BulkItemResult(
                        index=idx,
                        success=True,
                        reference=res.delivery.id,
                        delivery=res.delivery,
                    )
                )
                success_count += 1
        except Exception as exc:
            err_msg = str(getattr(exc, "detail", exc))
            results.append(
                BulkItemResult(
                    index=idx,
                    success=False,
                    error=err_msg,
                )
            )
            failure_count += 1

    db.commit()

    return DeliveryBulkCreateResponse(
        batch_id=batch_identifier,
        total_items=len(items),
        successful_count=success_count,
        failed_count=failure_count,
        results=results,
    )


@router.post("/{delivery_id}/resend-pin", response_model=DeliveryCreateResponse)
def api_resend_delivery_pin(
    delivery_id: str,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Securely regenerate and resend a proof-of-delivery confirmation PIN out-of-band."""
    return resend_delivery_pin(db, delivery_id, current_user)


@router.get("/", response_model=List[DeliveryResponse])
def api_list_deliveries(
    status_filter: Optional[DeliveryStatus] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    current_user: Profile = Depends(get_current_actor),
    db: Session = Depends(get_db),
):
    """List deliveries scoped by tenant role (Merchants see their orders; Operators see assigned trips; supports x-api-key)."""
    query = db.query(Delivery).filter(Delivery.is_deleted == False)

    # Tenant isolation
    if current_user.role == AppRole.MERCHANT:
        query = query.filter(Delivery.merchant_id == current_user.id)
    elif current_user.role == AppRole.OPERATOR:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if op:
            query = query.filter(Delivery.operator_id == op.id)
        else:
            return []
    # Admin sees all

    if status_filter:
        query = query.filter(Delivery.status == status_filter)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Delivery.id.ilike(term),
                Delivery.recipient_name.ilike(term),
                Delivery.recipient_phone.ilike(term),
                Delivery.destination_address.ilike(term),
                Delivery.destination_area.ilike(term),
            )
        )
    return query.order_by(Delivery.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{delivery_id}", response_model=DeliveryResponse)
def api_get_delivery(
    delivery_id: str,
    current_user: Profile = Depends(get_current_actor),
    db: Session = Depends(get_db),
):
    """Get full details of a delivery (enforcing tenant access permissions)."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.is_deleted == False).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery order not found.")

    if current_user.role == AppRole.MERCHANT and delivery.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this delivery order.")
    elif current_user.role == AppRole.OPERATOR:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if not op or delivery.operator_id != op.id:
            raise HTTPException(status_code=403, detail="Forbidden: You are not the assigned operator for this order.")

    return delivery


@router.get("/track/{tracking_token}", response_model=DeliveryPublicTrackingResponse)
def api_get_public_tracking(tracking_token: str, db: Session = Depends(get_db)):
    """Public customer tracking portal endpoint strictly by 32-character tracking token.
    
    Protects privacy: masks name and phone, hides exact street address and coordinates.
    Rejects predictable delivery references.
    """
    return get_public_tracking(db, tracking_token)


@router.post("/track/{tracking_token}/verify-recipient", response_model=RecipientVerifyChallengeResponse)
def api_verify_recipient_challenge(
    tracking_token: str,
    request: RecipientVerifyChallengeRequest,
    db: Session = Depends(get_db),
):
    """Verify recipient phone challenge server-side to unlock proof-of-delivery OTP confirmation."""
    return verify_recipient_challenge(db, tracking_token, request.phone_last_4)


@router.get("/{identifier}/tracking", response_model=DeliveryPublicTrackingResponse)
def api_get_tracking(identifier: str, db: Session = Depends(get_db)):
    """Public customer tracking portal endpoint by tracking token.
    
    Note: Requires the cryptographically secure tracking token. Human-readable delivery IDs are rejected.
    """
    return get_public_tracking(db, identifier)


@router.post("/{delivery_id}/regenerate-token", response_model=DeliveryResponse)
def api_regenerate_tracking_token(
    delivery_id: str,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Regenerate public tracking URL token, immediately revoking the previous tracking link."""
    return regenerate_tracking_token(db, delivery_id, current_user)


@router.post("/{delivery_id}/assign", response_model=DeliveryResponse)
def api_assign_operator(
    delivery_id: str,
    request: DeliveryAssignRequest,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Assign delivery to a registered courier operator fleet with availability and area validation."""
    return assign_operator(db, delivery_id, request, current_user)


@router.post("/{delivery_id}/status", response_model=DeliveryResponse)
def api_update_status(
    delivery_id: str,
    request: DeliveryStatusUpdateRequest,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update delivery status enforcing valid state machine transitions and role authority."""
    return update_delivery_status(db, delivery_id, request, current_user)


@router.post("/{delivery_id}/verify-otp", response_model=DeliveryResponse)
def api_verify_otp(
    delivery_id: str,
    request: DeliveryVerifyOTPRequest,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm delivery via 6-digit recipient PIN with 3-attempt brute-force protection."""
    return verify_delivery_otp(db, delivery_id, request, current_user)


@router.delete("/{delivery_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_delivery(
    delivery_id: str,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Soft-delete a delivery order (only permitted for unassigned or cancelled orders by merchant owner/admin).
    
    In compliance with permanent regulatory audit trail standards, delivery orders are soft-deleted,
    marked CANCELLED, and all immutable DeliveryEvent records are permanently preserved.
    """
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id, Delivery.is_deleted == False).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery order not found.")

    if current_user.role != AppRole.ADMIN and delivery.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot delete another merchant's delivery.")

    if delivery.status not in [DeliveryStatus.PENDING, DeliveryStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Cannot delete an order that has already been dispatched or delivered.")

    now = datetime.now(timezone.utc)
    delivery.is_deleted = True
    delivery.deleted_at = now
    delivery.status = DeliveryStatus.CANCELLED
    if delivery.tracking_token:
        delivery.tracking_token = f"revoked_{delivery.id}_{uuid.uuid4().hex[:12]}"

    # Record immutable audit event
    actor_role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    del_event = DeliveryEvent(
        delivery_id=delivery.id,
        status=DeliveryStatus.CANCELLED,
        actor_name=current_user.full_name,
        actor_role=actor_role_str,
        note=f"Delivery order soft-deleted and archived by {current_user.email}. Compliance audit records permanently retained.",
    )
    db.add(del_event)
    db.commit()


# ==============================================================================
# ==============================================================================
# Outbox Manual Reconciliation Workflows (Admin Only & Privacy-Hardened)
# ==============================================================================
class OutboxReconciliationRequest(BaseModel):
    resolution: Literal["mark_sent", "requeue", "mark_failed"]
    reason: str = Field(..., min_length=10, description="Mandatory operator audit reason and resolution evidence.")
    provider_message_id: Optional[str] = Field(None, description="External provider message ID if confirmed delivered.")
    evidence_reference: Optional[str] = Field(None, description="External ticket, telco reference, or customer contact note.")
    evidence_type: Literal["manual_operator_asserted", "provider_telemetry_verified"] = Field(
        "manual_operator_asserted",
        description="Distinguishes manually asserted audit justification from provider-verified telemetry evidence.",
    )
    reconciliation_request_id: Optional[str] = Field(
        None,
        description="Optional client reconciliation tracking ID; auto-generated if omitted.",
    )


@router.get("/outbox/reconciliation", status_code=status.HTTP_200_OK)
def api_list_outbox_reconciliations(
    current_user: Profile = Depends(require_roles([AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """List all outbox notification items currently in RECONCILIATION_REQUIRED state.
    
    Strictly restricted to Admin profiles. Recipient phone numbers are masked to protect customer privacy.
    """
    items = (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.status == NotificationDeliveryStatus.RECONCILIATION_REQUIRED)
        .order_by(NotificationOutbox.updated_at.desc())
        .all()
    )
    return [
        {
            "id": it.id,
            "delivery_id": it.delivery_id,
            "recipient_phone_masked": mask_phone(it.recipient_phone),
            "provider": it.provider,
            "idempotency_key": it.idempotency_key,
            "provider_message_id": it.provider_message_id,
            "failure_classification": it.failure_classification,
            "error_details": it.error_details,
            "retry_count": it.retry_count,
            "evidence_type": getattr(it, "evidence_type", None),
            "reconciliation_request_id": getattr(it, "reconciliation_request_id", None),
            "created_at": it.created_at,
            "updated_at": it.updated_at,
        }
        for it in items
    ]


@router.post("/outbox/{outbox_id}/reconcile", status_code=status.HTTP_200_OK)
def api_reconcile_outbox_item(
    outbox_id: str,
    req: OutboxReconciliationRequest,
    current_user: Profile = Depends(require_roles([AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Manual reconciliation workflow: resolve an ambiguous outbox item with mandatory audit reasoning."""
    item = db.query(NotificationOutbox).filter(NotificationOutbox.id == outbox_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbox notification record not found.")

    if req.resolution == "mark_sent":
        if not (req.provider_message_id or req.evidence_reference):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Marking an outbox notification as 'mark_sent' requires explicit evidence: provide provider_message_id or evidence_reference.",
            )
        if req.evidence_type == "provider_telemetry_verified":
            if not req.provider_message_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Provider-verified resolution requires an authoritative provider_message_id.",
                )
            # Contact the configured provider to verify message existence, status, and delivery association
            from backend.app.services.notification_service import get_notification_provider
            provider_name = (item.provider or settings.SMS_PROVIDER or "").lower()
            if provider_name == "simulated" or provider_name not in ["termii", "twilio"]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Simulated notifications cannot be used for 'provider_telemetry_verified' resolution. "
                        "Evidence from local sandbox providers does not qualify as carrier telemetry. "
                        "Use 'manual_operator_asserted' with supporting ticket reference, or configure an authoritative carrier (Termii/Twilio)."
                    ),
                )
            active_provider = get_notification_provider(provider_name)
            telemetry_res = None
            if active_provider and hasattr(active_provider, "check_message_status"):
                try:
                    telemetry_res = active_provider.check_message_status(
                        idempotency_key=item.idempotency_key or "",
                        provider_message_id=req.provider_message_id,
                        recipient_phone=item.recipient_phone,
                        delivery_id=item.delivery_id,
                    )
                except Exception as exc:
                    logger.warning(f"Provider telemetry verification check exception: {exc}")

            if not telemetry_res or telemetry_res.status != NotificationDeliveryStatus.SENT:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Provider telemetry verification failed: message ID '{req.provider_message_id}' "
                        f"could not be confirmed as successfully dispatched by provider '{provider_name}'. "
                        "Verify carrier logs or use 'manual_operator_asserted' with supporting ticket reference."
                    ),
                )

    now = datetime.now(timezone.utc)
    recon_id = req.reconciliation_request_id or f"recon-{uuid.uuid4().hex[:12]}"
    item.reconciliation_request_id = recon_id
    item.evidence_type = req.evidence_type

    resolution_audit_desc = (
        f"Outbox manual reconciliation [{recon_id}]: action='{req.resolution}', "
        f"evidence_type='{req.evidence_type}', reason='{req.reason}', "
        f"evidence='{req.evidence_reference or req.provider_message_id}'"
    )

    if req.resolution == "mark_sent":
        item.status = NotificationDeliveryStatus.SENT
        item.provider_message_id = req.provider_message_id or item.provider_message_id or f"MANUAL_RECONCILED_{current_user.id[:8]}"
        item.status_reconciled_at = now
        item.sent_at = item.sent_at or now
        item.failure_classification = "manual_asserted_resolution" if req.evidence_type == "manual_operator_asserted" else "provider_verified_resolution"
        item.error_details = (
            f"Manually verified sent by admin {current_user.email} (evidence_type: {req.evidence_type}). "
            f"Reason: {req.reason}. Evidence: {req.evidence_reference or req.provider_message_id}."
        )
        item.locked_at = None
        item.locked_by = None
    elif req.resolution == "requeue":
        if item.status not in [NotificationDeliveryStatus.FAILED, NotificationDeliveryStatus.RECONCILIATION_REQUIRED]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot requeue notification in active status '{item.status.value}'. Requeue is only permitted for failed or reconciliation-required items.",
            )

        item.status = NotificationDeliveryStatus.QUEUED
        item.failure_classification = "manual_requeue_authorized"
        item.retry_count = 0  # Reset retry counter so exhausted items are eligible for processing

        # Explicit dispatch attempt increment while preserving initial idempotency key in audit history
        current_attempt = getattr(item, "dispatch_attempt", 1) or 1
        new_attempt = current_attempt + 1
        item.dispatch_attempt = new_attempt
        if not getattr(item, "original_idempotency_key", None):
            item.original_idempotency_key = item.idempotency_key

        # Preserve the previous provider message ID in attempt history and clear active provider_message_id
        # so the worker performs a fresh dispatch rather than incorrectly short-circuiting to SENT!
        if item.provider_message_id:
            item.last_failed_provider_message_id = item.provider_message_id
            item.provider_message_id = None

        base_idempotency = (item.original_idempotency_key or item.idempotency_key or f"outbox_{item.id}")[:48]
        item.idempotency_key = f"{base_idempotency}_att{new_attempt}"

        item.error_details = (
            f"Supervisor {current_user.email} authorized manual requeue (dispatch_attempt: {new_attempt}, "
            f"prior_idempotency: {item.original_idempotency_key}, "
            f"prior_provider_msg_id: {item.last_failed_provider_message_id}). Reason: {req.reason}."
        )
        item.next_attempt_at = now
        item.locked_at = None
        item.locked_by = None
    elif req.resolution == "mark_failed":
        item.status = NotificationDeliveryStatus.FAILED
        item.failure_classification = "manually_marked_failed"
        item.error_details = f"Marked permanently failed by admin {current_user.email}. Reason: {req.reason}."
        item.locked_at = None
        item.locked_by = None

    # Append immutable audit entry to delivery events
    deliv = db.query(Delivery).filter(Delivery.id == item.delivery_id).first()
    if deliv:
        event = DeliveryEvent(
            delivery_id=item.delivery_id,
            status=deliv.status,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role.value,
            note=f"{resolution_audit_desc}, actor='{current_user.email}'.",
            occurred_at=now,
        )
        db.add(event)

    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "delivery_id": item.delivery_id,
        "status": item.status.value,
        "provider_message_id": item.provider_message_id,
        "error_details": item.error_details,
        "reconciled_by": current_user.email,
        "reconciled_at": now.isoformat(),
        "audit_reason": req.reason,
    }
