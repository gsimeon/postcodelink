"""Authentication and profile schemas."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from backend.app.models.enums import AppRole


class UserRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=8)  # Enforce minimum 8 characters
    phone: Optional[str] = None
    business_name: Optional[str] = None
    # NOTE: Public registration MUST NOT allow specifying role. Role is strictly assigned by server.


class AdminCreateUserRequest(BaseModel):
    full_name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=8)
    phone: Optional[str] = None
    role: AppRole
    business_name: Optional[str] = None


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProfileResponse(BaseModel):
    id: str
    full_name: str
    email: str
    role: AppRole
    phone: Optional[str] = None
    business_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    profile: ProfileResponse
