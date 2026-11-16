"""Operators / Courier fleets router with RBAC and fleet data privacy."""
from typing import List, Union, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.operator import Operator
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.schemas.operator import (
    OperatorCreate,
    OperatorUpdate,
    OperatorResponse,
    OperatorDirectoryResponse,
)
from backend.app.core.auth_deps import get_current_actor, get_current_user, require_roles

router = APIRouter(prefix="/operators", tags=["operators"])


@router.get("/", response_model=Union[List[OperatorResponse], List[OperatorDirectoryResponse]])
def api_list_operators(
    available_only: bool = Query(False),
    service_area: Optional[str] = Query(None),
    current_user: Profile = Depends(get_current_actor),
    db: Session = Depends(get_db)
):
    """List logistics operators.
    
    - Admins: Receive full fleet management telemetry (phone, GPS, active workloads).
    - Merchants: Receive privacy-preserved dispatch directory (business name, rating, vehicle, service zones).
    """
    query = db.query(Operator)
    if available_only:
        query = query.filter(Operator.is_available == True)

    operators = query.order_by(Operator.completed_deliveries.desc()).all()

    if service_area:
        target_area = service_area.strip().lower()
        operators = [
            op for op in operators
            if op.service_areas and any(target_area in (area or "").lower() for area in op.service_areas)
        ]

    if current_user.role == AppRole.ADMIN:
        return operators

    # Return privacy-preserved directory for merchants and other users
    directory = [
        OperatorDirectoryResponse(
            id=op.id,
            business_name=op.business_name,
            vehicle_type=op.vehicle_type,
            service_areas=op.service_areas or [],
            is_available=op.is_available,
            rating=op.rating,
            has_capacity=(op.active_deliveries_count < (op.max_active_deliveries or 15)),
        )
        for op in operators
    ]
    return directory


@router.post("/", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
def api_create_operator(
    request: OperatorCreate,
    current_user: Profile = Depends(require_roles([AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Register a new courier operator (Admin only)."""
    op = Operator(
        profile_id=request.profile_id,
        business_name=request.business_name.strip(),
        phone=request.phone.strip(),
        vehicle_type=request.vehicle_type,
        service_areas=request.service_areas,
        is_available=request.is_available,
        current_lat=request.current_lat,
        current_lng=request.current_lng,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return op


@router.get("/{operator_id}", response_model=Union[OperatorResponse, OperatorDirectoryResponse])
def api_get_operator(
    operator_id: str,
    current_user: Profile = Depends(get_current_actor),
    db: Session = Depends(get_db)
):
    """Get single operator details. Full details for Admin or fleet owner; directory view for merchants."""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found.")

    if current_user.role == AppRole.ADMIN or op.profile_id == current_user.id:
        return op

    return OperatorDirectoryResponse(
        id=op.id,
        business_name=op.business_name,
        vehicle_type=op.vehicle_type,
        service_areas=op.service_areas or [],
        is_available=op.is_available,
        rating=op.rating,
        has_capacity=(op.active_deliveries_count < (op.max_active_deliveries or 15)),
    )


@router.patch("/{operator_id}", response_model=OperatorResponse)
def api_update_operator(
    operator_id: str,
    request: OperatorUpdate,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update operator status or availability (Admin or Operator Profile owner)."""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found.")

    if current_user.role != AppRole.ADMIN and op.profile_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You can only update your own operator fleet profile.")

    update_data = request.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(op, field, val)

    db.commit()
    db.refresh(op)
    return op
