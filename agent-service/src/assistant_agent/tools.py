from __future__ import annotations

import asyncio
import logging
import re
import time as _time
from dataclasses import replace
from datetime import timedelta
from typing import Annotated, Any, Literal

import sqlglot
from pydantic import Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from .admin.db import utcnow
from .admin.store import KnowledgeQuotaError
from .analysis import (
    dimension_contribution as compute_contribution,
    period_compare as compute_period_compare,
    structure_effect as compute_structure_effect,
)
from .auth import sign_mcp_token
from .deps import AgentDeps
from .forecast import trend_forecast as compute_trend_forecast
from .labels import translate_labels
from .mcp_client import MCPClient, MCPError
from .mcp_policy import compact_result, compact_schema, gate_call
from .models import (
    ColumnInfo,
    ContributionResult,
    DatasetCandidate,
    DatasetFilter,
    DatasetInfoResult,
    MetricInfo,
    MetadataSearchResult,
    PeriodCompareResult,
    QueryDatasetResult,
    RunSqlResult,
    StructureEffectResult,
    TrendForecastResult,
    KnowledgeItem,
    KnowledgeListResult,
    KnowledgeSaveResult,
    WriteProposalResult,
)
from .write_actions import build_plan, collect_snapshot, risk_level

logger = logging.getLogger(__name__)

ANALYSIS_ROW_LIMIT = 20_000

KNOWLEDGE_ITEM_MAX_CHARS = 600


def _truncate_knowledge(row: dict[str, Any]) -> dict[str, Any]:
    """员工知识库条目走同一套 token 预算：正文截断，长度另给。"""
    body = str(row.get("content") or "")
    return {
        **row,
        "content": body[:KNOWLEDGE_ITEM_MAX_CHARS],
        "content_chars": len(body),
        "truncated": len(body) > KNOWLEDGE_ITEM_MAX_CHARS,
    }


def _refresh_mcp_token(ctx: RunContext[AgentDeps]) -> str:
    """以当前用户身份自签一个短命 MCP JWT（入口 token 只有 5 分钟）。

    长任务/中途离开后回来继续时，中途的工具调用会撞 401；这里每次调用重新
    签发，滑动续期，RBAC/RLS 语义不变（身份仍是该用户）。
    """
    return sign_mcp_token(
        ctx.deps.settings,
        ctx.deps.user.username,
        ctx.deps.user.roles,
        ttl=300,
        jti_prefix=f"agent-{ctx.deps.run_id}",
    )


def _client(ctx: RunContext[AgentDeps]) -> MCPClient:
    return MCPClient(
        ctx.deps.settings.mcp_url,
        _refresh_mcp_token(ctx),
        timeout=120.0,
        on_call=ctx.deps.record_mcp_call,
    )


def _client_unlogged(ctx: RunContext[AgentDeps]) -> MCPClient:
    """取数工具自己合并中文别名后再写审计，不能让 on_call 先落一份旧结果。"""
    return MCPClient(
        ctx.deps.settings.mcp_url,
        _refresh_mcp_token(ctx),
        timeout=120.0,
    )


def _elapsed_ms(started: float) -> int:
    return int((_time.perf_counter() - started) * 1000)


def _sample_row(
    rows: list[dict[str, Any]], names: list[str]
) -> dict[str, Any] | None:
    if not rows:
        return None
    first = rows[0]
    return {name: first.get(name) for name in names if name in first}


def _hint_labels(
    ctx: RunContext[AgentDeps], names: list[str]
) -> dict[str, str]:
    """同轮数据集信息里的中文别名（search_metadata 目录或 mcp_call 调 get_dataset_info）。"""
    hints: dict[str, str] = {}
    for mapping in ctx.deps.dataset_labels.values():
        for name in names:
            if name in mapping:
                hints.setdefault(name, mapping[name])
    return hints


def _retry(ctx: RunContext[AgentDeps], message: object) -> ModelRetry:
    """记录最后一次工具报错，便于失败时向用户说明具体原因。"""
    text = str(message)
    ctx.deps.last_tool_error = text[:500]
    return ModelRetry(text)


def _compute(ctx: RunContext[AgentDeps], fn: Any, *args: Any, **kwargs: Any) -> Any:
    """列名/维度写错时让模型自己纠正，而不是整轮失败。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise _retry(ctx, f"分析计算失败：{exc}") from exc


def _require_employee_tool(
    ctx: RunContext[AgentDeps], tool_name: str, *aliases: str
) -> None:
    """选中 AI 员工时，未勾选的工具一律不允许调用。

    aliases 是等价名称（如助手工具包装的 MCP 工具名），用于兼容旧白名单。
    """
    if ctx.deps.employee_tool_allowed(tool_name, *aliases):
        return
    employee = ctx.deps.employee or {}
    name = employee.get("nickname") or employee.get("username") or "当前 AI 员工"
    raise _retry(ctx, 
        f"{name} 未开通 {tool_name}，无法调用；请改用已开通的工具或切换 AI 员工"
    )


def _label_of(name: str, item: dict[str, Any]) -> str | None:
    """字段的中文口径名：`verbose_name`（别名）优先，其次 `description`（备注）。

    有的数据集只填了备注没填别名（如 ods_order_detail），只读 verbose_name 会
    整表拿不到中文名；表达式本身不是口径名（COUNT(*)），要丢掉。
    """
    for key in ("verbose_name", "description"):
        value = str(item.get(key) or "").strip()
        if not value:
            continue
        if value.lower() == name.lower() or value == item.get("expression"):
            continue
        return value
    return None


def _columns(items: Any) -> list[ColumnInfo]:
    columns: list[ColumnInfo] = []
    for item in items or []:
        if isinstance(item, str):
            columns.append(ColumnInfo(name=item))
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("column_name")
        if not name:
            continue
        name = str(name)
        columns.append(
            ColumnInfo(
                name=name,
                type=item.get("type") or item.get("data_type"),
                verbose_name=_label_of(name, item),
            )
        )
    return columns


def _metrics(items: Any) -> list[MetricInfo]:
    metrics: list[MetricInfo] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("metric_name")
        if not name:
            continue
        name = str(name)
        metrics.append(
            MetricInfo(
                name=name,
                expression=item.get("expression"),
                description=item.get("description"),
                verbose_name=_label_of(name, item),
            )
        )
    return metrics


# 本地匹配权重：越靠近"业务口径定义"的字段越能证明这个数据集相关
_MATCH_WEIGHTS = {
    "table": 6,
    "dataset_note": 5,
    "metric": 4,
    "column": 3,
    "schema": 2,
}

# 口语词，参与子串匹配会大量误命中
_NOISE_TERMS = frozenset(
    {
        "多少", "什么", "怎么", "如何", "请问", "帮我", "一下", "这个", "那个",
        "哪些", "是否", "可以", "需要", "数据", "情况", "问题", "分析", "统计",
        "看一下", "告诉", "分别", "以及", "还有", "并且", "我们", "你们",
    }
)

MAX_DETAILED_DATASETS = 3
METADATA_COLUMN_CAP = 60
METADATA_METRIC_CAP = 40


def _query_terms(query: str) -> list[str]:
    """把问题拆成可用于匹配字段名的词。

    Superset 服务端的 `search` 只在 table_name/schema/sql 等结构字段上做子串
    匹配（见 DatasetRestApi.search_columns），中文口径词必然返回 0 条，所以
    分词与匹配必须在本地对指标名/列名及其别名做。
    """
    raw = (query or "").strip().lower()
    if not raw:
        return []
    terms: list[str] = []

    def add(term: str) -> None:
        term = term.strip().strip("_")
        if len(term) < 2 or term in _NOISE_TERMS or term in terms:
            return
        if term.isascii() and len(term) < 3:
            return  # 两字母拉丁词（id、no）误命中率太高
        terms.append(term)

    add(raw)
    for run in re.findall(r"[一-鿿]+", raw):
        if len(run) <= 4:
            sizes = range(len(run), 1, -1)
        else:
            add(run)
            sizes = (3, 2)
        for size in sizes:
            for start in range(0, len(run) - size + 1):
                add(run[start : start + size])
    for token in re.findall(r"[a-z0-9_]+", raw):
        add(token)
        for part in token.split("_"):
            add(part)
    return terms


def _dataset_fields(item: dict[str, Any]):
    """产出可匹配的字段：(权重键, 展示标签, 文本, 是否标识符)。"""
    table = str(item.get("table_name") or "")
    if table:
        yield "table", f"表名 {table}", table, True
    schema = str(item.get("schema") or "")
    if schema:
        yield "schema", f"schema {schema}", schema, True
    note = str(item.get("description") or "")
    if note:
        yield "dataset_note", "数据集说明", note, False
    for metric in item.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("metric_name") or metric.get("name") or "")
        if not name:
            continue
        yield "metric", f"指标 {name}", name, True
        gloss = _label_of(name, metric)
        if gloss:
            yield "metric", f"指标「{gloss}」({name})", gloss, False
    for column in item.get("columns") or []:
        if not isinstance(column, dict):
            continue
        name = str(column.get("column_name") or column.get("name") or "")
        if not name:
            continue
        yield "column", f"列 {name}", name, True
        gloss = _label_of(name, column)
        if gloss:
            yield "column", f"列「{gloss}」({name})", gloss, False


def _match_datasets(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按命中字段加权打分并排序；每个字段最多计一次权重，避免同义词碎片刷分。"""
    terms = _query_terms(query)
    if not terms:
        return []
    scored: list[dict[str, Any]] = []
    for item in items:
        score = 0
        hits: list[tuple[int, str]] = []
        for kind, label, text, is_name in _dataset_fields(item):
            low = text.lower()
            if any(
                term in low or (is_name and low in term) for term in terms
            ):
                weight = _MATCH_WEIGHTS[kind]
                score += weight
                hits.append((weight, label))
        if not score:
            continue
        hits.sort(key=lambda pair: -pair[0])
        scored.append(
            {
                "item": item,
                "score": score,
                "matched_in": [label for _, label in hits[:3]],
            }
        )
    scored.sort(
        key=lambda row: (-row["score"], str(row["item"].get("table_name") or ""))
    )
    return scored


def _item_labels(item: dict[str, Any]) -> dict[str, str]:
    """从目录条目提取 字段名 -> 中文口径名，供图表中文列名复用。"""
    labels: dict[str, str] = {}
    for group in ("columns", "metrics"):
        for entry in item.get(group) or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("column_name") or entry.get("metric_name") or "")
            if not name:
                continue
            label = _label_of(name, entry)
            if label:
                labels[name] = label
    return labels


def _cache_item_labels(ctx: RunContext[AgentDeps], item: dict[str, Any]) -> None:
    labels = _item_labels(item)
    if not labels:
        return
    for key in (item.get("id"), item.get("table_name")):
        if key is not None:
            ctx.deps.dataset_labels[str(key)] = labels


def _detailed_dataset(row: dict[str, Any]) -> DatasetInfoResult:
    """目录条目 -> 给模型看的详情，宽表按上限裁剪并注明。"""
    item = row["item"]
    columns = _columns(item.get("columns"))
    metrics = _metrics(item.get("metrics"))
    warnings: list[str] = []
    if len(columns) > METADATA_COLUMN_CAP:
        warnings.append(
            f"列共 {len(columns)} 个，只列出前 {METADATA_COLUMN_CAP} 个；"
            "完整字段用 mcp_call(\"get_dataset_info\", {\"request\": {\"identifier\": <id>}}) 查"
        )
        columns = columns[:METADATA_COLUMN_CAP]
    if len(metrics) > METADATA_METRIC_CAP:
        warnings.append(
            f"指标共 {len(metrics)} 个，只列出前 {METADATA_METRIC_CAP} 个"
        )
        metrics = metrics[:METADATA_METRIC_CAP]
    return DatasetInfoResult(
        id=item.get("id", "unknown"),
        name=str(item.get("table_name") or item.get("id") or "unknown"),
        schema=item.get("schema"),
        database=item.get("database_name"),
        database_id=item.get("database_id"),
        main_dttm_col=item.get("main_dttm_col"),
        columns=columns,
        metrics=metrics,
        warnings=warnings,
        matched_in=list(row.get("matched_in") or []),
    )


def _error(data: Any) -> str | None:
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return None


def validate_single_statement(sql: str) -> None:
    """只允许一条语句；"只读"交给 Superset 与数据库账号，不在这里重复实现。

    多语句是实测中唯一宿主不拦、且会静默出错的：`SELECT 1; SELECT 2` 返回
    `success:true`，但顶层 `rows` 只装最后一条的结果，模型会把部分结果当全部。
    其余防护的实测归属：DML -> "DML queries are not allowed on this database"，
    DDL / 危险函数（SLEEP / LOAD_FILE / BENCHMARK / CURRENT_USER）/
    `SHOW GRANTS` / `INTO OUTFILE` 也都被 Superset 挡；生产环境还要把连接账号
    设成只读作为第二层（见 AGENTS 护栏）。
    """
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"SQL 解析失败：{exc}") from exc
    if len(statements) != 1 or statements[0] is None:
        raise ValueError("只允许执行单条 SQL 语句")


def guard_execute_sql_arguments(
    arguments: dict[str, Any] | None, max_rows: int
) -> dict[str, Any]:
    """mcp_call 直调 execute_sql 时的护栏：单语句校验 + 行数上限。

    只读不在这里重复实现：宿主拒 DML/DDL，生产连接账号按只读配置。
    """
    args = dict(arguments or {})
    request = dict(args.get("request") or {})
    sql = str(request.get("sql") or "")
    validate_single_statement(sql)
    try:
        limit = int(request.get("limit") or max_rows)
    except (TypeError, ValueError):
        limit = max_rows
    request["limit"] = max(1, min(limit, max_rows))
    request.setdefault("timeout", 30)
    args["request"] = request
    return args


def clamp_dataset_row_limit(
    arguments: dict[str, Any] | None, max_rows: int
) -> dict[str, Any]:
    """mcp_call 调 query_dataset 时，把显式 row_limit 收到 Agent 上限内。"""
    args = dict(arguments or {})
    request = dict(args.get("request") or {})
    if request.get("row_limit") is None:
        return args
    try:
        wanted = int(request.get("row_limit"))
    except (TypeError, ValueError):
        wanted = max_rows
    request["row_limit"] = max(1, min(wanted, max_rows))
    args["request"] = request
    return args


# 宿主 get_dataset_info 默认只回 column_name/type/is_dttm，实测 7 列里 0 个带
# 中文别名；且部分数据集的中文名只存在备注 description 里。
DATASET_INFO_COLUMN_FIELDS = (
    "column_name",
    "type",
    "is_dttm",
    "verbose_name",
    "description",
)


def guard_dataset_info_arguments(
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """`mcp_call` 直调 get_dataset_info 时补上 column_fields（模型常漏）。"""
    args = dict(arguments or {})
    request = dict(args.get("request") or {})
    if not request.get("column_fields"):
        request["column_fields"] = list(DATASET_INFO_COLUMN_FIELDS)
        args["request"] = request
    return args


def _cache_info_labels(
    ctx: RunContext[AgentDeps], data: dict[str, Any], identifier: Any
) -> None:
    """把数据集信息里的中文别名写进缓存，供 query_dataset / run_sql 复用。"""
    labels = _item_labels(data)
    if not labels:
        return
    for key in (data.get("id"), identifier):
        if key is not None:
            ctx.deps.dataset_labels[str(key)] = labels


async def _probe_dataset_labels(
    ctx: RunContext[AgentDeps], identifier: Any
) -> dict[str, str]:
    """缓存没命中时向宿主要一次权威别名（单个数据集，比全目录便宜）。

    查过就记一个键（哪怕是空），避免同一轮对着没有别名的表反复请求。
    """
    key = str(identifier)
    if key in ctx.deps.dataset_labels:
        return ctx.deps.dataset_labels[key]
    try:
        data = await _client_unlogged(ctx).call_tool(
            "get_dataset_info",
            {
                "request": {
                    "identifier": identifier,
                    "column_fields": list(DATASET_INFO_COLUMN_FIELDS),
                }
            },
        )
    except Exception as exc:  # noqa: BLE001 - 别名拿不到不影响取数
        logger.warning("dataset alias probe failed for %s: %s", key, exc)
        ctx.deps.dataset_labels.setdefault(key, {})
        return {}
    labels = _item_labels(data) if isinstance(data, dict) else {}
    for cache_key in (
        key,
        str(data.get("id")) if isinstance(data, dict) else None,
        str(data.get("table_name")) if isinstance(data, dict) else None,
    ):
        if cache_key:
            ctx.deps.dataset_labels.setdefault(cache_key, labels)
    return labels


async def _fetch_window(
    ctx: RunContext[AgentDeps],
    *,
    dataset_id: int | str,
    metrics: list[str],
    columns: list[str],
    start: str,
    end: str,
    filters: list[DatasetFilter] | None = None,
    logged: bool = True,
) -> list[dict[str, Any]]:
    request: dict[str, Any] = {
        "dataset_id": dataset_id,
        "metrics": metrics,
        "columns": columns,
        "time_range": f"{start} : {end}",
        "row_limit": ANALYSIS_ROW_LIMIT,
    }
    if filters:
        request["filters"] = [f.model_dump(exclude_none=True) for f in filters]
    # 分析工具把这次取数当内部实现，自己再落一条“分析工具”审计，
    # 否则历史里会看到一条分析步骤挂着三条重复的 query_dataset
    mcp = _client(ctx) if logged else _client_unlogged(ctx)
    data = await mcp.call_tool("query_dataset", {"request": request})
    error = _error(data)
    if error:
        raise _retry(ctx, f"分析取数失败：{error}")
    if not isinstance(data, dict):
        raise _retry(ctx, "分析取数返回了无法识别的数据")
    rows = data.get("data") or data.get("rows") or []
    total_rows = data.get("total_rows")
    if total_rows is not None and int(total_rows) > len(rows):
        # 宿主 MCP 的单次响应上限约 50KB，超出会截断行且不重算 summary，只能靠 total_rows 判定
        raise _retry(
            ctx,
            f"{start} ~ {end} 的聚合结果被宿主响应体积上限截断（共 {int(total_rows)} 行，"
            f"只返回 {len(rows)} 行）。请缩小该日期区间，或减少分组维度（维度越多、行数越多）。",
        )
    return rows


async def _fetch_rows(
    ctx: RunContext[AgentDeps],
    *,
    dataset_id: int | str,
    metrics: list[str],
    columns: list[str],
    windows: list[tuple[str, str]],
    filters: list[DatasetFilter] | None = None,
    logged: bool = True,
) -> list[dict[str, Any]]:
    """按区间分别取数再拼接。

    同比这类跨度很大的对比若一次取整段，中间的空白月份也会占满宿主的响应体积，
    截断后往往整段丢掉本期数据。分窗口取数把行数降到只与两个区间有关。
    """
    rows: list[dict[str, Any]] = []
    for start, end in windows:
        rows.extend(
            await _fetch_window(
                ctx,
                dataset_id=dataset_id,
                metrics=metrics,
                columns=columns,
                start=start,
                end=end,
                filters=filters,
                logged=logged,
            )
        )
    return rows


def attach_tools(
    agent: Agent[AgentDeps, str],
    *,
    allow_delegation: bool = False,
) -> None:
    if allow_delegation:

        @agent.tool
        async def delegate_to_employee(
            ctx: RunContext[AgentDeps],
            employee: Annotated[
                str,
                Field(
                    description=(
                        "目标 AI 牛马的 username 或昵称，必须是当前可用牛马列表中的一项"
                    )
                ),
            ],
            task: Annotated[
                str,
                Field(
                    description=(
                        "要交给对方完成的子任务，写清目标、指标、时间范围和期望产出"
                    )
                ),
            ],
        ) -> str:
            """把子任务交给另一个 AI 牛马执行，并返回对方的回答。

            只有当前 AI 牛马开启「可协调其他牛马」时才会提供此工具。
            """
            ctx.deps.begin_tool("delegate_to_employee")
            current = ctx.deps.employee or {}
            if not current.get("can_delegate"):
                raise _retry(ctx, "当前 AI 牛马没有开启协调能力")
            candidates = ctx.deps.delegates or []
            if not candidates:
                raise _retry(ctx, "当前没有可调用的 AI 牛马")
            needle = employee.strip().lower()
            target = next(
                (
                    item
                    for item in candidates
                    if str(item.get("username") or "").lower() == needle
                    or str(item.get("nickname") or "").lower() == needle
                ),
                None,
            )
            if target is None:
                names = "、".join(
                    f"{item.get('nickname') or item.get('username')}"
                    f"（{item.get('username')}）"
                    for item in candidates
                )
                raise _retry(
                    ctx,
                    f"没有可调用的 AI 牛马「{employee}」；可用：{names}",
                )
            task_text = task.strip()
            if not task_text:
                raise _retry(ctx, "交给其他 AI 牛马的任务不能为空")
            target_name = target.get("nickname") or target.get("username") or "AI 牛马"

            target_runtime = None
            if target.get("model_id"):
                target_runtime = ctx.deps.store.get_runtime_model(
                    int(target["model_id"])
                )
            runtime = target_runtime or ctx.deps.runtime
            wanted_skills = {
                int(item) for item in (target.get("skill_ids") or [])
            }
            skills = (
                [
                    item
                    for item in ctx.deps.store.list_skills(enabled_only=True)
                    if int(item["id"]) in wanted_skills
                ]
                if wanted_skills
                else []
            )
            nested_deps = replace(
                ctx.deps,
                employee=target,
                delegates=[],
                runtime=runtime,
                model_name=(
                    runtime.model_name
                    if runtime is not None
                    else ctx.deps.model_name
                ),
                tool_names=list(ctx.deps.tool_names),
                mcp_calls=ctx.deps.mcp_calls,
                audit_sequence=ctx.deps.audit_sequence,
                dataset_labels={},
                last_tool_error="",
            )
            limit = (
                ctx.deps.max_tool_calls
                if ctx.deps.max_tool_calls is not None
                else ctx.deps.settings.max_tool_calls
            )
            usage_limits = (
                UsageLimits(
                    request_limit=int(limit) + 8,
                    tool_calls_limit=int(limit) + 8,
                )
                if limit
                else None
            )
            try:
                from .agent import build_agent
                from . import llm_log

                nested_agent = build_agent(
                    ctx.deps.settings,
                    runtime,
                    page_context=ctx.deps.page_context,
                    skills=skills,
                    employee=target,
                    delegates=[],
                    reasoning_effort=ctx.deps.reasoning_effort,
                )
                with llm_log.scope(
                    purpose="delegate", employee=target_name, run_id=None
                ):
                    result = await asyncio.wait_for(
                        nested_agent.run(
                            task_text,
                            deps=nested_deps,
                            usage_limits=usage_limits,
                        ),
                        timeout=180,
                    )
            except asyncio.TimeoutError as exc:
                raise _retry(
                    ctx, f"调用「{target_name}」超时，请缩小任务范围后重试"
                ) from exc
            except ModelRetry:
                raise
            except Exception as exc:  # noqa: BLE001
                message = str(exc).strip() or "未知错误"
                raise _retry(
                    ctx, f"调用「{target_name}」失败：{message[:300]}"
                ) from exc
            finally:
                ctx.deps.tool_calls = max(
                    ctx.deps.tool_calls, nested_deps.tool_calls
                )
                ctx.deps.tool_names = list(nested_deps.tool_names)
                ctx.deps.mcp_calls = max(
                    ctx.deps.mcp_calls, nested_deps.mcp_calls
                )
                ctx.deps.audit_sequence = max(
                    ctx.deps.audit_sequence, nested_deps.audit_sequence
                )
            output = str(getattr(result, "output", "") or "").strip()
            if len(output) > 6000:
                output = output[:6000] + "…"
            return f"【{target_name}】{output or '已完成，但没有返回文本结果。'}"

    @agent.tool
    async def search_metadata(
        ctx: RunContext[AgentDeps],
        query: Annotated[
            str,
            Field(
                description=(
                    "业务口径词，例如“销售额”“出发日期”“order amount”；"
                    "可以是中文名、字段备注或英文表名"
                )
            ),
        ],
    ) -> MetadataSearchResult:
        """检索数据集、字段和已保存指标口径。

        一次调用返回可见数据集的目录，以及其中最相关几个的列与指标（含中文口径
        名）。匹配在本地按表名、指标名、列名以及它们的别名/备注进行，所以中文业务
        词也能命中。`datasets` 为空但 `candidates` 非空时，说明没匹配上而不是没有
        数据，请按目录判断口径或向用户确认，不要回答"没有数据"。
        """
        ctx.deps.begin_tool("search_metadata")
        _require_employee_tool(ctx, "search_metadata", "list_datasets")
        arguments = {
            "request": {
                "page": 1,
                "page_size": 100,
                # 目录一次带回列与指标：省掉逐个 get_dataset_info，
                # 也让中文别名能参与本地匹配
                "select_columns": [
                    "id",
                    "table_name",
                    "schema",
                    "database_id",
                    "database_name",
                    "main_dttm_col",
                    "description",
                    "metrics",
                    "columns",
                ],
            }
        }
        started = _time.perf_counter()
        # 不用 on_call 自动落审计：整份目录（每个数据集的全部列）体积太大，
        # 改成手动记录模型实际看到的裁剪版
        mcp = _client_unlogged(ctx)
        try:
            listing = await mcp.call_tool("list_datasets", arguments)
        except Exception as exc:  # noqa: BLE001 - 失败也要留审计
            ctx.deps.record_mcp_call(
                "list_datasets", arguments, None, str(exc), _elapsed_ms(started)
            )
            raise _retry(ctx, str(exc)) from exc
        duration_ms = _elapsed_ms(started)
        error = _error(listing)
        if error:
            ctx.deps.record_mcp_call(
                "list_datasets", arguments, listing, error, duration_ms
            )
            raise _retry(ctx, error)
        catalog = listing if isinstance(listing, dict) else {}
        items = [
            item for item in catalog.get("datasets") or [] if isinstance(item, dict)
        ]
        try:
            total_visible = int(catalog.get("total_count") or len(items))
        except (TypeError, ValueError):
            total_visible = len(items)
        warnings: list[str] = []
        if not items:
            ctx.deps.record_mcp_call(
                "list_datasets",
                arguments,
                {"datasets": [], "total_count": total_visible},
                None,
                duration_ms,
            )
            raise _retry(
                ctx,
                f"当前用户在 Superset 里没有可见的数据集（共 {total_visible} 个）。"
                "请如实说明需要先申请数据集权限，不要编造数据。",
            )
        # 别名缓存覆盖整个目录，后续 query_dataset 不用再调模型翻译
        for item in items:
            _cache_item_labels(ctx, item)

        def _candidate(entry: dict[str, Any], matched: list[str]) -> DatasetCandidate:
            return DatasetCandidate(
                id=entry.get("id", "unknown"),
                name=str(entry.get("table_name") or entry.get("id") or "unknown"),
                column_count=len(
                    [c for c in entry.get("columns") or [] if isinstance(c, dict)]
                ),
                metric_count=len(
                    [m for m in entry.get("metrics") or [] if isinstance(m, dict)]
                ),
                matched_in=matched,
            )

        ranked = _match_datasets(query, items)
        if ranked:
            results = [_detailed_dataset(row) for row in ranked[:MAX_DETAILED_DATASETS]]
            candidates = [
                _candidate(row["item"], row["matched_in"])
                for row in ranked[MAX_DETAILED_DATASETS:]
            ]
        else:
            results = []
            candidates = [_candidate(item, []) for item in items]
            warnings.append(
                f"没有与「{query}」匹配的表名、指标名或列名；"
                f"已列出全部 {len(candidates)} 个可见数据集目录，"
                "请从中判断口径（必要时用 mcp_call 调 get_dataset_info 看字段），不要回答没有数据。"
            )
        if total_visible > len(items):
            warnings.append(
                f"可见数据集共 {total_visible} 个，这里只取前 {len(items)} 个；"
                "需要更多请用 mcp_call(\"list_datasets\", ...) 翻页。"
            )
        result = MetadataSearchResult(
            query=query,
            datasets=results,
            candidates=candidates,
            total_visible=total_visible,
            warnings=warnings,
        )
        ctx.deps.record_mcp_call(
            "list_datasets",
            arguments,
            {
                "search": query,
                "total_count": total_visible,
                # 只记录模型实际看到的裁剪版，不存整份原始目录
                "result": result.model_dump(mode="json"),
            },
            None,
            duration_ms,
        )
        return result

    @agent.tool
    async def query_dataset(
        ctx: RunContext[AgentDeps],
        dataset_id: Annotated[int | str, Field(description="数据集 ID")],
        metrics: Annotated[
            list[str],
            Field(description="已保存指标名列表，例如 ['total_amount']"),
        ],
        columns: Annotated[
            list[str],
            Field(description="分组维度列名列表，例如 ['region']；可为空"),
        ] = [],
        time_range: Annotated[
            str | None,
            Field(description="Superset 时间范围，例如 'Last 30 days' 或 '2026-09-01 : 2026-10-24'"),
        ] = None,
        row_limit: Annotated[int, Field(ge=1)] = 100,
        filters: Annotated[
            list[DatasetFilter] | None,
            Field(
                description=(
                    "维度值过滤（等价 WHERE），例如 "
                    "[{'col':'region','op':'IN','val':['east']}]；"
                    "用户说“只看某个区域/品类”“排除某值”时用这个，不要写 SQL"
                )
            ),
        ] = None,
        time_column: Annotated[
            str | None,
            Field(description="time_range 作用的时间列；缺省用数据集的主时间列"),
        ] = None,
        order_by: Annotated[
            list[str] | None,
            Field(description="排序字段（列名或指标名），例如 ['total_amount']"),
        ] = None,
        order_desc: Annotated[
            bool, Field(description="排序方向：true 降序（默认），false 升序")
        ] = True,
        chart_type: Annotated[
            Literal["auto", "bar", "line", "pie"],
            Field(
                description=(
                    "结果图表类型：趋势/走势用 line，比较/排名用 bar，"
                    "占比/构成（指标非负）用 pie；不确定用 auto（默认）"
                )
            ),
        ] = "auto",
    ) -> QueryDatasetResult:
        """用数据集语义层查询聚合结果，权限与 RLS 由 Superset 按当前用户判定。

        只接受数据集信息里的已保存指标名和列名，不接受 SUM(x) 这类
        表达式。值过滤用 filters、排序用 order_by、指定时间列用 time_column。
        普通用户问数必须用这个工具。
        """
        ctx.deps.begin_tool("query_dataset")
        _require_employee_tool(ctx, "query_dataset")
        limit = min(row_limit, ctx.deps.effective_max_rows())
        request: dict[str, Any] = {
            "dataset_id": dataset_id,
            "metrics": metrics,
            "columns": columns,
            "time_range": time_range,
            "row_limit": limit,
        }
        if filters:
            request["filters"] = [
                item.model_dump(exclude_none=True) for item in filters
            ]
        if time_column:
            request["time_column"] = time_column
        if order_by:
            request["order_by"] = order_by
            request["order_desc"] = order_desc
        arguments = {"request": request}
        started = _time.perf_counter()
        try:
            data = await _client_unlogged(ctx).call_tool(
                "query_dataset", arguments
            )
        except Exception as exc:  # noqa: BLE001 - 失败也要留审计
            ctx.deps.record_mcp_call(
                "query_dataset", arguments, None, str(exc), _elapsed_ms(started)
            )
            raise _retry(ctx, str(exc)) from exc
        duration_ms = _elapsed_ms(started)
        error = _error(data)
        if error:
            ctx.deps.record_mcp_call(
                "query_dataset", arguments, data, error, duration_ms
            )
            raise _retry(ctx, error)
        if not isinstance(data, dict):
            ctx.deps.record_mcp_call(
                "query_dataset", arguments, None, "数据集查询返回为空", duration_ms
            )
            raise RuntimeError("数据集查询返回为空")
        rows = list(data.get("data") or data.get("rows") or [])
        truncated = False
        if len(rows) > limit:
            rows = rows[:limit]
            truncated = True
        warnings = list(data.get("warnings") or [])
        if truncated:
            warnings.append(f"结果已截断到 {limit} 行")
        columns_out = _columns(data.get("columns"))
        if not columns_out and rows:
            columns_out = [ColumnInfo(name=str(key)) for key in rows[0]]
        resolved_id = str(data.get("dataset_id", dataset_id))
        cached_labels = ctx.deps.dataset_labels.get(resolved_id, {})
        column_names = [column.name for column in columns_out]
        labels_out = {
            name: label
            for name, label in cached_labels.items()
            if name in column_names
        }
        dataset_name = data.get("dataset_name") or str(dataset_id)
        missing = [name for name in column_names if name not in labels_out]
        if missing:
            # 先向宿主要权威别名（别名/备注是人写的，比模型猜的准），拿不到才翻译
            probed = await _probe_dataset_labels(ctx, resolved_id)
            if probed:
                labels_out.update(
                    {name: probed[name] for name in missing if name in probed}
                )
                missing = [name for name in missing if name not in labels_out]
        if missing:
            extra = await translate_labels(
                missing,
                settings=ctx.deps.settings,
                runtime=ctx.deps.runtime,
                dataset=str(dataset_name),
                sample=_sample_row(rows, missing),
            )
            labels_out.update(extra)
            if extra:
                # 同轮后续 run_sql / 再次查询直接复用，不再重复翻译
                ctx.deps.dataset_labels.setdefault(resolved_id, {}).update(extra)
        ctx.deps.record_mcp_call(
            "query_dataset",
            arguments,
            {**data, "labels": labels_out, "chart_type": chart_type},
            None,
            duration_ms,
        )
        return QueryDatasetResult(
            dataset_id=data.get("dataset_id", dataset_id),
            dataset_name=dataset_name,
            columns=columns_out,
            rows=rows,
            labels=labels_out,
            chart_type=chart_type,
            row_count=len(rows),
            from_dttm=data.get("from_dttm"),
            to_dttm=data.get("to_dttm"),
            applied_filters=[
                item
                for item in data.get("applied_filters") or []
                if isinstance(item, dict)
            ],
            warnings=warnings,
        )

    @agent.tool
    async def run_sql(
        ctx: RunContext[AgentDeps],
        sql: Annotated[str, Field(description="单条 SQL 查询（只读由 Superset 与数据库账号保证）")],
        database_id: Annotated[int, Field(description="数据库连接 ID")] = 1,
        limit: Annotated[int, Field(ge=1)] = 200,
        chart_type: Annotated[
            Literal["auto", "bar", "line", "pie"],
            Field(
                description=(
                    "结果图表类型：趋势/走势用 line，比较/排名用 bar，"
                    "占比/构成（指标非负）用 pie；不确定用 auto（默认）"
                )
            ),
        ] = "auto",
    ) -> RunSqlResult:
        """执行单条只读 SQL（是否可用由 Superset 的 SQL Lab 权限判定）。

        服务端会按当前用户注入 RLS；没有 SQL Lab 查询权限的用户会被 Superset 拒绝，
        此时如实说明并改用 query_dataset。这里只拦多语句（宿主会静默只回最后一条
        结果）；只读由 Superset 的 DML/DDL 拦截与数据库账号保证。同时限制超时和
        返回行数，成功时原样返回实际执行的 SQL。
        """
        ctx.deps.begin_tool("run_sql")
        _require_employee_tool(ctx, "run_sql", "execute_sql")
        try:
            validate_single_statement(sql)
        except ValueError as exc:
            raise _retry(ctx, str(exc)) from exc
        limit = min(limit, ctx.deps.effective_max_rows())
        arguments = {
            "request": {
                "database_id": database_id,
                "sql": sql,
                "limit": limit,
                "timeout": 30,
            }
        }
        started = _time.perf_counter()
        try:
            data = await _client_unlogged(ctx).call_tool(
                "execute_sql", arguments
            )
        except Exception as exc:  # noqa: BLE001 - 失败也要留审计
            ctx.deps.record_mcp_call(
                "execute_sql", arguments, None, str(exc), _elapsed_ms(started)
            )
            raise _retry(ctx, str(exc)) from exc
        duration_ms = _elapsed_ms(started)
        if isinstance(data, dict) and not data.get("success", True):
            error = str(data.get("error") or "SQL 执行失败")
            ctx.deps.record_mcp_call(
                "execute_sql", arguments, data, error, duration_ms
            )
            raise _retry(ctx, error)
        if not isinstance(data, dict):
            ctx.deps.record_mcp_call(
                "execute_sql", arguments, None, "SQL 执行返回为空", duration_ms
            )
            raise RuntimeError("SQL 执行返回为空")
        rows = list(data.get("rows") or [])
        truncated = False
        if len(rows) > limit:
            rows = rows[:limit]
            truncated = True
        executed_sql = sql
        statements = data.get("statements") or []
        if statements and isinstance(statements[0], dict):
            executed_sql = statements[0].get("executed_sql") or sql
        warnings = [] if not truncated else [f"结果已截断到 {limit} 行"]
        columns_out = _columns(data.get("columns"))
        if not columns_out and rows:
            columns_out = [ColumnInfo(name=str(key)) for key in rows[0]]
        column_names = [column.name for column in columns_out]
        labels_out = _hint_labels(ctx, column_names)
        missing = [name for name in column_names if name not in labels_out]
        if missing:
            labels_out.update(
                await translate_labels(
                    missing,
                    settings=ctx.deps.settings,
                    runtime=ctx.deps.runtime,
                    sql=str(executed_sql),
                    sample=_sample_row(rows, missing),
                )
            )
        ctx.deps.record_mcp_call(
            "execute_sql",
            arguments,
            {**data, "labels": labels_out, "chart_type": chart_type},
            None,
            duration_ms,
        )
        return RunSqlResult(
            sql=str(executed_sql),
            columns=columns_out,
            rows=rows,
            labels=labels_out,
            row_count=len(rows),
            truncated=truncated,
            warnings=warnings,
            chart_type=chart_type,
        )

    @agent.tool
    async def period_compare(
        ctx: RunContext[AgentDeps],
        dataset_id: Annotated[int | str, Field(description="数据集 ID")],
        metric: Annotated[str, Field(description="已保存指标名，例如 total_amount")],
        base_start: Annotated[str, Field(description="基期开始日期 YYYY-MM-DD")],
        base_end: Annotated[str, Field(description="基期结束日期 YYYY-MM-DD")],
        current_start: Annotated[str, Field(description="本期开始日期 YYYY-MM-DD")],
        current_end: Annotated[str, Field(description="本期结束日期 YYYY-MM-DD")],
        dimensions: Annotated[
            list[str] | None,
            Field(description="分组维度，可多列交叉，例如 [\"region\", \"category\"]；不传则只看总量"),
        ] = None,
        time_column: Annotated[str, Field(description="数据集的时间列，默认 order_date")] = "order_date",
        filters: Annotated[
            list[DatasetFilter] | None, Field(description="可选的维度值过滤，例如只看某个区域")
        ] = None,
    ) -> PeriodCompareResult:
        """环比/同比对比，含统计口径与显著性。

        工具自己按两个日期区间分别取聚合数据再计算，不需要把明细行传进来。
        两期天数不同时自动改用日历天日均（basis=daily_avg），并给出覆盖率、
        日波动、Welch t 检验；周期未结束时基期要传相同天数。
        """
        ctx.deps.begin_tool("period_compare")
        _require_employee_tool(ctx, "period_compare", "query_dataset")
        dims = list(dimensions or [])
        rows = await _fetch_rows(
            ctx,
            dataset_id=dataset_id,
            metrics=[metric],
            columns=[time_column, *dims],
            windows=[(base_start, base_end), (current_start, current_end)],
            filters=filters,
            logged=False,
        )
        result = _compute(
            ctx,
            compute_period_compare,
            rows,
            period_col=time_column,
            value_col=metric,
            base_start=base_start,
            base_end=base_end,
            current_start=current_start,
            current_end=current_end,
            dimensions=dims,
        )
        # 只落一条分析工具调用：历史/导出才会显示“环比对比”卡片而不是三条重复的 query_dataset
        ctx.deps.record_tool_call(
            "period_compare",
            {
                "dataset_id": dataset_id,
                "metric": metric,
                "dimensions": dims,
                "base_start": base_start,
                "base_end": base_end,
                "current_start": current_start,
                "current_end": current_end,
                "time_column": time_column,
                "filters": [f.model_dump(exclude_none=True) for f in filters] if filters else None,
            },
            result.model_dump(),
        )
        return result

    @agent.tool
    async def dimension_contribution(
        ctx: RunContext[AgentDeps],
        dataset_id: Annotated[int | str, Field(description="数据集 ID")],
        metric: Annotated[str, Field(description="已保存指标名")],
        dimensions: Annotated[
            list[str],
            Field(description="归因维度，可多列，例如 [\"region\", \"category\"]；多列时同时给出各单维度排名"),
        ],
        base_start: Annotated[str, Field(description="基期开始日期 YYYY-MM-DD")],
        base_end: Annotated[str, Field(description="基期结束日期 YYYY-MM-DD")],
        current_start: Annotated[str, Field(description="本期开始日期 YYYY-MM-DD")],
        current_end: Annotated[str, Field(description="本期结束日期 YYYY-MM-DD")],
        time_column: Annotated[str, Field(description="数据集的时间列")] = "order_date",
        filters: Annotated[
            list[DatasetFilter] | None, Field(description="可选的维度值过滤")
        ] = None,
    ) -> ContributionResult:
        """按维度计算贡献额、贡献率、拉动百分点与集中度。

        支持多列交叉分组；多列时用同一份数据额外给出每个单维度的贡献排名
        （dimension_ranking），不额外取数。返回 HHI 集中度、正负抵消程度，
        总变化接近 0 时会警告贡献率失真。
        """
        ctx.deps.begin_tool("dimension_contribution")
        _require_employee_tool(ctx, "dimension_contribution", "query_dataset")
        rows = await _fetch_rows(
            ctx,
            dataset_id=dataset_id,
            metrics=[metric],
            columns=[time_column, *dimensions],
            windows=[(base_start, base_end), (current_start, current_end)],
            filters=filters,
            logged=False,
        )
        result = _compute(
            ctx,
            compute_contribution,
            rows,
            dimensions=dimensions,
            value_col=metric,
            period_col=time_column,
            base_start=base_start,
            base_end=base_end,
            current_start=current_start,
            current_end=current_end,
        )
        ctx.deps.record_tool_call(
            "dimension_contribution",
            {
                "dataset_id": dataset_id,
                "metric": metric,
                "dimensions": dimensions,
                "base_start": base_start,
                "base_end": base_end,
                "current_start": current_start,
                "current_end": current_end,
                "time_column": time_column,
                "filters": [f.model_dump(exclude_none=True) for f in filters] if filters else None,
            },
            result.model_dump(),
        )
        return result

    @agent.tool
    async def structure_effect(
        ctx: RunContext[AgentDeps],
        dataset_id: Annotated[int | str, Field(description="数据集 ID")],
        numerator_metric: Annotated[str, Field(description="比率分子的已保存指标，例如 total_amount")],
        denominator_metric: Annotated[str, Field(description="比率分母的已保存指标，例如 count")],
        dimensions: Annotated[
            list[str], Field(description="结构维度，可多列，例如 [\"category\"] 或 [\"region\", \"category\"]")
        ],
        base_start: Annotated[str, Field(description="基期开始日期 YYYY-MM-DD")],
        base_end: Annotated[str, Field(description="基期结束日期 YYYY-MM-DD")],
        current_start: Annotated[str, Field(description="本期开始日期 YYYY-MM-DD")],
        current_end: Annotated[str, Field(description="本期结束日期 YYYY-MM-DD")],
        time_column: Annotated[str, Field(description="数据集的时间列")] = "order_date",
        filters: Annotated[
            list[DatasetFilter] | None, Field(description="可选的维度值过滤")
        ] = None,
    ) -> StructureEffectResult:
        """把比率型指标的变化拆成结构效应、效率效应和交互项。

        输入两个已保存指标（分子/分母）和一个或多个结构维度；工具内部取聚合
        数据并计算，返回三项占比、主导项、每个成员的权重变化与自身效应，
        并校验三项之和与总变化的残差。
        """
        ctx.deps.begin_tool("structure_effect")
        _require_employee_tool(ctx, "structure_effect", "query_dataset")
        rows = await _fetch_rows(
            ctx,
            dataset_id=dataset_id,
            metrics=[numerator_metric, denominator_metric],
            columns=[time_column, *dimensions],
            windows=[(base_start, base_end), (current_start, current_end)],
            filters=filters,
            logged=False,
        )
        result = _compute(
            ctx,
            compute_structure_effect,
            rows,
            dimensions=dimensions,
            numerator_col=numerator_metric,
            denominator_col=denominator_metric,
            period_col=time_column,
            base_start=base_start,
            base_end=base_end,
            current_start=current_start,
            current_end=current_end,
        )
        ctx.deps.record_tool_call(
            "structure_effect",
            {
                "dataset_id": dataset_id,
                "numerator_metric": numerator_metric,
                "denominator_metric": denominator_metric,
                "dimensions": dimensions,
                "base_start": base_start,
                "base_end": base_end,
                "current_start": current_start,
                "current_end": current_end,
                "time_column": time_column,
                "filters": [f.model_dump(exclude_none=True) for f in filters] if filters else None,
            },
            result.model_dump(),
        )
        return result

    @agent.tool
    async def trend_forecast(
        ctx: RunContext[AgentDeps],
        dataset_id: Annotated[int | str, Field(description="数据集 ID")],
        metric: Annotated[str, Field(description="要预测的已保存指标名")],
        start: Annotated[str, Field(description="历史开始日期 YYYY-MM-DD，建议至少 60 天")],
        end: Annotated[str, Field(description="历史结束日期 YYYY-MM-DD")],
        horizon_days: Annotated[int, Field(description="向后预测天数，1-365，默认 7")] = 7,
        time_column: Annotated[str, Field(description="数据集的时间列")] = "order_date",
        filters: Annotated[
            list[DatasetFilter] | None, Field(description="可选过滤，例如只预测某个区域")
        ] = None,
    ) -> TrendForecastResult:
        """日粒度趋势预测：线性趋势检验 + STL 分解 + 阻尼 Holt-Winters + 回测 + 预测区间。

        工具自己取历史日聚合数据。返回趋势斜率与显著性、趋势/季节强度、
        留出集 MAPE 回测（对比朴素法与季节朴素法）、95% 预测区间与未来每日值。
        历史不足 14 天、覆盖率低于 50% 或指标恒定不给预测，只说明原因。
        预测假设结构不变、无节假日/促销冲击，回答时必须转述 assumptions。
        """
        ctx.deps.begin_tool("trend_forecast")
        _require_employee_tool(ctx, "trend_forecast", "query_dataset")
        rows = await _fetch_rows(
            ctx,
            dataset_id=dataset_id,
            metrics=[metric],
            columns=[time_column],
            windows=[(start, end)],
            filters=filters,
            logged=False,
        )
        result = _compute(
            ctx,
            compute_trend_forecast,
            rows,
            period_col=time_column,
            value_col=metric,
            start=start,
            end=end,
            horizon_days=horizon_days,
        )
        ctx.deps.record_tool_call(
            "trend_forecast",
            {
                "dataset_id": dataset_id,
                "metric": metric,
                "start": start,
                "end": end,
                "horizon_days": horizon_days,
                "time_column": time_column,
                "filters": [f.model_dump(exclude_none=True) for f in filters] if filters else None,
            },
            result.model_dump(),
        )
        return result

    @agent.tool
    async def mcp_search(
        ctx: RunContext[AgentDeps],
        query: Annotated[
            str | None,
            Field(
                description=(
                    "关键词，例如 'dashboard 布局'、'告警'、'标签'、'导出图表数据'；"
                    "留空返回基础工具"
                ),
                max_length=200,
            ),
        ] = None,
        with_schema: Annotated[
            bool,
            Field(description="true 时返回匹配工具的完整入参 schema（调用前确认参数用）"),
        ] = False,
    ) -> dict[str, Any]:
        """发现 Superset MCP 的可用工具（按当前用户权限过滤后的可见集合）。

        专用工具覆盖不到的能力先用它查；返回的工具名和描述可直接给
        `mcp_call` 使用。权限由 Superset 判定，看不见或调不动就是没权限。
        """
        ctx.deps.begin_tool("mcp_search")
        _require_employee_tool(ctx, "mcp_search")
        mcp = _client(ctx)
        try:
            data = await mcp.search_tools(query or None)
        except MCPError as exc:
            raise _retry(ctx, str(exc)) from exc
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("tools") or []
        else:
            items = []
        items = [item for item in items if isinstance(item, dict)]
        # 常驻工具（health_check/get_instance_info）不会出现在 search_tools，
        # 从 tools/list 补进来，保证全部工具都能被发现；本请求内缓存避免重复往返。
        pinned = ctx.deps.mcp_pinned_tools
        if pinned is None:
            try:
                pinned = await mcp.list_tools()
            except MCPError:
                pinned = []
            else:
                ctx.deps.mcp_pinned_tools = pinned
        known = {str(item.get("name") or "") for item in items}
        needle = (query or "").strip().lower()
        for item in pinned:
            name = str(item.get("name") or "")
            if not name or name in known or name in {"search_tools", "call_tool"}:
                continue
            if needle:
                haystack = " ".join(
                    str(item.get(key) or "")
                    for key in ("name", "title", "description")
                ).lower()
                if needle not in haystack:
                    continue
            items.append(item)
            known.add(name)
        tools: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if not ctx.deps.employee_tool_allowed(str(item.get("name") or "")):
                continue
            annotations = item.get("annotations") or {}
            entry: dict[str, Any] = {
                "name": item.get("name"),
                "title": item.get("title"),
                "description": str(item.get("description") or "")[:200],
                "read_only": bool(annotations.get("readOnlyHint")),
                "destructive": bool(annotations.get("destructiveHint")),
            }
            if with_schema:
                entry["input_schema"] = compact_schema(item.get("inputSchema"))
            tools.append(entry)
        return {
            "count": len(tools),
            "tools": tools,
            "note": (
                "只读工具可直接 mcp_call；改动持久对象的操作必须走 propose_write。"
            ),
        }

    @agent.tool
    async def mcp_call(
        ctx: RunContext[AgentDeps],
        tool_name: Annotated[
            str,
            Field(description="mcp_search 返回的 MCP 工具名，例如 get_chart_data"),
        ],
        arguments: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "该工具的入参对象，绝大多数工具要求包在 request 里，"
                    "例如 {'request': {'identifier': 1}}"
                )
            ),
        ] = None,
    ) -> Any:
        """调用 Superset MCP 工具，覆盖专用工具之外的能力（RBAC/RLS 由 Superset 判定）。

        只读工具人人可用，能否取到数据完全取决于当前用户身份；没有权限会被
        Superset 拒绝，此时如实说明，不要绕过。写操作默认只出预览，
        真正落库必须走 propose_write。
        """
        ctx.deps.begin_tool("mcp_call")
        _require_employee_tool(ctx, "mcp_call")
        allowed, note, normalized = gate_call(tool_name, arguments)
        if not allowed:
            raise _retry(ctx, note)
        _require_employee_tool(ctx, tool_name)
        if tool_name == "execute_sql":
            # 与 run_sql 同一套护栏：单语句校验 + 行数/超时上限（只读与 RLS 由 Superset 保证）
            try:
                normalized = guard_execute_sql_arguments(
                    normalized, ctx.deps.effective_max_rows()
                )
            except ValueError as exc:
                raise _retry(ctx, str(exc)) from exc
        elif tool_name == "query_dataset":
            normalized = clamp_dataset_row_limit(
                normalized, ctx.deps.effective_max_rows()
            )
        elif tool_name == "get_dataset_info":
            normalized = guard_dataset_info_arguments(normalized)
        log_extra = None
        if tool_name == "query_dataset":
            request = (normalized or {}).get("request") or {}
            dataset_id = request.get("dataset_id")
            hint = (
                ctx.deps.dataset_labels.get(str(dataset_id))
                if dataset_id is not None
                else None
            )
            if hint:
                log_extra = {"labels": hint}
        try:
            data = await _client(ctx).call_tool(
                tool_name, normalized, log_extra=log_extra
            )
        except MCPError as exc:
            raise _retry(ctx, str(exc)) from exc
        error = _error(data)
        if error:
            raise _retry(ctx, error)
        if tool_name == "get_dataset_info" and isinstance(data, dict):
            _cache_info_labels(
                ctx,
                data,
                ((normalized or {}).get("request") or {}).get("identifier"),
            )
        if tool_name == "get_dataset_info":
            # 数据集的列/指标列表就是载荷本身，原样给模型（不裁项数、不压字符）
            payload, notes = data, []
        else:
            payload, notes = compact_result(data)
        if note:
            notes = [note, *notes]
        if notes:
            return {"result": payload, "notes": notes}
        return payload

    @agent.tool
    async def save_knowledge(
        ctx: RunContext[AgentDeps],
        title: Annotated[
            str,
            Field(description="知识条目标题，同一标题会覆盖更新", max_length=200),
        ],
        content: Annotated[
            str,
            Field(
                description=(
                    "提炼后的知识内容：由你从用户提供的原始信息中抽取要点，"
                    "写成简洁、自包含、可直接引用的条目（口径、定义、规则、"
                    "偏好等）；不要照抄原始长文本"
                ),
                max_length=8000,
            ),
        ],
    ) -> KnowledgeSaveResult:
        """把当前用户提供的业务知识存入其个人知识库（覆盖同标题条目）。

        适用场景：用户说"记住这个口径/以后按这个算/这是我们团队的定义"，
        或主动分享业务规则、指标口径、缩写含义。存入前必须先提炼压缩。
        这类写入算「自动沉淀」，不会覆盖用户在知识库里手填的同名条目。
        """
        ctx.deps.begin_tool("save_knowledge")
        _require_employee_tool(ctx, "save_knowledge")
        if ctx.deps.store is None:
            raise _retry(ctx, "知识库存储不可用")
        try:
            item = ctx.deps.store.upsert_knowledge(
                ctx.deps.user.username,
                title,
                content,
                source="auto",
            )
        except KnowledgeQuotaError as exc:
            raise _retry(ctx, 
                f"{exc}；请如实告知用户到「知识库」清理后再让我记录，不要改名重试"
            ) from exc
        except ValueError as exc:
            raise _retry(ctx, f"知识条目无效：{exc}") from exc
        ctx.deps.audit.log(
            "knowledge_saved",
            user=ctx.deps.user.username,
            title=title,
            content_chars=len(content),
        )
        return KnowledgeSaveResult(
            saved=True,
            title=item["title"],
            updated_at=str(item.get("updated_at") or ""),
        )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[AgentDeps],
        query: Annotated[
            str,
            Field(description="检索关键词，来自用户问题中的业务概念", max_length=500),
        ],
    ) -> KnowledgeListResult:
        """在当前用户的个人知识库中检索业务知识（全文检索，正文按预算截断）。

        回答业务口径/定义类问题前先调用；结果为空说明该用户没有相关记录。
        `total_matched` 大于 `count` 时说明还有更多命中，可换关键词再查。
        """
        ctx.deps.begin_tool("search_knowledge")
        _require_employee_tool(ctx, "search_knowledge")
        if ctx.deps.store is None:
            raise _retry(ctx, "知识库存储不可用")
        limit = 5
        found = ctx.deps.store.search_knowledge(
            ctx.deps.user.username, query, limit=limit
        )
        items = [{**item, "scope": "user"} for item in found["items"]]
        total = int(found.get("total_matched") or len(items))
        employee = ctx.deps.employee
        if employee and len(items) < limit:
            rows = ctx.deps.store.search_employee_knowledge(
                int(employee["id"]), query, limit=limit - len(items)
            )
            items.extend(
                {**_truncate_knowledge(row), "scope": "employee"} for row in rows
            )
            total += len(rows)
        result = KnowledgeListResult(
            items=[KnowledgeItem(**item) for item in items],
            count=len(items),
            total_matched=total,
        )
        # 命中落库，历史详情/导出/审计才能还原“这条回答引用了哪些知识”
        ctx.deps.record_tool_call(
            "search_knowledge", {"query": query}, result.model_dump()
        )
        return result

    @agent.tool
    async def list_knowledge(
        ctx: RunContext[AgentDeps],
    ) -> KnowledgeListResult:
        """列出当前用户知识库的**目录**（标题 + 来源 + 更新时间，不含正文）。

        要看某条的具体内容，用它的关键词再调 search_knowledge；不要凭标题猜。
        """
        ctx.deps.begin_tool("list_knowledge")
        _require_employee_tool(ctx, "list_knowledge")
        if ctx.deps.store is None:
            raise _retry(ctx, "知识库存储不可用")
        items = ctx.deps.store.knowledge_directory(ctx.deps.user.username)
        return KnowledgeListResult(
            items=[KnowledgeItem(**item) for item in items],
            count=len(items),
            total_matched=len(items),
        )

    @agent.tool
    async def delete_knowledge(
        ctx: RunContext[AgentDeps],
        knowledge_id: Annotated[
            int,
            Field(description="要删除的知识条目 id，先 list_knowledge 拿到 id"),
        ],
    ) -> dict[str, Any]:
        """删除当前用户知识库中指定 id 的条目（移入回收站，用户可自行恢复）。

        仅在用户明确要求删除时使用；只能删该用户自己的条目。
        """
        ctx.deps.begin_tool("delete_knowledge")
        _require_employee_tool(ctx, "delete_knowledge")
        if ctx.deps.store is None:
            raise _retry(ctx, "知识库存储不可用")
        try:
            ctx.deps.store.delete_knowledge(
                ctx.deps.user.username, knowledge_id
            )
        except LookupError as exc:
            raise _retry(ctx, str(exc)) from exc
        ctx.deps.audit.log(
            "knowledge_deleted",
            user=ctx.deps.user.username,
            knowledge_id=knowledge_id,
        )
        return {"deleted": True, "trashed": True}

    @agent.tool
    async def propose_write(
        ctx: RunContext[AgentDeps],
        action_type: Annotated[
            Literal[
                "create_chart",
                "create_dashboard",
                "add_chart_to_dashboard",
                "create_chart_and_add_to_dashboard",
                "update_chart",
                "update_dataset_metric",
                "update_dashboard",
                "duplicate_dashboard",
                "set_dashboard_certification",
                "restore_chart",
                "restore_dashboard",
                "delete_chart",
                "delete_dashboard",
                "remove_chart_from_dashboard",
                "add_native_filter",
            ],
            Field(description="要执行的写操作类型"),
        ],
        summary: Annotated[
            str,
            Field(description="用中文向用户说明将要做什么、影响对象和风险"),
        ],
        payload: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "create_chart: {dataset_id, metric, chart_type=bar|line|area|pie|table|big_number, "
                    "dimension?, chart_name?}; "
                    "create_dashboard: {chart_ids:[int], dashboard_title, published?}; "
                    "add_chart_to_dashboard: {dashboard_id, chart_id, target_tab?}; "
                    "create_chart_and_add_to_dashboard: {dataset_id, metric, chart_type?, dimension?, "
                    "chart_name?, dashboard_id? 或 dashboard_title?}; "
                    "update_chart: {chart_id, chart_type?, metric?, dimension?, chart_name?} 修改已有图表；"
                    "改可视化形式需 metric+chart_type（pie/table 另需 dimension），只改名就只给 chart_name; "
                    "update_dataset_metric: {dataset_id, metric, updates:{expression?,verbose_name?,"
                    "description?,d3format?,warning_text?}}; "
                    "delete_chart: {chart_id}; delete_dashboard: {dashboard_id}; "
                    "remove_chart_from_dashboard: {dashboard_id, chart_id}; "
                    "update_dashboard: {dashboard_id, updates:{dashboard_title?,description?,slug?,published?}}; "
                    "duplicate_dashboard: {dashboard_id, dashboard_title?}; "
                    "set_dashboard_certification: {dashboard_id, certified_by?, certification_details?}（都留空即清除认证）; "
                    "restore_chart: {chart_id}; restore_dashboard: {dashboard_id}; "
                    "add_native_filter: {dashboard_id, filter_type=filter_select|filter_time, name, "
                    "description?, scope_chart_ids?; filter_select 另需 dataset_id+column，可选 "
                    "multi_select/default_to_first_item/enable_empty_filter/sort_ascending/search_all_options; "
                    "filter_time 可选 default_time_range（如 'Last year'）} 仅新增，改/删/重排不支持"
                )
            ),
        ],
    ) -> WriteProposalResult:
        """生成待确认的写操作方案：建图、建板、加图到看板、建图并加看板、改图、改数据集指标、
        改看板信息、复制看板、设置/清除认证、恢复图表/看板、删除图表/看板、从看板移除图表、
        给看板新增原生筛选器（仅新增，回滚＝移除新筛选器）。

        不直接执行；用户确认后由前端调用确认接口执行；禁止声称已经执行。
        删除类为高风险操作：Superset 开启软删除时对象进回收站、可回滚恢复，
        永久删除则无法回滚，summary 里要写清楚影响对象。
        """
        ctx.deps.begin_tool("propose_write")
        _require_employee_tool(ctx, "propose_write")
        if ctx.deps.store is None:
            raise _retry(ctx, "写操作需要审计存储，当前会话不可用")
        try:
            plan = build_plan(action_type, payload)
            _require_employee_tool(ctx, str(plan.get("tool")))
            next_step = plan.get("next_step") or {}
            if next_step.get("tool"):
                _require_employee_tool(ctx, str(next_step["tool"]))
            existing = ctx.deps.store.find_pending_write_action(
                username=ctx.deps.user.username,
                conversation_id=ctx.deps.conversation_id,
                action_type=action_type,
                plan=plan,
            )
            if existing:
                raise _retry(
                    ctx,
                    "已有完全相同的待确认方案"
                    f"（{existing['id']}），不要重复生成；"
                    "请提示用户点击已有确认卡。",
                )
            snapshot = await collect_snapshot(
                _client(ctx),
                action_type,
                plan,
            )
            action = ctx.deps.store.create_write_action(
                username=ctx.deps.user.username,
                conversation_id=ctx.deps.conversation_id,
                run_id=ctx.deps.run_id,
                action_type=action_type,
                risk_level=risk_level(action_type),
                summary=summary,
                plan=plan,
                snapshot=snapshot,
                expires_at=utcnow() + timedelta(minutes=15),
            )
        except (MCPError, ValueError) as exc:
            raise _retry(ctx, f"写操作方案无效：{exc}") from exc

        ctx.deps.audit.log(
            "write_proposed",
            user=ctx.deps.user.username,
            action_id=action["id"],
            action_type=action_type,
            risk_level=action["risk_level"],
            summary=summary,
        )
        snapshot_summary = {
            key: value
            for key, value in {
                "dataset_name": snapshot.get("dataset_name"),
                "metric": (snapshot.get("metric") or {}).get("metric_name"),
                "chart_ids": snapshot.get("chart_ids"),
            }.items()
            if value
        }
        return WriteProposalResult(
            action_id=action["id"],
            status=action["status"],
            action_type=action_type,
            risk_level=action["risk_level"],
            summary=summary,
            tool=plan["tool"],
            arguments=plan["arguments"],
            snapshot_summary=snapshot_summary,
            expires_at=action["expires_at"],
        )


def attach_skills(agent: Agent[AgentDeps, str], skills: list[dict[str, Any]]) -> None:
    """把后台自定义技能注册为 run_skill_* 工具。

    每请求调用：读最新启用技能，重建 agent 工具集（热生效）。
    """
    for skill in skills:
        if not skill.get("enabled"):
            continue
        name = str(skill.get("name") or "").strip()
        instruction = str(skill.get("instruction") or "").strip()
        title = str(skill.get("title") or "").strip()
        description = str(skill.get("description") or "").strip()
        if not name or not instruction:
            continue
        tool_name = f"run_skill_{name}"

        def _make_skill_tool(tname: str, tinstruction: str, ttitle: str, tdesc: str):
            async def _skill_tool(ctx: RunContext[AgentDeps]) -> str:
                ctx.deps.begin_tool(tname)
                return tinstruction

            _skill_tool.__name__ = tname
            _skill_tool.__doc__ = (
                f"技能「{ttitle}」：{tdesc or '按以下指令处理用户请求'}。"
                f"返回的是指令文本，你必须按指令执行后续步骤。"
            )
            return _skill_tool

        agent.tool(_make_skill_tool(tool_name, instruction, title, description))
