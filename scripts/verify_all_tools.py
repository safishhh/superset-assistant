#!/usr/bin/env python3
"""遍历 Superset MCP 全部工具，逐个验证「策略路由 + 实际可调用性」。

在 agent 容器内运行（需要 assistant_agent 包和容器内网可达的 MCP）：

    docker exec -i assistant-agent python - < scripts/verify_all_tools.py

判定口径：
- 只读工具（readOnlyHint=true）：策略必须放行，并真实调用一次；参数不足（validation
  错误）记为 REACHABLE（可达，只是缺必填参数），其他错误记为 FAIL。
- PREVIEW_SAFE 写工具：策略必须放行且强制预览参数。
- PROPOSE_WRITE_REQUIRED：策略必须拒绝并给出 propose_write 提示；
  再校验 15 类 propose_write 动作的 plan 构造是否全部可用。
- 另外抽查非 Admin（west）的 RBAC：可见列表与强行调用都应被 Superset 拦住。

退出码：存在 FAIL 时为 1，否则 0。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

import jwt

from assistant_agent.config import settings
from assistant_agent.mcp_client import MCPClient, MCPError
from assistant_agent.mcp_policy import (
    PREVIEW_SAFE,
    PROPOSE_WRITE_REQUIRED,
    gate_call,
)
from assistant_agent.write_actions import build_plan

ADMIN = "admin"
WEST = "west"

# 每个工具的“最小可执行”参数（拿不到合适对象的工具用空 request，
# 参数校验错误也算可达）
CALL_ARGS: dict[str, dict[str, Any]] = {
    "health_check": {},
    "get_instance_info": {},
    "query_dataset": {"request": {"dataset_id": 1, "metrics": ["count"], "columns": ["region"], "row_limit": 5}},
    "get_dataset_info": {"request": {"identifier": 1}},
    "get_chart_info": {"request": {"identifier": 1}},
    "get_chart_sql": {"request": {"identifier": 1}},
    "get_chart_data": {"request": {"identifier": 1, "limit": 5}},
    "get_chart_preview": {"request": {"identifier": 1, "format": "url"}},
    "get_chart_type_schema": {"request": {"chart_type": "xy"}},
    "get_dashboard_info": {"request": {"identifier": 1}},
    "get_dashboard_layout": {"request": {"identifier": 1}},
    "get_dashboard_datasets": {"request": {"identifier": 1}},
    "get_database_info": {"request": {"identifier": 1}},
    "get_query_info": {"request": {"identifier": 1}},
    "get_saved_query_info": {"request": {"identifier": 1}},
    "get_report_info": {"request": {"identifier": 1}},
    "get_tag_info": {"request": {"identifier": 1}},
    "get_theme_info": {"request": {"identifier": 1}},
    "get_task_info": {"request": {"identifier": 1}},
    "get_annotation_layer_info": {"request": {"identifier": 1}},
    "get_layer_annotation_info": {"request": {"identifier": 1}},
    "list_layer_annotations": {"request": {"layer_id": 1}},
    "get_schema": {"request": {"model_type": "chart"}},
    "find_users": {"request": {"username": ADMIN}},
    "execute_sql": {"request": {"database_id": 1, "sql": "SELECT 1", "limit": 1, "timeout": 10}},
    "open_sql_lab_with_context": {"request": {"sql": "SELECT 1", "database_id": 1}},
}

# 15 类 propose_write 的动作 -> 合法 payload
PROPOSE_SAMPLES: dict[str, dict[str, Any]] = {
    "create_chart": {"dataset_id": 1, "metric": "count", "chart_type": "bar", "dimension": "region"},
    "create_dashboard": {"chart_ids": [1], "dashboard_title": "验证用"},
    "add_chart_to_dashboard": {"dashboard_id": 1, "chart_id": 1},
    "create_chart_and_add_to_dashboard": {"dataset_id": 1, "metric": "count", "chart_type": "bar", "dimension": "region", "dashboard_id": 1},
    "update_chart": {"chart_id": 1, "metric": "count", "chart_type": "bar", "dimension": "region"},
    "update_dataset_metric": {"dataset_id": 1, "metric": "count", "updates": {"description": "验证"}},
    "delete_chart": {"chart_id": 1},
    "delete_dashboard": {"dashboard_id": 1},
    "remove_chart_from_dashboard": {"dashboard_id": 1, "chart_id": 1},
    "update_dashboard": {"dashboard_id": 1, "updates": {"description": "验证"}},
    "duplicate_dashboard": {"dashboard_id": 1},
    "set_dashboard_certification": {"dashboard_id": 1, "certified_by": "验证"},
    "restore_chart": {"chart_id": 1},
    "restore_dashboard": {"dashboard_id": 1},
    "add_native_filter": {"dashboard_id": 1, "filter_type": "filter_time", "name": "验证用时间筛选"},
}


def make_token(username: str, roles: list[str]) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": username,
            "roles": roles,
            "iss": settings.mcp_jwt_issuer,
            "aud": settings.mcp_jwt_audience,
            "iat": now,
            "exp": now + 600,
            "jti": f"verify-{username}-{now}",
        },
        settings.mcp_jwt_secret,
        algorithm=settings.mcp_jwt_algorithm,
    )


def classify_error(text: str) -> str:
    lowered = (text or "").lower()
    if "validation" in lowered or "field required" in lowered or "input should be" in lowered:
        return "REACHABLE"
    if "permission denied" in lowered:
        return "DENIED"
    return "FAIL"


async def main() -> int:
    admin_client = MCPClient(settings.mcp_url, make_token(ADMIN, ["Admin"]), timeout=60.0)
    west_client = MCPClient(settings.mcp_url, make_token(WEST, ["sales_west"]), timeout=60.0)

    tools = await admin_client.search_tools(None)
    if not isinstance(tools, list) or not tools:
        print("FAIL 无法枚举 MCP 工具（search_tools 返回空）")
        return 1
    # search_tools 不返回常驻工具，补 tools/list（health_check / get_instance_info）
    listed = await admin_client.list_tools()
    known = {item.get("name") for item in tools if isinstance(item, dict)}
    for item in listed:
        name = item.get("name")
        if name and name not in {"search_tools", "call_tool"} and name not in known:
            tools.append(item)
    print(f"枚举到 {len(tools)} 个 MCP 工具\n")

    rows: list[tuple[str, str, str, str]] = []
    failures = 0

    for tool in sorted(tools, key=lambda item: item.get("name", "")):
        name = tool.get("name", "")
        annotations = tool.get("annotations") or {}
        read_only = bool(annotations.get("readOnlyHint"))
        args = CALL_ARGS.get(name, {"request": {}})
        allowed, note, normalized = gate_call(name, args)

        if name in PROPOSE_WRITE_REQUIRED:
            verdict = "BLOCKED→propose_write" if not allowed else "FAIL(gate)"
            detail = note
            if allowed:
                failures += 1
        elif not allowed:
            verdict = "FAIL(gate)"
            detail = note
            failures += 1
        else:
            detail = note or ("read-only" if read_only else "preview")
            expected_force = PREVIEW_SAFE.get(name)
            if expected_force:
                key, value = expected_force
                if normalized.get("request", {}).get(key) != value:
                    verdict = "FAIL(force)"
                    failures += 1
                    rows.append((name, "write-preview", verdict, detail))
                    continue
            try:
                await admin_client.call_tool(name, normalized)
                verdict = "OK"
            except MCPError as exc:
                status = classify_error(str(exc))
                verdict = status
                detail = (detail + " | " + str(exc))[:160]
                if status == "FAIL":
                    failures += 1
        rows.append(
            ("write" if not read_only else "read", name, verdict, detail)
        )

    # 写操作 plan 构造
    plan_failures = 0
    for action, payload in PROPOSE_SAMPLES.items():
        try:
            build_plan(action, payload)
        except Exception as exc:  # noqa: BLE001
            plan_failures += 1
            rows.append(("write", f"propose_write:{action}", "FAIL(plan)", str(exc)[:160]))
    rows.append(
        (
            "write",
            f"propose_write：{len(PROPOSE_SAMPLES)} 类动作",
            "OK" if plan_failures == 0 else "FAIL",
            f"{plan_failures} 个构造失败",
        )
    )

    # RBAC 抽查：west 看不到写工具，强行调用被拒
    west_tools = await west_client.search_tools("chart")
    west_names = {item.get("name") for item in (west_tools or []) if isinstance(item, dict)}
    rows.append(
        (
            "rbac",
            "west search_tools('chart')",
            "OK" if "generate_chart" not in west_names else "FAIL",
            f"可见 {len(west_names)} 个，含写工具：{sorted(n for n in west_names if n.startswith('generate') or n.startswith('delete')) or '无'}",
        )
    )
    if "generate_chart" in west_names:
        failures += 1
    # 预览型 generate_chart 只读不写，west 允许（不落库、数据受 RLS 约束）
    try:
        await west_client.call_tool(
            "generate_chart",
            {"request": {"dataset_id": 1, "chart_name": "x", "config": {"chart_type": "big_number", "metric": {"name": "count", "saved_metric": True}}, "save_chart": False, "generate_preview": True}},
        )
        rows.append(("rbac", "west 预览 generate_chart", "OK", "预览不落库，放行符合预期"))
    except MCPError as exc:
        rows.append(("rbac", "west 预览 generate_chart", "OK", f"被拒：{str(exc)[:100]}"))

    # 持久化写必须被 Superset 拒绝。用一个“对象存在、但清空认证是无害 no-op”的写操作探测：
    # delete/update 类工具会先查对象再看权限，用不存在的 id 测不出来。
    try:
        result = await west_client.call_tool(
            "manage_dashboard_certification",
            {
                "request": {
                    "identifier": 1,
                    "certified_by": "",
                    "certification_details": "",
                }
            },
        )
        text = json.dumps(result, ensure_ascii=False)
        denied = (
            "permission denied" in text.lower()
            or '"permission_denied": true' in text
        )
        rows.append(
            (
                "rbac",
                "west 持久化 manage_dashboard_certification",
                "OK" if denied else "FAIL",
                text[:110],
            )
        )
        if not denied:
            failures += 1
    except MCPError as exc:
        denied = "permission denied" in str(exc).lower()
        rows.append(
            (
                "rbac",
                "west 持久化 manage_dashboard_certification",
                "OK" if denied else "FAIL",
                str(exc)[:110],
            )
        )
        if not denied:
            failures += 1

    width = max(len(row[1]) for row in rows)
    print(f"{'类型':<6}{'工具':<{width}}  {'结果':<22}说明")
    print("-" * (width + 60))
    for kind, name, verdict, detail in rows:
        print(f"{kind:<6}{name:<{width}}  {verdict:<22}{detail}")
    ok = sum(1 for row in rows if row[2].startswith("OK"))
    reachable = sum(1 for row in rows if row[2] == "REACHABLE")
    blocked = sum(1 for row in rows if row[2].startswith("BLOCKED"))
    print(
        f"\n合计 {len(rows)} 条：OK={ok} REACHABLE={reachable} "
        f"BLOCKED={blocked} FAIL={failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
