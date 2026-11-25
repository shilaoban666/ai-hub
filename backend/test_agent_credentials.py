from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from credential_crypto import AgentCredentialCrypto, AgentCredentialError
from database import Base
from models import Agent, AIModel, McpService
from schemas import McpServiceResponse, ModelResponse


class _FakeAESGCM:
    def __init__(self, _key):
        pass

    def encrypt(self, _nonce, value, aad):
        return value + b"|" + aad

    def decrypt(self, _nonce, value, aad):
        suffix = b"|" + aad
        if not value.endswith(suffix):
            raise ValueError("bad aad")
        return value[:-len(suffix)]


def _settings(key="x" * 32):
    return SimpleNamespace(
        agent_credential_encryption_key=key,
        agent_credential_key_version="v1",
    )


def test_legacy_plaintext_remains_readable_without_key():
    model = AIModel(id=1, user_id=7, name="m", provider="p", api_key="legacy")
    mcp = McpService(id=2, user_id=7, name="s", type="stdio", config='{"token":"legacy"}')
    assert model.api_key == "legacy"
    assert mcp.config == '{"token":"legacy"}'
    assert model.api_key_encrypted is None
    assert mcp.config_encrypted is None


def test_model_and_mcp_credentials_encrypt_and_round_trip():
    app_settings = _settings()
    with (
        patch("credential_crypto._aesgcm_class", return_value=_FakeAESGCM),
        patch("credential_crypto.settings", app_settings),
    ):
        model = AIModel(id=1, user_id=7, name="m", provider="p", api_key="legacy")
        model.store_api_key("secret-key", app_settings=app_settings)
        assert model._api_key_plaintext == ""
        assert model.api_key_encrypted.startswith("aesgcm1:v1:")
        assert model.api_key == "secret-key"

        mcp = McpService(id=2, user_id=7, name="s", type="sse", config="legacy")
        mcp.store_config('{"headers":{"Authorization":"Bearer secret"}}', app_settings)
        assert mcp._config_plaintext is None
        assert mcp.config_encrypted.startswith("aesgcm1:v1:")
        assert "Bearer secret" in mcp.config


def test_ciphertext_is_bound_to_record_identity():
    app_settings = _settings()
    with (
        patch("credential_crypto._aesgcm_class", return_value=_FakeAESGCM),
        patch("credential_crypto.settings", app_settings),
    ):
        source = AIModel(id=1, user_id=7, name="m1", provider="p", api_key="")
        source.store_api_key("secret", app_settings=app_settings)
        target = AIModel(id=2, user_id=7, name="m2", provider="p", api_key="")
        target.api_key_encrypted = source.api_key_encrypted
        try:
            _ = target.api_key
        except AgentCredentialError:
            pass
        else:
            raise AssertionError("ciphertext copied to another record must not decrypt")


def test_agent_mcp_overrides_are_encrypted_and_identity_bound():
    app_settings = _settings()
    with (
        patch("credential_crypto._aesgcm_class", return_value=_FakeAESGCM),
        patch("credential_crypto.settings", app_settings),
    ):
        agent = Agent(id=4, user_id=7, name="agent")
        overrides = [{
            "mcp_id": 2,
            "env": {},
            "headers": {"Authorization": "Bearer secret"},
        }]
        agent.store_mcp_overrides(overrides, app_settings=app_settings)
        assert agent.mcp_overrides_encrypted.startswith("aesgcm1:v1:")
        assert agent.mcp_overrides == overrides

        other = Agent(id=5, user_id=7, name="other")
        other.mcp_overrides_encrypted = agent.mcp_overrides_encrypted
        try:
            _ = other.mcp_overrides
        except AgentCredentialError:
            pass
        else:
            raise AssertionError("MCP overrides copied to another Agent must not decrypt")


def test_encrypted_values_persist_and_keep_api_response_shape():
    app_settings = _settings()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with (
        patch("credential_crypto._aesgcm_class", return_value=_FakeAESGCM),
        patch("credential_crypto.settings", app_settings),
    ):
        db = factory()
        model = AIModel(
            id=1,
            user_id=7,
            name="model",
            provider="provider",
            api_key="",
            api_protocol="openai-completions",
            reasoning_support="auto",
            is_deleted=False,
        )
        model.store_api_key("secret-key", app_settings=app_settings)
        mcp = McpService(
            id=2,
            user_id=7,
            name="mcp",
            type="sse",
            config=None,
            is_deleted=False,
            is_public=False,
        )
        mcp.store_config('{"headers":{"Authorization":"Bearer secret"}}', app_settings)
        db.add_all([model, mcp])
        db.commit()
        db.expire_all()

        stored_model = db.query(AIModel).filter_by(id=1).one()
        stored_mcp = db.query(McpService).filter_by(id=2).one()
        assert stored_model._api_key_plaintext == ""
        assert stored_mcp._config_plaintext is None
        assert ModelResponse.model_validate(stored_model).api_key == ""
        assert "Bearer secret" in McpServiceResponse.model_validate(stored_mcp).config
        db.close()


def test_invalid_or_missing_key_fails_closed_for_encrypted_values():
    crypto = AgentCredentialCrypto(b"x" * 32)
    with patch("credential_crypto._aesgcm_class", return_value=_FakeAESGCM):
        envelope = crypto.encrypt("secret", purpose="ai-model:7:1:api-key")
    model = AIModel(id=1, user_id=7, name="m", provider="p", api_key="")
    model.api_key_encrypted = envelope
    with patch("credential_crypto.settings", _settings(key="")):
        try:
            _ = model.api_key
        except AgentCredentialError:
            pass
        else:
            raise AssertionError("encrypted values must not fall back to stale plaintext")


if __name__ == "__main__":
    test_legacy_plaintext_remains_readable_without_key()
    test_model_and_mcp_credentials_encrypt_and_round_trip()
    test_ciphertext_is_bound_to_record_identity()
    test_agent_mcp_overrides_are_encrypted_and_identity_bound()
    test_encrypted_values_persist_and_keep_api_response_shape()
    test_invalid_or_missing_key_fails_closed_for_encrypted_values()
    print("agent credential tests passed")
