"""Customer schemas."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class CustomerBase(BaseModel):
    full_name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=7)
    email: Optional[str] = None
    default_address: str = Field(..., min_length=3)
    area: str
    state: str
    postcode: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerResponse(CustomerBase):
    id: str
    total_orders: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
