"""v6.2.0 regression tests for production-hostname session cookies and CSRF origin enforcement."""
import uuid
from unittest.mock import patch

from fastapi import Response
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.core.security import create_access_token
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models.enums import AppRole
from backend.app.models.profile import Profile
from backend.app.routers.auth import _set_session_cookie


def test_production_session_cookie_attributes_lax_and_none():
    for samesite_mode in ("lax", "none"):
        resp = Response()
        with (
            patch.object(settings, "ENVIRONMENT", "production"),
            patch.object(settings, "SESSION_COOKIE_SAMESITE", samesite_mode),
        ):
            _set_session_cookie(resp, "jwt.token.value")

        set_cookie = resp.headers.get("set-cookie", "")
        assert "postcodelink_session=jwt.token.value" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert f"SameSite={samesite_mode}" in set_cookie


def test_production_hostname_csrf_and_origin_enforcement():
    client = TestClient(app)
    db = SessionLocal()
    try:
        uid = str(uuid.uuid4())
        merchant = Profile(
            id=uid,
            full_name="Prod Cookie Merchant",
            phone=f"+23480{str(uuid.UUID(uid).int)[:8]}",
            email=f"prod-cookie-{uid[:6]}@postcodelink.ng",
            hashed_password="pw",
            role=AppRole.MERCHANT,
        )
        db.add(merchant)
        db.commit()

        token = create_access_token({"sub": uid, "role": AppRole.MERCHANT.value})
        client.cookies.set("postcodelink_session", token)

        with (
            patch.object(settings, "ENVIRONMENT", "production"),
            patch.object(settings, "CORS_ORIGINS", ["https://app.postcodelink.ng"]),
        ):
            # 1. Missing X-Requested-With -> 403
            r_no_xhr = client.post(
                "/api/v1/api-keys/",
                json={"name": "No XHR", "monthly_quota": 50, "environment": "test"},
                headers={"Origin": "https://app.postcodelink.ng"},
            )
            assert r_no_xhr.status_code == 403

            # 2. Missing Origin/Referer in production -> 403
            r_no_origin = client.post(
                "/api/v1/api-keys/",
                json={"name": "No Origin", "monthly_quota": 50, "environment": "test"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            assert r_no_origin.status_code == 403

            # 3. Untrusted Origin -> 403
            r_evil = client.post(
                "/api/v1/api-keys/",
                json={"name": "Evil Origin", "monthly_quota": 50, "environment": "test"},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": "https://evil.example",
                },
            )
            assert r_evil.status_code == 403

            # 4. Trusted production Origin + X-Requested-With -> 201
            r_ok = client.post(
                "/api/v1/api-keys/",
                json={"name": "Trusted Prod Origin", "monthly_quota": 50, "environment": "test"},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": "https://app.postcodelink.ng",
                },
            )
            assert r_ok.status_code == 201
    finally:
        db.close()
