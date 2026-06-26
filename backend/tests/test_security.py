"""Unit tests for security utilities."""
import pytest

from app.core.security import (
    decrypt_credentials,
    decrypt_credentials_b64,
    encrypt_credentials,
    encrypt_credentials_b64,
    get_request_id,
)


def test_encrypt_decrypt_roundtrip() -> None:
    """Encrypt then decrypt should return the original plaintext."""
    plaintext = '{"api_key": "sk-test-12345", "secret": "mysecret"}'
    ciphertext = encrypt_credentials(plaintext)
    assert isinstance(ciphertext, bytes)
    assert len(ciphertext) > 12  # Must have nonce + actual ciphertext
    recovered = decrypt_credentials(ciphertext)
    assert recovered == plaintext


def test_encrypt_produces_different_ciphertexts() -> None:
    """Each encrypt call should produce a different ciphertext (random nonce)."""
    plaintext = "same input"
    c1 = encrypt_credentials(plaintext)
    c2 = encrypt_credentials(plaintext)
    assert c1 != c2  # Different nonces


def test_decrypt_wrong_data_raises() -> None:
    """Decrypting garbage data should raise ValueError."""
    with pytest.raises(ValueError):
        decrypt_credentials(b"\x00" * 50)


def test_b64_roundtrip() -> None:
    """Base64 encode/decode roundtrip should work."""
    plaintext = "broker:apikey123"
    b64 = encrypt_credentials_b64(plaintext)
    assert isinstance(b64, str)
    recovered = decrypt_credentials_b64(b64)
    assert recovered == plaintext


def test_get_request_id_is_uuid() -> None:
    """get_request_id should return a valid UUID4 string."""
    import uuid

    req_id = get_request_id()
    parsed = uuid.UUID(req_id, version=4)
    assert str(parsed) == req_id


def test_get_request_id_unique() -> None:
    """Consecutive calls should return different IDs."""
    ids = {get_request_id() for _ in range(100)}
    assert len(ids) == 100
