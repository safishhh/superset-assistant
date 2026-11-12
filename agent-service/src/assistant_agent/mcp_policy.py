from __future__ import annotations

"""MCP 透传门控。

权限完全交给 Superset 服务端（tools/list 可见性过滤 + 调用期 FAB RBAC 已实测生效），
本模块只管一件事：**改动持久状态的写操作必须走 propose_write 的确认/快照/回滚流程**。
默认只出预览的写工具放行，并把持久化参数强制改回预览，避免"模型顺手保存"。
"""

import json
from typing import Any

# MCP 自身的通道，模型不该经由 mcp_call 再调一次
INFRA_TOOLS = frozenset({"search_tools", "call_tool"})

# 会直接改动 Superset 持久对象：必须走 propose_write
PROPOSE_WRITE_REQUIRED = frozenset(
    {
        "add_chart_to_existing_dashboard",
        "create_dataset",
        "create_theme",
        "create_virtual_dataset",
        "delete_chart",
        "delete_dashboard",
        "duplicate_dashboard",
        "generate_dashboard",
        "manage_dashboard_certification",
        "manage_dashboard_owners",
        "manage_dashboard_roles",
        "manage_native_filters",
        "remove_chart_from_dashboard",
        "restore_chart",
        "restore_dashboard",
        "save_sql_query",
        "update_dashboard",
        "update_dataset_metric",
    }
)

# 禁止直调、但 propose_write 的 15 类动作也不支持：既没有确认通道，也不该对用户
# 承诺"确认后就能执行"。rc2 的 MCP 没有 delete_dataset/delete_theme/
# delete_saved_query，新建对象无法经 MCP 回滚；改 owner/角色属于权限变更一律不做。
# manage_native_filters 不在此列：新增已做成 add_native_filter 动作，
# 其余子操作由 gate_call 按请求内容单独拒绝。
NOT_SUPPORTED_BY_PROPOSE_WRITE = frozenset(
    {
        "create_dataset",
        "create_virtual_dataset",
        "create_theme",
        "save_sql_query",
        "manage_dashboard_owners",
        "manage_dashboard_roles",
    }
)

# 默认不改动持久状态的写工具：放行，并把持久化开关按回预览语义
PREVIEW_SAFE: dict[str, tuple[str, Any] | None] = {
    "generate_chart": ("save_chart", False),
    "update_chart": ("generate_preview", True),
    "update_chart_preview": None,  # 只改缓存里的未保存 form_data
    "generate_explore_link": None,  # 只生成 URL
}

# 未知工具名兜底：像写操作的一律要求走 propose_write（上游新增写工具默认拒绝）
WRITE_VERB_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "restore_",
    "duplicate_",
    "manage_",
    "save_",
    "add_",
    "remove_",
    "set_",
    "clear_",
    "grant_",
    "revoke_",
    "import_",
    "install_",
)

MAX_RESULT_CHARS = 12_000
MAX_SCHEMA_CHARS = 8_000
MAX_LIST_ITEMS = 40
MAX_STRING_CHARS = 800


def gate_call(
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any]]:
    """返回 (是否放行, 提示文本, 规范化后的参数)。"""
    name = (tool_name or "").strip()
    args = dict(arguments or {})
    if not name:
        return False, "缺少 tool_name", args
    if name in INFRA_TOOLS:
        return (
            False,
            f"{name} 是 MCP 基础设施工具，请改用 mcp_search 发现、mcp_call 调用",
            args,
        )
    if name in PROPOSE_WRITE_REQUIRED:
        if name == "manage_native_filters":
            request = args.get("request") or {}
            if (
                request.get("update")
                or request.get("remove")
                or request.get("reorder") is not None
            ):
                return (
                    False,
                    "原生筛选器只开放新增（propose_write 的 add_native_filter 动作）；"
                    "修改/删除/重排的改前配置读不全、无法可靠回滚，"
                    "请指引用户在 Superset 看板编辑器完成，不要说成没有权限。",
                    args,
                )
            return (
                False,
                "manage_native_filters 会改动看板持久配置，新增筛选器必须用 "
                "propose_write 的 add_native_filter 动作生成待确认方案"
                "（回滚＝按返回的筛选器 id 移除），不要直接调用",
                args,
            )
        if name in NOT_SUPPORTED_BY_PROPOSE_WRITE:
            return (
                False,
                f"{name} 属于助手不开放的写操作：改前状态读不到或无法回滚，"
                "propose_write 也没有对应动作，不能生成确认方案。"
                "请如实告知用户该操作需在 Superset 界面完成，不要说成没有权限。",
                args,
            )
        return (
            False,
            f"{name} 会直接改动 Superset 持久对象，必须用 propose_write 生成待确认方案"
            "（有快照和回滚），不要直接调用",
            args,
        )
    if name in PREVIEW_SAFE:
        guard = PREVIEW_SAFE[name]
        if guard is None:
            return True, "", args
        key, value = guard
        request = dict(args.get("request") or {})
        forced = request.get(key) != value
        request[key] = value
        args["request"] = request
        note = (
            f"已按预览模式执行（{key}={value}），未写入 Superset；"
            "需要真正保存请改用 propose_write"
            if forced
            else ""
        )
        return True, note, args
    if name.startswith(WRITE_VERB_PREFIXES):
        return (
            False,
            f"{name} 看起来是写操作且不在预览白名单内，请用 propose_write 生成确认方案",
            args,
        )
    return True, "", args


def _shrink(value: Any, notes: list[str]) -> Any:
    if isinstance(value, dict):
        return {key: _shrink(item, notes) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            notes.append(f"列表已截断到 {MAX_LIST_ITEMS} 项（共 {len(value)} 项）")
            return [_shrink(item, notes) for item in value[:MAX_LIST_ITEMS]]
        return [_shrink(item, notes) for item in value]
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        notes.append("超长文本字段已截断")
        return value[:MAX_STRING_CHARS] + "…"
    return value


def compact_result(
    data: Any,
    max_chars: int = MAX_RESULT_CHARS,
) -> tuple[Any, list[str]]:
    """把 MCP 响应压到可控体积，避免透传撑爆上下文。"""
    notes: list[str] = []
    payload = _shrink(data, notes)
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    if len(text) > max_chars:
        notes.append(f"响应过大，已压缩为前 {max_chars} 字符的文本预览")
        return {"_preview": text[:max_chars]}, notes
    return payload, notes


def compact_schema(schema: Any) -> Any:
    payload, _ = compact_result(schema, MAX_SCHEMA_CHARS)
    return payload
