"""State machine for delivery lifecycle transitions."""
from typing import Dict, List, Tuple
from backend.app.models.enums import DeliveryStatus

ALLOWED_TRANSITIONS: Dict[DeliveryStatus, List[DeliveryStatus]] = {
    DeliveryStatus.PENDING: [DeliveryStatus.ASSIGNED, DeliveryStatus.CANCELLED],
    DeliveryStatus.ASSIGNED: [DeliveryStatus.PICKED_UP, DeliveryStatus.CANCELLED, DeliveryStatus.PENDING],
    DeliveryStatus.PICKED_UP: [DeliveryStatus.IN_TRANSIT, DeliveryStatus.FAILED],
    DeliveryStatus.IN_TRANSIT: [DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.FAILED],
    DeliveryStatus.OUT_FOR_DELIVERY: [DeliveryStatus.DELIVERED, DeliveryStatus.FAILED],
    DeliveryStatus.FAILED: [DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.CANCELLED],
    DeliveryStatus.DELIVERED: [],  # terminal
    DeliveryStatus.CANCELLED: [],  # terminal
}


def can_transition(current_status: DeliveryStatus, next_status: DeliveryStatus) -> Tuple[bool, str]:
    """Validate whether current_status can transition to next_status."""
    if current_status == next_status:
        return True, "No status change."
        
    allowed = ALLOWED_TRANSITIONS.get(current_status, [])
    if next_status in allowed:
        return True, f"Valid transition from {current_status.value} to {next_status.value}."
        
    return False, f"Invalid transition: cannot move delivery from '{current_status.value}' to '{next_status.value}'."

