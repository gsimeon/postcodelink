"""Customer directory router."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.database import get_db
from backend.app.models.customer import Customer
from backend.app.schemas.customer import CustomerCreate, CustomerResponse

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/", response_model=List[CustomerResponse])
def api_list_customers(
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db)
):
    """List recurring delivery customers and recipient address book."""
    query = db.query(Customer)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Customer.full_name.ilike(term),
                Customer.phone.ilike(term),
                Customer.default_address.ilike(term),
                Customer.area.ilike(term),
            )
        )
    return query.order_by(Customer.total_orders.desc()).limit(limit).all()


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def api_create_customer(request: CustomerCreate, db: Session = Depends(get_db)):
    """Add a new customer to recipient address directory."""
    cust = db.query(Customer).filter(Customer.phone == request.phone.strip()).first()
    if cust:
        cust.total_orders += 1
        cust.default_address = request.default_address.strip()
        cust.area = request.area.strip()
        cust.state = request.state.strip()
        if request.postcode:
            cust.postcode = request.postcode.strip()
        db.commit()
        db.refresh(cust)
        return cust

    new_cust = Customer(
        full_name=request.full_name.strip(),
        phone=request.phone.strip(),
        email=request.email.strip() if request.email else None,
        default_address=request.default_address.strip(),
        area=request.area.strip(),
        state=request.state.strip(),
        postcode=request.postcode.strip() if request.postcode else None,
        total_orders=1,
    )
    db.add(new_cust)
    db.commit()
    db.refresh(new_cust)
    return new_cust

