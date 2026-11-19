"""Customer directory router with strict tenant isolation."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.database import get_db
from backend.app.models.customer import Customer
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.schemas.customer import CustomerCreate, CustomerResponse
from backend.app.core.auth_deps import get_authenticated_merchant_or_api_key

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/", response_model=List[CustomerResponse])
def api_list_customers(
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    current_user: Profile = Depends(get_authenticated_merchant_or_api_key),
    db: Session = Depends(get_db),
):
    """List customer address book scoped strictly to the authenticated merchant."""
    query = db.query(Customer)
    if current_user.role == AppRole.MERCHANT:
        query = query.filter(Customer.merchant_id == current_user.id)

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
def api_create_customer(
    request: CustomerCreate,
    current_user: Profile = Depends(get_authenticated_merchant_or_api_key),
    db: Session = Depends(get_db),
):
    """Add or update customer in the authenticated merchant's address directory."""
    merchant_id = current_user.id
    cust = db.query(Customer).filter(
        Customer.merchant_id == merchant_id,
        Customer.phone == request.phone.strip()
    ).first()

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
        merchant_id=merchant_id,
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


@router.get("/{customer_id}", response_model=CustomerResponse)
def api_get_customer(
    customer_id: str,
    current_user: Profile = Depends(get_authenticated_merchant_or_api_key),
    db: Session = Depends(get_db),
):
    """Get customer record scoped strictly to merchant ownership."""
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found.")

    if current_user.role != AppRole.ADMIN and cust.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot access another merchant's customer.")

    return cust


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_customer(
    customer_id: str,
    current_user: Profile = Depends(get_authenticated_merchant_or_api_key),
    db: Session = Depends(get_db),
):
    """Delete a customer entry from merchant's address book."""
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found.")

    if current_user.role != AppRole.ADMIN and cust.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot delete another merchant's customer.")

    db.delete(cust)
    db.commit()
