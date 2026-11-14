"""Analytics and metrics router."""
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.database import get_db
from backend.app.models.delivery import Delivery
from backend.app.models.operator import Operator
from backend.app.models.customer import Customer
from backend.app.models.enums import DeliveryStatus, PostcodeStatus

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def api_get_analytics_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get high-level operations, verification accuracy, and fleet KPIs."""
    total_deliveries = db.query(func.count(Delivery.id)).scalar() or 0
    delivered = db.query(func.count(Delivery.id)).filter(Delivery.status == DeliveryStatus.DELIVERED).scalar() or 0
    in_transit = db.query(func.count(Delivery.id)).filter(
        Delivery.status.in_([DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.PICKED_UP])
    ).scalar() or 0
    pending = db.query(func.count(Delivery.id)).filter(
        Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.ASSIGNED])
    ).scalar() or 0
    cancelled = db.query(func.count(Delivery.id)).filter(Delivery.status == DeliveryStatus.CANCELLED).scalar() or 0

    verified_postcodes = db.query(func.count(Delivery.id)).filter(
        Delivery.postcode_status == PostcodeStatus.VERIFIED
    ).scalar() or 0

    verification_rate = (
        round((verified_postcodes / total_deliveries) * 100, 1) if total_deliveries > 0 else 100.0
    )

    total_revenue = db.query(func.sum(Delivery.fee)).filter(
        Delivery.status != DeliveryStatus.CANCELLED
    ).scalar() or 0.0

    active_operators = db.query(func.count(Operator.id)).filter(Operator.is_available == True).scalar() or 0
    total_customers = db.query(func.count(Customer.id)).scalar() or 0

    return {
        "total_deliveries": total_deliveries,
        "delivered": delivered,
        "in_transit": in_transit,
        "pending": pending,
        "cancelled": cancelled,
        "verified_postcodes_count": verified_postcodes,
        "verification_rate_percent": verification_rate,
        "total_revenue_ngn": total_revenue,
        "active_operators": active_operators,
        "total_customers": total_customers,
    }

