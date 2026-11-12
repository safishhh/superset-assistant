from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .admin.api import router as admin_router
from .admin.crypto import SecretBox
from .admin.db import AdminDB
from .admin.store import AdminStore
from .api_shared import _limit_defaults
from .audit import AuditLogger
from .auth import verify_token
from .config import settings
from .limits import UserRateLimiter
from .logging_setup import configure_logging, set_log_retention
from .routes import chat, conversations, knowledge, users, writes
from .runs import RunRegistry
from .tool_catalog import LEGACY_UNRESTRICTED_AGENT_TOOLS

configure_logging(settings.log_dir, settings.log_retention_days)
logger = logging.getLogger(__name__)


async def _retention_loop(
    store: AdminStore,
    audit: AuditLogger,
    days: int,
    interval_seconds: int,
) -> None:
    interval = max(60, interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            purged = await asyncio.to_thread(store.purge_old, days)
            jsonl = await asyncio.to_thread(
                audit.purge_old,
                days,
                store.archive_audit_events,
            )
            knowledge = await asyncio.to_thread(store.prune_knowledge_retention)
            logger.info(
                "retention purge: db=%s jsonl=%s knowledge=%s",
                purged,
                jsonl,
                knowledge,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("retention purge failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.audit = AuditLogger(settings.audit_path)
    admin_db = AdminDB(settings.admin_db_url)
    admin_db.ensure_schema()
    store = AdminStore(admin_db, SecretBox(settings.admin_secret_key))
    store.seed_default_provider(settings)
    store.seed_employees()
    store.seed_skills()
    employees_migrated = store.migrate_employee_tool_catalog(
        LEGACY_UNRESTRICTED_AGENT_TOOLS
    )
    log_settings = store.get_log_settings(settings.log_retention_days)
    set_log_retention(int(log_settings.get("retention_days") or settings.log_retention_days))
    store.get_limit_config(_limit_defaults(settings))
    purged = store.purge_old(settings.admin_retention_days)
    knowledge_pruned = store.prune_knowledge_retention()
    jsonl_purged = app.state.audit.purge_old(
        settings.admin_retention_days,
        store.archive_audit_events,
    )
    app.state.admin_store = store
    app.state.rate_limiter = UserRateLimiter()
    app.state.runs = RunRegistry()
    retention_task = None
    if settings.admin_retention_interval_seconds > 0:
        retention_task = asyncio.create_task(
            _retention_loop(
                store,
                app.state.audit,
                settings.admin_retention_days,
                settings.admin_retention_interval_seconds,
            )
        )
    logger.info(
        "assistant agent started: mcp=%s model=%s mock=%s admin_db=%s purge=%s jsonl=%s knowledge=%s employees_migrated=%s",
        settings.mcp_url,
        settings.llm_model or "-",
        settings.mock_llm,
        settings.admin_db_url,
        purged,
        jsonl_purged,
        knowledge_pruned,
        employees_migrated,
    )
    try:
        yield
    finally:
        app.state.runs.shutdown()
        if retention_task is not None:
            retention_task.cancel()
            with suppress(asyncio.CancelledError):
                await retention_task


app = FastAPI(title="Superset Assistant Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "authorization",
        "content-type",
        "x-conversation-id",
        "x-superset-context",
        "x-employee-id",
        "x-model-id",
        "x-reasoning-effort",
    ],
    expose_headers=["Content-Disposition", "X-Run-Id"],
)


@app.middleware("http")
async def block_disabled_assistant_users(request: Request, call_next):
    """后台按用户关闭助手后，除 /api/me（用于前端判断入口）外统一拒绝。"""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/me":
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                user = verify_token(auth.split(" ", 1)[1].strip(), settings)
            except Exception:  # noqa: BLE001
                user = None
            if user is not None:
                store = getattr(request.app.state, "admin_store", None)
                if store is not None and not store.user_ai_enabled(user.username):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "AI 助手已被管理员关闭，请联系管理员"},
                    )
    return await call_next(request)


app.include_router(admin_router)
app.include_router(users.router)
app.include_router(conversations.router)
app.include_router(knowledge.router)
app.include_router(writes.router)
app.include_router(chat.router)


@app.get("/healthz")
async def healthz(request: Request) -> dict:
    runtime = request.app.state.admin_store.get_runtime_model()
    return {
        "status": "ok",
        "model_configured": bool(
            runtime or settings.llm_model or settings.mock_llm
        ),
        "mock_llm": settings.mock_llm,
        "model": runtime.model_name if runtime else (settings.llm_model or "mock"),
        "mcp_url": settings.mcp_url,
    }


_static_dir = Path(settings.admin_static_dir)
if (_static_dir / "index.html").exists():
    if (_static_dir / "assets").exists():
        app.mount(
            "/admin/assets",
            StaticFiles(directory=_static_dir / "assets"),
            name="admin-assets",
        )

    @app.get("/admin")
    @app.get("/admin/{path:path}")
    async def admin_spa(path: str = ""):
        if path.startswith("api") or path.startswith("assets"):
            raise HTTPException(status_code=404)
        return FileResponse(_static_dir / "index.html")

else:

    @app.get("/admin")
    async def admin_not_built():
        return HTMLResponse(
            "<h1>AI 管理页未构建</h1>"
            "<p>请运行 scripts/build-admin.sh 后重启 Agent。</p>",
            status_code=503,
        )
