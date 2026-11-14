"""Database seed script populating authentic Nigerian logistics, postcode, and courier data."""
import logging
from datetime import datetime, timezone, timedelta
from backend.app.database import engine, SessionLocal, Base
from backend.app.models.profile import Profile
from backend.app.models.operator import Operator
from backend.app.models.customer import Customer
from backend.app.models.delivery import Delivery
from backend.app.models.delivery_event import DeliveryEvent
from backend.app.models.postcode import PostcodeDirectory
from backend.app.models.enums import DeliveryStatus, PostcodeStatus, AppRole, VehicleType
from backend.app.services.postcode_service import OFFICIAL_POSTCODES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")


def seed_database():
    """Initializes tables and seeds base records."""
    logger.info("Creating database tables if not exist...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Seed Postcodes
        existing_pc = db.query(PostcodeDirectory).count()
        if existing_pc == 0:
            logger.info("Seeding official Nigerian postcode directory...")
            for pc in OFFICIAL_POSTCODES:
                db_pc = PostcodeDirectory(
                    code=pc["code"],
                    area=pc["area"],
                    state=pc["state"],
                    lga=pc.get("lga"),
                    lat=pc.get("lat"),
                    lng=pc.get("lng"),
                    is_active=True
                )
                db.add(db_pc)
            db.commit()
            logger.info(f"Seeded {len(OFFICIAL_POSTCODES)} postcodes.")

        # 2. Seed Default Merchant Profile
        merchant = db.query(Profile).filter(Profile.email == "dispatch@postcodelink.ng").first()
        if not merchant:
            logger.info("Seeding default merchant profile...")
            merchant = Profile(
                full_name="Babatunde Adeleke",
                role=AppRole.MERCHANT,
                phone="+2348023456789",
                email="dispatch@postcodelink.ng",
                business_name="Lagos Gadget Hub & Fulfillment"
            )
            db.add(merchant)
            db.commit()
            db.refresh(merchant)

        # 3. Seed Courier Operators
        existing_ops = db.query(Operator).count()
        if existing_ops == 0:
            logger.info("Seeding courier fleet operators...")
            operators_data = [
                {
                    "business_name": "Apex Express Dispatch",
                    "phone": "+2348031122334",
                    "vehicle_type": VehicleType.MOTORCYCLE,
                    "service_areas": ["Ikeja", "Alausa", "Ogba", "Maryland"],
                    "is_available": True,
                    "rating": 4.9,
                    "completed_deliveries": 342,
                    "active_deliveries_count": 2,
                    "current_lat": 6.5960,
                    "current_lng": 3.3444,
                },
                {
                    "business_name": "Island Swift Couriers",
                    "phone": "+2348058899001",
                    "vehicle_type": VehicleType.MOTORCYCLE,
                    "service_areas": ["Victoria Island", "Ikoyi", "Lekki Phase 1", "Marina"],
                    "is_available": True,
                    "rating": 4.8,
                    "completed_deliveries": 510,
                    "active_deliveries_count": 1,
                    "current_lat": 6.4281,
                    "current_lng": 3.4219,
                },
                {
                    "business_name": "Mainland Cargo Van Logistics",
                    "phone": "+2348094455667",
                    "vehicle_type": VehicleType.VAN,
                    "service_areas": ["Yaba", "Surulere", "Festac Town", "Gbagada"],
                    "is_available": True,
                    "rating": 4.7,
                    "completed_deliveries": 189,
                    "active_deliveries_count": 0,
                    "current_lat": 6.5095,
                    "current_lng": 3.3711,
                },
            ]
            for op in operators_data:
                db_op = Operator(**op)
                db.add(db_op)
            db.commit()

        # 4. Seed Customers
        existing_cust = db.query(Customer).count()
        if existing_cust == 0:
            logger.info("Seeding customer address book...")
            customers_data = [
                {
                    "full_name": "Chioma Nwosu",
                    "phone": "08034567890",
                    "email": "chioma.nwosu@example.com",
                    "default_address": "14 Admiralty Way",
                    "area": "Lekki Phase 1",
                    "state": "Lagos",
                    "postcode": "101241",
                    "total_orders": 8,
                },
                {
                    "full_name": "Emeka Okafor",
                    "phone": "08023456781",
                    "email": "emeka.o@example.com",
                    "default_address": "28 Isaac John Street, GRA",
                    "area": "Ikeja",
                    "state": "Lagos",
                    "postcode": "100211",
                    "total_orders": 14,
                },
                {
                    "full_name": "Amina Bello",
                    "phone": "08081234567",
                    "email": "amina.b@example.com",
                    "default_address": "5 Broad Street",
                    "area": "Marina",
                    "state": "Lagos",
                    "postcode": "100001",
                    "total_orders": 4,
                },
            ]
            for c in customers_data:
                db.add(Customer(**c))
            db.commit()

        # 5. Seed Deliveries
        existing_del = db.query(Delivery).count()
        if existing_del == 0:
            logger.info("Seeding delivery records...")
            op1 = db.query(Operator).filter(Operator.business_name.like("%Apex%")).first()
            op2 = db.query(Operator).filter(Operator.business_name.like("%Island%")).first()

            now = datetime.now(timezone.utc)
            sample_deliveries = [
                {
                    "id": "PL-2026-A1098B",
                    "merchant_id": merchant.id if merchant else None,
                    "operator_id": op1.id if op1 else None,
                    "recipient_name": "Emeka Okafor",
                    "recipient_phone": "08023456781",
                    "destination_address": "28 Isaac John Street, GRA",
                    "destination_landmark": "Opposite Radisson Blu",
                    "destination_area": "Ikeja",
                    "destination_state": "Lagos",
                    "postcode_input": "100211",
                    "postcode_status": PostcodeStatus.VERIFIED,
                    "verified_postcode": "100211",
                    "package_description": "HP Envy 15 Laptop & Accessories",
                    "fee": 3500.0,
                    "pickup_address": "Computer Village Plaza, Ikeja",
                    "status": DeliveryStatus.OUT_FOR_DELIVERY,
                    "lat": 6.5960,
                    "lng": 3.3444,
                    "otp": "482910",
                    "otp_attempts": 0,
                    "otp_max_attempts": 3,
                    "pod_verified": False,
                    "created_at": now - timedelta(hours=3),
                    "updated_at": now - timedelta(minutes=25),
                },
                {
                    "id": "PL-2026-B8712C",
                    "merchant_id": merchant.id if merchant else None,
                    "operator_id": op2.id if op2 else None,
                    "recipient_name": "Chioma Nwosu",
                    "recipient_phone": "08034567890",
                    "destination_address": "14 Admiralty Way",
                    "destination_landmark": "Beside IMAX Cinema",
                    "destination_area": "Lekki Phase 1",
                    "destination_state": "Lagos",
                    "postcode_input": "101241",
                    "postcode_status": PostcodeStatus.VERIFIED,
                    "verified_postcode": "101241",
                    "package_description": "Sony WH-1000XM5 Headphones",
                    "fee": 2800.0,
                    "pickup_address": "Lagos Central Hub, Alausa",
                    "status": DeliveryStatus.DELIVERED,
                    "lat": 6.4474,
                    "lng": 3.4723,
                    "otp": "912384",
                    "otp_attempts": 0,
                    "otp_max_attempts": 3,
                    "pod_verified": True,
                    "pod_note": "Handed directly to recipient at gatehouse.",
                    "created_at": now - timedelta(hours=6),
                    "updated_at": now - timedelta(hours=1),
                },
                {
                    "id": "PL-2026-C4409D",
                    "merchant_id": merchant.id if merchant else None,
                    "operator_id": None,
                    "recipient_name": "Amina Bello",
                    "recipient_phone": "08081234567",
                    "destination_address": "5 Broad Street",
                    "destination_landmark": "Near CMS Bus Stop",
                    "destination_area": "Marina",
                    "destination_state": "Lagos",
                    "postcode_input": "100001",
                    "postcode_status": PostcodeStatus.VERIFIED,
                    "verified_postcode": "100001",
                    "package_description": "Documents & Security Token",
                    "fee": 2200.0,
                    "pickup_address": "Lagos Central Hub, Alausa",
                    "status": DeliveryStatus.PENDING,
                    "lat": 6.4531,
                    "lng": 3.3958,
                    "otp": "730192",
                    "otp_attempts": 0,
                    "otp_max_attempts": 3,
                    "pod_verified": False,
                    "created_at": now - timedelta(minutes=45),
                    "updated_at": now - timedelta(minutes=45),
                },
            ]

            for d_data in sample_deliveries:
                deliv = Delivery(**d_data)
                db.add(deliv)
                db.flush()

                # Add initial event
                e1 = DeliveryEvent(
                    delivery_id=deliv.id,
                    status=DeliveryStatus.PENDING,
                    actor_name="Merchant Admin",
                    actor_role="merchant",
                    note="Order placed and registered in dispatch queue.",
                    occurred_at=deliv.created_at,
                )
                db.add(e1)

                if deliv.status in [DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.DELIVERED]:
                    e2 = DeliveryEvent(
                        delivery_id=deliv.id,
                        status=DeliveryStatus.ASSIGNED,
                        actor_name="Dispatch Coordinator",
                        actor_role="dispatcher",
                        note="Assigned to courier fleet rider.",
                        occurred_at=deliv.created_at + timedelta(minutes=20),
                    )
                    e3 = DeliveryEvent(
                        delivery_id=deliv.id,
                        status=DeliveryStatus.OUT_FOR_DELIVERY,
                        actor_name="Fleet Rider",
                        actor_role="operator",
                        note="Package out for last-mile delivery to recipient.",
                        occurred_at=deliv.created_at + timedelta(hours=1),
                    )
                    db.add_all([e2, e3])

                if deliv.status == DeliveryStatus.DELIVERED:
                    e4 = DeliveryEvent(
                        delivery_id=deliv.id,
                        status=DeliveryStatus.DELIVERED,
                        actor_name="Recipient / Courier POD",
                        actor_role="recipient",
                        note="Verified via recipient 6-digit confirmation PIN.",
                        occurred_at=deliv.updated_at,
                    )
                    db.add(e4)

            db.commit()
            logger.info("Seeded delivery records and event audit trails.")

        logger.info("Database seeding completed successfully!")
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
