"""Deliveries router."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.database import get_db
from backend.app.models.delivery import Delivery
from backend.app.models.enums import DeliveryStatus
from backend.app.schemas.delivery import (
    DeliveryCreateRequest,
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

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post("/", response_model=DeliveryResponse, status_code=status.HTTP_201_CREATED)
def api_create_delivery(request: DeliveryCreateRequest, db: Session = Depends(get_db)):
    """Create a new delivery record with verified or unverified postcode linking."""
    return create_delivery(db, request)


@router.get("/", response_model=List[DeliveryResponse])
def api_list_deliveries(
    status_filter: Optional[DeliveryStatus] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List deliveries with optional filtering by status and text search."""
    query = db.query(Delivery)
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
def api_get_delivery(delivery_id: str, db: Session = Depends(get_db)):
    """Get full details of a delivery (Merchant & Operator view)."""
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Delivery order not found.")
    return delivery


@router.get("/{delivery_id}/tracking", response_model=DeliveryPublicTrackingResponse)
def api_get_tracking(delivery_id: str, db: Session = Depends(get_db)):
    """Public tracking portal endpoint. Masked recipient phone and masked PIN for privacy."""
    return get_public_tracking(db, delivery_id)


@router.post("/{delivery_id}/assign", response_model=DeliveryResponse)
def api_assign_operator(delivery_id: str, request: DeliveryAssignRequest, db: Session = Depends(get_db)):
    """Assign delivery to a registered courier operator fleet."""
    return assign_operator(db, delivery_id, request)


@router.post("/{delivery_id}/status", response_model=DeliveryResponse)
def api_update_status(delivery_id: str, request: DeliveryStatusUpdateRequest, db: Session = Depends(get_db)):
    """Update delivery status enforcing valid state machine transitions."""
    return update_delivery_status(db, delivery_id, request)


@router.post("/{delivery_id}/verify-otp", response_model=DeliveryResponse)
def api_verify_otp(delivery_id: str, request: DeliveryVerifyOTPRequest, db: Session = Depends(get_db)):
    """Confirm delivery via 6-digit recipient PIN with 3-attempt brute-force protection."""
    return verify_delivery_otp(db, delivery_id, request)

