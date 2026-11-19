"""Verification Evidence model for auditable official postcode verification records."""
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, String, DateTime, Boolean
from backend.app.database import Base


def default_valid_until():
    """Default validity window for official verification: 30 days from issuance."""
    return datetime.now(timezone.utc) + timedelta(days=30)


class VerificationEvidence(Base):
    """Immutable audit record establishing verified provenance from official NIPOST gateway."""
    __tablename__ = "verification_evidence"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    postcode = Column(String(20), nullable=False, index=True)
    provider = Column(String(64), nullable=False, default="NIPOST")
    provider_reference_id = Column(String(128), nullable=True)  # Upstream transaction or receipt ID
    verification_method = Column(String(64), nullable=False, default="validator_autofill_pipeline")  # validator | autofill | validator_autofill_pipeline
    dataset_version = Column(String(32), nullable=True, default=None)
    verified_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_until = Column(DateTime, nullable=False, default=default_valid_until)
    response_hash = Column(String(64), nullable=False)  # SHA-256 of raw response data
    status = Column(String(32), nullable=False, default="verified")  # verified | partial | rejected
    address_metadata_source = Column(String(64), nullable=False, default="nipost_autofill")  # nipost_autofill | local_enrichment | unverified
    is_active = Column(Boolean, nullable=False, default=True)

    @property
    def is_expired(self) -> bool:
        if not self.valid_until:
            return True
        now = datetime.now(timezone.utc)
        target = self.valid_until
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return now > target
