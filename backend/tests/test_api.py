"""Comprehensive automated test suite verifying security, tenant isolation, RBAC, and OTP protection."""
import pytest
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.config import Settings
from backend.app.services.delivery_service import DISPATCHED_NOTIFICATIONS
from backend.app.database import SessionLocal
from backend.app.models.operator import Operator

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
    assert data["version"] == "1.2.0"

    h_res = client.get("/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "healthy"
    assert h_res.json()["database"] == "connected"


def test_public_registration_cannot_escalate_to_admin():
    """CRITICAL REGRESSION TEST: Verify public registration strictly locks role to MERCHANT.
    
    Submitting 'role': 'admin' or any other escalated role MUST be ignored or rejected,
    and the created account MUST be MERCHANT only.
    """
    import secrets
    email = f"hacker_{secrets.token_hex(4)}@postcodelink.ng"
    res = client.post("/api/v1/auth/register", json={
        "full_name": "Suspicious User",
        "email": email,
        "password": "HackerPassword123!",
        "role": "admin",  # Attacker attempts privilege escalation
        "business_name": "Exploit Logistics"
    })
    assert res.status_code == 201
    reg_data = res.json()
    # The returned profile MUST have role == 'merchant', NOT 'admin'
    assert reg_data["profile"]["role"] == "merchant"
    token = reg_data["access_token"]

    # Verify through /auth/me that the authenticated identity is strictly MERCHANT
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "merchant"

    # Attacker attempts to call the admin-only user creation endpoint -> MUST be 403 Forbidden
    escalate_res = client.post("/api/v1/auth/admin/create-user", json={
        "full_name": "Created Admin",
        "email": f"secondary_{secrets.token_hex(4)}@postcodelink.ng",
        "password": "AdminPassword123!",
        "role": "admin"
    }, headers={"Authorization": f"Bearer {token}"})
    assert escalate_res.status_code == 403
    assert "forbidden" in escalate_res.json()["detail"].lower()


def test_admin_can_create_operators_and_admins():
    """Verify that only authorized Platform Admins can provision Operator and Admin accounts."""
    import secrets
    admin_token = get_auth_token("admin@postcodelink.ng", "AdminSecure2026!")

    # Admin creates an operator account
    op_email = f"courier_{secrets.token_hex(4)}@postcodelink.ng"
    res_op = client.post("/api/v1/auth/admin/create-user", json={
        "full_name": "Swift Logistics Dispatcher",
        "email": op_email,
        "password": "CourierPass123!",
        "role": "operator",
        "business_name": "Swift Express Fleet"
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert res_op.status_code == 201
    assert res_op.json()["role"] == "operator"

    # Operator logs in and receives operator JWT
    op_token = get_auth_token(op_email, "CourierPass123!")
    me_op = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {op_token}"})
    assert me_op.status_code == 200
    assert me_op.json()["role"] == "operator"


def test_tenant_isolation_deliveries():
    """Verify that Merchant A cannot access or mutate Merchant B's delivery orders."""
    import secrets
    token_a = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    email_b = f"merchant_tenant_{secrets.token_hex(4)}@postcodelink.ng"
    reg_b = client.post("/api/v1/auth/register", json={
        "full_name": "Merchant Beta",
        "email": email_b,
        "password": "PasswordBeta123!",
        "business_name": "Beta Stores"
    })
    assert reg_b.status_code == 201
    token_b = reg_b.json()["access_token"]

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

    # Merchant B tries to delete Merchant A's order -> MUST return 403 Forbidden
    del_res = client.delete(f"/api/v1/deliveries/{order_a_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_res.status_code == 403


def test_customer_tenant_isolation():
    """CRITICAL REGRESSION TEST: Verify customer address book is strictly scoped to merchant_id."""
    import secrets
    token_a = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    
    # Register isolated Merchant B
    email_b = f"customer_tenant_{secrets.token_hex(4)}@postcodelink.ng"
    reg_b = client.post("/api/v1/auth/register", json={
        "full_name": "Isolated Merchant B",
        "email": email_b,
        "password": "PasswordBeta123!",
        "business_name": "Isolated Stores"
    })
    assert reg_b.status_code == 201
    token_b = reg_b.json()["access_token"]

    # Merchant A creates a customer record
    cust_res_a = client.post("/api/v1/customers/", json={
        "full_name": "Exclusive Customer A",
        "phone": "08011112233",
        "email": "cust_a@vip.ng",
        "default_address": "10 Marina Road",
        "area": "Marina",
        "state": "Lagos",
        "postcode": "100001"
    }, headers={"Authorization": f"Bearer {token_a}"})
    assert cust_res_a.status_code == 201
    cust_a_id = cust_res_a.json()["id"]

    # Merchant B lists customers -> Customer A must NOT appear
    list_b = client.get("/api/v1/customers/", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    cust_b_ids = [c["id"] for c in list_b.json()]
    assert cust_a_id not in cust_b_ids

    # Merchant B attempts direct access to Customer A -> MUST return 403 Forbidden
    get_b = client.get(f"/api/v1/customers/{cust_a_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert get_b.status_code == 403

    # Merchant B attempts to delete Customer A -> MUST return 403 Forbidden
    del_b = client.delete(f"/api/v1/customers/{cust_a_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_b.status_code == 403

    # Merchant A can access their own customer
    get_a = client.get(f"/api/v1/customers/{cust_a_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert get_a.status_code == 200
    assert get_a.json()["full_name"] == "Exclusive Customer A"


def test_zero_knowledge_pin_no_raw_pin_in_api_response():
    """CRITICAL REGRESSION TEST: Verify PIN is never returned in any API response or notification payload."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    DISPATCHED_NOTIFICATIONS.clear()

    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Zero Knowledge Recipient",
        "recipient_phone": "08055667788",
        "destination_address": "14 Admiralty Way",
        "destination_area": "Lekki Phase 1",
        "destination_state": "Lagos",
        "postcode_input": "101241",
        "package_description": "Luxury Watch",
        "fee": 5000.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    resp_data = create_res.json()

    # 1. delivery response must NOT have 'otp' or 'delivery_pin'
    deliv = resp_data["delivery"]
    assert "otp" not in deliv
    assert "otp_hash" not in deliv
    assert "delivery_pin" not in deliv

    # 2. notification_dispatch must NOT have 'delivery_pin'
    notif = resp_data["notification_dispatch"]
    assert "delivery_pin" not in notif
    assert "otp" not in notif
    assert notif["status"] == "DISPATCHED"

    # 3. Whole response string must not contain any 6-digit PIN attribute
    assert "pin" not in resp_data["notification_dispatch"]

    # 4. Out-of-band simulated SMS gateway DID receive the notification
    order_id = deliv["id"]
    matching_sms = [s for s in DISPATCHED_NOTIFICATIONS if s["delivery_id"] == order_id]
    assert len(matching_sms) == 1
    assert len(matching_sms[0]["pin"]) == 6
    assert matching_sms[0]["recipient_phone"] == "08055667788"


def test_public_tracking_privacy_and_token():
    """CRITICAL REGRESSION TEST: Verify tracking token works and masks recipient PII."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Chukwudi Nnamdi",
        "recipient_phone": "08034567890",
        "destination_address": "Flat 4, 12 Glover Road, Ikoyi",
        "destination_landmark": "Opposite Golden Gate",
        "destination_area": "Ikoyi",
        "destination_state": "Lagos",
        "postcode_input": "101233",
        "package_description": "Private Documents",
        "fee": 3500.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    deliv = create_res.json()["delivery"]
    order_id = deliv["id"]
    tracking_token = deliv["tracking_token"]

    # Tracking by cryptographically random URL token
    token_track = client.get(f"/api/v1/deliveries/{tracking_token}/tracking")
    assert token_track.status_code == 200
    track_data = token_track.json()

    # 1. Masked Name: 'Chukwudi Nnamdi' -> 'C******* N*****'
    assert track_data["recipient_name_masked"] == "C******* N*****"

    # 2. Masked Phone: '080****7890'
    assert track_data["recipient_phone_masked"] == "080****7890"

    # 3. General Location Only: 'Ikoyi, Lagos'
    assert track_data["destination_general_location"] == "Ikoyi, Lagos"

    # 4. Sensitive internal details MUST NOT exist in public response
    assert "destination_address" not in track_data
    assert "destination_landmark" not in track_data
    assert "lat" not in track_data
    assert "lng" not in track_data
    assert "fee" not in track_data
    assert "package_description" not in track_data
    assert "otp" not in track_data
    assert "otp_hash" not in track_data
    assert "otp_masked" not in track_data

    # Tracking by order_id also works
    id_track = client.get(f"/api/v1/deliveries/{order_id}/tracking")
    assert id_track.status_code == 200
    assert id_track.json()["recipient_name_masked"] == track_data["recipient_name_masked"]


def test_postcode_verification_strictness():
    """Verify exact match, estimated match, and no false fallbacks to 100001."""
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


def test_operator_assignment_idempotency_and_capacity_guard():
    """Verify operator assignment idempotency and capacity limit enforcement (max 15)."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    # Fetch operators
    ops = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {token}"}).json()
    apex_op = next((o for o in ops if "Apex" in o["business_name"]), ops[0])
    op_id = apex_op["id"]

    # Ensure operator starts in clean state with available capacity
    db = SessionLocal()
    try:
        db_op = db.query(Operator).filter(Operator.id == op_id).first()
        if db_op:
            db_op.active_deliveries_count = 3
            db.commit()
    finally:
        db.close()

    # Create delivery
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Capacity Test Recipient",
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

    # 1. First assignment to Apex
    assign1 = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={
        "operator_id": op_id
    }, headers={"Authorization": f"Bearer {token}"})
    assert assign1.status_code == 200

    # Get operator active count
    ops_after1 = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {token}"}).json()
    count1 = next(o for o in ops_after1 if o["id"] == op_id)["active_deliveries_count"]

    # 2. Re-assigning to the SAME operator MUST be idempotent (active_deliveries_count unchanged)
    assign2 = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={
        "operator_id": op_id
    }, headers={"Authorization": f"Bearer {token}"})
    assert assign2.status_code == 200

    ops_after2 = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {token}"}).json()
    count2 = next(o for o in ops_after2 if o["id"] == op_id)["active_deliveries_count"]
    assert count1 == count2, "Operator active count must not double-increment on reassignment"

    # 3. Capacity guard test: Set operator active deliveries to 15 in database
    db = SessionLocal()
    try:
        db_op = db.query(Operator).filter(Operator.id == op_id).first()
        db_op.active_deliveries_count = 15
        db.commit()

        # Create another delivery and try assigning to overloaded operator -> MUST return 400
        create_overload = client.post("/api/v1/deliveries/", json={
            "recipient_name": "Overload Order",
            "recipient_phone": "08033334445",
            "destination_address": "Allen Avenue",
            "destination_area": "Ikeja",
            "destination_state": "Lagos",
            "postcode_input": "100211",
            "package_description": "Hardware",
            "fee": 2500.0
        }, headers={"Authorization": f"Bearer {token}"}).json()
        overload_id = create_overload["delivery"]["id"]

        blocked_assign = client.post(f"/api/v1/deliveries/{overload_id}/assign", json={
            "operator_id": op_id
        }, headers={"Authorization": f"Bearer {token}"})
        assert blocked_assign.status_code == 400
        assert "maximum dispatch capacity" in blocked_assign.json()["detail"]
    finally:
        # Guarantee reset operator active count even if assertions fail
        db_op = db.query(Operator).filter(Operator.id == op_id).first()
        if db_op:
            db_op.active_deliveries_count = 3
            db.commit()
        db.close()


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
    deliv_id = create_res.json()["delivery"]["id"]

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
    DISPATCHED_NOTIFICATIONS.clear()
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

    # Retrieve dispatched PIN from simulated SMS gateway
    sms = next(n for n in reversed(DISPATCHED_NOTIFICATIONS) if n["delivery_id"] == fresh_id)
    fresh_pin = sms["pin"]

    # Verify once -> DELIVERED (200 OK)
    verify1 = client.post(f"/api/v1/deliveries/{fresh_id}/verify-otp", json={
        "otp": fresh_pin
    }, headers={"Authorization": f"Bearer {token}"})
    assert verify1.status_code == 200
    assert verify1.json()["status"] == "delivered"
    assert verify1.json()["pod_verified"] is True

    # Attempt 2 on already delivered order -> MUST fail with 400 (single-use enforced)
    verify2 = client.post(f"/api/v1/deliveries/{fresh_id}/verify-otp", json={
        "otp": fresh_pin
    }, headers={"Authorization": f"Bearer {token}"})
    assert verify2.status_code == 400
    assert "already been verified" in verify2.json()["detail"]


def test_production_config_secret_guard():
    """Verify that Settings validation raises ValueError if running in production with insecure secret."""
    with pytest.raises(ValueError, match="Fatal Security Error"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="postcodelink_dev_secret_key_12345"
        )

    # Valid secret in production passes
    valid_prod_settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a_very_strong_production_secret_key_that_is_at_least_32_chars_long"
    )
    assert valid_prod_settings.ENVIRONMENT == "production"
