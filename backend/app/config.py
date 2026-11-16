"""Application configuration using Pydantic Settings."""
import os
import secrets
from typing import List, Any, Optional
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
    SECRET_KEY: str = os.getenv("SECRET_KEY", "postcodelink_dev_secret_key_32_characters_minimum")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Outbox Payload Cryptography: Dedicated authenticated encryption key (distinct from SECRET_KEY)
    OUTBOX_ENCRYPTION_KEY: str = os.getenv(
        "OUTBOX_ENCRYPTION_KEY",
        "postcodelink_dev_outbox_key_32_characters_minimum"
    )
    OUTBOX_PREVIOUS_ENCRYPTION_KEYS: Optional[str] = os.getenv("OUTBOX_PREVIOUS_ENCRYPTION_KEYS", None)
    
    # Process Role: Segregate HTTP serving ("api") from background dispatch ("worker") or unified ("all_in_one")
    PROCESS_ROLE: str = os.getenv("PROCESS_ROLE", "api")
    
    # Delivery PIN / OTP Security
    OTP_MAX_ATTEMPTS: int = 3
    OTP_LOCKOUT_MINUTES: int = 15
    OTP_EXPIRE_HOURS: int = 24
    
    # Seeding & External Integrations
    # SEED_DEMO_DATA seeds the reference postcode dataset in development (strictly forbidden in production)
    # SEED_DEMO_ACCOUNTS seeds default merchant/admin/operator profiles (strictly forbidden in production)
    SEED_DEMO_DATA: bool = False
    SEED_DEMO_ACCOUNTS: bool = False
    
    # Official NIPOST API Gateway Integration
    NIPOST_API_BASE_URL: str = os.getenv("NIPOST_API_BASE_URL", os.getenv("NIPOST_API_URL", ""))
    NIPOST_API_URL: str = os.getenv("NIPOST_API_URL", os.getenv("NIPOST_API_BASE_URL", ""))
    NIPOST_API_KEY: str = os.getenv("NIPOST_API_KEY", "")
    NIPOST_LOOKUP_PATH: str = os.getenv("NIPOST_LOOKUP_PATH", "/v1/lookup")
    NIPOST_TIMEOUT_SECONDS: float = 5.0

    # Trusted Reverse Proxies for Real Client IP extraction and rate limiting.
    # In production, default is strictly empty (direct external connections cannot spoof X-Forwarded-For).
    # In production, reverse proxies (e.g. Cloudflare, AWS ALB, Nginx) must be explicitly configured
    # via TRUSTED_PROXIES environment variable (comma-separated list of IP addresses or CIDR blocks).
    # In development/test mode, only loopback addresses and testclient are permitted.
    # Note: Broad private subnets (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) are strictly excluded by default
    # to prevent untrusted internal containers or shared infrastructure from forging client IPs.
    TRUSTED_PROXIES: List[str] = (
        [p.strip() for p in os.getenv("TRUSTED_PROXIES").split(",") if p.strip()]
        if os.getenv("TRUSTED_PROXIES") is not None
        else (["127.0.0.1", "::1", "localhost", "testclient"] if os.getenv("ENVIRONMENT", "development") != "production" else [])
    )

    # SMS & WhatsApp Out-of-band Dispatch Gateway
    SMS_PROVIDER: str = "simulated"
    TERMII_API_KEY: str = ""
    TERMII_SENDER_ID: str = "PostcodeLnk"
    TERMII_BASE_URL: str = os.getenv("TERMII_BASE_URL", "https://api.ng.termii.com")
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # Background Outbox Retry Worker
    OUTBOX_WORKER_ENABLED: bool = False
    OUTBOX_WORKER_INTERVAL_SECONDS: int = 5
    OUTBOX_LEASE_TIMEOUT_MINUTES: int = 5
    OUTBOX_WORKER_HEARTBEAT_THRESHOLD_SECONDS: int = 120

    # Redis Cache & Distributed Rate Limiting
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    REDIS_REQUIRED_IN_PRODUCTION: bool = True
    RATE_LIMIT_REDIS_FAIL_CLOSED: bool = True
    ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION: bool = os.getenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "false").lower() in ["true", "1"]
    PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE", "15"))

    @model_validator(mode="before")
    @classmethod
    def set_environment_defaults(cls, data: Any) -> Any:
        """Default SEED_DEMO_DATA to True in non-production environments unless explicitly overridden."""
        if isinstance(data, dict):
            env = data.get("ENVIRONMENT") or os.getenv("ENVIRONMENT", "development")
            if env != "production" and "SEED_DEMO_DATA" not in data:
                data["SEED_DEMO_DATA"] = True
        return data

    @model_validator(mode="after")
    def validate_production_security(self):
        """Reject startup if running in production with weak secrets, simulated provider, or insecure defaults."""
        if self.ENVIRONMENT == "production":
            raw_secret = self.SECRET_KEY
            if not raw_secret or len(raw_secret) < 32 or raw_secret.startswith("postcodelink_dev"):
                raise ValueError("Fatal Security Error: In production, SECRET_KEY must be set to a strong secret (at least 32 characters).")

            # Process role validation
            role = (self.PROCESS_ROLE or "").strip().lower()
            if role not in ["api", "worker", "all_in_one"]:
                raise ValueError(f"Fatal Production Configuration Error: PROCESS_ROLE must be 'api', 'worker', or 'all_in_one', got '{self.PROCESS_ROLE}'.")

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

            # Dedicated outbox encryption key validation
            raw_outbox_key = self.OUTBOX_ENCRYPTION_KEY
            if not raw_outbox_key or len(raw_outbox_key) < 32 or raw_outbox_key.startswith("postcodelink_dev"):
                raise ValueError("Fatal Security Error: In production, OUTBOX_ENCRYPTION_KEY must be set to a dedicated strong secret (at least 32 characters).")

            if raw_outbox_key == raw_secret:
                raise ValueError("Fatal Security Error: OUTBOX_ENCRYPTION_KEY must be distinct from SECRET_KEY to ensure cryptographic domain separation.")

            # Distributed rate limiting requires Redis by default in production
            if self.REDIS_REQUIRED_IN_PRODUCTION and not self.REDIS_URL and not self.ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION:
                raise ValueError(
                    "Fatal Production Configuration Error: REDIS_URL must be configured in production "
                    "for distributed rate limiting. Set ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true only "
                    "if explicitly running an isolated single-instance development or staging deployment."
                )

            # Demo account seeding is strictly forbidden in production
            if self.SEED_DEMO_ACCOUNTS:
                raise ValueError("Fatal Security Error: SEED_DEMO_ACCOUNTS cannot be enabled in production environment.")

            if self.SEED_DEMO_DATA:
                raise ValueError("Fatal Security Error: SEED_DEMO_DATA cannot be enabled in production environment.")

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
