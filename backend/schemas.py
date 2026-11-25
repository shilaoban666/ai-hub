from pydantic import AfterValidator, BeforeValidator, BaseModel, Field, field_validator
from typing import Annotated, Dict, Literal, Optional, List
from datetime import datetime
from decimal import Decimal
from runtimes import validate_runtime_type

RuntimeType = Annotated[str, AfterValidator(validate_runtime_type)]


def normalize_conversation_examples(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [item.strip() if isinstance(item, str) else item
                for item in value if not isinstance(item, str) or item.strip()]
    return value


ConversationExamples = Annotated[
    List[Annotated[str, Field(min_length=1, max_length=1000)]],
    Field(max_length=10), BeforeValidator(normalize_conversation_examples),
]


class SkillBase(BaseModel):
    name: str
    version: str
    description: Optional[str] = None
    conversation_examples: ConversationExamples = Field(default_factory=list)
    author: Optional[str] = None
    module: Optional[str] = None
    roles: Optional[str] = None
    rating: Optional[str] = None
    comment_count: Optional[int] = 0
    icon: Optional[str] = None
    cover: Optional[str] = None
    content: Optional[str] = None
    files: Optional[str] = None
    is_deleted: Optional[bool] = False
    is_public: Optional[bool] = False


class SkillCreate(SkillBase):
    git_sync_direction: Optional[int] = 0  # 0=不同步, 1=git→本地, 2=本地→git


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    conversation_examples: ConversationExamples = Field(default_factory=list)
    author: Optional[str] = None
    module: Optional[str] = None
    roles: Optional[str] = None
    rating: Optional[str] = None
    comment_count: Optional[int] = None
    icon: Optional[str] = None
    cover: Optional[str] = None
    content: Optional[str] = None
    files: Optional[str] = None
    is_public: Optional[bool] = None
    git_sync_direction: Optional[int] = None  # 0=不同步, 1=git→本地, 2=本地→git
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_access_token: Optional[str] = None


class SkillReleaseBase(BaseModel):
    version: str
    description: Optional[str] = Field(default=None, max_length=1000)


class SkillReleaseCreate(SkillReleaseBase):
    pass


class SkillReleaseResponse(SkillReleaseBase):
    id: int
    skill_id: int
    file_url: str
    created_at: datetime
    content_sha256: Optional[str] = None
    status: str = "published"
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    native_approved: bool = False
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None

    class Config:
        from_attributes = True


class SkillResponse(SkillBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    git_provider: Optional[str] = None
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_last_synced_at: Optional[datetime] = None
    git_sync_status: Optional[str] = None
    git_last_commit_sha: Optional[str] = None
    git_sync_direction: Optional[int] = 0

    class Config:
        from_attributes = True


class SkillListResponse(BaseModel):
    total: int
    items: List[SkillResponse]


class SkillCollaboratorCreate(BaseModel):
    user_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=100)


class SkillCollaboratorResponse(BaseModel):
    id: int
    skill_id: int
    user_id: int
    username: str
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True


class SkillPublicResponse(SkillBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    git_provider: Optional[str] = None
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_last_synced_at: Optional[datetime] = None
    git_sync_status: Optional[str] = None
    git_last_commit_sha: Optional[str] = None
    git_sync_direction: Optional[int] = 0

    class Config:
        from_attributes = True


class SkillPublicListResponse(BaseModel):
    total: int
    items: List[SkillPublicResponse]


# === MCP Service Schemas ===

class McpServiceBase(BaseModel):
    name: str
    type: str  # stdio / sse / streamable_http / json
    description: Optional[str] = None
    config: Optional[str] = None  # JSON 配置字符串
    usage_instructions: Optional[str] = None  # Markdown 使用说明
    tags: Optional[str] = Field(default=None, max_length=500)  # 标签，逗号分隔
    author: Optional[str] = None
    cover: Optional[str] = None
    is_public: Optional[bool] = False

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value):
        return value.strip() if isinstance(value, str) else value


class McpServiceCreate(McpServiceBase):
    pass


class McpServiceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    config: Optional[str] = None
    usage_instructions: Optional[str] = None
    tags: Optional[str] = Field(default=None, max_length=500)
    author: Optional[str] = None
    cover: Optional[str] = None
    is_public: Optional[bool] = None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value):
        return value.strip() if isinstance(value, str) else value


class McpServiceResponse(McpServiceBase):
    id: int
    is_deleted: Optional[bool] = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class McpServiceListResponse(BaseModel):
    total: int
    items: List[McpServiceResponse]


class McpServicePublicResponse(McpServiceBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class McpServicePublicListResponse(BaseModel):
    total: int
    items: List[McpServicePublicResponse]


# === AI Model Schemas ===

class ModelBase(BaseModel):
    name: str
    provider: str
    api_key: str
    api_proxy_url: Optional[str] = None
    api_protocol: Literal["openai-completions", "anthropic-messages"]
    reasoning_support: Literal["auto", "enabled", "disabled"] = "auto"
    remarks: Optional[str] = None


class ModelCreate(ModelBase):
    pass


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = None
    api_proxy_url: Optional[str] = None
    api_protocol: Optional[Literal["openai-completions", "anthropic-messages"]] = None
    reasoning_support: Optional[Literal["auto", "enabled", "disabled"]] = None
    remarks: Optional[str] = None


class ModelResponse(ModelBase):
    id: int
    # API responses never contain the secret.  The client only needs to know
    # whether a credential is configured so it can keep an empty edit field.
    has_api_key: bool = False
    scope: Literal["platform", "user"] = "user"
    is_enabled: bool = True
    health_status: str = "unknown"
    compatible_runtimes: List[str] = Field(default_factory=list)
    is_deleted: Optional[bool] = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("api_key", mode="before")
    @classmethod
    def redact_api_key(cls, _value):
        """A response schema must never materialize a model credential."""
        return ""

    class Config:
        from_attributes = True


class ModelListResponse(BaseModel):
    total: int
    items: List[ModelResponse]


# === Prompt Template Schemas ===

class PromptTemplateBase(BaseModel):
    name: str
    category: str = Field(default="其他", min_length=1, max_length=50)
    content: str
    variables: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    is_public: Optional[bool] = False

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return value.strip() if isinstance(value, str) else value


class PromptTemplateCreate(PromptTemplateBase):
    pass


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = Field(default=None, min_length=1, max_length=50)
    content: Optional[str] = None
    variables: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    is_public: Optional[bool] = None

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return value.strip() if isinstance(value, str) else value


class PromptTemplateResponse(PromptTemplateBase):
    id: int
    user_id: Optional[int] = None
    is_deleted: Optional[bool] = False
    is_system: Optional[bool] = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PromptTemplateListResponse(BaseModel):
    total: int
    items: List[PromptTemplateResponse]


class PromptTemplatePublicResponse(BaseModel):
    id: int
    name: str
    category: str
    content: str
    variables: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PromptTemplatePublicListResponse(BaseModel):
    total: int
    items: List[PromptTemplatePublicResponse]


# === Git Sync Schemas ===

class GitBindRequest(BaseModel):
    provider: str = "gitlab"  # gitlab / github
    repo_url: str
    branch: Optional[str] = "main"
    access_token: Optional[str] = None

class GitPushRequest(BaseModel):
    commit_message: Optional[str] = None
    force: bool = False

class GitPullRequest(BaseModel):
    force: bool = False

class GitSyncStatusResponse(BaseModel):
    id: int
    git_provider: Optional[str] = None
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_last_synced_at: Optional[datetime] = None
    git_sync_status: Optional[str] = None
    git_last_commit_sha: Optional[str] = None
    git_sync_direction: Optional[int] = 0

    class Config:
        from_attributes = True

class GitDiffResponse(BaseModel):
    local_changes: list
    remote_changes: list
    conflict: bool
    conflicting_files: list

class GitTestConnectionRequest(BaseModel):
    provider: str = "gitlab"  # gitlab / github
    repo_url: str
    access_token: Optional[str] = None
    branch: Optional[str] = "main"

# 兼容旧名称
GitlabBindRequest = GitBindRequest
GitlabPushRequest = GitPushRequest
GitlabPullRequest = GitPullRequest
GitlabSyncStatusResponse = GitSyncStatusResponse
GitlabDiffResponse = GitDiffResponse
GitlabTestConnectionRequest = GitTestConnectionRequest


# === Agent Schemas (基于 Claude Code 的智能体) ===

ThinkingLevel = Literal[
    "inherit", "off", "minimal", "low", "medium", "high", "xhigh",
    "adaptive", "max",
]
ReasoningVisibility = Literal["off", "on", "stream"]
WorkspaceFilePath = Annotated[str, Field(min_length=1, max_length=1000)]
McpOverrideKey = Annotated[str, Field(min_length=1, max_length=200)]
McpOverrideValue = Annotated[str, Field(max_length=20_000)]


class AgentMcpOverride(BaseModel):
    mcp_id: int = Field(gt=0)
    env: Dict[McpOverrideKey, McpOverrideValue] = Field(
        default_factory=dict,
        max_length=100,
    )
    headers: Dict[McpOverrideKey, McpOverrideValue] = Field(
        default_factory=dict,
        max_length=100,
    )


class AgentBase(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=20_000)
    icon: Optional[str] = Field(default=None, max_length=255)
    cover: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, max_length=200_000)
    default_model_id: Optional[int] = None
    runtime_type: Optional[RuntimeType] = "claude_code"
    thinking_level: ThinkingLevel = "inherit"
    reasoning_visibility: ReasoningVisibility = "off"
    max_turns: Optional[int] = Field(default=50, ge=1, le=200)
    timeout_seconds: Optional[int] = Field(default=600, ge=1, le=3600)
    model_ids: Optional[List[int]] = Field(default_factory=list, max_length=50)


class AgentCreate(AgentBase):
    skill_ids: Optional[List[int]] = Field(default_factory=list, max_length=100)
    mcp_ids: Optional[List[int]] = Field(default_factory=list, max_length=50)
    prompt_template_ids: Optional[List[int]] = Field(default_factory=list, max_length=50)
    mcp_overrides: Optional[List[AgentMcpOverride]] = Field(
        default_factory=list,
        max_length=50,
    )


class AgentUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=20_000)
    icon: Optional[str] = Field(default=None, max_length=255)
    cover: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, max_length=200_000)
    default_model_id: Optional[int] = None
    runtime_type: Optional[RuntimeType] = None
    # Confirm the exact destination, so a policy change while the dialog is
    # open cannot authorize a different runtime transition.
    confirm_runtime_change: Optional[RuntimeType] = None
    thinking_level: Optional[ThinkingLevel] = None
    reasoning_visibility: Optional[ReasoningVisibility] = None
    max_turns: Optional[int] = Field(default=None, ge=1, le=200)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    skill_ids: Optional[List[int]] = Field(default=None, max_length=100)
    mcp_ids: Optional[List[int]] = Field(default=None, max_length=50)
    prompt_template_ids: Optional[List[int]] = Field(default=None, max_length=50)
    mcp_overrides: Optional[List[AgentMcpOverride]] = Field(default=None, max_length=50)
    model_ids: Optional[List[int]] = Field(default=None, max_length=50)


class AgentResponse(AgentBase):
    can_edit: bool = True
    id: int
    user_id: int
    kind: str = "expert"
    settings_version: Optional[int] = None
    is_public: bool
    skill_ids: List[int] = []
    mcp_ids: List[int] = []
    mcp_overrides: List[AgentMcpOverride] = Field(default_factory=list)
    model_ids: List[int] = []
    models: List[dict] = []  # [{id, name, provider}]
    skills: List[dict] = []  # [{id, name, conversation_examples}]
    prompt_template_ids: List[int] = []
    prompt_templates: List[dict] = []
    skill_installation_ids: List[int] = []
    skill_bindings: List[dict] = []
    mcp_connection_ids: List[int] = []
    mcp_connections: List[dict] = []
    session_count: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    total: int
    items: List[AgentResponse]


class AgentStatisticsSummary(BaseModel):
    total_runs: int
    succeeded_runs: int
    failed_runs: int
    cancelled_runs: int
    active_runs: int
    abnormal_runs: int
    success_rate: float
    failure_rate: float
    median_duration_ms: Optional[int] = None
    p95_duration_ms: Optional[int] = None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_tokens: int
    average_tokens_per_run: int
    charged_points: Decimal = Decimal("0.00")


class AgentStatisticsTrendItem(BaseModel):
    date: str
    charged_points: Decimal = Decimal("0.00")
    total_runs: int
    succeeded_runs: int
    failed_runs: int
    cancelled_runs: int
    active_runs: int
    abnormal_runs: int
    success_rate: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_tokens: int


class AgentStatisticsSourceItem(BaseModel):
    source: str
    charged_points: Decimal = Decimal("0.00")
    total_runs: int
    succeeded_runs: int
    failed_runs: int
    cancelled_runs: int
    active_runs: int
    abnormal_runs: int
    success_rate: float


class AgentStatisticsErrorItem(BaseModel):
    error_code: str
    count: int
    last_occurred_at: Optional[datetime] = None
    latest_message: Optional[str] = None


class AgentStatisticsFailureItem(BaseModel):
    run_id: str
    status: str
    source: str
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class AgentStatisticsResponse(BaseModel):
    days: int
    start_at: datetime
    end_at: datetime
    credit_display_name: str = "积分"
    summary: AgentStatisticsSummary
    trend: List[AgentStatisticsTrendItem]
    sources: List[AgentStatisticsSourceItem]
    errors: List[AgentStatisticsErrorItem]
    recent_failures: List[AgentStatisticsFailureItem]


class AgentSessionCreate(BaseModel):
    agent_id: int
    title: Optional[str] = Field(default=None, max_length=200)


class AgentSessionResponse(BaseModel):
    id: int
    agent_id: int
    user_id: int
    title: Optional[str] = None
    active_run_id: Optional[str] = None
    active_run_status: Optional[str] = None
    active_run_started_at: Optional[datetime] = None
    claude_session_id: Optional[str] = None
    runtime_type: Optional[str] = None
    model_id: Optional[int] = None
    config_version: Optional[int] = None
    runtime_session_id: Optional[str] = None
    runtime_state: str = "active"
    source: str = "web"
    source_binding_id: Optional[int] = None
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        protected_namespaces = ()


class AgentSessionListResponse(BaseModel):
    total: int
    items: List[AgentSessionResponse]


class MessageSkillReference(BaseModel):
    id: int
    name: str


class MessageFeedbackResponse(BaseModel):
    rating: Literal["like", "dislike"]
    reasons: List[str] = Field(default_factory=list)
    comment: str = ""


class AgentMessageResponse(BaseModel):
    id: int
    role: str
    run_id: Optional[str] = None
    content: Optional[str] = None
    attached_files: List[str] = Field(default_factory=list)
    skill: Optional[MessageSkillReference] = None
    charged_points: Optional[Decimal] = None
    feedback: Optional[MessageFeedbackResponse] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentSessionMessagesResponse(BaseModel):
    session: AgentSessionResponse
    items: List[AgentMessageResponse]
    has_more: bool = False


class AgentConversationShareResponse(BaseModel):
    token: str
    created_at: Optional[datetime] = None


class PublicConversationShareResponse(BaseModel):
    title: Optional[str] = None
    agent_name: str
    agent_icon: Optional[str] = None
    shared_at: Optional[datetime] = None
    items: List[AgentMessageResponse]
    has_more: bool = False


class SavedMessageInput(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(default="", max_length=500_000)


class SaveMessagesRequest(BaseModel):
    messages: List[SavedMessageInput] = Field(default_factory=list, max_length=100)


class AgentMessageRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    content: str = Field(min_length=1, max_length=200_000)
    session_id: Optional[int] = None
    runtime_type: Optional[RuntimeType] = None
    model_id: Optional[int] = None  # 前端可覆盖模型
    skill_id: Optional[int] = None  # 前端可选指定技能（单选，基于该 skill 思考执行）
    attached_files: Optional[List[WorkspaceFilePath]] = Field(
        default_factory=list,
        max_length=20,
    )
    permission_mode: Optional[Literal["acceptEdits", "default"]] = None


class RuntimeInstanceResponse(BaseModel):
    id: Optional[int] = None
    agent_id: int
    runtime_type: str = "claude_code"
    deployment_mode: str
    external_agent_id: str
    endpoint: Optional[str] = None
    status: str
    runtime_version: Optional[str] = None
    image_ref: Optional[str] = None
    desired_config_hash: Optional[str] = None
    applied_config_hash: Optional[str] = None
    last_health_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    readiness_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PermissionRequestInternal(BaseModel):
    """runtime → 后端:兼容权限请求事件"""
    run_id: str = Field(min_length=1, max_length=32)
    req_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=200)
    tool_input: dict = Field(default_factory=dict)


class PermissionDecideRequest(BaseModel):
    """前端 → 后端:用户授权决策"""
    run_id: str = Field(min_length=1, max_length=32)
    req_id: str = Field(min_length=1, max_length=100)
    decision: Literal["allow", "deny"]
    remember: bool = False
    tool_key: Optional[str] = None
    reason: Optional[str] = None


