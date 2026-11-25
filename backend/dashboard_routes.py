from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import CurrentUser, get_current_active_user
from sub2api_database import execute_sub2api_query


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
public_router = APIRouter(prefix="/api/public", tags=["public-dashboard"])

LOCAL_TZ = timezone(timedelta(hours=8))
TOKEN_EXPR = """
    COALESCE(input_tokens, 0)
    + COALESCE(output_tokens, 0)
    + COALESCE(cache_creation_tokens, 0)
    + COALESCE(cache_read_tokens, 0)
    + COALESCE(image_output_tokens, 0)
"""
CACHE_EXPR = """
    COALESCE(cache_creation_tokens, 0)
    + COALESCE(cache_read_tokens, 0)
"""


def _parse_date(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.strptime(value, "%Y-%m-%d")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)

    if end_of_day and len(value) == 10:
        parsed = parsed + timedelta(days=1)
    return parsed


def _resolve_period(
    period: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[datetime, datetime, datetime, datetime]:
    now = datetime.now(LOCAL_TZ)
    period = period or "7d"

    if period == "today":
        start_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_at = now
    elif period == "month":
        start_at = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_at = now
    elif period == "custom":
        start_at = _parse_date(start_date)
        end_at = _parse_date(end_date, end_of_day=True)
        if not start_at or not end_at:
            raise HTTPException(status_code=400, detail="Custom period requires start_date and end_date")
    else:
        start_at = now - timedelta(days=7)
        end_at = now

    if start_at >= end_at:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    duration = end_at - start_at
    previous_end = start_at
    previous_start = previous_end - duration
    return start_at, end_at, previous_start, previous_end


def _normalize_granularity(granularity: str) -> str:
    if granularity not in {"hour", "day", "week"}:
        return "day"
    return granularity


def _normalize_limit(limit: int, default: int = 50, maximum: int = 200) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _safe_query(sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return execute_sub2api_query(sql, params)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"sub2api query failed: {exc}") from exc


@router.get("/summary/token-usage")
def get_summary_token_usage(
    period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
    granularity: str = Query("day"),
    search: str = Query(""),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="仅超级管理员可查看全局用量看板")
    return _build_summary_token_usage_payload(period, granularity, search, start_date, end_date, limit)


def _build_summary_token_usage_payload(
    period: str,
    granularity: str,
    search: str,
    start_date: Optional[str],
    end_date: Optional[str],
    limit: int,
) -> Dict[str, Any]:
    start_at, end_at, previous_start, previous_end = _resolve_period(period, start_date, end_date)
    granularity = _normalize_granularity(granularity)
    limit = _normalize_limit(limit)
    search_like = f"%{search.strip().lower()}%"

    common_params = {
        "start_at": start_at,
        "end_at": end_at,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "granularity": granularity,
        "search": search.strip().lower(),
        "search_like": search_like,
        "limit": limit,
    }

    summary_sql = f"""
        WITH period_logs AS (
            SELECT user_id, created_at, input_tokens, output_tokens,
                   cache_creation_tokens, cache_read_tokens, image_output_tokens
            FROM usage_logs
            WHERE created_at >= :start_at AND created_at < :end_at
        ),
        previous_user_usage AS (
            SELECT user_id, SUM({TOKEN_EXPR}) AS total_tokens
            FROM usage_logs
            WHERE created_at >= :previous_start AND created_at < :previous_end
            GROUP BY user_id
        ),
        current_user_usage AS (
            SELECT user_id, SUM({TOKEN_EXPR}) AS total_tokens
            FROM period_logs
            GROUP BY user_id
        ),
        minute_usage AS (
            SELECT date_trunc('minute', created_at) AS bucket,
                   SUM({TOKEN_EXPR}) AS total_tokens
            FROM period_logs
            GROUP BY bucket
        )
        SELECT
            COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM({CACHE_EXPR}), 0) AS cache_tokens,
            COALESCE(SUM(image_output_tokens), 0) AS image_output_tokens,
            COUNT(*) AS request_count,
            COUNT(DISTINCT user_id) AS active_users,
            COALESCE(MAX((SELECT MAX(total_tokens) FROM minute_usage)), 0) AS peak_tpm,
            COALESCE(AVG({TOKEN_EXPR}), 0) AS avg_tokens_per_request,
            (
                SELECT COUNT(*)
                FROM current_user_usage cu
                LEFT JOIN previous_user_usage pu ON pu.user_id = cu.user_id
                WHERE pu.total_tokens > 0
                  AND cu.total_tokens >= pu.total_tokens * 3
            ) AS anomaly_users
        FROM period_logs
    """
    summary_row = (_safe_query(summary_sql, common_params) or [{}])[0]
    total_tokens = _to_int(summary_row.get("total_tokens"))
    cache_tokens = _to_int(summary_row.get("cache_tokens"))

    trend_sql = f"""
        SELECT
            date_trunc(:granularity, created_at) AS bucket,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM({CACHE_EXPR}), 0) AS cache_tokens,
            COALESCE(SUM(image_output_tokens), 0) AS image_output_tokens,
            COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens
        FROM usage_logs
        WHERE created_at >= :start_at AND created_at < :end_at
        GROUP BY bucket
        ORDER BY bucket
    """
    trend_rows = _safe_query(trend_sql, common_params)

    user_sql = f"""
        WITH current_usage AS (
            SELECT
                ul.user_id,
                COUNT(*) AS request_count,
                COALESCE(SUM(ul.input_tokens), 0) AS input_tokens,
                COALESCE(SUM(ul.output_tokens), 0) AS output_tokens,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens,
                COALESCE(SUM({CACHE_EXPR}), 0) AS cache_tokens
            FROM usage_logs ul
            WHERE ul.created_at >= :start_at AND ul.created_at < :end_at
            GROUP BY ul.user_id
        ),
        previous_usage AS (
            SELECT
                user_id,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens
            FROM usage_logs
            WHERE created_at >= :previous_start AND created_at < :previous_end
            GROUP BY user_id
        ),
        peak_usage AS (
            SELECT user_id, MAX(minute_tokens) AS peak_tpm
            FROM (
                SELECT
                    user_id,
                    date_trunc('minute', created_at) AS bucket,
                    COALESCE(SUM({TOKEN_EXPR}), 0) AS minute_tokens
                FROM usage_logs
                WHERE created_at >= :start_at AND created_at < :end_at
                GROUP BY user_id, bucket
            ) t
            GROUP BY user_id
        )
        SELECT
            u.id AS user_id,
            COALESCE(NULLIF(u.username, ''), split_part(u.email, '@', 1)) AS display_name,
            u.email,
            cu.request_count,
            cu.input_tokens,
            cu.output_tokens,
            cu.cache_tokens,
            cu.total_tokens,
            COALESCE(pu.peak_tpm, 0) AS peak_tpm,
            CASE
                WHEN prev.total_tokens > 0
                THEN ROUND(((cu.total_tokens - prev.total_tokens) * 100.0 / prev.total_tokens)::numeric, 2)
                WHEN cu.total_tokens > 0 THEN 100
                ELSE 0
            END AS trend_rate
        FROM current_usage cu
        JOIN users u ON u.id = cu.user_id
        LEFT JOIN previous_usage prev ON prev.user_id = cu.user_id
        LEFT JOIN peak_usage pu ON pu.user_id = cu.user_id
        WHERE (
            :search = ''
            OR LOWER(COALESCE(NULLIF(u.username, ''), split_part(u.email, '@', 1))) LIKE :search_like
            OR LOWER(u.email) LIKE :search_like
            OR EXISTS (
                SELECT 1 FROM api_keys ak
                WHERE ak.user_id = u.id
                  AND LOWER(ak.name) LIKE :search_like
            )
        )
        ORDER BY cu.total_tokens DESC
        LIMIT :limit
    """
    user_rows = _safe_query(user_sql, common_params)

    users = []
    for row in user_rows:
        user_total = _to_int(row.get("total_tokens"))
        trend_rate = _to_float(row.get("trend_rate"))
        users.append({
            "user_id": _to_int(row.get("user_id")),
            "username": row.get("display_name") or "",
            "email": row.get("email") or "",
            "request_count": _to_int(row.get("request_count")),
            "input_tokens": _to_int(row.get("input_tokens")),
            "output_tokens": _to_int(row.get("output_tokens")),
            "cache_tokens": _to_int(row.get("cache_tokens")),
            "total_tokens": user_total,
            "cache_ratio": round((_to_int(row.get("cache_tokens")) / user_total * 100), 2) if user_total else 0,
            "peak_tpm": _to_int(row.get("peak_tpm")),
            "trend_rate": trend_rate,
            "status": "growth" if trend_rate >= 200 else "normal",
        })

    return {
        "period": {
            "type": period,
            "granularity": granularity,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        "summary": {
            "total_tokens": total_tokens,
            "input_tokens": _to_int(summary_row.get("input_tokens")),
            "output_tokens": _to_int(summary_row.get("output_tokens")),
            "cache_tokens": cache_tokens,
            "image_output_tokens": _to_int(summary_row.get("image_output_tokens")),
            "cache_ratio": round((cache_tokens / total_tokens * 100), 2) if total_tokens else 0,
            "request_count": _to_int(summary_row.get("request_count")),
            "active_users": _to_int(summary_row.get("active_users")),
            "peak_tpm": _to_int(summary_row.get("peak_tpm")),
            "avg_tokens_per_request": _to_float(summary_row.get("avg_tokens_per_request")),
            "anomaly_users": _to_int(summary_row.get("anomaly_users")),
        },
        "trend": [
            {
                "bucket": _iso(row.get("bucket")),
                "input_tokens": _to_int(row.get("input_tokens")),
                "output_tokens": _to_int(row.get("output_tokens")),
                "cache_tokens": _to_int(row.get("cache_tokens")),
                "image_output_tokens": _to_int(row.get("image_output_tokens")),
                "total_tokens": _to_int(row.get("total_tokens")),
            }
            for row in trend_rows
        ],
        "users": users,
    }


@public_router.get("/token-usage")
def get_public_token_usage(
    period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
    granularity: str = Query("day"),
    search: str = Query(""),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """公开版全局 Token 用量看板（不走鉴权，临时供外部调用）。

    返回结构与 /api/dashboard/summary/token-usage 一致，但不做登录与超管校验。
    注意：该接口会暴露全平台用户的邮箱与 token 用量，仅作临时外部用途，不应长期开放。
    """
    return _build_summary_token_usage_payload(period, granularity, search, start_date, end_date, limit)


def _resolve_current_sub2api_user(current_user: CurrentUser) -> Dict[str, Any]:
    username = (current_user.username or "").strip().lower()
    username_prefix = username.split("@", 1)[0] if username else ""
    email = (current_user.email or "").strip().lower()

    if not username_prefix and not email:
        raise HTTPException(status_code=400, detail="Current user has no username or email")

    rows = _safe_query(
        """
        SELECT
            id AS user_id,
            COALESCE(NULLIF(username, ''), split_part(email, '@', 1)) AS display_name,
            email
        FROM users
        WHERE (
            :username_prefix != ''
            AND (
                LOWER(split_part(email, '@', 1)) = :username_prefix
                OR LOWER(COALESCE(username, '')) = :username_prefix
            )
        )
        OR (:email != '' AND LOWER(email) = :email)
        ORDER BY
            CASE WHEN :email != '' AND LOWER(email) = :email THEN 0 ELSE 1 END,
            id
        LIMIT 1
        """,
        {
            "username_prefix": username_prefix,
            "email": email,
        },
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="未找到与当前 AI Hub 用户匹配的 sub2api 用户",
        )
    return rows[0]


def _build_user_token_usage_payload(
    user_id: int,
    period: str,
    granularity: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Dict[str, Any]:
    start_at, end_at, previous_start, previous_end = _resolve_period(period, start_date, end_date)
    granularity = _normalize_granularity(granularity)
    params = {
        "user_id": user_id,
        "start_at": start_at,
        "end_at": end_at,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "granularity": granularity,
    }

    summary_sql = f"""
        WITH current_usage AS (
            SELECT
                COUNT(*) AS request_count,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM({CACHE_EXPR}), 0) AS cache_tokens,
                COALESCE(SUM(image_output_tokens), 0) AS image_output_tokens,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens,
                COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                COALESCE(AVG(first_token_ms), 0) AS avg_first_token_ms
            FROM usage_logs
            WHERE user_id = :user_id
              AND created_at >= :start_at AND created_at < :end_at
        ),
        all_usage AS (
            SELECT COALESCE(SUM({TOKEN_EXPR}), 0) AS platform_tokens
            FROM usage_logs
            WHERE created_at >= :start_at AND created_at < :end_at
        ),
        previous_usage AS (
            SELECT COALESCE(SUM({TOKEN_EXPR}), 0) AS previous_tokens
            FROM usage_logs
            WHERE user_id = :user_id
              AND created_at >= :previous_start AND created_at < :previous_end
        )
        SELECT
            u.id AS user_id,
            COALESCE(NULLIF(u.username, ''), split_part(u.email, '@', 1)) AS display_name,
            u.email,
            cu.*,
            au.platform_tokens,
            pu.previous_tokens
        FROM users u
        CROSS JOIN current_usage cu
        CROSS JOIN all_usage au
        CROSS JOIN previous_usage pu
        WHERE u.id = :user_id
    """
    summary_rows = _safe_query(summary_sql, params)
    if not summary_rows:
        raise HTTPException(status_code=404, detail="sub2api user not found")
    summary_row = summary_rows[0]
    total_tokens = _to_int(summary_row.get("total_tokens"))
    cache_tokens = _to_int(summary_row.get("cache_tokens"))
    platform_tokens = _to_int(summary_row.get("platform_tokens"))
    previous_tokens = _to_int(summary_row.get("previous_tokens"))

    trend_sql = f"""
        SELECT
            date_trunc(:granularity, created_at) AS bucket,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM({CACHE_EXPR}), 0) AS cache_tokens,
            COALESCE(SUM(image_output_tokens), 0) AS image_output_tokens,
            COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens
        FROM usage_logs
        WHERE user_id = :user_id
          AND created_at >= :start_at AND created_at < :end_at
        GROUP BY bucket
        ORDER BY bucket
    """
    model_sql = f"""
        SELECT
            COALESCE(NULLIF(requested_model, ''), NULLIF(model, ''), 'unknown') AS name,
            COUNT(*) AS request_count,
            COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens
        FROM usage_logs
        WHERE user_id = :user_id
          AND created_at >= :start_at AND created_at < :end_at
        GROUP BY name
        ORDER BY total_tokens DESC
        LIMIT 10
    """
    api_key_sql = f"""
        SELECT
            COALESCE(NULLIF(ak.name, ''), '未命名 API Key') AS name,
            COUNT(*) AS request_count,
            COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens
        FROM usage_logs ul
        LEFT JOIN api_keys ak ON ak.id = ul.api_key_id
        WHERE ul.user_id = :user_id
          AND ul.created_at >= :start_at AND ul.created_at < :end_at
        GROUP BY name
        ORDER BY total_tokens DESC
        LIMIT 10
    """
    endpoint_sql = f"""
        SELECT
            COALESCE(NULLIF(inbound_endpoint, ''), 'unknown') AS name,
            COUNT(*) AS request_count,
            COALESCE(SUM({TOKEN_EXPR}), 0) AS total_tokens
        FROM usage_logs
        WHERE user_id = :user_id
          AND created_at >= :start_at AND created_at < :end_at
        GROUP BY name
        ORDER BY total_tokens DESC
        LIMIT 10
    """
    recent_sql = f"""
        SELECT
            ul.created_at,
            COALESCE(NULLIF(ak.name, ''), '未命名 API Key') AS api_key_name,
            COALESCE(NULLIF(ul.requested_model, ''), NULLIF(ul.model, ''), 'unknown') AS model,
            ul.request_type,
            ul.stream,
            COALESCE(ul.input_tokens, 0) AS input_tokens,
            COALESCE(ul.output_tokens, 0) AS output_tokens,
            COALESCE({CACHE_EXPR}, 0) AS cache_tokens,
            COALESCE(ul.image_output_tokens, 0) AS image_output_tokens,
            COALESCE({TOKEN_EXPR}, 0) AS total_tokens,
            ul.duration_ms,
            ul.first_token_ms
        FROM usage_logs ul
        LEFT JOIN api_keys ak ON ak.id = ul.api_key_id
        WHERE ul.user_id = :user_id
          AND ul.created_at >= :start_at AND ul.created_at < :end_at
        ORDER BY ul.created_at DESC
        LIMIT 20
    """

    trend_rows = _safe_query(trend_sql, params)
    model_rows = _safe_query(model_sql, params)
    api_key_rows = _safe_query(api_key_sql, params)
    endpoint_rows = _safe_query(endpoint_sql, params)
    recent_rows = _safe_query(recent_sql, params)

    def with_ratio(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "name": row.get("name") or "unknown",
                "request_count": _to_int(row.get("request_count")),
                "total_tokens": _to_int(row.get("total_tokens")),
                "ratio": round((_to_int(row.get("total_tokens")) / total_tokens * 100), 2) if total_tokens else 0,
            }
            for row in rows
        ]

    trend_rate = 100 if previous_tokens == 0 and total_tokens > 0 else (
        round((total_tokens - previous_tokens) * 100 / previous_tokens, 2) if previous_tokens else 0
    )

    return {
        "period": {
            "type": period,
            "granularity": granularity,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        "user": {
            "user_id": _to_int(summary_row.get("user_id")),
            "username": summary_row.get("display_name") or "",
            "email": summary_row.get("email") or "",
        },
        "summary": {
            "total_tokens": total_tokens,
            "platform_ratio": round((total_tokens / platform_tokens * 100), 2) if platform_tokens else 0,
            "request_count": _to_int(summary_row.get("request_count")),
            "input_tokens": _to_int(summary_row.get("input_tokens")),
            "output_tokens": _to_int(summary_row.get("output_tokens")),
            "cache_tokens": cache_tokens,
            "image_output_tokens": _to_int(summary_row.get("image_output_tokens")),
            "cache_ratio": round((cache_tokens / total_tokens * 100), 2) if total_tokens else 0,
            "avg_duration_ms": _to_float(summary_row.get("avg_duration_ms")),
            "avg_first_token_ms": _to_float(summary_row.get("avg_first_token_ms")),
            "trend_rate": trend_rate,
        },
        "trend": [
            {
                "bucket": _iso(row.get("bucket")),
                "input_tokens": _to_int(row.get("input_tokens")),
                "output_tokens": _to_int(row.get("output_tokens")),
                "cache_tokens": _to_int(row.get("cache_tokens")),
                "image_output_tokens": _to_int(row.get("image_output_tokens")),
                "total_tokens": _to_int(row.get("total_tokens")),
            }
            for row in trend_rows
        ],
        "models": with_ratio(model_rows),
        "api_keys": with_ratio(api_key_rows),
        "endpoints": with_ratio(endpoint_rows),
        "recent_requests": [
            {
                "created_at": _iso(row.get("created_at")),
                "api_key_name": row.get("api_key_name") or "",
                "model": row.get("model") or "",
                "request_type": _to_int(row.get("request_type")),
                "stream": bool(row.get("stream")),
                "input_tokens": _to_int(row.get("input_tokens")),
                "output_tokens": _to_int(row.get("output_tokens")),
                "cache_tokens": _to_int(row.get("cache_tokens")),
                "image_output_tokens": _to_int(row.get("image_output_tokens")),
                "total_tokens": _to_int(row.get("total_tokens")),
                "duration_ms": _to_int(row.get("duration_ms")),
                "first_token_ms": _to_int(row.get("first_token_ms")),
            }
            for row in recent_rows
        ],
    }


@router.get("/personal/token-usage")
def get_personal_token_usage(
    period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
    granularity: str = Query("day"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    sub2api_user = _resolve_current_sub2api_user(current_user)
    payload = _build_user_token_usage_payload(
        _to_int(sub2api_user.get("user_id")),
        period,
        granularity,
        start_date,
        end_date,
    )
    payload["user"]["aihub_username"] = current_user.username or ""
    payload["user"]["aihub_first_name"] = current_user.first_name or ""
    return payload


@router.get("/summary/token-usage/users/{user_id}")
def get_summary_token_usage_user_detail(
    user_id: int,
    period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
    granularity: str = Query("day"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="无权查看其他用户的用量数据")
    return _build_user_token_usage_payload(user_id, period, granularity, start_date, end_date)
