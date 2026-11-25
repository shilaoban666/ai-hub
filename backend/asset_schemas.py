"""Request schemas for versioned enterprise assets."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SkillInstallRequest(BaseModel):
    release_id: Optional[int] = Field(default=None, gt=0)
    skill_id: Optional[int] = Field(default=None, gt=0)
    agent_id: Optional[int] = Field(default=None, gt=0)


class SkillDevelopmentRequest(BaseModel):
    enabled: bool
    agent_id: Optional[int] = Field(default=None, gt=0)


class SkillChangeReleaseRequest(BaseModel):
    release_id: Optional[int] = Field(default=None, gt=0)
    use_latest: bool = False
    agent_id: Optional[int] = Field(default=None, gt=0)


class SystemSkillInstallRequest(BaseModel):
    release_id: int = Field(gt=0)


class SkillReviewRequest(BaseModel):
    native_approved: bool = False
    reason: Optional[str] = Field(default=None, max_length=1000)


class SkillRevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class AssetBindingRequest(BaseModel):
    agent_id: int = Field(gt=0)


class CredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    secret: str = Field(min_length=1, max_length=20_000)


class CredentialRotateRequest(BaseModel):
    secret: str = Field(min_length=1, max_length=20_000)


class McpDefinitionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=20_000)
    transport_type: str = Field(pattern="^(stdio|sse|http|streamable_http|streamable-http|json)$")
    config: dict[str, Any]
    is_public: bool = False
    headers: Optional[dict[str, str]] = Field(default=None, max_length=50)
    env: Optional[dict[str, str]] = Field(default=None, max_length=50)
    source_mcp_service_id: Optional[int] = Field(default=None, gt=0)
    auth_mode: Literal["none", "manual", "current_user"] = "manual"


class McpHeadersUpdateRequest(BaseModel):
    headers: dict[str, Optional[str]] = Field(max_length=50)
    auth_mode: Literal["none", "manual", "current_user"] = "manual"
    inherit_system: bool = False
    agent_id: Optional[int] = Field(default=None, gt=0)


class McpSecretUpdateRequest(BaseModel):
    """Update one connection's HTTP headers or stdio environment variables."""
    values: dict[str, Optional[str]] = Field(default_factory=dict, max_length=50)
    agent_id: Optional[int] = Field(default=None, gt=0)


class McpImportRequest(BaseModel):
    agent_id: Optional[int] = Field(default=None, gt=0)
    source_mcp_service_id: int = Field(gt=0)
    # Values belong to the destination resource-center connection, never the
    # MCP management record being imported.
    secrets: Optional[dict[str, dict[str, str]]] = Field(default=None, max_length=2)
    auth_mode: Literal["none", "manual", "current_user"] = "manual"


class McpRevisionCreateRequest(BaseModel):
    config: dict[str, Any]


class McpConnectionCreateRequest(BaseModel):
    definition_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    credential_reference_id: Optional[int] = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=100)
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    auth_mode: Literal["none", "manual", "current_user"] = "manual"
    agent_id: Optional[int] = Field(default=None, gt=0)
    tool_policy: dict[str, Any] = Field(default_factory=dict)


class McpConnectionUpdateRequest(BaseModel):
    agent_id: Optional[int] = Field(default=None, gt=0)
    revision_id: Optional[int] = Field(default=None, gt=0)
    credential_reference_id: Optional[int] = Field(default=None, gt=0)
    clear_credential: bool = False
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    config_overrides: Optional[dict[str, Any]] = None
    auth_mode: Optional[Literal["none", "manual", "current_user"]] = None
    tool_policy: Optional[dict[str, Any]] = None


class McpConnectionStatusRequest(BaseModel):
    status: Literal["active", "disabled"]
    agent_id: Optional[int] = Field(default=None, gt=0)


class PromptImportRequest(BaseModel):
    agent_id: Optional[int] = Field(default=None, gt=0)
    source_template_id: int = Field(gt=0)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)


class PromptBindingRequest(BaseModel):
    agent_id: int = Field(gt=0)
    position: int = Field(default=0, ge=0, le=1000)


class SystemPromptCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="其他", min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=200_000)
    variables: Optional[str] = Field(default=None, max_length=100_000)
    description: Optional[str] = Field(default=None, max_length=20_000)
    source_template_id: Optional[int] = Field(default=None, gt=0)


class SystemPromptUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    content: Optional[str] = Field(default=None, min_length=1, max_length=200_000)
    variables: Optional[str] = Field(default=None, max_length=100_000)
    description: Optional[str] = Field(default=None, max_length=20_000)
