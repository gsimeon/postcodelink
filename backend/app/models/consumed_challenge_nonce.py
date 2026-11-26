"""ConsumedChallengeNonce model for distributed atomic one-time recipient challenge replay protection."""
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from backend.app.database import Base


class ConsumedChallengeNonce(Base):
    """Stores consumed recipient challenge nonces to prevent replay across multiple API instances."""
    __tablename__ = "consumed_challenge_nonces"

    nonce = Column(String(64), primary_key=True, nullable=False)
    tracking_token = Column(String(64), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
