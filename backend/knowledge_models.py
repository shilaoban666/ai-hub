"""Tables for the Bailian knowledge base console, DingTalk drive sync and call usage."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint
from datetime import datetime, timezone

from sqlalchemy.sql import func

from database import Base


def utcnow():
    """Naive UTC, matching how the dashboards compare stored timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class KnowledgeSettings(Base):
    """Singleton integration settings; secrets are stored encrypted."""

    __tablename__ = "knowledge_settings"

    id = Column(Integer, primary_key=True, default=1)
    bailian_endpoint = Column(
        String(200), nullable=False,
        default="bailian.cn-beijing.aliyuncs.com", server_default="bailian.cn-beijing.aliyuncs.com",
    )
    bailian_access_key_id = Column(String(200), nullable=True)
    bailian_access_key_secret_encrypted = Column(Text, nullable=True)
    bailian_workspace_id = Column(String(100), nullable=True)
    default_index_id = Column(String(100), nullable=True)
    default_category_id = Column(String(100), nullable=True)
    dingtalk_client_id = Column(String(200), nullable=True)
    dingtalk_client_secret_encrypted = Column(Text, nullable=True)
    # JSON lists of first-level department names; NULL means the built-in defaults.
    usage_departments = Column(Text, nullable=True)
    upload_departments = Column(Text, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), onupdate=utcnow)


class KnowledgeDingtalkIdentity(Base):
    """DingTalk unionId bound by QR scan; the drive APIs act as this person."""

    __tablename__ = "knowledge_dingtalk_identities"

    user_id = Column(Integer, primary_key=True, autoincrement=False)
    union_id = Column(String(100), nullable=False)
    nick = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), onupdate=utcnow)


class KnowledgeUpload(Base):
    __tablename__ = "knowledge_uploads"
    __table_args__ = (Index("ix_knowledge_uploads_user_created", "user_id", "created_at"),)

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    index_id = Column(String(100), nullable=False)
    index_name = Column(String(200), nullable=True)
    category_id = Column(String(100), nullable=False)
    category_name = Column(String(200), nullable=True)
    file_name = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    # uploading -> parsing -> indexing -> completed | failed
    status = Column(String(20), nullable=False, default="uploading", index=True)
    bailian_file_id = Column(String(100), nullable=True)
    bailian_job_id = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    sync_dingtalk = Column(Boolean, nullable=False, default=False, server_default="0")
    dingtalk_workspace_id = Column(String(100), nullable=True)
    dingtalk_folder_id = Column(String(100), nullable=True)
    dingtalk_folder_path = Column(String(500), nullable=True)
    # none | pending | success | failed
    dingtalk_status = Column(String(20), nullable=False, default="none", server_default="none")
    dingtalk_dentry_id = Column(String(100), nullable=True)
    dingtalk_error = Column(Text, nullable=True)
    dingtalk_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), onupdate=utcnow)


class KnowledgeCallLog(Base):
    """One knowledge base retrieval made through AI Hub."""

    __tablename__ = "knowledge_call_logs"
    __table_args__ = (
        Index("ix_knowledge_calls_created_user", "created_at", "user_id"),
        UniqueConstraint("external_id", name="uq_knowledge_calls_external"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    index_id = Column(String(100), nullable=False)
    index_name = Column(String(200), nullable=True)
    source = Column(String(30), nullable=False, default="api", server_default="api")
    query = Column(String(1000), nullable=False, default="")
    status = Column(String(20), nullable=False, default="success")
    result_count = Column(Integer, nullable=False, default=0)
    query_tokens = Column(Integer, nullable=False, default=0)
    result_tokens = Column(Integer, nullable=False, default=0)
    rag_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    error_message = Column(String(1000), nullable=True)
    # Conversation that triggered the retrieval (agent session id), when the caller passes one.
    session_id = Column(String(64), nullable=True, index=True)
    # Calls read back from chats (the agent's knowledge base MCP tool) carry that tool call's id, so a
    # chat counted live and again by a backfill is recorded once.
    external_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())


class KnowledgeCallHit(Base):
    """A document recalled by one retrieval call; one row per distinct document per call."""

    __tablename__ = "knowledge_call_hits"
    __table_args__ = (Index("ix_knowledge_call_hits_created_doc", "created_at", "doc_name"),)

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    call_id = Column(BigInteger, nullable=False, index=True)
    index_id = Column(String(100), nullable=False)
    doc_name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())


class KnowledgeDocLink(Base):
    """DingTalk link for a knowledge base document, read from the「钉钉文件链接对照表」kept in the index.

    Documents imported straight into Bailian have no upload row here, so their drive link comes from
    that table. A row with a NULL url records a lookup that found nothing, so it is not repeated on
    every page view; it is retried after a while in case the table was updated.
    """

    __tablename__ = "knowledge_doc_links"
    __table_args__ = (UniqueConstraint("index_id", "doc_name", name="uq_knowledge_doc_links_index_doc"),)

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    index_id = Column(String(100), nullable=False)
    doc_name = Column(String(255), nullable=False)
    dingtalk_url = Column(String(500), nullable=True)
    folder_path = Column(String(500), nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())


# Columns added after the tables first shipped; ensure_schema adds them to existing databases.
LATE_COLUMNS = {
    "knowledge_settings": {"usage_departments": "TEXT NULL", "upload_departments": "TEXT NULL"},
    "knowledge_uploads": {"dingtalk_url": "VARCHAR(500) NULL"},
    "knowledge_call_logs": {"session_id": "VARCHAR(64) NULL", "external_id": "VARCHAR(100) NULL"},
}
# Indexes that come with a late column: (table, index name, DDL).
LATE_INDEXES = (
    ("knowledge_call_logs", "uq_knowledge_calls_external",
     "CREATE UNIQUE INDEX uq_knowledge_calls_external ON knowledge_call_logs (external_id)"),
)


def ensure_schema(engine) -> None:
    """Idempotently add late columns and their indexes (create_all never alters existing tables).

    Runs at app startup. A failure here (e.g. a database account without ALTER rights) is logged and
    left to the 063 migration; it must never stop AI Hub from starting.
    """
    import logging

    from sqlalchemy import inspect, text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        inspector = inspect(engine)
        with engine.begin() as connection:
            for table, columns in LATE_COLUMNS.items():
                if not inspector.has_table(table):
                    continue
                existing = {column["name"] for column in inspector.get_columns(table)}
                for name, ddl in columns.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            for table, index, ddl in LATE_INDEXES:
                if not inspector.has_table(table):
                    continue
                live = inspect(connection)
                names = {item["name"] for item in live.get_indexes(table)}
                names |= {item["name"] for item in live.get_unique_constraints(table)}
                if index not in names:
                    connection.execute(text(ddl))
    except SQLAlchemyError:
        logging.getLogger("aihub.knowledge").error(
            "knowledge schema upgrade skipped; run migrations/063_knowledge_base.sql", exc_info=True)
