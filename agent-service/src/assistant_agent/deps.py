from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLogger
from .auth import UserContext
from .config import Settings

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    user: UserContext
    settings: Settings
    audit: AuditLogger
    tool_calls: int = 0
    tool_names: list[str] = field(default_factory=list)
    conversation_id: str = ""
    run_id: str = ""
    model_name: str = ""
    store: Any = None
    # 当前请求使用的模型（字段别名翻译等一次性调用复用同一 provider）
    runtime: Any = None
    mcp_calls: int = 0
    # 本请求内缓存 tools/list 的常驻工具（health_check/get_instance_info），
    # 避免每次 mcp_search 都多打一次 list_tools；可见性按用户固定，缓存安全
    mcp_pinned_tools: list[dict[str, Any]] | None = None
    # 落库的 ai_tool_call 序号（MCP 调用与内置工具共用，保证同一轮内顺序一致）
    audit_sequence: int = 0
    page_context: dict[str, Any] = field(default_factory=dict)
    employee: dict[str, Any] | None = None
    # 当前员工可调用的其他 AI 牛马（已按授权/白名单过滤，排除自己）
    delegates: list[dict[str, Any]] = field(default_factory=list)
    reasoning_effort: str = "default"
    # dataset_id(str) -> {列/指标名: 中文别名}，来自 search_metadata 目录或 mcp_call 调
    # get_dataset_info，供图表标签使用
    dataset_labels: dict[str, dict[str, str]] = field(default_factory=dict)
    # 单次请求工具调用上限（后台「运行限制」可改；None = 用 settings 默认，0 = 不限制）
    max_tool_calls: int | None = None
    # 单次工具返回行数上限（后台「运行限制」可改；None = 用 settings 默认）
    max_rows: int | None = None
    # 最近一次工具报错内容（ModelRetry），用于失败时给用户具体原因
    last_tool_error: str = ""

    def effective_max_rows(self) -> int:
        """单次查询行数上限：后台配置 > 环境默认，且不超过 Superset 的硬上限。"""
        value = self.max_rows if self.max_rows is not None else self.settings.max_rows
        try:
            rows = int(value)
        except (TypeError, ValueError):
            rows = self.settings.max_rows
        ceiling = max(1, int(self.settings.superset_sql_max_row or 5000))
        return max(1, min(rows, ceiling))

    def employee_tool_allowed(self, *tool_names: str) -> bool:
        """选中 AI 员工时按其工具白名单放行；未配置（None）表示不限制。

        可传多个等价名称（助手工具名 + 它包装的 MCP 工具名），
        任一命中即放行，兼容旧版只勾选 MCP 工具的白名单。
        """
        if self.employee is None:
            return True
        allowed = self.employee.get("tools")
        if allowed is None:
            return True
        allowed_set = set(allowed)
        return any(name in allowed_set for name in tool_names)

    def begin_tool(self, name: str) -> None:
        self.tool_calls += 1
        self.tool_names.append(name)
        self.audit.log(
            "tool_call",
            user=self.user.username,
            roles=list(self.user.roles),
            tool=name,
            sequence=self.tool_calls,
        )
        limit = (
            self.max_tool_calls
            if self.max_tool_calls is not None
            else self.settings.max_tool_calls
        )
        if limit and self.tool_calls > limit:
            raise RuntimeError(
                f"工具调用次数超过上限（{limit}），请缩小问题范围后重试"
            )

    def record_mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        error: str | None,
        duration_ms: int,
    ) -> None:
        self.mcp_calls += 1
        self.audit_sequence += 1
        if self.store is None or not self.conversation_id:
            return
        try:
            self.store.log_tool(
                conversation_id=self.conversation_id,
                run_id=self.run_id,
                username=self.user.username,
                model_name=self.model_name,
                sequence=self.audit_sequence,
                tool_name=tool_name,
                args=arguments,
                result=result,
                duration_ms=duration_ms,
                status="error" if error else "ok",
                error=error or "",
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to write audit tool call")

    def record_tool_call(
        self,
        tool_name: str,
        args: Any,
        result: Any,
        *,
        status: str = "ok",
        error: str = "",
    ) -> None:
        """落库内置工具调用（如知识库检索），让历史/导出/审计能还原命中内容。"""
        if self.store is None or not self.conversation_id:
            return
        self.audit_sequence += 1
        try:
            self.store.log_tool(
                conversation_id=self.conversation_id,
                run_id=self.run_id,
                username=self.user.username,
                model_name=self.model_name,
                sequence=self.audit_sequence,
                tool_name=tool_name,
                args=args,
                result=result,
                duration_ms=0,
                status=status,
                error=error,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to write audit tool call")

