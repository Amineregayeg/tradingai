"""Security utilities for Trading AI Co-Pilot.

Provides:
- AES-256-GCM encryption / decryption for broker credentials
- Request ID generation
"""
import base64
import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

# ---------------------------------------------------------------------------
# AES-256-GCM helpers
# ---------------------------------------------------------------------------

_GCM_NONCE_BYTES = 12  # 96-bit nonce recommended for GCM


def _derive_key() -> bytes:
    """Derive a 32-byte key from settings.secret_key via SHA-256.

    Using SHA-256 gives us a stable, deterministic 256-bit key from an
    arbitrary-length passphrase without requiring a stored salt.
    """
    import hashlib

    return hashlib.sha256(settings.secret_key.encode()).digest()


def encrypt_credentials(plaintext: str) -> bytes:
    """Encrypt *plaintext* credentials using AES-256-GCM.

    Returns the raw bytes of ``nonce || ciphertext`` which can be stored
    directly in the ``encrypted_creds`` BYTEA column.
    """
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_GCM_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_credentials(ciphertext_blob: bytes) -> str:
    """Decrypt a credential blob produced by :func:`encrypt_credentials`.

    Args:
        ciphertext_blob: Raw bytes as stored in the database (nonce || ciphertext).

    Returns:
        The original plaintext credentials string.

    Raises:
        ValueError: If decryption fails (wrong key, corrupted data).
    """
    if len(ciphertext_blob) <= _GCM_NONCE_BYTES:
        raise ValueError("Ciphertext blob is too short — likely corrupted")
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = ciphertext_blob[:_GCM_NONCE_BYTES]
    ciphertext = ciphertext_blob[_GCM_NONCE_BYTES:]
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("Failed to decrypt credentials — wrong key or corrupted data") from exc
    return plaintext_bytes.decode("utf-8")


def encrypt_credentials_b64(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 string (for JSON transport)."""
    return base64.urlsafe_b64encode(encrypt_credentials(plaintext)).decode()


def decrypt_credentials_b64(b64_blob: str) -> str:
    """Decrypt a base64-encoded credential blob."""
    raw = base64.urlsafe_b64decode(b64_blob.encode())
    return decrypt_credentials(raw)


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------


def get_request_id() -> str:
    """Generate a new UUID4 request ID string."""
    return str(uuid.uuid4())
