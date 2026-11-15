"""API Key Management and authentication router."""
import secrets
import hashlib
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from sqlalchemy import update, case, and_, or_

from backend.app.database import get_db
from backend.app.models.api_key import ApiKey
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.core.auth_deps import require_roles
from backend.app.core.rate_limiter import check_api_key_rate_limit

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str = "Production API Key"
    monthly_quota: int = 10000
    expires_in_days: Optional[int] = None


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    monthly_quota: int
    current_period: str
    period_usage_count: int
    usage_count: int
    rate_limit_per_minute: int
    is_active: bool
    is_revoked: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreatedResponse(ApiKeyResponse):
    api_key: str  # Plaintext key returned strictly once upon generation


def get_api_key_merchant(
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    db: Session = Depends(get_db),
) -> Profile:
    """FastAPI security dependency authenticating callers via x-api-key header with atomic monthly quota enforcement."""
    if not x_api_key or not isinstance(x_api_key, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing 'x-api-key' authentication header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    clean_key = x_api_key.strip()
    hashed = hashlib.sha256(clean_key.encode("utf-8")).hexdigest()

    key_record = db.query(ApiKey).filter(ApiKey.hashed_key == hashed).first()
    if not key_record or not key_record.is_active or getattr(key_record, "is_revoked", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    now = datetime.now(timezone.utc)
    if key_record.expires_at:
        exp = key_record.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

    # 1. Enforce per-minute sliding window rate limiting
    check_api_key_rate_limit(key_record.id, getattr(key_record, "rate_limit_per_minute", 60))

    # 2. Concurrency-safe single atomic database operation:
    # Handles both calendar-month period rollover and quota-conditioned usage increment together
    now_period = now.strftime("%Y-%m")
    stmt = (
        update(ApiKey)
        .where(
            ApiKey.id == key_record.id,
            ApiKey.is_active == True,
            ApiKey.is_revoked == False,
            or_(
                # Scenario A: Same billing period with quota capacity remaining
                and_(
                    ApiKey.current_period == now_period,
                    ApiKey.period_usage_count < ApiKey.monthly_quota,
                ),
                # Scenario B: Rollover into new calendar period with non-zero quota
                and_(
                    ApiKey.current_period != now_period,
                    ApiKey.monthly_quota >= 1,
                ),
            ),
        )
        .values(
            period_usage_count=case(
                (ApiKey.current_period == now_period, ApiKey.period_usage_count + 1),
                else_=1,
            ),
            current_period=now_period,
            usage_count=ApiKey.usage_count + 1,
            last_used_at=now,
        )
    )
    result = db.execute(stmt)
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly API key quota of {key_record.monthly_quota} requests exceeded for period {now_period}.",
        )

    return key_record.merchant


@router.post("/", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def api_create_api_key(
    req: CreateApiKeyRequest,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Generate a new secure API key with prefix indexing and monthly request quota."""
    raw_token = secrets.token_urlsafe(32)
    raw_key = f"pl_live_{raw_token}"
    prefix = raw_key[:12]
    hashed = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=req.expires_in_days) if req.expires_in_days else None

    key_obj = ApiKey(
        merchant_id=current_user.id,
        name=req.name.strip(),
        key_prefix=prefix,
        hashed_key=hashed,
        monthly_quota=max(1, req.monthly_quota),
        current_period=now.strftime("%Y-%m"),
        period_usage_count=0,
        usage_count=0,
        rate_limit_per_minute=60,
        is_active=True,
        is_revoked=False,
        expires_at=expires_at,
    )
    db.add(key_obj)
    db.commit()
    db.refresh(key_obj)

    resp_dict = {
        "id": key_obj.id,
        "name": key_obj.name,
        "key_prefix": key_obj.key_prefix,
        "monthly_quota": key_obj.monthly_quota,
        "current_period": key_obj.current_period,
        "period_usage_count": key_obj.period_usage_count,
        "usage_count": key_obj.usage_count,
        "rate_limit_per_minute": key_obj.rate_limit_per_minute,
        "is_active": key_obj.is_active,
        "is_revoked": key_obj.is_revoked,
        "created_at": key_obj.created_at,
        "expires_at": key_obj.expires_at,
        "last_used_at": key_obj.last_used_at,
        "api_key": raw_key,
    }
    return ApiKeyCreatedResponse(**resp_dict)


@router.post("/{key_id}/rotate", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def api_rotate_api_key(
    key_id: str,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Rotate an existing API key: revokes the old key and generates a fresh credential preserving quota configuration."""
    now = datetime.now(timezone.utc)
    now_period = now.strftime("%Y-%m")

    # Concurrent rotation protection: conditional atomic update ensures exactly one rotation succeeds
    stmt = (
        update(ApiKey)
        .where(
            and_(
                ApiKey.id == key_id,
                ApiKey.merchant_id == current_user.id,
                ApiKey.is_active.is_(True),
                ApiKey.is_revoked.is_(False),
            )
        )
        .values(is_active=False, is_revoked=True)
    )
    res = db.execute(stmt)
    if res.rowcount == 0:
        existing = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.merchant_id == current_user.id).first()
        if not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="API key has already been rotated or revoked.",
        )

    old_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()

    # Generate fresh key
    raw_token = secrets.token_urlsafe(32)
    raw_key = f"pl_live_{raw_token}"
    prefix = raw_key[:12]
    hashed = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    # Quota inheritance: new credential inherits current billing period usage count from rotated key
    # This prevents merchants from resetting their monthly allowance via credential rotation
    inherited_period_usage = old_key.period_usage_count if getattr(old_key, "current_period", None) == now_period else 0
    inherited_usage = getattr(old_key, "usage_count", 0)

    new_key = ApiKey(
        merchant_id=current_user.id,
        name=f"{old_key.name} (Rotated)",
        key_prefix=prefix,
        hashed_key=hashed,
        monthly_quota=old_key.monthly_quota,
        current_period=now_period,
        period_usage_count=inherited_period_usage,
        usage_count=inherited_usage,
        rate_limit_per_minute=old_key.rate_limit_per_minute,
        is_active=True,
        is_revoked=False,
        expires_at=old_key.expires_at,
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)

    resp_dict = {
        "id": new_key.id,
        "name": new_key.name,
        "key_prefix": new_key.key_prefix,
        "monthly_quota": new_key.monthly_quota,
        "current_period": new_key.current_period,
        "period_usage_count": new_key.period_usage_count,
        "usage_count": new_key.usage_count,
        "rate_limit_per_minute": new_key.rate_limit_per_minute,
        "is_active": new_key.is_active,
        "is_revoked": new_key.is_revoked,
        "created_at": new_key.created_at,
        "expires_at": new_key.expires_at,
        "last_used_at": new_key.last_used_at,
        "api_key": raw_key,
    }
    return ApiKeyCreatedResponse(**resp_dict)


@router.get("/", response_model=List[ApiKeyResponse])
def api_list_api_keys(
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """List all API keys belonging to the authenticated merchant."""
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.merchant_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/{key_id}", status_code=status.HTTP_200_OK)
def api_revoke_api_key(
    key_id: str,
    current_user: Profile = Depends(require_roles([AppRole.MERCHANT, AppRole.ADMIN])),
    db: Session = Depends(get_db),
):
    """Revoke an active API key, immediately blocking all future authentication requests."""
    key_record = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.merchant_id == current_user.id)
        .first()
    )
    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found.",
        )

    key_record.is_active = False
    key_record.is_revoked = True
    db.commit()
    return {"message": "API key successfully revoked.", "key_id": key_id, "is_active": False, "is_revoked": True}
