from functools import lru_cache
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL

from database import settings


def _build_sub2api_postgres_url() -> Optional[str]:
    """Build the sub2api PostgreSQL connection URL from .env settings."""
    if settings.sub2api_postgres_url:
        return settings.sub2api_postgres_url

    required = [
        settings.sub2api_postgres_host,
        settings.sub2api_postgres_database,
        settings.sub2api_postgres_user,
        settings.sub2api_postgres_password,
    ]
    if not all(required):
        return None

    return URL.create(
        "postgresql+psycopg2",
        username=settings.sub2api_postgres_user,
        password=settings.sub2api_postgres_password,
        host=settings.sub2api_postgres_host,
        port=settings.sub2api_postgres_port,
        database=settings.sub2api_postgres_database,
        query={"sslmode": settings.sub2api_postgres_sslmode},
    ).render_as_string(hide_password=False)


@lru_cache()
def get_sub2api_engine() -> Engine:
    url = _build_sub2api_postgres_url()
    if not url:
        raise RuntimeError("sub2api PostgreSQL is not configured")

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=5,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 5},
        echo=False,
    )


def execute_sub2api_query(
    sql: str,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Execute a read-only SQL query against sub2api PostgreSQL."""
    engine = get_sub2api_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]
