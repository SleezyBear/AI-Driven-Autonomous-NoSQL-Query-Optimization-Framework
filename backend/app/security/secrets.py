"""AES-256-GCM encryption for control-plane secrets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from secrets import token_bytes
from typing import cast

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MASTER_KEY_PATH = Path("/run/secrets/control_plane_master_key")
NONCE_LENGTH = 12
MASTER_KEY_LENGTH = 32


class MasterKeyError(ValueError):
    """Raised when the file-backed AES-256 key is unavailable or invalid."""


@dataclass(frozen=True)
class SecretMetadata:
    """Identifiers that must be authenticated with an encrypted secret."""

    secret_id: str
    target_id: str
    secret_type: str
    key_version: str

    def associated_data(self) -> bytes:
        """Return a deterministic AAD representation for AES-GCM."""
        return "|".join((self.secret_id, self.target_id, self.secret_type, self.key_version)).encode(
            "utf-8"
        )


@dataclass(frozen=True)
class EncryptedSecretPayload:
    """Ciphertext fields suitable for storage without plaintext or master-key material."""

    nonce: bytes
    ciphertext: bytes
    key_version: str


def load_master_key(path: Path = MASTER_KEY_PATH) -> bytes:
    """Read the exact 32-byte AES-256 key from the mounted secret file."""
    try:
        key = path.read_bytes()
    except OSError as error:
        raise MasterKeyError(f"Unable to read master key file: {path}") from error
    if len(key) != MASTER_KEY_LENGTH:
        raise MasterKeyError("Control-plane master key must contain exactly 32 bytes.")
    return key


class SecretCipher:
    """Encrypt and decrypt secrets while authenticating immutable secret metadata."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != MASTER_KEY_LENGTH:
            raise MasterKeyError("Control-plane master key must contain exactly 32 bytes.")
        self._cipher = AESGCM(master_key)

    def encrypt(self, plaintext: bytes, metadata: SecretMetadata) -> EncryptedSecretPayload:
        """Encrypt plaintext with a fresh 12-byte AES-GCM nonce."""
        nonce = token_bytes(NONCE_LENGTH)
        return EncryptedSecretPayload(
            nonce=nonce,
            ciphertext=self._cipher.encrypt(nonce, plaintext, metadata.associated_data()),
            key_version=metadata.key_version,
        )

    def decrypt(self, payload: EncryptedSecretPayload, metadata: SecretMetadata) -> bytes:
        """Decrypt a payload only when its authenticated metadata is unchanged."""
        if len(payload.nonce) != NONCE_LENGTH:
            raise ValueError("Encrypted secret nonce must contain exactly 12 bytes.")
        if payload.key_version != metadata.key_version:
            raise ValueError("Encrypted secret key version does not match authenticated metadata.")
        return cast(bytes, self._cipher.decrypt(payload.nonce, payload.ciphertext, metadata.associated_data()))
