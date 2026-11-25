"""Application configuration using Pydantic Settings."""
import os
import math
import secrets
from collections import Counter
from typing import List, Any, Optional, Dict, ClassVar, Set, Union
from pydantic import model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def calculate_shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy in bits per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def validate_cryptographic_secret(raw_secret: str, secret_name: str) -> None:
    """Validate that a production secret meets cryptographic strength standards:
    1. Minimum length >= 32 characters.
    2. No disallowed repository templates, default prefixes, or predictable keywords.
    3. Maximum character concentration <= 25% (rejects repetitive character stuffing like 'a'*32).
    4. Minimum unique character diversity (>= 10 unique characters in a 32+ char secret).
    5. No repeated character runs of 5 or more (e.g. 'aaaaa').
    6. No simple ascending/descending sequential runs of 6 or more (e.g. '123456', 'abcdef').
    7. Shannon entropy >= 3.0 bits per character.
    
    Production Secret Rotation & Management Policy:
    - Never hardcode or reuse secrets across environments or functional domains.
    - Production secrets MUST be generated using cryptographically authentic random generators:
        python -c "import secrets; print(secrets.token_urlsafe(32))"
        or: openssl rand -hex 32
    - Recommended for production: Inject credentials from a managed secret manager
      (e.g. AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager, or Azure Key Vault).
    - JWT Secret Rotation: Update SECRET_KEY in secrets manager; new tokens sign with new key,
      existing tokens expire per ACCESS_TOKEN_EXPIRE_MINUTES.
    - Outbox Encryption Rotation: Ensure pending messages in outbox are dispatched, or
      execute key migration script to re-encrypt pending outbox records under the new OUTBOX_ENCRYPTION_KEY.
    """
    secret = (raw_secret or "").strip()
    disallowed_patterns = [
        "postcodelink_dev",
        "postcodelink_prod",
        "postcodelink_production",
        "postcodelink_ci",
        "replace_with_",
        "generate_secure",
        "your_secret_key",
        "super_secure",
        "example",
        "changeme",
        "secret123",
        "password",
        "admin123",
    ]
    if not secret or any(p in secret.lower() for p in disallowed_patterns):
        raise ValueError(
            f"Fatal Security Error: In production, {secret_name} must be set to an authentic, cryptographically strong secret. "
            "Repository template defaults, example values, and predictable prefixes are strictly prohibited."
        )

    if len(secret) < 32:
        raise ValueError(
            f"Fatal Security Error: In production, {secret_name} must be at least 32 characters."
        )

    # 1. Repetitive character concentration check (rejects repetitive padding like 'a'*32 + 'suffix')
    counts = Counter(secret)
    max_char_count = max(counts.values())
    if max_char_count / len(secret) > 0.25:
        raise ValueError(
            f"Fatal Security Error: In production, {secret_name} has insufficient character variety "
            f"(single character occurs {max_char_count} times in a {len(secret)}-character secret; maximum allowed concentration is 25%)."
        )

    # 2. Minimum distinct characters check
    if len(counts) < 10:
        raise ValueError(
            f"Fatal Security Error: In production, {secret_name} has insufficient character diversity "
            f"({len(counts)} unique characters; minimum required is 10)."
        )

    # 3. Repeated character run check (e.g. 'aaaaa')
    for i in range(len(secret) - 4):
        if len(set(secret[i:i + 5])) == 1:
            raise ValueError(
                f"Fatal Security Error: In production, {secret_name} contains repetitive character runs (5 or more identical characters in a row)."
            )

    # 4. Simple sequential character runs check (e.g. '123456', 'abcdef')
    lower_s = secret.lower()
    for i in range(len(lower_s) - 5):
        chunk = lower_s[i:i + 6]
        diffs = [ord(chunk[j + 1]) - ord(chunk[j]) for j in range(len(chunk) - 1)]
        if all(d == 1 for d in diffs) or all(d == -1 for d in diffs):
            raise ValueError(
                f"Fatal Security Error: In production, {secret_name} contains predictable sequential character sequences (e.g. '{chunk}')."
            )

    # 5. Shannon entropy check (minimum 3.0 bits/char)
    entropy = calculate_shannon_entropy(secret)
    if entropy < 3.0:
        raise ValueError(
            f"Fatal Security Error: In production, {secret_name} has insufficient Shannon entropy "
            f"({entropy:.2f} bits/character; minimum required is 3.0 bits/character). "
            "Generate cryptographically authentic secrets using `secrets.token_urlsafe(32)` or `openssl rand -hex 32`."
        )



class Settings(BaseSettings):
    PROJECT_NAME: str = "PostcodeLink Nigeria API"
    VERSION: str = "1.2.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
    
    # Database URL: default SQLite, switchable to PostgreSQL via DATABASE_URL
    DATABASE_URL: str = "sqlite:///./postcodelink.db"
    
    # CORS
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://postcodelink.ng",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json
                return [str(x).strip() for x in json.loads(s) if str(x).strip()]
            return [x.strip() for x in s.split(",") if x.strip()]
        return []
    
    # Security & JWT Token Auth with Versioned Key Rotation
    SECRET_KEY: str = os.getenv("SECRET_KEY", "postcodelink_dev_secret_key_32_characters_minimum")
    JWT_KEY_ID: str = os.getenv("JWT_KEY_ID", "v1")
    JWT_PREVIOUS_SECRETS: List[str] = (
        [s.strip() for s in os.getenv("JWT_PREVIOUS_SECRETS").split(",") if s.strip()]
        if os.getenv("JWT_PREVIOUS_SECRETS")
        else []
    )
    JWT_PREVIOUS_KEYS_MAP: Dict[str, str] = {}
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Parse JSON environment variable for explicit key-to-secret mapping if provided
        raw_map = os.getenv("JWT_PREVIOUS_KEYS_MAP")
        if raw_map and isinstance(raw_map, str) and raw_map.strip().startswith("{"):
            try:
                import json
                parsed = json.loads(raw_map.strip())
                if isinstance(parsed, dict):
                    self.JWT_PREVIOUS_KEYS_MAP.update({str(k): str(v) for k, v in parsed.items()})
            except Exception:
                pass

    def get_jwt_verification_keys(self) -> Dict[str, str]:
        """Return complete mapping of key ID (kid) -> secret key for versioned JWT verification."""
        keys: Dict[str, str] = {}
        if self.SECRET_KEY:
            keys[self.JWT_KEY_ID] = self.SECRET_KEY.strip()
        if self.JWT_PREVIOUS_KEYS_MAP:
            for kid, sec in self.JWT_PREVIOUS_KEYS_MAP.items():
                if sec:
                    keys[str(kid).strip()] = str(sec).strip()
        for idx, sec in enumerate(self.JWT_PREVIOUS_SECRETS):
            if sec:
                sec_clean = sec.strip()
                if ":" in sec_clean and len(sec_clean.split(":", 1)[0]) < 16:
                    k, v = sec_clean.split(":", 1)
                    keys[k.strip()] = v.strip()
                else:
                    keys[f"v_prev_{idx+1}"] = sec_clean
        return keys

    def get_all_jwt_verification_secrets(self) -> List[str]:
        """Return list of all candidate secrets for decoding tokens during transition."""
        secrets = []
        for s in self.get_jwt_verification_keys().values():
            if s and s not in secrets:
                secrets.append(s)
        for s in self.JWT_PREVIOUS_SECRETS:
            val = s.split(":", 1)[1].strip() if ":" in s and len(s.split(":", 1)[0]) < 16 else s.strip()
            if val and val not in secrets:
                secrets.append(val)
        return secrets

    # Delivery PIN / OTP Hashing Key (Cryptographic Domain Separation from JWT)
    OTP_SECRET_KEY: str = os.getenv("OTP_SECRET_KEY", "")
    OTP_PREVIOUS_SECRETS: List[str] = (
        [s.strip() for s in os.getenv("OTP_PREVIOUS_SECRETS").split(",") if s.strip()]
        if os.getenv("OTP_PREVIOUS_SECRETS")
        else []
    )
    # Dedicated Recipient Challenge Signing Key (strictly separated from JWT SECRET_KEY)
    CHALLENGE_SECRET_KEY: str = os.getenv("CHALLENGE_SECRET_KEY", "")
    
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
    NIPOST_VALIDATE_PATH: str = os.getenv("NIPOST_VALIDATE_PATH", "")  # Blank uses documented unified /v1/lookup; set "/v1/validate" only for two-stage Validator/Autofill
    NIPOST_AUTH_SCHEME: str = os.getenv("NIPOST_AUTH_SCHEME", "x-api-key")  # "x-api-key" (quickstart default), "bearer", "api_key", or "none"
    NIPOST_QUERY_PARAM: str = os.getenv("NIPOST_QUERY_PARAM", "code")  # "code", "postcode", or "both"
    NIPOST_TIMEOUT_SECONDS: float = 5.0

    # Auditable Commercial NIPOST Authorization (required before enabling pl_live_ commercial resale)
    NIPOST_PRODUCTION_AUTHORIZED: bool = os.getenv("NIPOST_PRODUCTION_AUTHORIZED", "false").strip().lower() == "true"
    NIPOST_AUTHORIZATION_AGREEMENT_REF: str = os.getenv("NIPOST_AUTHORIZATION_AGREEMENT_REF", "").strip()
    NIPOST_AUTHORIZATION_APPROVER: str = os.getenv("NIPOST_AUTHORIZATION_APPROVER", "").strip()
    NIPOST_AUTHORIZATION_APPROVED_AT: str = os.getenv("NIPOST_AUTHORIZATION_APPROVED_AT", "").strip()
    NIPOST_AUTHORIZATION_EXPIRES_AT: str = os.getenv("NIPOST_AUTHORIZATION_EXPIRES_AT", "").strip()
    NIPOST_AUTHORIZATION_REVOKED: bool = os.getenv("NIPOST_AUTHORIZATION_REVOKED", "false").strip().lower() == "true"
    NIPOST_AUTHORIZATION_SCOPE: str = os.getenv("NIPOST_AUTHORIZATION_SCOPE", "").strip()

    def has_nipost_scope(self, required_scope: str) -> bool:
        """Check whether the recorded commercial authorization scope explicitly includes required_scope."""
        raw = (self.NIPOST_AUTHORIZATION_SCOPE or "").strip().lower()
        if not raw:
            return False
        tokens = {tok.strip() for tok in raw.replace(";", ",").replace(" ", ",").split(",") if tok.strip()}
        return required_scope.lower() in tokens or "commercial_api" in tokens

    @property
    def is_nipost_production_authorized(self) -> bool:
        """True only when commercial authorization is enabled, not revoked, not expired,
        and the full approval record (agreement_ref, approver, valid non-future approved_at,
        and explicit postcode_verification scope) is present.
        """
        if self.NIPOST_AUTHORIZATION_REVOKED:
            return False
        if not (
            self.NIPOST_PRODUCTION_AUTHORIZED
            and self.NIPOST_AUTHORIZATION_AGREEMENT_REF.strip()
            and self.NIPOST_AUTHORIZATION_APPROVER.strip()
            and self.NIPOST_AUTHORIZATION_APPROVED_AT.strip()
            and self.has_nipost_scope("postcode_verification")
        ):
            return False
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        try:
            approved_dt = datetime.fromisoformat(self.NIPOST_AUTHORIZATION_APPROVED_AT.strip().replace("Z", "+00:00"))
            if approved_dt.tzinfo is None:
                approved_dt = approved_dt.replace(tzinfo=timezone.utc)
            if approved_dt > now:
                return False
            if self.NIPOST_AUTHORIZATION_EXPIRES_AT.strip():
                expires_dt = datetime.fromisoformat(self.NIPOST_AUTHORIZATION_EXPIRES_AT.strip().replace("Z", "+00:00"))
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                if expires_dt <= now:
                    return False
        except ValueError:
            return False
        return True

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
        else (["127.0.0.1", "::1", "localhost", "testclient"] if os.getenv("ENVIRONMENT", "development").strip().lower() != "production" else [])
    )

    # SMS & WhatsApp Out-of-band Dispatch Gateway
    SMS_PROVIDER: str = "simulated"
    TERMII_API_KEY: str = ""
    TERMII_SENDER_ID: str = "PostcodeLnk"
    TERMII_BASE_URL: str = os.getenv("TERMII_BASE_URL", "https://api.ng.termii.com")
    TERMII_CHANNEL: str = os.getenv("TERMII_CHANNEL", "dnd")
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

    ALLOWED_ENVIRONMENTS: ClassVar[Set[str]] = {"development", "test", "staging", "production"}

    @model_validator(mode="before")
    @classmethod
    def set_environment_defaults(cls, data: Any) -> Any:
        """Normalize ENVIRONMENT and fail closed on unknown environments."""
        if isinstance(data, dict):
            raw_env = data.get("ENVIRONMENT") or os.getenv("ENVIRONMENT", "development")
            if not isinstance(raw_env, str):
                raise ValueError("Fatal Configuration Error: ENVIRONMENT must be a string.")
            normalized_env = raw_env.strip().lower()
            if normalized_env not in cls.ALLOWED_ENVIRONMENTS:
                raise ValueError(
                    f"Fatal Configuration Error: Unknown ENVIRONMENT '{raw_env}'. "
                    f"Allowed environments are: {', '.join(sorted(cls.ALLOWED_ENVIRONMENTS))}."
                )
            data["ENVIRONMENT"] = normalized_env
            if normalized_env != "production" and "SEED_DEMO_DATA" not in data:
                data["SEED_DEMO_DATA"] = True
        return data

    @model_validator(mode="after")
    def validate_production_security(self):
        """Reject startup if running in production with weak secrets, simulated provider, or insecure defaults."""
        if self.ENVIRONMENT == "production":
            raw_secret = (self.SECRET_KEY or "").strip()
            validate_cryptographic_secret(raw_secret, "SECRET_KEY")

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
            raw_outbox_key = (self.OUTBOX_ENCRYPTION_KEY or "").strip()
            validate_cryptographic_secret(raw_outbox_key, "OUTBOX_ENCRYPTION_KEY")

            if raw_outbox_key == raw_secret:
                raise ValueError("Fatal Security Error: OUTBOX_ENCRYPTION_KEY must be distinct from SECRET_KEY to ensure cryptographic domain separation.")

            # Versioned JWT previous keys validation
            for prev_jwt in self.JWT_PREVIOUS_SECRETS:
                validate_cryptographic_secret(prev_jwt, "JWT_PREVIOUS_SECRETS key")

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

            # Dedicated OTP secret key validation (Mandatory in production for domain separation)
            raw_otp_key = (self.OTP_SECRET_KEY or "").strip()
            if not raw_otp_key:
                raise ValueError(
                    "Fatal Security Error: In production, OTP_SECRET_KEY must be explicitly configured and distinct from SECRET_KEY and OUTBOX_ENCRYPTION_KEY."
                )
            validate_cryptographic_secret(raw_otp_key, "OTP_SECRET_KEY")
            if raw_otp_key == raw_secret:
                raise ValueError("Fatal Security Error: OTP_SECRET_KEY must be distinct from SECRET_KEY to ensure cryptographic domain separation.")
            if raw_otp_key == raw_outbox_key:
                raise ValueError("Fatal Security Error: OTP_SECRET_KEY must be distinct from OUTBOX_ENCRYPTION_KEY to ensure cryptographic domain separation.")
            for prev_otp in self.OTP_PREVIOUS_SECRETS:
                validate_cryptographic_secret(prev_otp, "OTP_PREVIOUS_SECRETS key")
            for prev_kid, prev_key in self.JWT_PREVIOUS_KEYS_MAP.items():
                validate_cryptographic_secret(prev_key, f"JWT_PREVIOUS_KEYS_MAP key '{prev_kid}'")

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
