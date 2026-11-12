from __future__ import annotations

import time
from datetime import date
from typing import Any

import jwt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from .auth import (
    AdminIdentity,
    as_dict,
    clear_session_cookies,
    create_session_cookie,
    get_store,
    require_admin,
    require_csrf,
    verify_admin_ticket,
)
from ..logging_setup import (
    list_log_files,
    read_ai_calls,
    read_log_tail,
    set_log_retention,
)
from ..mcp_client import MCPClient, MCPError
from ..tool_catalog import build_tool_catalog
from .schemas import (
    AgentLimitsIn,
    EmployeeIn,
    EmployeeKnowledgeIn,
    EmployeeUpdateIn,
    LimitsIn,
    KnowledgeSettingsIn,
    LogSettingsIn,
    ModelIn,
    ModelUpdate,
    ProviderIn,
    ProviderUpdate,
    RoleEmployeesIn,
    SessionIn,
    SkillCreateIn,
    SkillUpdateIn,
    UserAIAccessIn,
)
from .store import AdminStore

router = APIRouter(prefix="/admin/api", tags=["admin"])


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, IntegrityError):
        return HTTPException(status_code=409, detail="duplicate or constraint violation")
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/session")
async def create_session(
    payload: SessionIn,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    store: AdminStore = request.app.state.admin_store
    settings = request.app.state.settings
    identity = verify_admin_ticket(payload.ticket, settings, store)
    csrf = create_session_cookie(response, identity, settings)
    return {"user": as_dict(identity), "csrf_token": csrf}


@router.post("/logout")
async def logout(
    response: Response,
    _identity: AdminIdentity = Depends(require_csrf),
) -> dict[str, bool]:
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(identity: AdminIdentity = Depends(require_admin)) -> dict[str, Any]:
    return as_dict(identity)


@router.get("/overview")
async def overview(
    days: int = Query(7, ge=1, le=365),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be before to")
    return store.overview(days, start=from_date, end=to_date)


@router.get("/limits")
async def limits(
    request: Request,
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    settings = request.app.state.settings
    return store.get_limit_config(
        {
            "rate_per_minute": settings.user_rate_limit_per_minute,
            "daily_requests": settings.user_daily_requests,
            "daily_tokens": settings.user_daily_tokens,
            "daily_cost": settings.user_daily_cost,
        }
    )


@router.put("/limits")
async def update_limits(
    payload: LimitsIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.save_limit_config(
            payload.model_dump(),
            identity.username,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.get("/agent-limits")
async def agent_limits(
    request: Request,
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    settings = request.app.state.settings
    data = store.get_agent_limits(
        {
            "max_tool_calls": settings.max_tool_calls,
            "max_rows": settings.max_rows,
        }
    )
    # 行数上限不能超过 Superset 的硬上限
    data["superset_sql_max_row"] = settings.superset_sql_max_row
    return data


@router.put("/agent-limits")
async def update_agent_limits(
    payload: AgentLimitsIn,
    request: Request,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    values = payload.model_dump(exclude_none=True)
    settings = request.app.state.settings
    if "max_rows" in values:
        ceiling = max(1, settings.superset_sql_max_row)
        values["max_rows"] = max(1, min(int(values["max_rows"]), ceiling))
    try:
        return store.save_agent_limits(
            values,
            identity.username,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.get("/logs")
async def logs(
    request: Request,
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "files": list_log_files(settings.log_dir),
        "settings": store.get_log_settings(settings.log_retention_days),
        "log_dir": str(settings.log_dir),
        "default_retention_days": settings.log_retention_days,
    }


@router.get("/logs/tail")
async def log_tail(
    request: Request,
    name: str = Query("agent.log"),
    lines: int = Query(500, ge=1, le=5000),
    level: str | None = Query(None, max_length=20),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return read_log_tail(settings.log_dir, name, lines, level)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="日志文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ai-calls")
async def ai_calls(
    request: Request,
    limit: int = Query(200, ge=1, le=1000),
    username: str = Query("", max_length=80),
    model: str = Query("", max_length=120),
    status: str = Query("", max_length=20),
    q: str = Query("", max_length=120),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    settings = request.app.state.settings
    return read_ai_calls(
        settings.log_dir,
        limit=limit,
        username=username,
        model=model,
        status=status,
        keyword=q,
    )


@router.put("/log-settings")
async def update_log_settings(
    payload: LogSettingsIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        after = store.save_log_settings(
            payload.model_dump(),
            identity.username,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    pruned = set_log_retention(int(after["retention_days"]))
    return {**after, "pruned": pruned}


@router.get("/knowledge-settings")
async def knowledge_settings(
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.get_knowledge_settings()


@router.put("/knowledge-settings")
async def update_knowledge_settings(
    payload: KnowledgeSettingsIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.save_knowledge_settings(
            payload.model_dump(), actor=identity.username
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.get("/skills")
async def skills(
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    items = store.list_skills()
    return {"items": items, "total": len(items)}


@router.post("/skills")
async def create_skill(
    payload: SkillCreateIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.create_skill(
            actor=identity.username,
            **payload.model_dump(),
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: int,
    payload: SkillUpdateIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_skill(skill_id, actor=identity.username, **payload.model_dump(exclude_unset=True))
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict:
    try:
        store.delete_skill(skill_id, actor=identity.username)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {"ok": True}


@router.get("/filters")
async def filters(
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.filter_options()


@router.get("/knowledge")
async def knowledge(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    username: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.admin_list_knowledge(
        page=page,
        page_size=page_size,
        username=username or None,
        search=search or None,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.delete("/knowledge/{knowledge_id}")
async def delete_knowledge(
    knowledge_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.admin_delete_knowledge(knowledge_id, actor=identity.username)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {"ok": True}


@router.get("/feedback")
async def feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    username: str | None = None,
    rating: str | None = Query(None, pattern="^(up|down)$"),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    sort_by: str = "created_at",
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.list_feedback(
        page=page,
        page_size=page_size,
        username=username or None,
        rating=rating,
        start=from_date,
        end=to_date,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/audit/conversations")
async def conversations(
    username: str | None = None,
    model_name: str | None = None,
    search: str | None = None,
    status: str | None = None,
    employee_id: int | None = None,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    sort_by: str = "last_at",
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.list_conversations(
        username=username,
        model_name=model_name,
        search=search,
        status=status,
        employee_id=employee_id,
        start=from_date,
        end=to_date,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/audit/conversations/{conversation_id}")
async def conversation_detail(
    conversation_id: str,
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    result = store.get_conversation(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return result


@router.get("/audit/write-actions")
async def write_actions(
    sort_by: str = "created_at",
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.list_write_actions(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/audit/operations")
async def operations(
    actor: str | None = None,
    action: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    return store.list_admin_audit(
        actor=actor,
        action=action,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/usage")
async def usage(
    days: int = Query(30, ge=1, le=365),
    group_by: str = Query(
        "day", pattern="^(day|user|model|detail|user_model|employee)$"
    ),
    username: str | None = None,
    model_name: str | None = None,
    employee_id: int | None = None,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be before to")
    return store.usage(
        days=days,
        group_by=group_by,
        username=username,
        model_name=model_name,
        employee_id=employee_id,
        start=from_date,
        end=to_date,
    )


@router.get("/providers")
async def providers(
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> list[dict[str, Any]]:
    return store.list_providers()


@router.post("/providers")
async def create_provider(
    payload: ProviderIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.create_provider(payload.model_dump(), identity.username)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_provider(
            provider_id, payload.model_dump(exclude_unset=True), identity.username
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, bool]:
    try:
        store.delete_provider(provider_id, identity.username)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: int,
    _identity: AdminIdentity = Depends(require_admin),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return await store.test_provider(provider_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.get("/models")
async def models(
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> list[dict[str, Any]]:
    return store.list_models()


@router.post("/models")
async def create_model(
    payload: ModelIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.create_model(payload.model_dump(), identity.username)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.put("/models/{model_id}")
async def update_model(
    model_id: int,
    payload: ModelUpdate,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_model(
            model_id, payload.model_dump(exclude_unset=True), identity.username
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.post("/models/{model_id}/default")
async def set_default_model(
    model_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.set_default_model(model_id, identity.username)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, bool]:
    try:
        store.delete_model(model_id, identity.username)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


# ---------- AI 员工（AI 牛马） ----------


def _admin_mcp_token(settings: Any, scope: str) -> str:
    """服务端自签一个短命 Admin JWT，用于读取 Superset 目录（工具/用户）。"""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "admin",
            "roles": ["Admin"],
            "iss": settings.mcp_jwt_issuer,
            "aud": settings.mcp_jwt_audience,
            "iat": now,
            "exp": now + 120,
            "jti": f"admin-{scope}-{now}",
        },
        settings.mcp_jwt_secret,
        algorithm=settings.mcp_jwt_algorithm,
    )


@router.get("/mcp-tools")
async def mcp_tools(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    """列出 Superset MCP 工具与助手内置工具（供 AI 员工勾选工具白名单）。"""
    settings = request.app.state.settings
    token = _admin_mcp_token(settings, "catalog")
    client = MCPClient(settings.mcp_url, token, timeout=30.0)
    try:
        tools = await client.search_tools(None)
    except MCPError:
        # 工具检索未启用时退回标准 tools/list（全量目录）
        tools = None
    if isinstance(tools, list):
        searched = tools
    elif isinstance(tools, dict):
        searched = tools.get("tools") or []
    else:
        searched = []
    listed: list[dict[str, Any]] = []
    try:
        listed = await client.list_tools()
    except MCPError as exc:
        if not searched:
            raise HTTPException(
                status_code=502, detail=f"MCP 不可用：{exc}"
            ) from exc
    # 常驻工具（health_check / get_instance_info）只在 tools/list 里，
    # 合成工具 search_tools / call_tool 不是业务工具，不展示。
    synthetic = {"search_tools", "call_tool"}
    by_name: dict[str, dict[str, Any]] = {}
    for tool in [*searched, *listed]:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        name = str(tool["name"])
        if name in synthetic:
            continue
        by_name.setdefault(name, tool)
    items = build_tool_catalog(list(by_name.values()))
    return {
        "items": items,
        "total": len(items),
        "mcp_total": sum(1 for item in items if item["source"] == "mcp"),
        "agent_total": sum(1 for item in items if item["source"] == "agent"),
    }


@router.get("/superset-users")
async def superset_users(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    """列出 Superset 用户（供 AI 员工勾选可见用户）。"""
    settings = request.app.state.settings
    token = _admin_mcp_token(settings, "users")
    client = MCPClient(settings.mcp_url, token, timeout=30.0)
    items: list[dict[str, Any]] = []
    page = 1
    try:
        while page <= 20:
            data = await client.call_tool(
                "list_users",
                {
                    "request": {
                        "page": page,
                        "page_size": 100,
                        "select_columns": [
                            "username",
                            "first_name",
                            "last_name",
                            "active",
                        ],
                    }
                },
            )
            if isinstance(data, str):
                raise HTTPException(
                    status_code=502, detail=f"Superset 用户列表不可用：{data[:200]}"
                )
            if not isinstance(data, dict):
                break
            for row in data.get("users") or []:
                if not isinstance(row, dict) or not row.get("username"):
                    continue
                username = str(row["username"])
                display = " ".join(
                    part
                    for part in (
                        str(row.get("first_name") or ""),
                        str(row.get("last_name") or ""),
                    )
                    if part
                )
                items.append(
                    {
                        "username": username,
                        "display_name": display,
                        "active": bool(row.get("active", True)),
                    }
                )
            if not data.get("has_next"):
                break
            page += 1
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=f"MCP 不可用：{exc}") from exc
    items.sort(key=lambda item: item["username"].lower())
    return {"items": items, "total": len(items)}



_DIRECTORY_ENGINES: dict[str, Any] = {}


def _superset_directory(settings: Any) -> dict[str, Any]:
    """只读 Superset 元数据库，返回用户/角色/分组（后台目录页用）。"""
    uri = getattr(settings, "superset_metadata_uri", "")
    if not uri:
        raise HTTPException(
            status_code=503, detail="未配置 SUPERSET_METADATA_URI，无法读取 Superset 用户目录"
        )
    engine = _DIRECTORY_ENGINES.get(uri)
    if engine is None:
        engine = create_engine(uri, pool_pre_ping=True)
        _DIRECTORY_ENGINES[uri] = engine
    with engine.connect() as connection:
        users = connection.execute(
            text(
                "SELECT id, username, first_name, last_name, email, active "
                "FROM ab_user ORDER BY username"
            )
        ).mappings().all()
        roles = connection.execute(
            text("SELECT id, name FROM ab_role ORDER BY name")
        ).mappings().all()
        user_roles = connection.execute(
            text(
                "SELECT ur.user_id, r.name FROM ab_user_role ur "
                "JOIN ab_role r ON r.id = ur.role_id"
            )
        ).all()
        groups = connection.execute(
            text("SELECT id, name FROM ab_group ORDER BY name")
        ).mappings().all()
        user_groups = connection.execute(
            text(
                "SELECT ug.user_id, g.name FROM ab_user_group ug "
                "JOIN ab_group g ON g.id = ug.group_id"
            )
        ).all()
        group_roles = connection.execute(
            text(
                "SELECT gr.group_id, r.name FROM ab_group_role gr "
                "JOIN ab_role r ON r.id = gr.role_id"
            )
        ).all()
    roles_by_user: dict[int, list[str]] = {}
    for user_id, name in user_roles:
        roles_by_user.setdefault(int(user_id), []).append(str(name))
    groups_by_user: dict[int, list[str]] = {}
    for user_id, name in user_groups:
        groups_by_user.setdefault(int(user_id), []).append(str(name))
    roles_by_group: dict[int, list[str]] = {}
    for group_id, name in group_roles:
        roles_by_group.setdefault(int(group_id), []).append(str(name))
    return {
        "users": [
            {
                "username": str(row["username"]),
                "first_name": str(row["first_name"] or ""),
                "last_name": str(row["last_name"] or ""),
                "email": str(row["email"] or ""),
                "active": bool(row["active"]),
                "roles": sorted(roles_by_user.get(int(row["id"]), [])),
                "groups": sorted(groups_by_user.get(int(row["id"]), [])),
            }
            for row in users
        ],
        "roles": [
            {
                "name": str(row["name"]),
                "user_count": sum(
                    1 for names in roles_by_user.values() if str(row["name"]) in names
                ),
                "group_count": len(roles_by_group.get(int(row["id"]), [])),
            }
            for row in roles
        ],
        "groups": [
            {
                "name": str(row["name"]),
                "user_count": sum(
                    1 for names in groups_by_user.values() if str(row["name"]) in names
                ),
            }
            for row in groups
        ],
    }


@router.get("/superset-directory")
async def superset_directory(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    """Superset 用户/角色/分组目录 + 每个用户的知识库条数。"""
    directory = _superset_directory(request.app.state.settings)
    store: AdminStore = request.app.state.admin_store
    counts = store.knowledge_counts_by_user()
    access = store.user_ai_access_map()
    users = []
    for user in directory["users"]:
        stats = counts.get(user["username"], {})
        users.append(
            {
                **user,
                "knowledge_active": int(stats.get("active", 0)),
                "knowledge_trash": int(stats.get("trash", 0)),
                "ai_enabled": access.get(user["username"], True),
            }
        )
    return {"users": users, "roles": directory["roles"], "groups": directory["groups"]}


@router.put("/users/{username}/ai-access")
async def set_user_ai_access(
    username: str,
    payload: UserAIAccessIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.set_user_ai_access(
            username,
            payload.enabled,
            actor=identity.username,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.get("/roles")
async def role_list(
    request: Request,
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    directory = _superset_directory(request.app.state.settings)
    return {"items": directory["roles"], "groups": directory["groups"]}


@router.get("/roles/{role_name}/employees")
async def role_employees(
    role_name: str,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    directory = _superset_directory(request.app.state.settings)
    all_roles = [item["name"] for item in directory["roles"]]
    store: AdminStore = request.app.state.admin_store
    items = store.list_employees_for_role(role_name, all_roles)
    users = [
        user
        for user in directory["users"]
        if role_name in (user.get("roles") or [])
    ]
    return {
        "role": role_name,
        "items": [
            {
                "id": item["id"],
                "username": item["username"],
                "nickname": item["nickname"],
                "title": item["title"],
                "avatar": item["avatar"],
                "enabled": item["enabled"],
                "available": item["available"],
            }
            for item in items
        ],
        "users": users,
    }


@router.put("/roles/{role_name}/employees")
async def set_role_employees(
    role_name: str,
    payload: RoleEmployeesIn,
    request: Request,
    identity: AdminIdentity = Depends(require_csrf),
) -> dict[str, Any]:
    directory = _superset_directory(request.app.state.settings)
    all_roles = [item["name"] for item in directory["roles"]]
    store: AdminStore = request.app.state.admin_store
    store.set_role_employees(
        role_name,
        payload.employee_ids,
        actor=identity.username,
        all_roles=all_roles,
    )
    return {"ok": True, "role": role_name}


@router.get("/employees")
async def employees(
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    items = store.list_employees()
    return {"items": items, "total": len(items)}


@router.post("/employees")
async def create_employee(
    payload: EmployeeIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.create_employee(actor=identity.username, values=payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.put("/employees/{employee_id}")
async def update_employee(
    employee_id: int,
    payload: EmployeeUpdateIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_employee(
            employee_id,
            actor=identity.username,
            updates=payload.model_dump(exclude_unset=True),
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.delete("/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.delete_employee(employee_id, actor=identity.username)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {"ok": True}


@router.get("/employees/{employee_id}/knowledge")
async def employee_knowledge(
    employee_id: int,
    store: AdminStore = Depends(get_store),
    _identity: AdminIdentity = Depends(require_admin),
) -> dict[str, Any]:
    items = store.list_employee_knowledge(employee_id)
    return {"items": items, "total": len(items)}


@router.post("/employees/{employee_id}/knowledge")
async def save_employee_knowledge(
    employee_id: int,
    payload: EmployeeKnowledgeIn,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.upsert_employee_knowledge(
            employee_id, payload.title, payload.content
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@router.delete("/employees/{employee_id}/knowledge/{knowledge_id}")
async def delete_employee_knowledge(
    employee_id: int,
    knowledge_id: int,
    identity: AdminIdentity = Depends(require_csrf),
    store: AdminStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.delete_employee_knowledge(employee_id, knowledge_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {"ok": True}
