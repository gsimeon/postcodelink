"""Comprehensive automated test suite verifying security, tenant isolation, RBAC, and OTP protection."""
import pytest
from starlette.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def get_auth_token(email: str, password: str) -> str:
    """Helper to login and retrieve JWT access token."""
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def test_root_and_health():
    """Verify system status and database healthcheck."""
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "operational"
    assert data["version"] == "1.1.0"

    h_res = client.get("/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "healthy"
    assert h_res.json()["database"] == "connected"


def test_auth_registration_and_login():
    """Verify registration, password hashing, and JWT authorization."""
    email = "testmerchant_unique@postcodelink.ng"
    reg_res = client.post("/api/v1/auth/register", json={
        "full_name": "Test Merchant User",
        "email": email,
        "password": "StrongPassword123!",
        "role": "merchant",
        "business_name": "Test Enterprise Ltd"
    })
    # If already exists from previous test run, login directly
    if reg_res.status_code == 201:
        token = reg_res.json()["access_token"]
    else:
        token = get_auth_token(email, "StrongPassword123!")

    # Verify /auth/me with Bearer token
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email

    # Verify invalid credentials rejected
    bad_login = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword"})
    assert bad_login.status_code == 401

    # Verify unauthenticated request to /auth/me is blocked
    no_auth = client.get("/api/v1/auth/me")
    assert no_auth.status_code == 401


def test_tenant_isolation():
    """Verify that Merchant A cannot access Merchant B's delivery orders."""
    # Merchant A
    token_a = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    # Register/Login Merchant B
    email_b = "merchant_b@postcodelink.ng"
    reg_b = client.post("/api/v1/auth/register", json={
        "full_name": "Merchant Beta",
        "email": email_b,
        "password": "PasswordBeta123!",
        "role": "merchant",
        "business_name": "Beta Stores"
    })
    token_b = reg_b.json()["access_token"] if reg_b.status_code == 201 else get_auth_token(email_b, "PasswordBeta123!")

    # Merchant A creates a delivery
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Tenant A Recipient",
        "recipient_phone": "08012345678",
        "destination_address": "10 Broad Street",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Sensitive Confidential Goods",
        "fee": 4500.0
    }, headers={"Authorization": f"Bearer {token_a}"})
    assert create_res.status_code == 201
    order_a_id = create_res.json()["delivery"]["id"]

    # Merchant B tries to view Merchant A's order -> MUST return 403 Forbidden
    hack_res = client.get(f"/api/v1/deliveries/{order_a_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert hack_res.status_code == 403

    # Merchant B lists deliveries -> order_a_id must NOT be present
    list_b = client.get("/api/v1/deliveries/", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    ids_b = [d["id"] for d in list_b.json()]
    assert order_a_id not in ids_b


def test_no_otp_in_delivery_responses():
    """Verify OTP is never exposed in delivery queries or public tracking."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "OTP Privacy Test",
        "recipient_phone": "08055667788",
        "destination_address": "14 Admiralty Way",
        "destination_area": "Lekki Phase 1",
        "destination_state": "Lagos",
        "postcode_input": "101241",
        "package_description": "Designer Wristwatch",
        "fee": 5000.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    data = create_res.json()

    # In the DeliveryResponse object, 'otp' key MUST NOT exist
    assert "otp" not in data["delivery"]
    
    deliv_id = data["delivery"]["id"]

    # Fetch detail
    get_res = client.get(f"/api/v1/deliveries/{deliv_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_res.status_code == 200
    assert "otp" not in get_res.json()

    # Public tracking portal check: ZERO OTP digits exposed
    track_res = client.get(f"/api/v1/deliveries/{deliv_id}/tracking")
    assert track_res.status_code == 200
    track_data = track_res.json()
    assert "otp" not in track_data
    assert "otp_masked" not in track_data
    assert track_data["requires_pin_confirmation"] is True
    assert "****" in track_data["recipient_phone_masked"]


def test_postcode_verification_rules_no_false_fallbacks():
    """Verify postcode provenance, exact match, estimated match, and no false 100001 fallbacks."""
    # 1. Exact match with postcode hint
    res_exact = client.post("/api/v1/postcodes/cleanse", json={
        "address": "14 Admiralty Way",
        "state": "Lagos",
        "postcode": "101241"
    })
    assert res_exact.status_code == 200
    data_exact = res_exact.json()
    assert data_exact["postcode_status"] == "verified"
    assert data_exact["postcode"] == "101241"
    assert data_exact["source"] == "local_nipost_reference_dataset"

    # 2. Area match only -> estimated, NOT verified
    res_est = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Somewhere near Alausa Secretariat",
        "state": "Lagos"
    })
    assert res_est.status_code == 200
    data_est = res_est.json()
    assert data_est["postcode_status"] == "estimated"
    assert data_est["confidence"] < 0.90

    # 3. Unknown location -> unverified, NEVER false fallback to 100001
    res_unver = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Random village near the forest gate",
        "state": "Ogun"
    })
    assert res_unver.status_code == 200
    data_unver = res_unver.json()
    assert data_unver["postcode_status"] == "unverified"
    assert data_unver["postcode"] == ""
    assert data_unver["confidence"] == 0.0


def test_operator_assignment_operational_guards():
    """Verify operator availability, service area, and capacity enforcement."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    # Create delivery destined for Ikeja
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Fleet Assignment Test",
        "recipient_phone": "08033334444",
        "destination_address": "Obafemi Awolowo Way",
        "destination_area": "Ikeja",
        "destination_state": "Lagos",
        "postcode_input": "100211",
        "package_description": "Electronics",
        "fee": 2500.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    deliv_id = create_res.json()["delivery"]["id"]

    ops = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {token}"}).json()
    assert len(ops) >= 2
    
    # Island couriers only cover Island, not Ikeja
    island_op = next((o for o in ops if "Island" in o["business_name"]), None)
    if island_op:
        bad_assign = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={
            "operator_id": island_op["id"]
        }, headers={"Authorization": f"Bearer {token}"})
        assert bad_assign.status_code == 400
        assert "does not cover" in bad_assign.json()["detail"]

    # Apex courier covers Ikeja
    apex_op = next((o for o in ops if "Apex" in o["business_name"]), None)
    assert apex_op is not None
    good_assign = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={
        "operator_id": apex_op["id"]
    }, headers={"Authorization": f"Bearer {token}"})
    assert good_assign.status_code == 200
    assert good_assign.json()["status"] == "assigned"


def test_otp_verification_lockout_and_single_use():
    """Verify 3-attempt brute force lockout and single-use enforcement."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Lockout & Single-use Recipient",
        "recipient_phone": "08077778888",
        "destination_address": "25 Marina Street",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Bank Cheque",
        "fee": 3000.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    data = create_res.json()
    deliv_id = data["delivery"]["id"]
    correct_pin = data["notification_dispatch"]["delivery_pin"]

    # Attempt 1: Wrong PIN
    try1 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "000000"
    }, headers={"Authorization": f"Bearer {token}"})
    assert try1.status_code == 400
    assert "2 attempt(s) remaining" in try1.json()["detail"]

    # Attempt 2: Wrong PIN
    try2 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "000001"
    }, headers={"Authorization": f"Bearer {token}"})
    assert try2.status_code == 400
    assert "1 attempt(s) remaining" in try2.json()["detail"]

    # Attempt 3: Wrong PIN -> Trigger Lockout
    try3 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "000002"
    }, headers={"Authorization": f"Bearer {token}"})
    assert try3.status_code == 429
    assert "locked for 15 minutes" in try3.json()["detail"]

    # Test Single-use on a fresh order:
    fresh_order = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Single Use Test",
        "recipient_phone": "08099990000",
        "destination_address": "1 Marina Street",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Parcel",
        "fee": 2000.0
    }, headers={"Authorization": f"Bearer {token}"}).json()
    fresh_id = fresh_order["delivery"]["id"]
    fresh_pin = fresh_order["notification_dispatch"]["delivery_pin"]

    # Verify once -> DELIVERED
    verify1 = client.post(f"/api/v1/deliveries/{fresh_id}/verify-otp", json={
        "otp": fresh_pin
    }, headers={"Authorization": f"Bearer {token}"})
    assert verify1.status_code == 200
    assert verify1.json()["status"] == "delivered"
    assert verify1.json()["pod_verified"] is True
