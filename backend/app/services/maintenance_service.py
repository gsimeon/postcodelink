"""Background maintenance and audit retention service helpers."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.app.models.login_attempt import LoginAttempt


def cleanup_expired_login_attempts(db: Session, retention_days: int = 30) -> int:
    """Purge login attempt audit records older than retention_days (Retention Policy)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = db.query(LoginAttempt).filter(LoginAttempt.attempted_at < cutoff).delete()
    db.commit()
    return deleted
