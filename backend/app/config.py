"""Application configuration using Pydantic Settings."""
import os
import secrets
from typing import List
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PostcodeLink Nigeria API"
    VERSION: str = "1.2.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Database URL: default SQLite, switchable to PostgreSQL via DATABASE_URL
    DATABASE_URL: str = "sqlite:///./postcodelink.db"
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://postcodelink.ng",
    ]
    
    # Security & JWT Token Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "postcodelink_dev_secret_key_" + secrets.token_hex(16))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Delivery PIN / OTP Security
    OTP_MAX_ATTEMPTS: int = 3
    OTP_LOCKOUT_MINUTES: int = 15
    OTP_EXPIRE_HOURS: int = 24
    
    # Seeding & External Integrations: SEED_DEMO_DATA defaults to True in dev only
    SEED_DEMO_DATA: bool = os.getenv("SEED_DEMO_DATA", "false").lower() in ("true", "1") or (os.getenv("ENVIRONMENT", "development") == "development")
    NIPOST_API_KEY: str = ""
    NIPOST_API_URL: str = ""

    # Trusted Proxies for Rate Limiting & Real IP extraction
    # Requests from IPs outside TRUSTED_PROXIES have X-Forwarded-For ignored to block spoofing
    TRUSTED_PROXIES: List[str] = [
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]

    # SMS & WhatsApp Out-of-band Dispatch Gateway
    SMS_PROVIDER: str = "simulated"
    TERMII_API_KEY: str = ""
    TERMII_SENDER_ID: str = "PostcodeLnk"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # Background Outbox Retry Worker
    OUTBOX_WORKER_ENABLED: bool = False
    OUTBOX_WORKER_INTERVAL_SECONDS: int = 5
    OUTBOX_LEASE_TIMEOUT_MINUTES: int = 5

    @model_validator(mode="after")
    def validate_production_security(self):
        """Reject startup if running in production with weak secret, simulated provider, or disabled worker."""
        if self.ENVIRONMENT == "production":
            raw_secret = self.SECRET_KEY
            if not raw_secret or len(raw_secret) < 32 or raw_secret.startswith("postcodelink_dev"):
                raise ValueError("Fatal Security Error: In production, SECRET_KEY must be set to a strong secret (at least 32 characters).")

            # Production SMS Gateway validation
            provider = (self.SMS_PROVIDER or "").strip().lower()
            if provider not in ["termii", "twilio"]:
                raise ValueError(
                    f"Fatal Production Configuration Error: SMS_PROVIDER must be 'termii' or 'twilio', got '{self.SMS_PROVIDER}'. Simulated SMS dispatch is strictly prohibited in production."
                )

            if provider == "termii" and not self.TERMII_API_KEY:
                raise ValueError("Fatal Production Configuration Error: TERMII_API_KEY must be configured when SMS_PROVIDER is 'termii'.")

            if provider == "twilio" and not (self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN and self.TWILIO_FROM_NUMBER):
                raise ValueError("Fatal Production Configuration Error: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER must be configured when SMS_PROVIDER is 'twilio'.")

            # Worker validation
            if not self.OUTBOX_WORKER_ENABLED:
                raise ValueError("Fatal Production Configuration Error: OUTBOX_WORKER_ENABLED must be true in production to ensure durable delivery notification dispatch.")

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
