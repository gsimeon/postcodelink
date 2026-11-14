"""Operators / Courier fleets router."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.operator import Operator
from backend.app.schemas.operator import OperatorCreate, OperatorUpdate, OperatorResponse

router = APIRouter(prefix="/operators", tags=["operators"])


@router.get("/", response_model=List[OperatorResponse])
def api_list_operators(db: Session = Depends(get_db)):
    """List all registered logistics operators."""
    return db.query(Operator).order_by(Operator.completed_deliveries.desc()).all()


@router.post("/", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
def api_create_operator(request: OperatorCreate, db: Session = Depends(get_db)):
    """Register a new courier operator."""
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


@router.get("/{operator_id}", response_model=OperatorResponse)
def api_get_operator(operator_id: str, db: Session = Depends(get_db)):
    """Get single operator details."""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found.")
    return op


@router.patch("/{operator_id}", response_model=OperatorResponse)
def api_update_operator(operator_id: str, request: OperatorUpdate, db: Session = Depends(get_db)):
    """Update operator status, availability, or dispatch details."""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found.")

    update_data = request.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(op, field, val)

    db.commit()
    db.refresh(op)
    return op

