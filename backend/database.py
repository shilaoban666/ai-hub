from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path
import sys

from pydantic import Field, field_validator



def _default_user_workspace_root() -> str:
    if sys.platform == "darwin":
        return str(Path(__file__).resolve().parent / "user_workspaces")
    return "/var/lib/aihub/user_workspaces"


class Settings(BaseSettings):
    database_url: str
    # Web chat temporary output; shared by all API workers. Empty disables new Web runs.
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    aihub_redis_prefix: str = "aihub:chat:"

    # sub2api PostgreSQL 数据源（URL 优先，未填则用下方字段拼接）
    sub2api_postgres_url: str = ""
    sub2api_postgres_host: str = ""
    sub2api_postgres_port: int = 5432
    sub2api_postgres_database: str = ""
    sub2api_postgres_user: str = ""
    sub2api_postgres_password: str = ""
    sub2api_postgres_sslmode: str = "prefer"

    # Git 仓库配置
    git_download_timeout: int = 180

    # 网关地址（前端也用这个值，即 VITE_API_BASE_URL）
    vite_api_base_url: str = "http://127.0.0.1:8080"
    # Runtime 共用的宿主机工作区。
    agent_workspace_root: str = ""
    agent_max_upload_files: int = 10
    agent_max_upload_file_bytes: int = 10 * 1024 * 1024
    agent_max_upload_total_bytes: int = 20 * 1024 * 1024
    # Chat image credentials are backend-only.
    oss_access_key_id: str = Field(default="", repr=False)
    oss_access_key_secret: str = Field(default="", repr=False)
    oss_bucket: str = "aihub"
    oss_endpoint: str = "oss-cn-shanghai.aliyuncs.com"
    oss_public_endpoint: str = "oss-cn-shanghai.aliyuncs.com"
    oss_chat_image_prefix: str = "tmp/chat-images"
    oss_feedback_image_prefix: str = "feedback/images"
    agent_execution_lease_seconds: int = 30
    agent_execution_lease_poll_seconds: float = 0.5
    agent_run_control_poll_seconds: float = 0.5
    agent_open_call_allow_query: bool = False
    agent_max_queued_runs: int = 20
    user_workspace_root: str = Field(default_factory=_default_user_workspace_root)
    skill_release_cache_root: str = ""
    user_workspace_quota_bytes: int = 10 * 1024 * 1024 * 1024
    user_workspace_user_prefix: str = "aihub_user_"
    agent_credential_encryption_key: str = ""
    agent_credential_key_version: str = "v1"
    # Internal URL reachable from Claude Runtime cells. Never points upstream.
    model_gateway_base_url: str = "http://127.0.0.1:15174/api/model-gateway"
    model_gateway_container_base_url: str = "http://host.docker.internal:15174/api/model-gateway"
    model_gateway_credential_ttl_seconds: int = 900
    model_gateway_request_timeout_seconds: int = 600
    # How long an ended Run may wait for missing gateway usage events before
    # settling from the usage that was recorded. The unreconciled portion is
    # absorbed by the platform after this grace period.
    model_gateway_reconciliation_grace_seconds: int = 24 * 60 * 60

    # Claude Code 执行隔离；为空时兼容读取下方旧 AGENT_* 配置。
    claude_code_sandbox_type: str = ""
    claude_code_native_workspace_root: str = ""
    claude_code_native_user_prefix: str = ""
    claude_code_native_claude_bin: str = ""
    claude_code_container_image: str = "aihub/claude-runtime:latest"
    claude_code_container_network: str = "bridge"
    claude_code_container_memory: str = "2g"
    claude_code_container_cpus: str = "2"
    claude_code_container_pids_limit: int = 256

    # Optional enterprise MCP egress controls. Public HTTP(S) targets work
    # without them; when configured, the host allowlist and proxy are enforced.
    mcp_egress_proxy_url: str = ""
    mcp_allowed_hosts: str = ""
    mcp_allow_private_networks: bool = False
    mcp_stdio_allowed_commands: str = ""

    # Claude Code 旧配置名，待所有部署迁移后删除。
    agent_sandbox_type: str = "directory"
    agent_native_workspace_root: str = ""
    agent_native_user_prefix: str = ""
    agent_linux_workspace_root: str = "/var/lib/aihub/agent_workspaces"
    agent_linux_user_prefix: str = "aihub_agent_"

    # Weixin iLink channel (disabled until credentials and an isolated worker are configured)
    weixin_ilink_enabled: bool = False
    weixin_ilink_default_base_url: str = ""
    weixin_ilink_allowed_hosts: str = ""
    weixin_ilink_qr_ttl_seconds: int = 480
    # DingTalk application registration + Stream Mode channel.
    dingtalk_enabled: bool = False
    dingtalk_registration_base_url: str = "https://oapi.dingtalk.com"
    dingtalk_registration_source: str = "openClaw"
    dingtalk_allowed_webhook_hosts: str = "api.dingtalk.com,oapi.dingtalk.com"
    dingtalk_qr_ttl_seconds: int = 7200
    dingtalk_max_stream_sessions: int = 64
    channel_credential_encryption_key: str = ""
    channel_credential_key_version: str = "v1"
    channel_id_hash_key: str = ""
    channel_worker_id: str = ""
    channel_poller_lease_seconds: int = 60
    channel_run_lease_seconds: int = 900
    channel_bind_poll_interval_seconds: int = 2
    channel_bind_session_timeout_seconds: int = 480
    channel_worker_poll_interval_seconds: int = 1
    channel_outbox_max_attempts: int = 8
    channel_max_text_chars: int = 4000
    channel_max_pending_messages_per_binding: int = 20
    channel_max_daily_runs_per_binding: int = 200

    # CORS 允许的来源（逗号分隔，留空则不允许跨域）
    cors_origins: str = ""

    # 本地认证配置（JWT + 默认管理员初始化）
    jwt_secret_key: str = "aihub-core-local-dev-secret-change-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 120
    jwt_refresh_token_expire_days: int = 7
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    @field_validator("user_workspace_root", mode="before")
    @classmethod
    def normalize_user_workspace_root(cls, value):
        configured = str(value or "").strip()
        if not configured:
            return _default_user_workspace_root()
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = Path(__file__).resolve().parent.parent / root
        return str(root)

    class Config:
        env_file = "../.env"
        extra = "ignore"
        protected_namespaces = ("settings_",)


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()


def _set_mysql_session_timezone(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET time_zone = '+00:00'")
    finally:
        cursor.close()


def _configure_database_timezone(db_engine):
    if db_engine.dialect.name == "mysql":
        # Worker leases use UTC; keep MySQL CURRENT_TIMESTAMP values in UTC too.
        event.listen(db_engine, "connect", _set_mysql_session_timezone)


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
)
_configure_database_timezone(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
