"""Encrypted MCP headers and environment variables, resolved at runtime."""
import json
import re

from credential_crypto import AgentCredentialError, decrypt_agent_credential, encrypt_agent_credential

ENCRYPTED_HEADERS = "_encrypted_http_headers"
ENCRYPTED_ENV = "_encrypted_mcp_env"
_PURPOSE = "mcp-http-headers"
_ENV_PURPOSE = "mcp-env"
MCP_AUTH_MODES = {"none", "manual", "current_user"}


def system_auth_mode(definition, personal=None):
    source = personal if personal is not None else definition
    return getattr(source, "auth_mode", None) or "manual"


def read_headers(config):
    if ENCRYPTED_HEADERS in config:
        return json.loads(decrypt_agent_credential(config[ENCRYPTED_HEADERS], purpose=_PURPOSE))
    return dict(config.get("headers") or {})


def store_headers(config, changes):
    previous = {key.lower(): value for key, value in read_headers(config).items()}
    headers = {}
    seen = set()
    for key, value in changes.items():
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or key.lower() in seen:
            raise ValueError("Invalid or duplicate HTTP header name")
        seen.add(key.lower())
        if value is None:
            if key.lower() not in previous:
                raise ValueError("No saved value for HTTP header")
            value = previous[key.lower()]
        if not isinstance(value, str) or any(ord(char) < 32 or ord(char) > 255 or ord(char) == 127 for char in value):
            raise ValueError("Invalid HTTP header value")
        headers[key] = value
    encrypted = encrypt_agent_credential(json.dumps(headers), purpose=_PURPOSE)
    if encrypted is None:
        raise AgentCredentialError("AGENT_CREDENTIAL_ENCRYPTION_KEY is required to save connector headers")
    result = dict(config)
    result.pop("headers", None)
    result[ENCRYPTED_HEADERS] = encrypted
    return result


def read_env(config):
    if ENCRYPTED_ENV in config:
        return json.loads(decrypt_agent_credential(config[ENCRYPTED_ENV], purpose=_ENV_PURPOSE))
    return dict(config.get("env") or {})


def store_env(config, changes):
    previous = read_env(config)
    env = dict(previous)
    for key, value in changes.items():
        if not isinstance(key, str):
            raise ValueError("Invalid environment variable name")
        key = key.strip()
        if not key or "=" in key or any(ord(char) < 32 or ord(char) == 127 for char in key):
            raise ValueError("Invalid environment variable name")
        if value is None:
            if key not in previous:
                raise ValueError("No saved value for environment variable")
            value = previous[key]
        if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Invalid environment variable value")
        env[key] = value
    encrypted = encrypt_agent_credential(json.dumps(env), purpose=_ENV_PURPOSE)
    if encrypted is None:
        raise AgentCredentialError("AGENT_CREDENTIAL_ENCRYPTION_KEY is required to save MCP environment variables")
    result = dict(config)
    result.pop("env", None)
    result[ENCRYPTED_ENV] = encrypted
    return result


def resolve_env(config, secret_env, namespace):
    if ENCRYPTED_ENV not in config:
        return config
    env = read_env(config)
    result = dict(config)
    result.pop(ENCRYPTED_ENV, None)
    result["env"] = {}
    for index, (key, value) in enumerate(env.items()):
        env_name = f"AIHUB_MCP_ENV_{namespace}_{index}"
        secret_env[env_name] = value
        result["env"][key] = "${" + env_name + "}"
    return result


def resolve_headers(
    config,
    secret_env,
    namespace,
    personal_headers=None,
    *,
    auth_mode="manual",
    request_authorization=None,
):
    if auth_mode not in MCP_AUTH_MODES:
        raise RuntimeError(f"Unsupported MCP authentication mode: {auth_mode}")
    if (
        ENCRYPTED_HEADERS not in config
        and personal_headers is None
        and auth_mode == "manual"
    ):
        return config
    headers = read_headers(config)
    if personal_headers is not None:
        overrides = read_headers({ENCRYPTED_HEADERS: personal_headers})
        overridden_names = {name.lower() for name in overrides}
        headers = {name: value for name, value in headers.items() if name.lower() not in overridden_names}
        headers.update(overrides)
    headers = {
        name: value
        for name, value in headers.items()
        if auth_mode == "manual" or name.lower() != "authorization"
    }
    if auth_mode == "current_user":
        if not request_authorization:
            raise RuntimeError(
                "连接器已设置为复用当前登录身份，但本次请求没有可用的 Bearer Token"
            )
        headers["Authorization"] = request_authorization
    result = dict(config)
    result.pop(ENCRYPTED_HEADERS, None)
    result["headers"] = {}
    for index, (key, value) in enumerate(headers.items()):
        env_name = f"AIHUB_MCP_HEADER_{namespace}_{index}"
        secret_env[env_name] = value
        result["headers"][key] = "${" + env_name + "}"
    return result
