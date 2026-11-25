"""At-rest encryption for Agent model and MCP credentials."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass

from database import settings


_ENVELOPE_VERSION = "aesgcm1"


class AgentCredentialError(RuntimeError):
    pass


def _aesgcm_class():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except (ImportError, OSError) as exc:
        raise AgentCredentialError(
            "The cryptography package is required for Agent credential encryption"
        ) from exc
    return AESGCM


def _decode_key(value: str) -> bytes:
    raw = (value or "").strip()
    candidates: list[bytes] = []
    try:
        candidates.append(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        pass
    try:
        candidates.append(bytes.fromhex(raw))
    except ValueError:
        pass
    candidates.append(raw.encode("utf-8"))
    for candidate in candidates:
        if len(candidate) == 32:
            return candidate
    raise AgentCredentialError(
        "AGENT_CREDENTIAL_ENCRYPTION_KEY must encode exactly 32 bytes"
    )


@dataclass(frozen=True)
class AgentCredentialCrypto:
    encryption_key: bytes
    key_version: str = "v1"

    @classmethod
    def from_settings(cls, app_settings=None):
        app_settings = app_settings or settings
        raw_key = str(app_settings.agent_credential_encryption_key or "").strip()
        if not raw_key:
            return None
        return cls(
            encryption_key=_decode_key(raw_key),
            key_version=str(app_settings.agent_credential_key_version or "v1"),
        )

    def encrypt(self, value: str, *, purpose: str) -> str:
        nonce = secrets.token_bytes(12)
        ciphertext = _aesgcm_class()(self.encryption_key).encrypt(
            nonce,
            value.encode("utf-8"),
            self._aad(purpose),
        )
        return ":".join((
            _ENVELOPE_VERSION,
            self.key_version,
            self._b64(nonce),
            self._b64(ciphertext),
        ))

    def decrypt(self, envelope: str, *, purpose: str) -> str:
        try:
            version, key_version, nonce_b64, ciphertext_b64 = envelope.split(":", 3)
            if version != _ENVELOPE_VERSION:
                raise ValueError("unsupported encryption envelope")
            if key_version != self.key_version:
                raise AgentCredentialError(
                    f"Agent credential key version {key_version!r} is unavailable"
                )
            plaintext = _aesgcm_class()(self.encryption_key).decrypt(
                self._unb64(nonce_b64),
                self._unb64(ciphertext_b64),
                self._aad(purpose),
            )
            return plaintext.decode("utf-8")
        except AgentCredentialError:
            raise
        except Exception as exc:
            raise AgentCredentialError("Agent credential decryption failed") from exc

    def _aad(self, purpose: str) -> bytes:
        if not purpose:
            raise ValueError("Encryption purpose is required")
        return f"aihub-agent:{self.key_version}:{purpose}".encode("utf-8")

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encrypt_agent_credential(value, *, purpose: str, app_settings=None):
    if value is None:
        return None
    crypto = AgentCredentialCrypto.from_settings(app_settings or settings)
    if crypto is None:
        return None
    return crypto.encrypt(str(value), purpose=purpose)


def decrypt_agent_credential(envelope: str, *, purpose: str, app_settings=None) -> str:
    crypto = AgentCredentialCrypto.from_settings(app_settings or settings)
    if crypto is None:
        raise AgentCredentialError(
            "AGENT_CREDENTIAL_ENCRYPTION_KEY is required to decrypt stored credentials"
        )
    return crypto.decrypt(envelope, purpose=purpose)
