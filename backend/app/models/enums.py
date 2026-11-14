"""Enumeration types for PostcodeLink models."""
import enum


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PostcodeStatus(str, enum.Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INVALID = "invalid"
    ESTIMATED = "estimated"


class AppRole(str, enum.Enum):
    MERCHANT = "merchant"
    OPERATOR = "operator"
    ADMIN = "admin"


class VehicleType(str, enum.Enum):
    MOTORCYCLE = "motorcycle"
    VAN = "van"
    TRUCK = "truck"
    BICYCLE = "bicycle"

