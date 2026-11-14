"""Authentication router enforcing secure registration, trusted proxy evaluation, and role boundaries."""
import time
import ipaddress
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models.profile import Profile
from backend.app.models.login_attempt import LoginAttempt
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

# Legacy dictionary retained for test fixture compatibility; active rate limiting is database-persisted
LOGIN_ATTEMPTS: Dict[str, Tuple[int, float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


def is_ip_in_trusted_proxy(ip_str: str, trusted_spec: str) -> bool:
    """Check if an IP string belongs to a trusted proxy host or CIDR subnet."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if "/" in trusted_spec:
            return ip in ipaddress.ip_network(trusted_spec, strict=False)
        return ip == ipaddress.ip_address(trusted_spec)
    except ValueError:
        return ip_str.lower() == trusted_spec.lower()


def get_trusted_client_ip(request: Request) -> str:
    """Extract real client IP only trusting X-Forwarded-For when direct request arrives via a configured trusted proxy."""
    direct_ip = request.client.host if request.client else "127.0.0.1"
    trusted_list = getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1", "localhost", "testclient"])

    # If the direct peer is NOT in trusted proxies, completely ignore X-Forwarded-For to defeat header spoofing
    is_trusted = any(is_ip_in_trusted_proxy(direct_ip, proxy) for proxy in trusted_list)
    if not is_trusted:
        return direct_ip

    # Peer is a trusted proxy: parse X-Forwarded-For chain from right to left
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        for ip in reversed(ips):
            if not any(is_ip_in_trusted_proxy(ip, proxy) for proxy in trusted_list):
                return ip
        if ips:
            return ips[0]

    return direct_ip


def cleanup_expired_login_attempts(db: Session, retention_days: int = 30) -> int:
    """Purge login attempt audit records older than retention_days (Retention Policy)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = db.query(LoginAttempt).filter(LoginAttempt.attempted_at < cutoff).delete()
    db.commit()
    return deleted


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
def api_login(request: UserLoginRequest, req: Request, db: Session = Depends(get_db)):
    """Authenticate with email and password to receive a JWT Bearer token with trusted-proxy rate limiting."""
    clean_email = request.email.strip().lower()
    client_ip = get_trusted_client_ip(req)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=LOCKOUT_DURATION_MINUTES)

    # 1. IP-level flood protection (max 30 failed attempts across all accounts from same IP in 15 mins)
    ip_failed_count = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.ip_address == client_ip,
            LoginAttempt.attempted_at >= window_start,
            LoginAttempt.is_successful == False,
        )
        .count()
    )
    if ip_failed_count >= 30:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed requests from your network. Please try again in 15 minutes."
        )

    # 2. Account-level lockout check: 5 failed attempts in 15 mins
    account_failed_count = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.email == clean_email,
            LoginAttempt.attempted_at >= window_start,
            LoginAttempt.is_successful == False,
        )
        .count()
    )
    if account_failed_count >= MAX_LOGIN_ATTEMPTS:
        latest_attempt = (
            db.query(LoginAttempt)
            .filter(LoginAttempt.email == clean_email, LoginAttempt.is_successful == False)
            .order_by(LoginAttempt.attempted_at.desc())
            .first()
        )
        if latest_attempt:
            att_time = latest_attempt.attempted_at
            if att_time.tzinfo is None:
                att_time = att_time.replace(tzinfo=timezone.utc)
            lockout_expiry = att_time + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            if now < lockout_expiry:
                rem_mins = max(1, int((lockout_expiry - now).total_seconds() + 59) // 60)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many failed login attempts. Account is temporarily locked. Try again in {rem_mins} minute(s)."
                )

    profile = db.query(Profile).filter(Profile.email == clean_email).first()
    if not profile or not verify_password(request.password, profile.hashed_password):
        # Record failed attempt in persistent database
        failed_record = LoginAttempt(
            email=clean_email,
            ip_address=client_ip,
            is_successful=False,
            attempted_at=now,
            user_agent=req.headers.get("user-agent"),
        )
        db.add(failed_record)
        db.commit()

        new_failed_count = account_failed_count + 1
        if new_failed_count >= MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Account is temporarily locked for 15 minutes."
            )
        else:
            remaining = MAX_LOGIN_ATTEMPTS - new_failed_count
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid email or password. {remaining} attempt(s) remaining.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Success: record success and clear prior failed attempts for this email
    success_record = LoginAttempt(
        email=clean_email,
        ip_address=client_ip,
        is_successful=True,
        attempted_at=now,
        user_agent=req.headers.get("user-agent"),
    )
    db.add(success_record)
    db.query(LoginAttempt).filter(
        LoginAttempt.email == clean_email,
        LoginAttempt.is_successful == False,
    ).delete()
    db.commit()

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
