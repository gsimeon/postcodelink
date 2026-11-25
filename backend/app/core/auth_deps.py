"""FastAPI Authentication and Role-Based Authorization Dependencies."""
from typing import List, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt

from backend.app.database import get_db
from backend.app.models.profile import Profile
from backend.app.models.enums import AppRole
from backend.app.core.security import decode_access_token

security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> Profile:
    """Dependency that authenticates via Bearer token or HttpOnly session cookie and returns the current Profile."""
    token: Optional[str] = None
    using_cookie = False
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif request is not None:
        token = request.cookies.get("postcodelink_session")
        using_cookie = bool(token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token or 'x-api-key' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if using_cookie and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not request.headers.get("x-requested-with"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed for cookie-authenticated state-changing request.",
            )
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source_url = origin or referer
        if source_url:
            from urllib.parse import urlparse
            from backend.app.config import settings
            parsed = urlparse(source_url)
            req_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            allowed = {o.rstrip("/") for o in settings.CORS_ORIGINS}
            self_origin = str(request.base_url).rstrip("/")
            if req_origin not in allowed and req_origin != self_origin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF origin validation failed for cookie-authenticated request.",
                )
    try:
        payload = decode_access_token(token)
        user_id: Optional[str] = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload. User identity missing.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user profile not found or deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return profile


def require_roles(allowed_roles: List[AppRole]):
    """Factory dependency enforcing that current_user has one of the required roles."""
    def role_checker(current_user: Profile = Depends(get_current_user)) -> Profile:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: User with role '{current_user.role.value}' does not have sufficient permissions.",
            )
        return current_user
    return role_checker


def get_current_actor(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
) -> Profile:
    """Unified actor dependency: authenticates via 'x-api-key' or Bearer JWT token."""
    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        from backend.app.routers.api_keys import get_api_key_merchant
        return get_api_key_merchant(x_api_key=x_api_key, db=db)
    return get_current_user(credentials=credentials, db=db)


def get_authenticated_merchant_or_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
) -> Profile:
    """Unified merchant dependency: accepts 'x-api-key' (metered) or merchant/admin Bearer JWT.
    
    Used by integration endpoints (deliveries, postcode cleansing, analytics) to authenticate
    external e-commerce platforms and automated logistics software with atomic monthly quota tracking.
    """
    actor = get_current_actor(request=request, credentials=credentials, db=db)
    if actor.role not in [AppRole.MERCHANT, AppRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: User with role '{actor.role.value}' cannot perform merchant operations.",
        )
    return actor


