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
from backend.app.core.auth_deps import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def api_get_analytics_overview(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get high-level operations, verification accuracy, and fleet KPIs (scoped to tenant)."""
    base_query = db.query(Delivery)
    if current_user.role == AppRole.MERCHANT:
        base_query = base_query.filter(Delivery.merchant_id == current_user.id)

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

    total_revenue = base_query.filter(
        Delivery.status != DeliveryStatus.CANCELLED
    ).with_entities(func.sum(Delivery.fee)).scalar() or 0.0

    active_operators = db.query(func.count(Operator.id)).filter(Operator.is_available == True).scalar() or 0
    total_customers = db.query(func.count(Customer.id)).scalar() or 0

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
