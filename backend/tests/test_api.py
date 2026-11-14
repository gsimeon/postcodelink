"""Automated test suite for FastAPI backend endpoints."""
import pytest
from starlette.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_root_and_health():
    """Verify system status and database health check."""
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "operational"
    assert data["version"] == "1.0.0"

    h_res = client.get("/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "healthy"
    assert h_res.json()["database"] == "connected"


def test_postcode_lookup():
    """Verify official Nigerian postcode search."""
    # Search Ikeja in Lagos
    res = client.get("/api/v1/postcodes/lookup?state=Lagos&area=Ikeja")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    codes = [m["code"] for m in data["matches"]]
    assert "100211" in codes


def test_address_cleanser_verified():
    """Verify that a valid Nigerian address gets recognized and linked to NIPOST code."""
    res = client.post("/api/v1/postcodes/cleanse", json={
        "address": "Plot 12 Alausa Secretariat Way",
        "state": "Lagos"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["postcode_status"] == "verified"
    assert data["postcode"] == "100271"
    assert data["area"] == "Alausa"
    assert data["confidence"] > 0.9


def test_delivery_creation_and_lifecycle():
    """Verify delivery creation, reference generation, and state transitions."""
    payload = {
        "recipient_name": "Tunde Bakare",
        "recipient_phone": "08099887766",
        "destination_address": "25 Marina Street",
        "destination_landmark": "Next to Central Bank",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Legal Contract Documents",
        "fee": 3000.0,
        "pickup_address": "Ikeja Dispatch Hub"
    }
    create_res = client.post("/api/v1/deliveries/", json=payload)
    assert create_res.status_code == 201
    delivery = create_res.json()
    
    assert delivery["id"].startswith("PL-2026-")
    assert delivery["status"] == "pending"
    assert delivery["postcode_status"] == "verified"
    assert delivery["verified_postcode"] == "100001"
    assert len(delivery["otp"]) == 6
    assert len(delivery["events"]) >= 1

    delivery_id = delivery["id"]

    # 1. Invalid status jump: pending directly to delivered should fail
    bad_jump = client.post(f"/api/v1/deliveries/{delivery_id}/status", json={
        "new_status": "delivered",
        "actor_name": "Rogue Courier"
    })
    assert bad_jump.status_code == 400

    # 2. Assign operator
    ops_res = client.get("/api/v1/operators/")
    assert ops_res.status_code == 200
    operators = ops_res.json()
    assert len(operators) > 0
    chosen_operator = operators[0]["id"]

    assign_res = client.post(f"/api/v1/deliveries/{delivery_id}/assign", json={
        "operator_id": chosen_operator,
        "actor_name": "Lead Dispatcher"
    })
    assert assign_res.status_code == 200
    assert assign_res.json()["status"] == "assigned"
    assert assign_res.json()["operator_id"] == chosen_operator

    # 3. Pick up
    pickup_res = client.post(f"/api/v1/deliveries/{delivery_id}/status", json={
        "new_status": "picked_up",
        "actor_name": "Rider 1",
        "actor_role": "operator"
    })
    assert pickup_res.status_code == 200
    assert pickup_res.json()["status"] == "picked_up"

    # 4. In transit
    transit_res = client.post(f"/api/v1/deliveries/{delivery_id}/status", json={
        "new_status": "in_transit",
        "actor_name": "Rider 1",
        "actor_role": "operator"
    })
    assert transit_res.status_code == 200

    # 5. Out for delivery
    out_res = client.post(f"/api/v1/deliveries/{delivery_id}/status", json={
        "new_status": "out_for_delivery",
        "actor_name": "Rider 1",
        "actor_role": "operator"
    })
    assert out_res.status_code == 200
    assert out_res.json()["status"] == "out_for_delivery"


def test_public_tracking_masks_otp():
    """Verify that the public tracking endpoint masks the OTP and recipient phone."""
    # Fetch existing delivery
    list_res = client.get("/api/v1/deliveries/")
    deliveries = list_res.json()
    assert len(deliveries) > 0
    target_id = deliveries[0]["id"]

    track_res = client.get(f"/api/v1/deliveries/{target_id}/tracking")
    assert track_res.status_code == 200
    tracking = track_res.json()

    # Verify sensitive data is masked
    assert tracking["otp_masked"].startswith("***")
    assert "****" in tracking["recipient_phone_masked"]
    assert "events" in tracking


def test_otp_verification_and_lockout():
    """Verify PIN confirmation with 3-attempt limit and lockout."""
    # Create test delivery
    payload = {
        "recipient_name": "Lockout Test User",
        "recipient_phone": "08011223344",
        "destination_address": "10 Broad Street",
        "destination_area": "Marina",
        "destination_state": "Lagos",
        "postcode_input": "100001",
        "package_description": "Test Package",
        "fee": 2000.0
    }
    deliv = client.post("/api/v1/deliveries/", json=payload).json()
    deliv_id = deliv["id"]
    correct_otp = deliv["otp"]

    # Attempt 1: Wrong PIN
    try1 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "000000",
        "recipient_phone": "08011223344"
    })
    assert try1.status_code == 400
    assert "2 attempt(s) remaining" in try1.json()["detail"]

    # Attempt 2: Wrong PIN
    try2 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "000001",
        "recipient_phone": "08011223344"
    })
    assert try2.status_code == 400
    assert "1 attempt(s) remaining" in try2.json()["detail"]

    # Attempt 3: Wrong PIN -> Trigger Lockout
    try3 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": "000002",
        "recipient_phone": "08011223344"
    })
    assert try3.status_code == 429
    assert "locked for 15 minutes" in try3.json()["detail"]

    # Attempt 4 (even with correct PIN): should remain locked
    try4 = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": correct_otp,
        "recipient_phone": "08011223344"
    })
    assert try4.status_code == 429
    assert "locked" in try4.json()["detail"]


def test_otp_verification_success():
    """Verify successful OTP verification marks order DELIVERED."""
    payload = {
        "recipient_name": "Success Test User",
        "recipient_phone": "08077665544",
        "destination_address": "15 Isaac John Street",
        "destination_area": "Ikeja",
        "destination_state": "Lagos",
        "postcode_input": "100211",
        "package_description": "Earphones",
        "fee": 1500.0
    }
    deliv = client.post("/api/v1/deliveries/", json=payload).json()
    deliv_id = deliv["id"]
    correct_otp = deliv["otp"]

    verify_res = client.post(f"/api/v1/deliveries/{deliv_id}/verify-otp", json={
        "otp": correct_otp,
        "recipient_phone": "08077665544",
        "note": "Package received in good condition"
    })
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "delivered"
    assert verify_res.json()["pod_verified"] is True

