"""Tests for AES-256-GCM secret storage protection."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from app.security.secrets import EncryptedSecretPayload, SecretCipher, SecretMetadata


@pytest.fixture
def metadata() -> SecretMetadata:
    return SecretMetadata(
        secret_id="secret-1",
        target_id="target-1",
        secret_type="MONGODB_EXECUTOR",
        key_version="v1",
    )


def test_ciphertext_does_not_reveal_plaintext(metadata: SecretMetadata) -> None:
    plaintext = b"mongodb://executor:password@database.example"
    cipher = SecretCipher(b"a" * 32)
    payload = cipher.encrypt(plaintext, metadata)

    assert payload.nonce != b""
    assert len(payload.nonce) == 12
    assert plaintext not in payload.ciphertext
    assert cipher.decrypt(payload, metadata) == plaintext


def test_altered_aad_prevents_decryption(metadata: SecretMetadata) -> None:
    cipher = SecretCipher(b"a" * 32)
    payload = cipher.encrypt(b"secret", metadata)
    altered_metadata = SecretMetadata(
        secret_id=metadata.secret_id,
        target_id="other-target",
        secret_type=metadata.secret_type,
        key_version=metadata.key_version,
    )

    with pytest.raises(InvalidTag):
        cipher.decrypt(payload, altered_metadata)


def test_nonce_is_random_for_each_encryption(metadata: SecretMetadata) -> None:
    cipher = SecretCipher(b"a" * 32)
    first = cipher.encrypt(b"same plaintext", metadata)
    second = cipher.encrypt(b"same plaintext", metadata)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_mismatched_key_version_is_rejected(metadata: SecretMetadata) -> None:
    cipher = SecretCipher(b"a" * 32)
    payload = cipher.encrypt(b"secret", metadata)
    invalid_payload = EncryptedSecretPayload(
        nonce=payload.nonce,
        ciphertext=payload.ciphertext,
        key_version="v2",
    )

    with pytest.raises(ValueError, match="key version"):
        cipher.decrypt(invalid_payload, metadata)

