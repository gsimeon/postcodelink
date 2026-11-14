"""Comprehensive automated test suite verifying security, tenant isolation, RBAC, and OTP protection."""
import secrets
import httpx
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.config import Settings
from backend.app.database import SessionLocal
from backend.app.models.operator import Operator
from backend.app.services.notification_service import (
    NotificationDispatchResult,
    NotificationDeliveryStatus,
)

from backend.app.routers.auth import LOGIN_ATTEMPTS

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_login_attempts():
    """Ensure clean login attempt tracking between test executions."""
    LOGIN_ATTEMPTS.clear()
    yield
    LOGIN_ATTEMPTS.clear()


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

    h_res = client.get("/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "healthy"
    assert h_res.json()["database"] == "connected"


def test_public_registration_cannot_escalate_to_admin():
    """CRITICAL REGRESSION TEST: Verify public registration strictly locks role to MERCHANT.
    
    Submitting 'role': 'admin' or any other escalated role MUST be ignored or rejected,
    and the created account MUST be MERCHANT only.
    """
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
        "phone": f"080{secrets.randbelow(90000000) + 10000000}",
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

    with patch("backend.app.services.delivery_service.notification_provider.send_delivery_pin") as mock_send:
        mock_send.return_value = NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS Gateway (Local Sandbox)",
            recipient_masked="080****7788",
            provider="simulated",
            message_preview="Notification queued in local environment.",
        )

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
        assert notif["status"] == "SIMULATED"

        # 3. Whole response string must not contain any 6-digit PIN attribute
        assert "pin" not in resp_data["notification_dispatch"]

        # 4. Out-of-band notification provider was called with the PIN
        assert mock_send.called
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["recipient_phone"] == "08055667788"
        assert len(call_kwargs["pin"]) == 6


def test_public_tracking_privacy_and_token_strictness():
    """CRITICAL REGRESSION TEST: Verify tracking token works, delivery ID is rejected, and token can be regenerated."""
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

    # 1. Tracking by cryptographically random URL token SUCCEEDS
    token_track = client.get(f"/api/v1/deliveries/track/{tracking_token}")
    assert token_track.status_code == 200
    track_data = token_track.json()

    # Masked recipient details
    assert track_data["recipient_name_masked"] == "C******* N*****"
    assert track_data["recipient_phone_masked"] == "080****7890"
    assert track_data["destination_general_location"] == "Ikoyi, Lagos"

    # Sensitive details MUST NOT exist
    assert "destination_address" not in track_data
    assert "destination_landmark" not in track_data
    assert "lat" not in track_data
    assert "fee" not in track_data
    assert "package_description" not in track_data

    # 2. Public tracking by human-readable Delivery.id MUST BE REJECTED with 404
    id_track = client.get(f"/api/v1/deliveries/track/{order_id}")
    assert id_track.status_code == 404

    id_track_compat = client.get(f"/api/v1/deliveries/{order_id}/tracking")
    assert id_track_compat.status_code == 404
    assert "tracking token" in id_track_compat.json()["detail"].lower()

    # 3. Token Regeneration: Merchant regenerates token, immediately invalidating old token
    regen_res = client.post(f"/api/v1/deliveries/{order_id}/regenerate-token", headers={"Authorization": f"Bearer {token}"})
    assert regen_res.status_code == 200
    new_token = regen_res.json()["tracking_token"]
    assert new_token != tracking_token

    # Old token now returns 404
    old_track = client.get(f"/api/v1/deliveries/track/{tracking_token}")
    assert old_track.status_code == 404

    # New token works
    new_track = client.get(f"/api/v1/deliveries/track/{new_token}")
    assert new_track.status_code == 200


def test_operator_directory_privacy():
    """CRITICAL REGRESSION TEST: Verify merchants cannot browse private operator phone/GPS data."""
    merchant_token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    admin_token = get_auth_token("admin@postcodelink.ng", "AdminSecure2026!")

    # 1. Merchant lists operators -> Receives restricted OperatorDirectoryResponse
    merchant_ops = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {merchant_token}"})
    assert merchant_ops.status_code == 200
    op_sample = merchant_ops.json()[0]

    # Sensitive fleet fields MUST NOT be present in merchant directory response
    assert "phone" not in op_sample
    assert "current_lat" not in op_sample
    assert "current_lng" not in op_sample
    assert "active_deliveries_count" not in op_sample

    # Public dispatch attributes MUST be present
    assert "business_name" in op_sample
    assert "vehicle_type" in op_sample
    assert "service_areas" in op_sample
    assert "rating" in op_sample
    assert "has_capacity" in op_sample

    # 2. Platform Admin lists operators -> Receives full OperatorResponse
    admin_ops = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_ops.status_code == 200
    admin_sample = admin_ops.json()[0]
    assert "phone" in admin_sample
    assert "active_deliveries_count" in admin_sample


def test_postcode_verification_consistency_and_conflict_detection():
    """Verify exact match, address conflict detection, and no false fallbacks."""
    # 1. Exact match with consistent area -> verified
    res_exact = client.post("/api/v1/postcodes/cleanse", json={
        "address": "14 Admiralty Way",
        "area": "Lekki Phase 1",
        "state": "Lagos",
        "postcode": "105102"
    })
    assert res_exact.status_code == 200
    data_exact = res_exact.json()
    assert data_exact["postcode_status"] == "verified"
    assert data_exact["postcode_valid"] is True
    assert data_exact["address_consistent"] is True
    assert data_exact["dispatch_confidence"] >= 0.90

    # 2. Postcode 105102 (Lekki Phase 1) with CONFLICTING area "Ikeja" -> conflict
    res_conflict = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Obafemi Awolowo Way",
        "area": "Ikeja",
        "state": "Lagos",
        "postcode": "105102"  # Mismatched code for Lekki, not Ikeja!
    })
    assert res_conflict.status_code == 200
    data_conflict = res_conflict.json()
    assert data_conflict["postcode_valid"] is True
    assert data_conflict["address_consistent"] is False
    assert data_conflict["postcode_status"] == "conflict"
    assert data_conflict["dispatch_confidence"] < 0.60

    # 3. Unknown location -> unverified, zero fallback to 100001
    res_unver = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Random farm cottage near thick bushes",
        "area": "Farm Area",
        "state": "Ogun"
    })
    assert res_unver.status_code == 200
    data_unver = res_unver.json()
    assert data_unver["postcode_status"] == "unverified"
    assert data_unver["postcode"] == ""
    assert data_unver["postcode_valid"] is False
    assert data_unver["dispatch_confidence"] == 0.0


def test_delivery_status_role_permission_matrix_and_counter_accounting():
    """CRITICAL REGRESSION TEST: Verify complete transition permissions and atomic counter adjustments."""
    merchant_token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    admin_token = get_auth_token("admin@postcodelink.ng", "AdminSecure2026!")

    # Create delivery
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "State Matrix Recipient",
        "recipient_phone": "08033334444",
        "destination_address": "Obafemi Awolowo Way",
        "destination_area": "Ikeja",
        "destination_state": "Lagos",
        "postcode_input": "100211",
        "package_description": "Electronics",
        "fee": 2500.0
    }, headers={"Authorization": f"Bearer {merchant_token}"})
    assert create_res.status_code == 201
    deliv_id = create_res.json()["delivery"]["id"]

    ops = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {admin_token}"}).json()
    apex_op = next((o for o in ops if "Apex" in o["business_name"]), ops[0])
    op_id = apex_op["id"]
    initial_active = apex_op["active_deliveries_count"]

    # 1. Assign to Apex operator -> active count + 1
    assign_res = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert assign_res.status_code == 200

    op_check1 = client.get(f"/api/v1/operators/{op_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert op_check1["active_deliveries_count"] == initial_active + 1

    # 2. Unassign back to PENDING by merchant -> active count - 1, operator_id set to None
    unassign_res = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "pending"}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert unassign_res.status_code == 200
    assert unassign_res.json()["operator_id"] is None

    op_check2 = client.get(f"/api/v1/operators/{op_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert op_check2["active_deliveries_count"] == initial_active

    # Re-assign for remaining tests
    client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {merchant_token}"})

    # 3. Merchant CANNOT move to IN_TRANSIT (Only courier or admin can)
    bad_transit = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "in_transit"}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert bad_transit.status_code == 403

    # 4. Merchant CANNOT arbitrarily mark FAILED (Only courier or admin can)
    bad_fail = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "failed"}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert bad_fail.status_code == 403

    # 5. Assigned Courier/Admin advances to PICKED_UP then IN_TRANSIT
    step1 = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "picked_up"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert step1.status_code == 200
    step2 = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "in_transit"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert step2.status_code == 200

    # 6. Merchant CANNOT cancel an order already in transit
    bad_cancel = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "cancelled"}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert bad_cancel.status_code == 403
    assert "in transit" in bad_cancel.json()["detail"].lower()

    # 7. Courier/Admin reports failure -> active count decremented
    fail_res = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "failed", "note": "Customer phone switched off"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert fail_res.status_code == 200

    op_check3 = client.get(f"/api/v1/operators/{op_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert op_check3["active_deliveries_count"] == initial_active


def test_analytics_tenant_scoping():
    """CRITICAL REGRESSION TEST: Verify analytics metrics are strictly tenant-isolated."""
    token_a = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    # Register isolated Merchant B
    email_b = f"analytics_merchant_{secrets.token_hex(4)}@postcodelink.ng"
    reg_b = client.post("/api/v1/auth/register", json={
        "full_name": "Analytics Merchant B",
        "email": email_b,
        "password": "PasswordBeta123!",
        "business_name": "Analytics B Enterprise"
    })
    token_b = reg_b.json()["access_token"]

    # Merchant B creates 1 delivery
    client.post("/api/v1/deliveries/", json={
        "recipient_name": "B Customer",
        "recipient_phone": "08012341234",
        "destination_address": "Allen Avenue",
        "destination_area": "Ikeja",
        "destination_state": "Lagos",
        "postcode_input": "100211",
        "package_description": "Goods",
        "fee": 5000.0
    }, headers={"Authorization": f"Bearer {token_b}"})

    # Merchant B creates 1 customer
    client.post("/api/v1/customers/", json={
        "full_name": "Customer of B Only",
        "phone": f"080{secrets.randbelow(90000000) + 10000000}",
        "default_address": "Allen Avenue",
        "area": "Ikeja",
        "state": "Lagos"
    }, headers={"Authorization": f"Bearer {token_b}"})

    # Analytics for Merchant B: total_deliveries = 1, total_customers = 1
    analytics_b = client.get("/api/v1/analytics/overview", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert analytics_b["total_deliveries"] == 1
    assert analytics_b["total_customers"] == 1
    assert analytics_b["total_revenue_ngn"] == 5000.0

    # Analytics for Fleet Rider (Operator role): Commercial revenue and customer book MUST BE HIDDEN
    rider_token = get_auth_token("rider@postcodelink.ng", "RiderPass123!")
    analytics_rider = client.get("/api/v1/analytics/overview", headers={"Authorization": f"Bearer {rider_token}"}).json()
    assert analytics_rider["total_customers"] == 0
    assert analytics_rider["total_revenue_ngn"] == 0.0


def test_operator_assignment_idempotency_and_capacity_guard():
    """Verify operator assignment idempotency and capacity limit enforcement (max 15)."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    admin_token = get_auth_token("admin@postcodelink.ng", "AdminSecure2026!")

    # Fetch operators
    ops = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {admin_token}"}).json()
    apex_op = next((o for o in ops if "Apex" in o["business_name"]), ops[0])
    op_id = apex_op["id"]

    # Reset operator active count to clean state
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

    ops_after1 = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {admin_token}"}).json()
    count1 = next(o for o in ops_after1 if o["id"] == op_id)["active_deliveries_count"]

    # 2. Re-assigning to the SAME operator MUST be idempotent (active_deliveries_count unchanged)
    assign2 = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={
        "operator_id": op_id
    }, headers={"Authorization": f"Bearer {token}"})
    assert assign2.status_code == 200

    ops_after2 = client.get("/api/v1/operators/", headers={"Authorization": f"Bearer {admin_token}"}).json()
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
        # Guarantee reset operator active count
        db_op = db.query(Operator).filter(Operator.id == op_id).first()
        if db_op:
            db_op.active_deliveries_count = 3
            db.commit()
        db.close()


def test_otp_verification_lockout_and_single_use():
    """Verify 3-attempt brute force lockout and single-use enforcement."""
    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    admin_token = get_auth_token("admin@postcodelink.ng", "AdminSecure2026!")

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

    # 1. Strict Stage Verification: Attempting verify-otp on PENDING order MUST fail with 409
    early_verify = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "123456"
    }, headers={"Authorization": f"Bearer {token}"})
    assert early_verify.status_code == 409
    assert "out for delivery" in early_verify.json()["detail"].lower()

    # Create & assign operator, then advance order to OUT_FOR_DELIVERY
    op_res = client.post("/api/v1/operators/", json={
        "business_name": "Stage Test Courier",
        "phone": "+2348077771111",
        "vehicle_type": "motorcycle",
        "service_areas": ["Lagos"],
        "max_capacity": 10
    }, headers={"Authorization": f"Bearer {admin_token}"}).json()
    op_id = op_res["id"]

    asgn = client.post(f"/api/v1/deliveries/{deliv_id}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {token}"})
    assert asgn.status_code == 200
    p1 = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "picked_up"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert p1.status_code == 200
    p2 = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "in_transit"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert p2.status_code == 200
    p3 = client.post(f"/api/v1/deliveries/{deliv_id}/status", json={"new_status": "out_for_delivery"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert p3.status_code == 200

    # Attempt 1: Wrong PIN on OUT_FOR_DELIVERY
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
    with patch("backend.app.services.delivery_service.notification_provider.send_delivery_pin") as mock_send:
        mock_send.return_value = NotificationDispatchResult(
            status=NotificationDeliveryStatus.SIMULATED,
            channel="Simulated SMS",
            recipient_masked="080****0000",
            provider="simulated",
            message_preview="PIN dispatched",
        )
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
        fresh_pin = mock_send.call_args.kwargs["pin"]

    # Advance fresh order to OUT_FOR_DELIVERY
    client.post(f"/api/v1/deliveries/{fresh_id}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {token}"})
    client.post(f"/api/v1/deliveries/{fresh_id}/status", json={"new_status": "picked_up"}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post(f"/api/v1/deliveries/{fresh_id}/status", json={"new_status": "in_transit"}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post(f"/api/v1/deliveries/{fresh_id}/status", json={"new_status": "out_for_delivery"}, headers={"Authorization": f"Bearer {admin_token}"})

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


def test_termii_notification_provider_http_dispatch():
    """Verify Termii SMS provider handles HTTP 200, API errors, and network timeouts accurately."""
    from backend.app.services.notification_service import (
        TermiiNotificationProvider,
        NotificationDeliveryStatus,
    )

    provider = TermiiNotificationProvider(api_key="test_termii_key_123", sender_id="PostcodeLnk")

    # 1. Success case: Termii returns {"code": "ok", "message_id": "998877"}
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"code": "ok", "message_id": "998877"}'
        mock_resp.json.return_value = {"code": "ok", "message_id": "998877"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        res = provider.send_delivery_pin("08012345678", "Amina Bello", "PL-2026-TEST", "456789")
        assert res.status == NotificationDeliveryStatus.SENT
        assert res.provider == "termii"
        assert res.recipient_masked == "080****5678"

    # 2. Rejection case: Termii returns HTTP 200 with error payload
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"message": "Insufficient wallet balance"}'
        mock_resp.json.return_value = {"message": "Insufficient wallet balance"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        res = provider.send_delivery_pin("08012345678", "Amina Bello", "PL-2026-TEST", "456789")
        assert res.status == NotificationDeliveryStatus.FAILED
        assert "Insufficient wallet balance" in (res.error_details or "")

    # 3. Network timeout case: httpx raises TimeoutException
    with patch("httpx.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out after 10.0s")

        res = provider.send_delivery_pin("08012345678", "Amina Bello", "PL-2026-TEST", "456789")
        assert res.status == NotificationDeliveryStatus.FAILED
        assert "timed out" in (res.error_details or "").lower()


def test_twilio_notification_provider_http_dispatch():
    """Verify Twilio provider handles HTTP 201 Created and HTTP errors accurately."""
    from backend.app.services.notification_service import (
        TwilioNotificationProvider,
        NotificationDeliveryStatus,
    )

    provider = TwilioNotificationProvider(
        account_sid="AC_test_account_sid",
        auth_token="auth_token_xyz",
        from_number="+1234567890"
    )

    # 1. Success case: Twilio returns HTTP 201 Created
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"sid": "SM12345", "status": "queued"}'
        mock_resp.json.return_value = {"sid": "SM12345", "status": "queued"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        res = provider.send_delivery_pin("+2348012345678", "Amina Bello", "PL-2026-TEST", "654321")
        assert res.status == NotificationDeliveryStatus.SENT
        assert res.provider == "twilio"

    # 2. Failure case: Twilio returns HTTP 400 Bad Request
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("400 Bad Request", request=MagicMock(), response=mock_resp)
        mock_post.return_value = mock_resp

        res = provider.send_delivery_pin("+2348012345678", "Amina Bello", "PL-2026-TEST", "654321")
        assert res.status == NotificationDeliveryStatus.FAILED
        assert "400" in (res.error_details or "")


def test_notification_outbox_persistence_and_retry():
    """Verify notification outbox records are created in DB and process_notification_outbox retries them."""
    from backend.app.models.notification_outbox import NotificationOutbox
    from backend.app.services.delivery_service import process_notification_outbox
    from backend.app.services.notification_service import NotificationDeliveryStatus

    token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")
    create_res = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Outbox Recipient",
        "recipient_phone": "08012344321",
        "destination_address": "45 Broad St, Lagos Island",
        "destination_area": "Lagos Island",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Documents",
        "fee": 2500.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    deliv_id = create_res.json()["delivery"]["id"]

    db = SessionLocal()
    try:
        outbox_entry = db.query(NotificationOutbox).filter(NotificationOutbox.delivery_id == deliv_id).first()
        assert outbox_entry is not None
        assert outbox_entry.delivery_id == deliv_id
        assert outbox_entry.status in [NotificationDeliveryStatus.SIMULATED, NotificationDeliveryStatus.SENT]
        assert outbox_entry.recipient_phone == "08012344321"

        # Manually set to FAILED to test the outbox processor retry
        outbox_entry.status = NotificationDeliveryStatus.FAILED
        outbox_entry.retry_count = 0
        db.commit()

        processed = process_notification_outbox(db, max_items=5)
        assert processed >= 1

        db.refresh(outbox_entry)
        assert outbox_entry.retry_count == 1
    finally:
        db.close()


def test_operator_workload_counter_no_double_decrement_on_failed_to_cancelled():
    """Verify that moving FAILED -> CANCELLED does NOT decrement active_deliveries_count a second time."""
    admin_token = get_auth_token("admin@postcodelink.ng", "AdminSecure2026!")
    merchant_token = get_auth_token("dispatch@postcodelink.ng", "MerchantPass123!")

    # 1. Create operator with multiple active deliveries
    op_res = client.post("/api/v1/operators/", json={
        "business_name": "Multi-Trip Logistics",
        "phone": "+2348098765432",
        "vehicle_type": "van",
        "service_areas": ["Lagos", "Ikoyi"],
        "max_capacity": 10
    }, headers={"Authorization": f"Bearer {admin_token}"}).json()
    op_id = op_res["id"]
    initial_active = op_res["active_deliveries_count"]

    # 2. Create 2 orders and assign to operator -> active count = initial + 2
    order1 = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Trip 1",
        "recipient_phone": "08011112222",
        "destination_address": "1 First Ave",
        "destination_area": "Ikoyi",
        "destination_state": "Lagos",
        "postcode_input": "101233",
        "package_description": "Order 1",
        "fee": 2500.0
    }, headers={"Authorization": f"Bearer {merchant_token}"}).json()["delivery"]["id"]

    order2 = client.post("/api/v1/deliveries/", json={
        "recipient_name": "Trip 2",
        "recipient_phone": "08033334444",
        "destination_address": "2 Second Ave",
        "destination_area": "Ikoyi",
        "destination_state": "Lagos",
        "postcode_input": "101233",
        "package_description": "Order 2",
        "fee": 2500.0
    }, headers={"Authorization": f"Bearer {merchant_token}"}).json()["delivery"]["id"]

    asgn1 = client.post(f"/api/v1/deliveries/{order1}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert asgn1.status_code == 200, asgn1.text
    asgn2 = client.post(f"/api/v1/deliveries/{order2}/assign", json={"operator_id": op_id}, headers={"Authorization": f"Bearer {merchant_token}"})
    assert asgn2.status_code == 200, asgn2.text

    op_check1 = client.get(f"/api/v1/operators/{op_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert op_check1["active_deliveries_count"] == initial_active + 2

    # 3. Advance order1 to PICKED_UP then FAILED -> count decrements by 1 (to initial + 1)
    client.post(f"/api/v1/deliveries/{order1}/status", json={"new_status": "picked_up"}, headers={"Authorization": f"Bearer {admin_token}"})
    client.post(f"/api/v1/deliveries/{order1}/status", json={"new_status": "failed", "note": "Customer unreachable"}, headers={"Authorization": f"Bearer {admin_token}"})

    op_check2 = client.get(f"/api/v1/operators/{op_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert op_check2["active_deliveries_count"] == initial_active + 1

    # 4. Now transition order1 from FAILED -> CANCELLED
    # CRITICAL TEST: Active count MUST NOT be decremented again! It must remain initial_active + 1
    client.post(f"/api/v1/deliveries/{order1}/status", json={"new_status": "cancelled", "note": "Cancelled after failed delivery"}, headers={"Authorization": f"Bearer {admin_token}"})

    op_check3 = client.get(f"/api/v1/operators/{op_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert op_check3["active_deliveries_count"] == initial_active + 1, (
        f"Double decrement bug detected! Expected {initial_active + 1}, got {op_check3['active_deliveries_count']}"
    )


def test_postcode_conflict_detection_when_conflicting_area_is_in_address_text():
    """Verify that a conflicting area in area_hint AND in address text is flagged as CONFLICT."""
    # User provides Lekki Phase 1 postcode 105102, but says area is Ikeja and address includes Ikeja
    cleanse_res = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Plot 12 Commercial Avenue, Ikeja, Lagos",
        "area": "Ikeja",
        "postcode": "105102",  # 105102 is Lekki Phase 1, NOT Ikeja!
        "state": "Lagos"
    }).json()

    # Must be marked CONFLICT, confidence lowered, address_consistent False
    assert cleanse_res["postcode_status"] == "conflict"
    assert cleanse_res["address_consistent"] is False
    assert cleanse_res["confidence"] <= 0.50
    assert cleanse_res["dispatch_confidence"] <= 0.50


def test_login_rate_limiting_lockout():
    """Verify that repeated failed login attempts trigger HTTP 429 lockout."""
    target_email = "lockout_victim@postcodelink.ng"
    # First register user
    client.post("/api/v1/auth/register", json={
        "full_name": "Rate Limit Target",
        "email": target_email,
        "password": "ValidPassword123!"
    })

    # Attempt 1-4: Invalid password -> 401 Unauthorized
    for i in range(4):
        resp = client.post("/api/v1/auth/login", json={
            "email": target_email,
            "password": f"WrongPass{i}"
        })
        assert resp.status_code == 401
        assert "attempt(s) remaining" in resp.json()["detail"]

    # Attempt 5: 5th failure -> triggers 429 lockout
    resp5 = client.post("/api/v1/auth/login", json={
        "email": target_email,
        "password": "WrongPass5"
    })
    assert resp5.status_code == 429
    assert "locked" in resp5.json()["detail"].lower()

    # Attempt 6: Even with correct password, locked out with 429
    resp6 = client.post("/api/v1/auth/login", json={
        "email": target_email,
        "password": "ValidPassword123!"
    })
    assert resp6.status_code == 429


def test_national_postcode_coverage_eleven_states():
    """Verify that the official postcode directory covers all 11 Nigerian states."""
    expected_states = [
        "Lagos", "Abuja FCT", "Rivers", "Oyo", "Ogun",
        "Kano", "Kaduna", "Enugu", "Delta", "Edo", "Anambra"
    ]
    for st in expected_states:
        res = client.get(f"/api/v1/postcodes/lookup?state={st}")
        assert res.status_code == 200
        records = res.json()["matches"]
        assert len(records) >= 1, f"No postcode records found for state {st}"
        assert any(st.lower() in r["state"].lower() for r in records)

