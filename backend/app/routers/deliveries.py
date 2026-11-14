"""Deliveries router with authentication, tenant isolation, and RBAC."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.database import get_db
from backend.app.models.delivery import Delivery
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.enums import DeliveryStatus, AppRole
from backend.app.schemas.delivery import (
    DeliveryCreateRequest,
    DeliveryCreateResponse,
    DeliveryStatusUpdateRequest,
    DeliveryAssignRequest,
    DeliveryVerifyOTPRequest,
    DeliveryResponse,
    DeliveryPublicTrackingResponse,
)
from backend.app.services.delivery_service import (
    create_delivery,
    assign_operator,
    update_delivery_status,
    verify_delivery_otp,
    get_public_tracking,
)
from backend.app.core.auth_deps import get_current_user, require_roles

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post("/", response_model=DeliveryCreateResponse, status_code=status.HTTP_201_CREATED)
def api_create_delivery(
    request: DeliveryCreateRequest,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Create a new delivery record scoped strictly to the authenticated merchant."""
    return create_delivery(db, request, current_user)


@router.get("/", response_model=List[DeliveryResponse])
def api_list_deliveries(
    status_filter: Optional[DeliveryStatus] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List deliveries scoped by tenant role (Merchants see their orders; Operators see assigned trips)."""
    query = db.query(Delivery)

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
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full details of a delivery (enforcing tenant access permissions)."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery order not found.")

    # Authorization
    if current_user.role == AppRole.MERCHANT and delivery.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this delivery order.")
    elif current_user.role == AppRole.OPERATOR:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if not op or delivery.operator_id != op.id:
            raise HTTPException(status_code=403, detail="Forbidden: You are not the assigned operator for this order.")

    return delivery


@router.get("/{delivery_id}/tracking", response_model=DeliveryPublicTrackingResponse)
def api_get_tracking(delivery_id: str, db: Session = Depends(get_db)):
    """Public customer tracking portal endpoint. Masked recipient phone, ZERO OTP digits exposed."""
    return get_public_tracking(db, delivery_id)


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
    """Update delivery status enforcing valid state machine transitions and authenticated actor claims."""
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
