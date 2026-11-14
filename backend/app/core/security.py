"""Cryptographic security utilities for authentication and OTP protection."""
import hmac
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
import bcrypt
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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
) -> Optional[str]:
    """Decrypt and verify authenticated delivery PIN envelope using AES-256-GCM with key rotation.
    
    Supports:
    - Primary format v2: AES-256-GCM with AAD and key rotation (OUTBOX_PREVIOUS_ENCRYPTION_KEYS).
    - Controlled migration for v1: HMAC-SHA256 authenticated envelope.
    - Controlled migration for legacy unversioned hex stream cipher.
    
    Returns the plaintext PIN if valid and authentic.
    Returns None if the payload has been tampered with or uses an invalid key/AAD.
    """
    if not payload or not isinstance(payload, str):
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
    # 1. Primary Format v2: AES-256-GCM
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

        # Verify AAD binding: if payload was bound to an AAD, require matching expected AAD
        expected_aad = aad if aad is not None else (f"delivery:{delivery_id}".encode("utf-8") if delivery_id else None)
        if expected_aad is not None and payload_aad != b"" and payload_aad != expected_aad:
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

    # =========================================================================
    # 2. Controlled Migration Path: v1 HMAC-SHA256 Envelope
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
    # 3. Controlled Migration Path: Legacy unversioned hex stream cipher
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


