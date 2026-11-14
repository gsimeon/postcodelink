"""Authentication router enforcing secure registration and role boundaries."""
import time
from typing import Dict, Tuple
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.schemas.auth import (
    UserRegisterRequest,
    AdminCreateUserRequest,
    UserLoginRequest,
    TokenResponse,
    ProfileResponse,
)
from backend.app.core.security import hash_password, verify_password, create_access_token
from backend.app.core.auth_deps import get_current_user, require_roles

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory tracking for failed login attempts: email -> (attempts_count, locked_until_epoch)
LOGIN_ATTEMPTS: Dict[str, Tuple[int, float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def api_register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """Register a new merchant account. Public registration ALWAYS defaults to MERCHANT."""
    clean_email = request.email.strip().lower()
    existing = db.query(Profile).filter(Profile.email == clean_email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists."
        )

    # CRITICAL SECURITY FIX: Role is strictly locked to MERCHANT for public registration.
    profile = Profile(
        full_name=request.full_name.strip(),
        email=clean_email,
        hashed_password=hash_password(request.password),
        phone=request.phone.strip() if request.phone else None,
        role=AppRole.MERCHANT,
        business_name=request.business_name.strip() if request.business_name else None,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    token = create_access_token({"sub": profile.id, "email": profile.email, "role": profile.role.value})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        profile=ProfileResponse.model_validate(profile)
    )


@router.post("/admin/create-user", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def api_admin_create_user(
    request: AdminCreateUserRequest,
    current_user: Profile = Depends(require_roles([AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Create an Operator or Admin account (Platform Administrators only)."""
    clean_email = request.email.strip().lower()
    existing = db.query(Profile).filter(Profile.email == clean_email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists."
        )

    profile = Profile(
        full_name=request.full_name.strip(),
        email=clean_email,
        hashed_password=hash_password(request.password),
        phone=request.phone.strip() if request.phone else None,
        role=request.role,
        business_name=request.business_name.strip() if request.business_name else None,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return ProfileResponse.model_validate(profile)


@router.post("/login", response_model=TokenResponse)
def api_login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate with email and password to receive a JWT Bearer token with brute-force rate limiting."""
    clean_email = request.email.strip().lower()
    now = time.time()

    # 1. Check if email is currently locked out
    if clean_email in LOGIN_ATTEMPTS:
        attempts, locked_until = LOGIN_ATTEMPTS[clean_email]
        if locked_until > now:
            rem_mins = max(1, int((locked_until - now + 59) // 60))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Account is temporarily locked. Try again in {rem_mins} minute(s)."
            )

    profile = db.query(Profile).filter(Profile.email == clean_email).first()
    if not profile or not verify_password(request.password, profile.hashed_password):
        # Record failed attempt
        attempts, _ = LOGIN_ATTEMPTS.get(clean_email, (0, 0.0))
        attempts += 1
        if attempts >= MAX_LOGIN_ATTEMPTS:
            LOGIN_ATTEMPTS[clean_email] = (attempts, now + LOCKOUT_DURATION_SECONDS)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Account is temporarily locked for 15 minutes."
            )
        else:
            LOGIN_ATTEMPTS[clean_email] = (attempts, 0.0)
            remaining = MAX_LOGIN_ATTEMPTS - attempts
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid email or password. {remaining} attempt(s) remaining.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Success: reset attempt counter
    LOGIN_ATTEMPTS.pop(clean_email, None)

    token = create_access_token({"sub": profile.id, "email": profile.email, "role": profile.role.value})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        profile=ProfileResponse.model_validate(profile)
    )


@router.get("/me", response_model=ProfileResponse)
def api_get_current_profile(current_user: Profile = Depends(get_current_user)):
    """Get authenticated user's profile details."""
    return ProfileResponse.model_validate(current_user)
