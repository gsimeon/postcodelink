"""Cryptographic security utilities for authentication and OTP protection."""
import hmac
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
import bcrypt
import jwt
from backend.app.config import settings


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


def hash_otp(otp: str, salt: Optional[str] = None) -> str:
    """Hash a delivery OTP using HMAC-SHA256 with server SECRET_KEY."""
    key = settings.SECRET_KEY.encode("utf-8")
    salt_val = salt or "postcodelink_otp_salt"
    msg = f"{salt_val}:{otp.strip()}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_otp_hash(plain_otp: str, stored_hash: str, salt: Optional[str] = None) -> bool:
    """Constant-time comparison for delivery PIN verification."""
    computed = hash_otp(plain_otp, salt)
    return hmac.compare_digest(computed, stored_hash)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a signed JWT access token."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def _derive_outbox_subkeys(master_key: str) -> Tuple[bytes, bytes]:
    """Derive distinct encryption and authentication subkeys from master key using domain separation."""
    raw_key = master_key.encode("utf-8")
    enc_key = hmac.new(raw_key, b"postcodelink-outbox-encryption-v1", hashlib.sha256).digest()
    mac_key = hmac.new(raw_key, b"postcodelink-outbox-authentication-v1", hashlib.sha256).digest()
    return enc_key, mac_key


def encrypt_authenticated_pin(pin: str, master_key: Optional[str] = None) -> str:
    """Authenticated encryption for delivery PIN in transit (AEAD envelope).
    
    Format: v1:<nonce_hex>:<ciphertext_hex>:<hmac_tag_hex>
    Guarantees both confidentiality and ciphertext integrity.
    Tampering with even one bit will cause verification to fail during decryption.
    """
    key = master_key or settings.OUTBOX_ENCRYPTION_KEY or settings.SECRET_KEY
    enc_key, mac_key = _derive_outbox_subkeys(key)

    nonce = secrets.token_bytes(16)
    keystream = hmac.new(enc_key, nonce, hashlib.sha256).digest()

    pin_bytes = pin.strip().encode("utf-8")
    ciphertext = bytes(p ^ k for p, k in zip(pin_bytes, keystream[:len(pin_bytes)]))

    # Authenticate prefix, nonce, and ciphertext
    authenticated_payload = b"v1:" + nonce + ciphertext
    tag = hmac.new(mac_key, authenticated_payload, hashlib.sha256).digest()

    return f"v1:{nonce.hex()}:{ciphertext.hex()}:{tag.hex()}"


def decrypt_authenticated_pin(payload: str, master_key: Optional[str] = None) -> Optional[str]:
    """Decrypt and verify authenticated delivery PIN envelope.
    
    Returns the plaintext PIN if valid and authentic.
    Returns None if the payload has been tampered with or uses an invalid key.
    """
    if not payload or not isinstance(payload, str):
        return None

    key = master_key or settings.OUTBOX_ENCRYPTION_KEY or settings.SECRET_KEY

    # Check for v1 envelope
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

        enc_key, mac_key = _derive_outbox_subkeys(key)
        expected_tag = hmac.new(mac_key, b"v1:" + nonce + ciphertext, hashlib.sha256).digest()

        # Strict constant-time MAC verification
        if not hmac.compare_digest(tag, expected_tag):
            return None

        keystream = hmac.new(enc_key, nonce, hashlib.sha256).digest()
        pin_bytes = bytes(c ^ k for c, k in zip(ciphertext, keystream[:len(ciphertext)]))
        try:
            return pin_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return None

    # Fallback: legacy unversioned hex stream cipher (during migration)
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


