"""Analytics and metrics router with tenant scoping."""
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.database import get_db
from backend.app.models.delivery import Delivery
from backend.app.models.operator import Operator
from backend.app.models.customer import Customer
from backend.app.models.profile import Profile
from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole
from backend.app.core.auth_deps import get_current_user, get_current_actor

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def api_get_analytics_overview(
    current_user: Profile = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get high-level operations, verification accuracy, and fleet KPIs (scoped strictly to tenant)."""
    base_query = db.query(Delivery)

    if current_user.role == AppRole.MERCHANT:
        base_query = base_query.filter(Delivery.merchant_id == current_user.id)
        # Merchant sees only their own customer address book count
        total_customers = db.query(func.count(Customer.id)).filter(Customer.merchant_id == current_user.id).scalar() or 0
        active_operators = db.query(func.count(Operator.id)).filter(Operator.is_available == True).scalar() or 0
        total_revenue = base_query.filter(
            Delivery.status != DeliveryStatus.CANCELLED
        ).with_entities(func.sum(Delivery.fee)).scalar() or 0.0

    elif current_user.role == AppRole.OPERATOR:
        op = db.query(Operator).filter(Operator.profile_id == current_user.id).first()
        if op:
            base_query = base_query.filter(Delivery.operator_id == op.id)
            active_operators = 1 if op.is_available else 0
        else:
            base_query = base_query.filter(Delivery.id == "__NON_EXISTENT__")
            active_operators = 0

        # Operators must NOT see merchant commercial revenues or other merchants' customer counts
        total_customers = 0
        total_revenue = 0.0

    else:
        # Platform Administrators see global platform-wide statistics
        total_customers = db.query(func.count(Customer.id)).scalar() or 0
        active_operators = db.query(func.count(Operator.id)).filter(Operator.is_available == True).scalar() or 0
        total_revenue = base_query.filter(
            Delivery.status != DeliveryStatus.CANCELLED
        ).with_entities(func.sum(Delivery.fee)).scalar() or 0.0

    total_deliveries = base_query.with_entities(func.count(Delivery.id)).scalar() or 0
    delivered = base_query.filter(Delivery.status == DeliveryStatus.DELIVERED).with_entities(func.count(Delivery.id)).scalar() or 0
    in_transit = base_query.filter(
        Delivery.status.in_([DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.PICKED_UP])
    ).with_entities(func.count(Delivery.id)).scalar() or 0
    pending = base_query.filter(
        Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.ASSIGNED])
    ).with_entities(func.count(Delivery.id)).scalar() or 0
    cancelled = base_query.filter(Delivery.status == DeliveryStatus.CANCELLED).with_entities(func.count(Delivery.id)).scalar() or 0

    verified_postcodes = base_query.filter(
        Delivery.postcode_status == PostcodeStatus.VERIFIED
    ).with_entities(func.count(Delivery.id)).scalar() or 0

    verification_rate = (
        round((verified_postcodes / total_deliveries) * 100, 1) if total_deliveries > 0 else 100.0
    )

    return {
        "tenant_id": current_user.id,
        "tenant_role": current_user.role.value,
        "total_deliveries": total_deliveries,
        "delivered": delivered,
        "in_transit": in_transit,
        "pending": pending,
        "cancelled": cancelled,
        "verified_postcodes_count": verified_postcodes,
        "verification_rate_percent": verification_rate,
        "total_revenue_ngn": float(total_revenue),
        "active_operators": active_operators,
        "total_customers": total_customers,
    }
