import json

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import CHAR, LONGTEXT
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base
from credit_labels import DEFAULT_CREDIT_DISPLAY_NAME


CHANNEL_BIND_SESSION_ID_TYPE = String(32).with_variant(
    CHAR(32, charset="ascii", collation="ascii_bin"),
    "mysql",
)


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    version = Column(String(20), nullable=False)
    description = Column(Text)
    conversation_examples = Column(JSON, nullable=True, default=list)
    development_mode = Column(Boolean, nullable=False, default=False, server_default="0")
    author = Column(String(100))
    module = Column(String(200))
    roles = Column(String(500))
    rating = Column(String(10))
    comment_count = Column(Integer, default=0)
    install_count = Column(BigInteger, nullable=False, default=0, server_default="0")
    icon = Column(String(255))
    cover = Column(String(500))  # 存储封面图片的URL路径
    content = Column(Text)
    files = Column(Text)
    is_deleted = Column(Boolean, default=False, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Git 绑定字段
    git_provider = Column(String(20), nullable=True, default="gitlab")  # gitlab / github
    git_repo_url = Column(String(500), nullable=True)
    git_branch = Column(String(100), nullable=True, default="main")
    git_access_token = Column(String(200), nullable=True)
    git_last_synced_at = Column(DateTime(timezone=True), nullable=True)
    git_sync_status = Column(String(20), nullable=True)  # never/synced/syncing/error
    git_last_commit_sha = Column(String(40), nullable=True)
    git_sync_direction = Column(Integer, nullable=False, default=0)  # 0=不同步, 1=git→本地, 2=本地→git

    # 关联发布历史
    releases = relationship("SkillRelease", back_populates="skill")
    collaborators = relationship(
        "SkillCollaborator",
        back_populates="skill",
        cascade="all, delete-orphan",
    )


class SkillCollaborator(Base):
    __tablename__ = "skill_collaborators"
    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="uq_skill_collaborators_skill_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(100), nullable=False)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    skill = relationship("Skill", back_populates="collaborators")


class SkillRelease(Base):
    __tablename__ = "skill_releases"

    id = Column(Integer, primary_key=True, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False)
    version = Column(String(20), nullable=False, index=True)
    description = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=False)
    content_sha256 = Column(String(64), nullable=True, index=True)
    manifest_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    status = Column(String(20), nullable=False, default="published", server_default="published", index=True)
    scan_status = Column(String(20), nullable=False, default="not_required", server_default="not_required")
    scan_report_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    published_by = Column(Integer, nullable=True)
    reviewed_by = Column(Integer, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    native_approved = Column(Boolean, nullable=False, default=False, server_default="0")
    revoked_by = Column(Integer, nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revocation_reason = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关联技能
    skill = relationship("Skill", back_populates="releases")


class McpService(Base):
    __tablename__ = "mcp_services"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text)
    type = Column(String(20), nullable=False)  # stdio / sse / streamable_http / json
    _config_plaintext = Column("config", Text)  # Legacy plaintext for dual-read migration.
    config_encrypted = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    usage_instructions = Column(Text)  # Markdown 使用说明
    tags = Column(String(500))  # 标签，逗号分隔
    author = Column(String(100))
    cover = Column(String(500))
    is_deleted = Column(Boolean, default=False, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def config(self):
        if self.config_encrypted:
            from credential_crypto import decrypt_agent_credential

            return decrypt_agent_credential(
                self.config_encrypted,
                purpose=f"mcp-service:{self.user_id}:{self.id}:config",
            )
        return self._config_plaintext

    @config.setter
    def config(self, value):
        self._config_plaintext = value
        self.config_encrypted = None

    def store_config(self, value, app_settings=None):
        from credential_crypto import encrypt_agent_credential

        encrypted = encrypt_agent_credential(
            value,
            purpose=f"mcp-service:{self.user_id}:{self.id}:config",
            app_settings=app_settings,
        )
        if encrypted is None:
            self._config_plaintext = value
            self.config_encrypted = None
        else:
            self._config_plaintext = None
            self.config_encrypted = encrypted


class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    scope = Column(String(20), nullable=False, default="user", server_default="user", index=True)
    is_enabled = Column(Boolean, nullable=False, default=True, server_default="1", index=True)
    health_status = Column(String(20), nullable=False, default="unknown", server_default="unknown")
    name = Column(String(100), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    _api_key_plaintext = Column("api_key", String(500), nullable=False, default="")
    api_key_encrypted = Column(Text, nullable=True)
    api_proxy_url = Column(String(500))
    api_protocol = Column(String(30), nullable=False, default="openai-completions")
    reasoning_support = Column(String(10), nullable=False, default="auto")
    remarks = Column(String(200), nullable=True, comment='备注，用于区分同名模型的不同来源')
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def compatible_runtimes(self):
        from model_compat import compatible_runtime_types

        return compatible_runtime_types(self)

    @property
    def has_api_key(self):
        """Expose credential presence without decrypting the credential."""
        return bool(self.api_key_encrypted or self._api_key_plaintext)

    @property
    def api_key(self):
        if self.api_key_encrypted:
            from credential_crypto import decrypt_agent_credential

            return decrypt_agent_credential(
                self.api_key_encrypted,
                purpose=f"ai-model:{self.user_id}:{self.id}:api-key",
            )
        return self._api_key_plaintext or ""

    @api_key.setter
    def api_key(self, value):
        self._api_key_plaintext = value or ""
        self.api_key_encrypted = None

    def store_api_key(self, value, app_settings=None):
        from credential_crypto import encrypt_agent_credential

        normalized = value or ""
        encrypted = encrypt_agent_credential(
            normalized,
            purpose=f"ai-model:{self.user_id}:{self.id}:api-key",
            app_settings=app_settings,
        )
        if encrypted is None:
            self._api_key_plaintext = normalized
            self.api_key_encrypted = None
        else:
            self._api_key_plaintext = ""
            self.api_key_encrypted = encrypted


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    category = Column(String(50), nullable=False, default="其他")
    content = Column(Text, nullable=False)
    variables = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    author = Column(String(100))
    is_deleted = Column(Boolean, default=False, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False, index=True)
    source_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=True, index=True)
    source_snapshot_hash = Column(String(64), nullable=True)
    imported_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WorkspacePromptReference(Base):
    """A workbench subscription to an author's template, without copying content."""

    __tablename__ = "workspace_prompt_references"

    user_id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("prompt_templates.id"), primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkspacePromptRemoval(Base):
    """Per-user workbench visibility; never deletes the source template."""

    __tablename__ = "workspace_prompt_removals"

    user_id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("prompt_templates.id"), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# === Agent Models (基于 Claude Code 的智能体) ===

# 智能体 ↔ Skill 多对多关联表
class UserWorkspace(Base):
    """Persistent file space owned by a user or one expert agent."""

    __tablename__ = "user_workspaces"
    __table_args__ = (
        UniqueConstraint("user_id", "agent_id", name="uq_user_workspaces_user_agent"),
        UniqueConstraint("user_id", "scope_agent_id", name="uq_user_workspaces_user_scope"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    workspace_key = Column(String(32), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    # MySQL treats NULL values as distinct in a unique key. Map the legacy
    # personal workspace (agent_id=NULL) to one stable scope for uniqueness.
    scope_agent_id = Column(
        BigInteger,
        Computed("COALESCE(agent_id, 0)", persisted=True),
        nullable=False,
    )
    status = Column(String(20), nullable=False, default="ready", server_default="ready", index=True)
    storage_path = Column(String(500), nullable=True)
    quota_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    used_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    migration_status = Column(
        String(30), nullable=False, default="not_required", server_default="not_required"
    )
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RuntimeCell(Base):
    """Logical pre-allocation for a user's hibernatable Runtime boundary."""

    __tablename__ = "runtime_cells"
    __table_args__ = (
        UniqueConstraint("user_id", "agent_id", name="uq_runtime_cells_user_agent"),
        UniqueConstraint("user_id", "scope_agent_id", name="uq_runtime_cells_user_scope"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id = Column(
        BigInteger, ForeignKey("user_workspaces.id"), nullable=False, unique=True, index=True
    )
    user_id = Column(Integer, nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    scope_agent_id = Column(
        BigInteger,
        Computed("COALESCE(agent_id, 0)", persisted=True),
        nullable=False,
    )
    runtime_type = Column(
        String(30), nullable=False, default="claude_code", server_default="claude_code"
    )
    sandbox_type = Column(String(20), nullable=False, default="container", server_default="container")
    status = Column(
        String(30), nullable=False, default="unprovisioned", server_default="unprovisioned", index=True
    )
    container_name = Column(String(200), nullable=True)
    image_ref = Column(String(500), nullable=True)
    desired_config_hash = Column(String(64), nullable=True)
    applied_config_hash = Column(String(64), nullable=True)
    last_started_at = Column(DateTime(timezone=True), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    hibernated_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserExecutionGate(Base):
    """Serialize cross-workspace admission decisions for one user's runs."""

    __tablename__ = "user_execution_gates"
    user_id = Column(Integer, primary_key=True)


class WorkspaceExecutionLease(Base):
    """One renewable, fenced writer lease per user workspace."""

    __tablename__ = "workspace_execution_leases"

    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), primary_key=True)
    run_id = Column(String(32), nullable=True, index=True)
    owner_id = Column(String(100), nullable=True)
    fencing_token = Column(BigInteger, nullable=False, default=0, server_default="0")
    lease_until = Column(DateTime(timezone=True), nullable=False, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkspaceRunView(Base):
    """Auditable lifecycle record for one isolated execution view."""

    __tablename__ = "workspace_run_views"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(32), ForeignKey("agent_runs.id"), nullable=False, unique=True, index=True)
    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="preparing", server_default="preparing", index=True)
    host_path = Column(String(500), nullable=True)
    sandbox_ref = Column(String(300), nullable=True)
    config_hash = Column(String(64), nullable=True)
    cleanup_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    prepared_at = Column(DateTime(timezone=True), nullable=True)
    cleaned_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SkillInstallation(Base):
    """A user's installation pinned to one immutable Skill release."""

    __tablename__ = "skill_installations"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_agent_id", "skill_id", name="uq_skill_installations_user_scope_skill"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    scope_agent_id = Column(Integer, nullable=False, default=0, server_default="0", index=True)
    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    release_id = Column(Integer, ForeignKey("skill_releases.id"), nullable=False, index=True)
    previous_release_id = Column(Integer, ForeignKey("skill_releases.id"), nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    granted_capabilities = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    installed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SystemSkillInstallation(Base):
    """An administrator-managed skill baseline available to every user."""

    __tablename__ = "system_skill_installations"
    __table_args__ = (
        UniqueConstraint("skill_id", name="uq_system_skill_installations_skill"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    release_id = Column(Integer, ForeignKey("skill_releases.id"), nullable=False, index=True)
    previous_release_id = Column(Integer, ForeignKey("skill_releases.id"), nullable=True)
    granted_capabilities = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    created_by = Column(Integer, nullable=False, index=True)
    installed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExpertSkillBinding(Base):
    __tablename__ = "expert_skill_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "installation_id", name="uq_expert_skill_binding"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    installation_id = Column(
        BigInteger, ForeignKey("skill_installations.id"), nullable=False, index=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CredentialReference(Base):
    """Versioned encrypted user secret referenced by MCP connections."""

    __tablename__ = "credential_references"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_agent_id", "name", name="uq_credential_references_user_scope_name"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    scope_agent_id = Column(Integer, nullable=False, default=0, server_default="0", index=True)
    name = Column(String(100), nullable=False)
    secret_encrypted = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    last_rotated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class McpDefinition(Base):
    __tablename__ = "mcp_definitions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, nullable=True, index=True)
    scope = Column(String(20), nullable=False, default="user", server_default="user", index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    transport_type = Column(String(30), nullable=False)
    auth_mode = Column(String(30), nullable=False, default="manual", server_default="manual")
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    source_mcp_service_id = Column(Integer, ForeignKey("mcp_services.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class McpRevision(Base):
    __tablename__ = "mcp_revisions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_mcp_revision_definition_version"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    definition_id = Column(BigInteger, ForeignKey("mcp_definitions.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    config_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    content_sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="published", server_default="published", index=True)
    security_report_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class McpUserHeaders(Base):
    """Personal HTTP headers layered over an administrator-provided MCP."""

    __tablename__ = "mcp_user_headers"

    user_id = Column(Integer, primary_key=True)
    definition_id = Column(BigInteger, ForeignKey("mcp_definitions.id"), primary_key=True)
    headers_encrypted = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    auth_mode = Column(String(30), nullable=False, default="manual", server_default="manual")
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class McpConnection(Base):
    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_agent_id", "name", name="uq_mcp_connections_user_scope_name"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    scope_agent_id = Column(Integer, nullable=False, default=0, server_default="0", index=True)
    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), nullable=False, index=True)
    definition_id = Column(BigInteger, ForeignKey("mcp_definitions.id"), nullable=False, index=True)
    revision_id = Column(BigInteger, ForeignKey("mcp_revisions.id"), nullable=False, index=True)
    credential_reference_id = Column(
        BigInteger, ForeignKey("credential_references.id"), nullable=True, index=True
    )
    name = Column(String(100), nullable=False)
    config_overrides_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    auth_mode = Column(String(30), nullable=False, default="manual", server_default="manual")
    tool_policy_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    last_test_status = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExpertMcpBinding(Base):
    __tablename__ = "expert_mcp_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "connection_id", name="uq_expert_mcp_binding"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    connection_id = Column(BigInteger, ForeignKey("mcp_connections.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssetSecurityEvent(Base):
    """Append-only audit trail for asset scanning, approval and revocation."""

    __tablename__ = "asset_security_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    asset_type = Column(String(30), nullable=False, index=True)
    asset_id = Column(BigInteger, nullable=False, index=True)
    action = Column(String(30), nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=False, index=True)
    reason = Column(String(1000), nullable=True)
    details_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


agent_skills = Table(
    "agent_skills", Base.metadata,
    Column("agent_id", Integer, ForeignKey("agents.id"), primary_key=True),
    Column("skill_id", Integer, ForeignKey("skills.id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now()),
)

# 智能体 ↔ MCP 多对多关联表
agent_mcps = Table(
    "agent_mcps", Base.metadata,
    Column("agent_id", Integer, ForeignKey("agents.id"), primary_key=True),
    Column("mcp_service_id", Integer, ForeignKey("mcp_services.id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now()),
)

# 智能体 ↔ AI Model 多对多关联表
agent_models = Table(
    "agent_models", Base.metadata,
    Column("agent_id", Integer, ForeignKey("agents.id"), primary_key=True),
    Column("model_id", Integer, ForeignKey("ai_models.id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now()),
)

# 自定义 Agent ↔ 提示词模板关联表。主提示词仍保存在 Agent.system_prompt，
# 这里的模板按 position 顺序展示，供用户选择并填入对话，不自动注入主提示词。
agent_prompt_templates = Table(
    "agent_prompt_templates", Base.metadata,
    Column("agent_id", Integer, ForeignKey("agents.id"), primary_key=True),
    Column("prompt_template_id", Integer, ForeignKey("prompt_templates.id"), primary_key=True),
    Column("position", Integer, nullable=False, default=0, server_default="0"),
    # Historical 051 data only; live references never read/write this content.
    Column("snapshot_json", Text().with_variant(LONGTEXT, "mysql"), nullable=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now()),
)


class Agent(Base):
    """智能体 - 支持多 runtime 的云端智能体配置"""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), nullable=True, index=True)
    kind = Column(String(30), nullable=False, default="expert", server_default="expert", index=True)
    default_agent_user_id = Column(Integer, nullable=True, unique=True)
    settings_version = Column(Integer, nullable=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(255), nullable=True)
    cover = Column(String(500), nullable=True)

    system_prompt = Column(Text, nullable=True)  # 智能体身份提示词
    noun_highlight_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    noun_explanation_url = Column(String(2000), nullable=False, default="", server_default="")
    default_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    runtime_type = Column(String(30), nullable=False, default="claude_code")  # Registered runtime identifier
    thinking_level = Column(String(20), nullable=False, default="inherit")
    reasoning_visibility = Column(String(20), nullable=False, default="off")
    max_turns = Column(Integer, default=50)  # 单次任务最大轮次
    timeout_seconds = Column(Integer, default=600)  # 执行硬超时
    mcp_overrides_encrypted = Column(
        Text().with_variant(LONGTEXT, "mysql"),
        nullable=True,
    )

    is_deleted = Column(Boolean, default=False, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关联
    skills = relationship("Skill", secondary=agent_skills, lazy="selectin")
    mcps = relationship("McpService", secondary=agent_mcps, lazy="selectin")
    models = relationship("AIModel", secondary=agent_models, lazy="selectin")
    prompt_templates = relationship(
        "PromptTemplate",
        secondary=agent_prompt_templates,
        order_by="agent_prompt_templates.c.position",
        lazy="selectin",
    )
    sessions = relationship("AgentSession", back_populates="agent", lazy="selectin")
    runtime_instance = relationship(
        "RuntimeInstance",
        back_populates="agent",
        uselist=False,
        lazy="selectin",
    )

    @property
    def mcp_overrides(self):
        if not self.mcp_overrides_encrypted:
            return []
        from credential_crypto import AgentCredentialError, decrypt_agent_credential

        raw = decrypt_agent_credential(
            self.mcp_overrides_encrypted,
            purpose=f"agent:{self.user_id}:{self.id}:mcp-overrides",
        )
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AgentCredentialError("Agent MCP overrides are invalid") from exc
        if not isinstance(value, list):
            raise AgentCredentialError("Agent MCP overrides are invalid")
        return value

    def store_mcp_overrides(self, value, app_settings=None):
        from credential_crypto import AgentCredentialError, encrypt_agent_credential

        normalized = value or []
        if not normalized:
            self.mcp_overrides_encrypted = None
            return
        encrypted = encrypt_agent_credential(
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
            purpose=f"agent:{self.user_id}:{self.id}:mcp-overrides",
            app_settings=app_settings,
        )
        if encrypted is None:
            raise AgentCredentialError(
                "AGENT_CREDENTIAL_ENCRYPTION_KEY is required for MCP overrides"
            )
        self.mcp_overrides_encrypted = encrypted


class RuntimeInstance(Base):
    """Long-lived runtime process or remote endpoint assigned to one agent."""
    __tablename__ = "runtime_instances"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    runtime_type = Column(String(30), nullable=False, default="claude_code", server_default="claude_code")
    deployment_mode = Column(String(20), nullable=False, default="managed", server_default="managed")
    external_agent_id = Column(String(100), nullable=False)
    endpoint = Column(String(500), nullable=True)
    auth_secret_encrypted = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="unprovisioned", server_default="unprovisioned", index=True)
    desired_config_hash = Column(String(64), nullable=True)
    applied_config_hash = Column(String(64), nullable=True)
    runtime_version = Column(String(50), nullable=True)
    image_ref = Column(String(500), nullable=True)
    worker_id = Column(String(100), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    last_health_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    agent = relationship("Agent", back_populates="runtime_instance")


class AgentSession(Base):
    """智能体会话 - 只存映射，历史由 runtime 自己管"""
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), nullable=True, index=True)
    title = Column(String(200), nullable=True)
    claude_session_id = Column(String(100), nullable=True)  # 兼容旧字段
    runtime_session_id = Column(String(200), nullable=True)  # runtime 内部会话 ID（--resume 等）
    runtime_type = Column(String(30), nullable=True)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True, index=True)
    config_version = Column(Integer, nullable=True)
    runtime_instance_id = Column(BigInteger, ForeignKey("runtime_instances.id"), nullable=True, index=True)
    runtime_state = Column(String(30), nullable=False, default="active", server_default="active")
    source = Column(String(30), nullable=False, default="web", server_default="web")
    source_binding_id = Column(
        BigInteger,
        ForeignKey("agent_channel_bindings.id"),
        nullable=True,
        index=True,
    )
    message_count = Column(Integer, default=0)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    agent = relationship("Agent", back_populates="sessions")


class AgentMessage(Base):
    """智能体对话消息"""
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentMessageFeedback(Base):
    """One current rating per user and assistant reply."""
    __tablename__ = "agent_message_feedback"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),)

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("agent_messages.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(200), nullable=False, default="")
    display_name = Column(String(200), nullable=False, default="")
    session_title = Column(String(200), nullable=False, default="未命名对话")
    rating = Column(String(10), nullable=False, index=True)
    reasons = Column(Text, nullable=False, default="[]")
    comment = Column(String(2000), nullable=False, default="")
    processing_status = Column(String(20), nullable=True, index=True)
    processing_remark = Column(Text, nullable=True)
    processing_images = Column(Text, nullable=True)
    assignee_user_id = Column(Integer, nullable=True, index=True)
    assignee_username = Column(String(200), nullable=True)
    assignee_name = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AgentConversationShare(Base):
    """Revocable public link for an AgentSession conversation."""

    __tablename__ = "agent_conversation_shares"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)


# === Agent channel models ===


class AgentChannelBinding(Base):
    """A stable one-to-one channel binding for an agent."""

    __tablename__ = "agent_channel_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_channel_bindings_agent_id"),
        UniqueConstraint(
            "provider",
            "provider_bot_id",
            name="uq_agent_channel_bindings_provider_bot",
        ),
        UniqueConstraint(
            "active_conversation_id",
            name="uq_agent_channel_bindings_active_conversation",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    provider = Column(
        String(30), nullable=False, default="weixin_ilink", server_default="weixin_ilink"
    )
    display_name = Column(
        String(100), nullable=False, default="微信ClawBot", server_default="微信ClawBot"
    )
    provider_bot_id = Column(String(200), nullable=True)
    provider_account_id = Column(String(200), nullable=True)
    access_token_encrypted = Column(Text, nullable=True)
    credential_key_version = Column(String(50), nullable=True)
    api_base_url = Column(String(500), nullable=True)
    active_conversation_id = Column(
        BigInteger,
        ForeignKey("channel_conversations.id", use_alter=True),
        nullable=True,
    )
    status = Column(String(30), nullable=False, default="unbound", server_default="unbound")
    poll_cursor = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    poller_owner = Column(String(100), nullable=True)
    poller_lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    poller_fencing_token = Column(BigInteger, nullable=False, default=0, server_default="0")
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_poll_at = Column(DateTime(timezone=True), nullable=True)
    last_inbound_at = Column(DateTime(timezone=True), nullable=True)
    last_outbound_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(Text, nullable=True)
    bound_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")


class ChannelBindSession(Base):
    """A short-lived QR-code binding attempt."""

    __tablename__ = "channel_bind_sessions"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "initiated_by_user_id",
            "idempotency_key",
            name="uq_channel_bind_sessions_idempotency",
        ),
    )

    id = Column(CHANNEL_BIND_SESSION_ID_TYPE, primary_key=True)
    binding_id = Column(
        BigInteger, ForeignKey("agent_channel_bindings.id"), nullable=False, index=True
    )
    initiated_by_user_id = Column(Integer, nullable=False, index=True)
    idempotency_key = Column(String(100), nullable=True)
    state_hash = Column(String(128), nullable=False)
    provider_qr_id = Column(String(200), nullable=True)
    qr_content_encrypted = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    status = Column(String(30), nullable=False, default="created", server_default="created")
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    scanned_at = Column(DateTime(timezone=True), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    pairing_attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    poll_interval_seconds = Column(Integer, nullable=True)
    poller_owner = Column(String(100), nullable=True)
    poller_lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    poller_fencing_token = Column(BigInteger, nullable=False, default=0, server_default="0")
    error_code = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChannelPairingAttempt(Base):
    """Per-sender pairing failures scoped to one short-lived bind session."""

    __tablename__ = "channel_pairing_attempts"

    bind_session_id = Column(
        CHANNEL_BIND_SESSION_ID_TYPE,
        ForeignKey("channel_bind_sessions.id"),
        primary_key=True,
    )
    sender_hash = Column(String(64), primary_key=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChannelConversation(Base):
    """A channel identity locked to one historical AgentSession."""

    __tablename__ = "channel_conversations"
    __table_args__ = (
        UniqueConstraint(
            "agent_session_id", name="uq_channel_conversations_agent_session_id"
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    binding_id = Column(
        BigInteger, ForeignKey("agent_channel_bindings.id"), nullable=False, index=True
    )
    external_wechat_user_id_hash = Column(String(64), nullable=False)
    external_wechat_user_id_encrypted = Column(Text, nullable=False)
    external_user_hash_key_version = Column(String(50), nullable=False)
    agent_session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False)
    latest_context_token_encrypted = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="active", server_default="active")
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChannelMessage(Base):
    """Durable inbound and outbound channel message record."""

    __tablename__ = "channel_messages"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "direction",
            "provider_message_id",
            name="uq_channel_messages_provider_message",
        ),
        UniqueConstraint(
            "binding_id",
            "client_message_id",
            name="uq_channel_messages_client_message",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    binding_id = Column(
        BigInteger, ForeignKey("agent_channel_bindings.id"), nullable=False, index=True
    )
    conversation_id = Column(
        BigInteger, ForeignKey("channel_conversations.id"), nullable=False, index=True
    )
    agent_session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    agent_message_id = Column(Integer, ForeignKey("agent_messages.id"), nullable=True)
    agent_run_id = Column(String(32), ForeignKey("agent_runs.id", use_alter=True), nullable=True, index=True)
    direction = Column(String(10), nullable=False)
    provider_message_id = Column(String(200), nullable=True)
    client_message_id = Column(String(100), nullable=True)
    message_type = Column(String(30), nullable=False)
    content = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    raw_payload_encrypted = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    context_token_encrypted = Column(Text, nullable=True)
    status = Column(String(30), nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    provider_created_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentRun(Base):
    """Persisted execution state shared by web and channel entry points."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_agent_runs_user_idempotency"),
        Index("ix_agent_runs_queue_admission", "user_id", "source", "status"),
    )

    id = Column(String(32), primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    workspace_id = Column(BigInteger, ForeignKey("user_workspaces.id"), nullable=True, index=True)
    source = Column(String(30), nullable=False, default="web", server_default="web")
    idempotency_key = Column(String(100), nullable=True)
    idempotency_fingerprint = Column(String(64), nullable=True)
    source_message_id = Column(
        BigInteger,
        ForeignKey("channel_messages.id"),
        nullable=True,
        unique=True,
    )
    status = Column(String(30), nullable=False, default="queued", server_default="queued", index=True)
    worker_id = Column(String(100), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    deadline_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default="0")
    config_snapshot = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    runtime_instance_id = Column(BigInteger, ForeignKey("runtime_instances.id"), nullable=True, index=True)
    runtime_run_id = Column(String(200), nullable=True)
    runtime_session_id = Column(String(200), nullable=True)
    runtime_protocol = Column(String(50), nullable=True)
    runtime_version = Column(String(50), nullable=True)
    assistant_message_id = Column(Integer, nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(BigInteger, nullable=True)
    input_tokens = Column(BigInteger, nullable=True)
    output_tokens = Column(BigInteger, nullable=True)
    cache_read_tokens = Column(BigInteger, nullable=True)
    cache_creation_tokens = Column(BigInteger, nullable=True)
    total_tokens = Column(BigInteger, nullable=True)
    usage_detail = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    pricing_snapshot = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    reserved_points = Column(Numeric(20, 2), nullable=False, default=0, server_default="0.00")
    charged_points = Column(Numeric(20, 2), nullable=False, default=0, server_default="0.00")
    settlement_status = Column(
        String(30), nullable=False, default="not_required", server_default="not_required", index=True
    )
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentOpenCall(Base):
    """One revocable external credential and resource allowlist per expert."""

    __tablename__ = "agent_open_calls"

    agent_id = Column(Integer, ForeignKey("agents.id"), primary_key=True)
    key_digest = Column(String(64), nullable=True)
    generation = Column(String(32), nullable=False)
    # Legacy columns retained for existing databases; execution uses agent bindings.
    default_prompt = Column(Text, nullable=True)
    skill_ids = Column(JSON, nullable=False, default=list)
    mcp_ids = Column(JSON, nullable=False, default=list)


class AgentOpenRequest(Base):
    """Input for a queued API run, scoped to the credential that submitted it."""

    __tablename__ = "agent_open_requests"

    run_id = Column(String(32), ForeignKey("agent_runs.id"), primary_key=True)
    generation = Column(String(32), nullable=False)
    prompt = Column(Text, nullable=True)
    skill_id = Column(Integer, nullable=True)


class AgentRunEvent(Base):
    """Legacy SQL output, retained only for upgrade replay and bounded cleanup."""

    __tablename__ = "agent_run_events"

    run_id = Column(String(32), primary_key=True)
    sequence = Column(Integer, primary_key=True)
    payload = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlatformAgentSettings(Base):
    """Immutable published enterprise assistant settings plus one editable draft."""

    __tablename__ = "platform_agent_settings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    version = Column(Integer, nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    assistant_name = Column(String(200), nullable=False, default="AI 助手")
    assistant_icon = Column(String(255), nullable=False, default="H", server_default="H")
    assistant_mascot = Column(String(255), nullable=False, default="@cow", server_default="@cow")
    assistant_description = Column(Text, nullable=True)
    system_prompt = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    runtime_type = Column(String(30), nullable=False, default="claude_code")
    thinking_level = Column(String(20), nullable=False, default="inherit", server_default="inherit")
    reasoning_visibility = Column(String(20), nullable=False, default="off", server_default="off")
    default_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    max_turns = Column(Integer, nullable=False, default=50)
    timeout_seconds = Column(Integer, nullable=False, default=600)
    credit_display_name = Column(String(50), nullable=False, default=DEFAULT_CREDIT_DISPLAY_NAME)
    credit_display_name_en = Column(String(50), nullable=False, default="Credits")
    initial_claim_amount = Column(Numeric(20, 2), nullable=False, default=0)
    daily_claim_amount = Column(Numeric(20, 2), nullable=False, default=0)
    per_run_limit = Column(Numeric(20, 2), nullable=False, default=0)
    low_balance_threshold = Column(Numeric(20, 2), nullable=False, default=0)
    claim_timezone = Column(String(50), nullable=False, default="Asia/Shanghai")
    max_concurrent_runs = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=False)
    published_by = Column(Integer, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkbenchSettings(Base):
    """Default assistant identity, published independently of execution policy."""
    __tablename__ = "workbench_settings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    version = Column(Integer, nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="draft", index=True)
    assistant_name = Column(String(200), nullable=False, default="AI 助手")
    assistant_icon = Column(String(255), nullable=False, default="H")
    assistant_mascot = Column(String(255), nullable=False, default="@cow")
    assistant_description = Column(Text, nullable=True)
    noun_highlight_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    noun_explanation_url = Column(String(2000), nullable=False, default="", server_default="")
    system_prompt = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    default_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    created_by = Column(Integer, nullable=False)
    published_by = Column(Integer, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlatformGlobalSettings(Base):
    """Singleton branding and shared Skill script environment settings."""

    __tablename__ = "platform_global_settings"

    id = Column(Integer, primary_key=True, default=1)
    brand_icon = Column(String(50), nullable=False, default="H", server_default="H")
    brand_name = Column(String(100), nullable=False, default="AI Hub", server_default="AI Hub")
    brand_subtitle = Column(String(100), nullable=False, default="合趣网络", server_default="合趣网络")
    runtime_environment = Column(JSON, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    available_balance = Column(Numeric(20, 2), nullable=False, default=0, server_default="0.00")
    reserved_balance = Column(Numeric(20, 2), nullable=False, default=0, server_default="0.00")
    status = Column(String(20), nullable=False, default="active", server_default="active")
    version = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CreditClaimRecord(Base):
    __tablename__ = "credit_claim_records"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_credit_claim_records_business_key"),
        UniqueConstraint(
            "user_id", "claim_type", "claim_date", name="uq_credit_claim_user_type_date"
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    claim_type = Column(String(20), nullable=False)
    claim_date = Column(Date, nullable=False, index=True)
    amount = Column(Numeric(20, 2), nullable=False)
    policy_version = Column(Integer, nullable=False)
    business_key = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CreditLedger(Base):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_credit_ledger_business_key"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    entry_type = Column(String(30), nullable=False, index=True)
    amount = Column(Numeric(20, 2), nullable=False)
    available_after = Column(Numeric(20, 2), nullable=False)
    reserved_after = Column(Numeric(20, 2), nullable=False)
    run_id = Column(String(32), nullable=True, index=True)
    business_key = Column(String(200), nullable=False)
    operator_user_id = Column(Integer, nullable=True)
    reason = Column(String(1000), nullable=True)
    metadata_json = Column("metadata", Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelPricingVersion(Base):
    __tablename__ = "model_pricing_versions"
    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_model_pricing_model_version"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    input_rate = Column(BigInteger, nullable=False, default=0)
    output_rate = Column(BigInteger, nullable=False, default=0)
    cache_read_rate = Column(BigInteger, nullable=False, default=0)
    cache_creation_rate = Column(BigInteger, nullable=False, default=0)
    rate_scale = Column(BigInteger, nullable=False, default=1000000)
    effective_from = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelUsageEvent(Base):
    __tablename__ = "model_usage_events"
    __table_args__ = (
        UniqueConstraint("provider_request_id", name="uq_model_usage_provider_request"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(32), nullable=False, index=True)
    provider_request_id = Column(String(200), nullable=False)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=False, index=True)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    cache_read_tokens = Column(BigInteger, nullable=False, default=0)
    cache_creation_tokens = Column(BigInteger, nullable=False, default=0)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw_usage = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)


class ModelRunCredential(Base):
    __tablename__ = "model_run_credentials"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    run_id = Column(String(32), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=False, index=True)
    pricing_version_id = Column(
        BigInteger, ForeignKey("model_pricing_versions.id"), nullable=False
    )
    max_points = Column(Numeric(20, 2), nullable=False)
    consumed_points = Column(Numeric(20, 2), nullable=False, default=0, server_default="0.00")
    request_count = Column(Integer, nullable=False, default=0, server_default="0")
    request_in_flight = Column(Boolean, nullable=False, default=False, server_default="0")
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ModelGatewayRequest(Base):
    """Durable progress for concurrent, metered platform-model requests."""
    __tablename__ = "model_gateway_requests"

    id = Column(String(100), primary_key=True)
    credential_id = Column(BigInteger, ForeignKey("model_run_credentials.id"), nullable=False, index=True)
    run_id = Column(String(32), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="started")
    billed_points = Column(Numeric(20, 2), nullable=False, default=0)
    charged_points = Column(Numeric(20, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AgentExecutionLease(Base):
    """One renewable, fenced execution lease per Agent."""

    __tablename__ = "agent_execution_leases"

    agent_id = Column(Integer, ForeignKey("agents.id"), primary_key=True)
    run_id = Column(String(32), nullable=True, index=True)
    owner_id = Column(String(100), nullable=True)
    fencing_token = Column(BigInteger, nullable=False, default=0, server_default="0")
    lease_until = Column(DateTime(timezone=True), nullable=False, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentPermissionRequest(Base):
    """Durable permission request shared by API processes."""

    __tablename__ = "agent_permission_requests"

    req_id = Column(String(100), primary_key=True)
    run_id = Column(
        String(32),
        ForeignKey("agent_runs.id"),
        nullable=False,
        index=True,
    )
    tool_key = Column(String(300), nullable=False)
    tool_name = Column(String(200), nullable=False)
    tool_input = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    decision = Column(String(10), nullable=True)
    reason = Column(String(1000), nullable=True)
    remember = Column(Boolean, nullable=False, default=False, server_default="0")
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChannelOutbox(Base):
    """Reliable delivery queue for normalized outbound channel messages."""

    __tablename__ = "channel_outbox"
    __table_args__ = (
        UniqueConstraint("run_id", "part_no", name="uq_channel_outbox_run_part"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    binding_id = Column(
        BigInteger, ForeignKey("agent_channel_bindings.id"), nullable=False, index=True
    )
    run_id = Column(String(32), ForeignKey("agent_runs.id"), nullable=False, index=True)
    channel_message_id = Column(
        BigInteger, ForeignKey("channel_messages.id"), nullable=False, unique=True
    )
    part_no = Column(Integer, nullable=False, default=0, server_default="0")
    payload = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    context_token_encrypted = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="pending", server_default="pending")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    lease_owner = Column(String(100), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    """Local user account for standalone JWT authentication."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(150), nullable=True, default="")
    email = Column(String(255), nullable=True, default="")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    is_staff = Column(Boolean, nullable=False, default=False, server_default="0")
    is_superuser = Column(Boolean, nullable=False, default=False, server_default="0")
    roles = Column(JSON, nullable=True)
    permissions = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
