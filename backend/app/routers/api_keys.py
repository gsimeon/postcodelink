"""API Key Management and authentication router."""
import secrets
import hashlib
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.api_key import ApiKey
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.core.auth_deps import require_roles

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str = "Production API Key"
    monthly_quota: int = 10000


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    monthly_quota: int
    usage_count: int
    is_active: bool
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
    """FastAPI security dependency authenticating callers via x-api-key header with monthly quota enforcement."""
    if not x_api_key or not isinstance(x_api_key, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing 'x-api-key' authentication header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    clean_key = x_api_key.strip()
    hashed = hashlib.sha256(clean_key.encode("utf-8")).hexdigest()

    key_record = db.query(ApiKey).filter(ApiKey.hashed_key == hashed).first()
    if not key_record or not key_record.is_active:
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

    # Monthly quota enforcement
    if key_record.usage_count >= key_record.monthly_quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly API quota of {key_record.monthly_quota} requests exceeded. Contact support to upgrade plan.",
        )

    # Concurrency-safe atomic usage increment
    db.query(ApiKey).filter(ApiKey.id == key_record.id).update(
        {
            ApiKey.usage_count: ApiKey.usage_count + 1,
            ApiKey.last_used_at: now,
        }
    )
    db.commit()

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

    key_obj = ApiKey(
        merchant_id=current_user.id,
        name=req.name.strip(),
        key_prefix=prefix,
        hashed_key=hashed,
        monthly_quota=max(100, req.monthly_quota),
        usage_count=0,
        is_active=True,
    )
    db.add(key_obj)
    db.commit()
    db.refresh(key_obj)

    resp_dict = {
        "id": key_obj.id,
        "name": key_obj.name,
        "key_prefix": key_obj.key_prefix,
        "monthly_quota": key_obj.monthly_quota,
        "usage_count": key_obj.usage_count,
        "is_active": key_obj.is_active,
        "created_at": key_obj.created_at,
        "expires_at": key_obj.expires_at,
        "last_used_at": key_obj.last_used_at,
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
    db.commit()
    return {"message": "API key successfully revoked.", "key_id": key_id, "is_active": False}
