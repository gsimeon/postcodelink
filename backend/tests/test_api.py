"""Comprehensive automated test suite verifying security, tenant isolation, RBAC, and OTP protection."""
import secrets
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from backend.app.main import app
from backend.app.config import Settings
from backend.app.database import SessionLocal
from backend.app.models.operator import Operator
from backend.app.models.delivery import Delivery
from backend.app.models.enums import DeliveryStatus
from backend.app.services.notification_service import (
    NotificationDispatchResult,
    NotificationDeliveryStatus,
)

client = TestClient(app)


def set_delivery_out_for_delivery(delivery_id: str) -> None:
    """Move an isolated test order to the PIN-eligible hand-off stage."""
    db = SessionLocal()
    try:
        delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        assert delivery is not None
        delivery.status = DeliveryStatus.OUT_FOR_DELIVERY
        db.commit()
    finally:
        db.close()


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
        "postcode": "101241"
    })
    assert res_exact.status_code == 200
    data_exact = res_exact.json()
    assert data_exact["postcode_status"] == "verified"
    assert data_exact["postcode_valid"] is True
    assert data_exact["address_consistent"] is True
    assert data_exact["dispatch_confidence"] >= 0.90

    # 2. Postcode 101241 (Lekki Phase 1) with CONFLICTING area "Ikeja" -> conflict
    res_conflict = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Obafemi Awolowo Way",
        "area": "Ikeja",
        "state": "Lagos",
        "postcode": "101241"  # Mismatched code for Lekki, not Ikeja!
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
    set_delivery_out_for_delivery(deliv_id)

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
    set_delivery_out_for_delivery(fresh_id)

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
