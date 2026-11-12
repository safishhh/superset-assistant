from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    mcp_url: str
    mcp_jwt_secret: str
    mcp_jwt_issuer: str
    mcp_jwt_audience: str
    mcp_jwt_algorithm: str = "HS256"
    max_tool_calls: int = 16
    max_rows: int = 500
    # Superset 的硬上限（SQL_MAX_ROW），Agent 的单次行数不能超过它
    superset_sql_max_row: int = 5000
    audit_path: Path = Path("/app/runtime/audit.jsonl")
    cors_origins: tuple[str, ...] = (
        "http://localhost:8088",
        "http://127.0.0.1:8088",
    )
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_disable_thinking: bool = False
    llm_timeout_seconds: int = 120
    mock_llm: bool = False
    admin_db_url: str = ""
    admin_static_dir: str = "/app/admin_static"
    admin_secret_key: str = ""
    admin_ticket_secret: str = ""
    admin_ticket_audience: str = "assistant-admin"
    admin_ticket_issuer: str = "assistant"
    admin_session_secret: str = ""
    admin_session_ttl: int = 1800
    admin_cookie_secure: bool = False
    admin_retention_days: int = 90
    admin_retention_interval_seconds: int = 86400
    user_rate_limit_per_minute: int = 20
    user_daily_requests: int = 200
    user_daily_tokens: int = 1_000_000
    user_daily_cost: float = 5.0
    superset_metadata_uri: str = ""
    log_dir: Path = Path("/app/runtime/logs")
    log_retention_days: int = 14

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mcp_url=os.environ.get("AGENT_MCP_URL", "http://superset-mcp:5008/mcp"),
            superset_metadata_uri=os.environ.get("SUPERSET_METADATA_URI", ""),
            mcp_jwt_secret=os.environ["MCP_JWT_SECRET"],
            mcp_jwt_issuer=os.environ.get("MCP_JWT_ISSUER", "assistant"),
            mcp_jwt_audience=os.environ.get("MCP_JWT_AUDIENCE", "superset-mcp"),
            mcp_jwt_algorithm=os.environ.get("MCP_JWT_ALGORITHM", "HS256"),
            max_tool_calls=int(os.environ.get("AGENT_MAX_TOOL_CALLS", "16")),
            max_rows=int(os.environ.get("AGENT_MAX_ROWS", "500")),
            superset_sql_max_row=int(
                os.environ.get("SUPERSET_SQL_MAX_ROW", "5000")
            ),
            audit_path=Path(
                os.environ.get("AGENT_AUDIT_PATH", "/app/runtime/audit.jsonl")
            ),
            cors_origins=tuple(
                _csv(
                    os.environ.get(
                        "AGENT_CORS_ORIGINS",
                        "http://localhost:8088,http://127.0.0.1:8088",
                    )
                )
            ),
            llm_model=os.environ.get("LLM_MODEL") or None,
            llm_base_url=os.environ.get("LLM_BASE_URL") or None,
            llm_api_key=os.environ.get("LLM_API_KEY") or None,
            llm_disable_thinking=_bool(
                os.environ.get("LLM_DISABLE_THINKING", "false")
            ),
            llm_timeout_seconds=int(
                os.environ.get("LLM_TIMEOUT_SECONDS", "120")
            ),
            mock_llm=_bool(os.environ.get("AGENT_MOCK_LLM", "true")),
            admin_db_url=os.environ.get(
                "ADMIN_DB_URL",
                "sqlite:////app/runtime/assistant_admin.db?check_same_thread=false&timeout=30",
            ),
            admin_static_dir=os.environ.get(
                "ADMIN_STATIC_DIR", "/app/admin_static"
            ),
            admin_secret_key=os.environ.get("ADMIN_SECRET_KEY", ""),
            admin_ticket_secret=os.environ.get("ADMIN_TICKET_SECRET", ""),
            admin_ticket_audience=os.environ.get(
                "ADMIN_TICKET_AUDIENCE", "assistant-admin"
            ),
            admin_ticket_issuer=os.environ.get(
                "ADMIN_TICKET_ISSUER", "assistant"
            ),
            admin_session_secret=os.environ.get("ADMIN_SESSION_SECRET", ""),
            admin_session_ttl=int(os.environ.get("ADMIN_SESSION_TTL", "1800")),
            admin_cookie_secure=_bool(
                os.environ.get("ADMIN_COOKIE_SECURE", "false")
            ),
            admin_retention_days=int(
                os.environ.get("ADMIN_RETENTION_DAYS", "90")
            ),
            admin_retention_interval_seconds=int(
                os.environ.get("ADMIN_RETENTION_INTERVAL_SECONDS", "86400")
            ),
            user_rate_limit_per_minute=int(
                os.environ.get("AGENT_USER_RATE_PER_MINUTE", "20")
            ),
            user_daily_requests=int(
                os.environ.get("AGENT_USER_DAILY_REQUESTS", "200")
            ),
            user_daily_tokens=int(
                os.environ.get("AGENT_USER_DAILY_TOKENS", "1000000")
            ),
            user_daily_cost=float(
                os.environ.get("AGENT_USER_DAILY_COST", "5.0")
            ),
            log_dir=Path(os.environ.get("AGENT_LOG_DIR", "/app/runtime/logs")),
            log_retention_days=int(
                os.environ.get("AGENT_LOG_RETENTION_DAYS", "14")
            ),
        )


settings = Settings.from_env()
