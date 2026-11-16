"""Cryptographic security utilities for authentication and OTP protection."""
import hmac
import hashlib
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
import bcrypt
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from backend.app.config import settings

logger = logging.getLogger("security")


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt and automatic salt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_otp_secret_key() -> str:
    """Return active secret key for OTP HMAC hashing (enforces domain separation from JWT).
    
    In production, OTP_SECRET_KEY must be explicitly set. Fallback to SECRET_KEY is strictly forbidden.
    """
    key = (getattr(settings, "OTP_SECRET_KEY", None) or "").strip()
    if key:
        return key
    if getattr(settings, "ENVIRONMENT", "development") == "production":
        raise RuntimeError(
            "Fatal Security Error: OTP_SECRET_KEY must be explicitly configured in production. "
            "Fallback to SECRET_KEY is strictly forbidden in production."
        )
    return settings.SECRET_KEY.strip()


def hash_otp(otp: str, salt: Optional[str] = None, key: Optional[str] = None) -> str:
    """Hash a delivery OTP using HMAC-SHA256 with dedicated OTP_SECRET_KEY."""
    raw_key = (key or get_otp_secret_key()).encode("utf-8")
    salt_val = salt or "postcodelink_otp_salt"
    msg = f"{salt_val}:{otp.strip()}".encode("utf-8")
    return hmac.new(raw_key, msg, hashlib.sha256).hexdigest()


def verify_otp_hash(plain_otp: str, stored_hash: str, salt: Optional[str] = None) -> bool:
    """Constant-time comparison for delivery PIN verification supporting zero-downtime key rotation.
    
    Tries current OTP_SECRET_KEY first; falls back to configured OTP_PREVIOUS_SECRETS to allow
    in-flight deliveries created before rotation to verify successfully.
    """
    if not plain_otp or not stored_hash:
        return False

    # 1. Test with current active key
    computed = hash_otp(plain_otp, salt, key=get_otp_secret_key())
    if hmac.compare_digest(computed, stored_hash):
        return True

    # 2. Key rotation fallback: test with previous OTP verification keys
    prev_keys = getattr(settings, "OTP_PREVIOUS_SECRETS", []) or []
    for prev_key in prev_keys:
        if prev_key and hmac.compare_digest(hash_otp(plain_otp, salt, key=prev_key), stored_hash):
            return True

    return False


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed JWT access token with key identifier (kid) header."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    headers = {"kid": getattr(settings, "JWT_KEY_ID", "v1")}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM, headers=headers)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a signed JWT access token using versioned key selection (kid).
    
    1. Inspects the unverified JWT header to extract 'kid'.
    2. If 'kid' is present:
       - Maps directly to the corresponding key in configured verification keys.
       - Rejects unknown, retired, or mismatched key identifiers immediately.
    3. If 'kid' is absent (unversioned legacy token):
       - Validates against active SECRET_KEY, falling back to JWT_PREVIOUS_SECRETS for backwards compatibility.
    """
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise jwt.PyJWTError("Malformed JWT header") from exc

    token_kid = header.get("kid")
    verification_keys = settings.get_jwt_verification_keys()

    if token_kid:
        if token_kid not in verification_keys:
            raise jwt.PyJWTError(f"Unknown or retired JWT key identifier: '{token_kid}'")
        selected_key = verification_keys[token_kid]
        return jwt.decode(token, selected_key, algorithms=[settings.JWT_ALGORITHM])

    # Legacy unversioned token fallback
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.InvalidSignatureError as exc:
        for prev_key in getattr(settings, "JWT_PREVIOUS_SECRETS", []) or []:
            try:
                return jwt.decode(token, prev_key, algorithms=[settings.JWT_ALGORITHM])
            except jwt.InvalidSignatureError:
                continue
        raise exc


def _derive_aes_key(master_key: str) -> bytes:
    """Derive standard 256-bit (32 bytes) key for AES-256-GCM using domain separation."""
    return hashlib.sha256(b"postcodelink-aes-256-gcm-v2:" + master_key.encode("utf-8")).digest()


def _derive_outbox_subkeys(master_key: str) -> Tuple[bytes, bytes]:
    """Derive distinct encryption and authentication subkeys for legacy v1 envelope migration."""
    raw_key = master_key.encode("utf-8")
    enc_key = hmac.new(raw_key, b"postcodelink-outbox-encryption-v1", hashlib.sha256).digest()
    mac_key = hmac.new(raw_key, b"postcodelink-outbox-authentication-v1", hashlib.sha256).digest()
    return enc_key, mac_key


def encrypt_authenticated_pin(
    pin: str,
    master_key: Optional[str] = None,
    delivery_id: Optional[str] = None,
    aad: Optional[bytes] = None,
) -> str:
    """Industry-standard AES-256-GCM authenticated encryption for delivery PIN in transit.
    
    Envelope Format: v2:<nonce_hex>:<aad_hex>:<ciphertext_and_tag_hex>
    Guarantees standard AEAD confidentiality, integrity, and authenticity.
    Binds the ciphertext to delivery and notification identifiers via Authenticated Additional Data (AAD).
    Tampering with even one bit will cause verification to fail during decryption.
    """
    key = master_key or settings.OUTBOX_ENCRYPTION_KEY or settings.SECRET_KEY
    aes_key = _derive_aes_key(key)
    aesgcm = AESGCM(aes_key)

    # Standard 96-bit (12 bytes) nonce recommended for AES-GCM
    nonce = secrets.token_bytes(12)

    # Bind ciphertext to delivery identifier via Authenticated Additional Data (AAD)
    if aad is not None:
        associated_data = aad
    elif delivery_id:
        associated_data = f"delivery:{delivery_id}".encode("utf-8")
    else:
        associated_data = b""

    pin_bytes = pin.strip().encode("utf-8")
    ciphertext_and_tag = aesgcm.encrypt(nonce, pin_bytes, associated_data)

    return f"v2:{nonce.hex()}:{associated_data.hex()}:{ciphertext_and_tag.hex()}"


def decrypt_authenticated_pin(
    payload: str,
    master_key: Optional[str] = None,
    delivery_id: Optional[str] = None,
    aad: Optional[bytes] = None,
    allow_legacy: bool = False,
    allow_unbound: bool = False,
) -> Optional[str]:
    """Decrypt and verify authenticated delivery PIN envelope using AES-256-GCM with key rotation.
    
    Supports:
    - Primary format v2: AES-256-GCM with strict context-bound AAD and key rotation (OUTBOX_PREVIOUS_ENCRYPTION_KEYS).
    - Context enforcement: Active delivery decryption requires delivery context (delivery_id or aad).
      Empty-AAD envelopes are strictly rejected unless allow_unbound=True is explicitly set for recovery.
    - Optional legacy migration: v1 HMAC-SHA256 and unversioned hex stream cipher ONLY when allow_legacy=True.
    
    Returns the plaintext PIN if valid and authentic.
    Returns None if the payload has been tampered with or fails strict AAD verification.
    """
    if not payload or not isinstance(payload, str):
        return None

    # Normal delivery PIN decryption strictly requires context
    expected_aad = aad if aad is not None else (f"delivery:{delivery_id}".encode("utf-8") if delivery_id else None)
    if not allow_unbound and expected_aad is None and not allow_legacy:
        logger.warning("Decryption rejected: delivery context is required for active PIN decryption")
        return None

    primary_key = master_key or settings.OUTBOX_ENCRYPTION_KEY or settings.SECRET_KEY

    # Candidate keys for key rotation and cross-key migration support
    candidate_keys = [primary_key]
    outbox_k = getattr(settings, "OUTBOX_ENCRYPTION_KEY", None)
    if outbox_k and outbox_k not in candidate_keys:
        candidate_keys.append(outbox_k)
    if settings.SECRET_KEY and settings.SECRET_KEY not in candidate_keys:
        candidate_keys.append(settings.SECRET_KEY)
    prev_keys_str = getattr(settings, "OUTBOX_PREVIOUS_ENCRYPTION_KEYS", None)
    if prev_keys_str:
        for k in prev_keys_str.split(","):
            clean_k = k.strip()
            if clean_k and clean_k not in candidate_keys:
                candidate_keys.append(clean_k)

    # =========================================================================
    # 1. Primary Format v2: Standard AES-256-GCM AEAD Envelope
    # =========================================================================
    if payload.startswith("v2:"):
        parts = payload.split(":")
        if len(parts) == 4:
            try:
                nonce = bytes.fromhex(parts[1])
                payload_aad = bytes.fromhex(parts[2]) if parts[2] else b""
                ciphertext_and_tag = bytes.fromhex(parts[3])
            except ValueError:
                return None
        elif len(parts) == 3:
            try:
                nonce = bytes.fromhex(parts[1])
                payload_aad = b""
                ciphertext_and_tag = bytes.fromhex(parts[2])
            except ValueError:
                return None
        else:
            return None

        # Context enforcement: Empty-AAD envelopes are strictly rejected in delivery workflows
        if not allow_unbound and payload_aad == b"":
            logger.warning("Decryption rejected: payload envelope has empty AAD; unbound envelopes are rejected in delivery workflows")
            return None

        # Strict bidirectional AAD binding:
        # 1. If payload was encrypted with AAD, caller MUST supply the matching delivery context.
        # 2. If caller expects a delivery ID / AAD, payload AAD MUST match exactly.
        if payload_aad != b"" and (expected_aad is None or payload_aad != expected_aad):
            return None
        if expected_aad is not None and (payload_aad == b"" or payload_aad != expected_aad):
            return None

        for cand_key in candidate_keys:
            try:
                aes_key = _derive_aes_key(cand_key)
                aesgcm = AESGCM(aes_key)
                plain_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, payload_aad)
                return plain_bytes.decode("utf-8")
            except Exception:
                continue

        # If all keys failed or tag verification failed due to tampering
        return None

    # If legacy fallback is disabled, strictly reject all non-v2 envelopes
    if not allow_legacy:
        return None

    # =========================================================================
    # 2. Controlled Legacy Migration Path: v1 HMAC-SHA256 Envelope (allow_legacy=True only)
    # =========================================================================
    if payload.startswith("v1:"):
        parts = payload.split(":")
        if len(parts) != 4:
            return None
        try:
            nonce = bytes.fromhex(parts[1])
            ciphertext = bytes.fromhex(parts[2])
            tag = bytes.fromhex(parts[3])
        except ValueError:
            return None

        for cand_key in candidate_keys:
            enc_key, mac_key = _derive_outbox_subkeys(cand_key)
            expected_tag = hmac.new(mac_key, b"v1:" + nonce + ciphertext, hashlib.sha256).digest()
            if hmac.compare_digest(tag, expected_tag):
                keystream = hmac.new(enc_key, nonce, hashlib.sha256).digest()
                pin_bytes = bytes(c ^ k for c, k in zip(ciphertext, keystream[:len(ciphertext)]))
                try:
                    return pin_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return None
        return None

    # =========================================================================
    # 3. Controlled Legacy Migration Path: Unversioned hex stream cipher (allow_legacy=True only)
    # =========================================================================
    try:
        raw = bytes.fromhex(payload)
        if len(raw) < 9:
            return None
        nonce = raw[:8]
        ciphertext = raw[8:]
        legacy_key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        keystream = hashlib.sha256(legacy_key + nonce).digest()
        pin_bytes = bytes(c ^ k for c, k in zip(ciphertext, keystream[:len(ciphertext)]))
        return pin_bytes.decode("utf-8")
    except Exception:
        return None


def migrate_legacy_transit_pin(
    payload: str,
    delivery_id: str,
    master_key: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Explicit migration pathway: decrypts legacy v1: or unversioned payload and re-encrypts to v2: with delivery AAD.
    
    Returns (plaintext_pin, upgraded_v2_envelope).
    If payload is invalid or already tampered, returns (None, None).
    """
    plain = decrypt_authenticated_pin(
        payload=payload,
        master_key=master_key,
        delivery_id=delivery_id,
        allow_legacy=True,
        allow_unbound=True,
    )
    if not plain:
        return None, None
    new_v2 = encrypt_authenticated_pin(
        pin=plain,
        master_key=master_key,
        delivery_id=delivery_id,
    )
    return plain, new_v2


