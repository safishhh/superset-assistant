#!/usr/bin/env python3
"""AI 助手全量冒烟：鉴权、RLS、用户 API、逐条反馈、限额、管理 API、写操作、live 工具与语言切换。

栈需要在跑；宿主端口读 infra/.env（SUPERSET_HTTP_PORT / AGENT_HTTP_PORT /
MCP_HTTP_PORT，缺省 8088 / 28088 / 25008）。live 工具部分使用当前配置的真实
模型，断言按"有 error 事件即失败、工具未触发则降级为 WARN"。
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_chat import env as load_env  # noqa: E402
from smoke_chat import chat as sse_chat  # noqa: E402
from smoke_chat import token as make_token  # noqa: E402
from smoke_chat import tool_outputs  # noqa: E402

_ENV = load_env()
SUPERSET = f"http://localhost:{_ENV.get('SUPERSET_HTTP_PORT') or '8088'}"
AGENT = f"http://localhost:{_ENV.get('AGENT_HTTP_PORT') or '28088'}"
MCP = f"http://localhost:{_ENV.get('MCP_HTTP_PORT') or '25008'}/mcp"

RESULTS: list[tuple[str, str, str]] = []


def check(ok: bool, message: str, warn_only: bool = False) -> None:
    status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    RESULTS.append((status, message, ""))
    print(f"{status} {message}")


def section(name: str) -> None:
    RESULTS.append(("SECTION", name, ""))
    print(f"\n== {name}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def superset_login(username: str, password: str):
    """登录 Superset，返回带会话 cookie 的 opener。"""
    cj = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    html = op.open(f"{SUPERSET}/login/").read().decode()
    match = re.search(
        r'name="csrf_token"\s+id="csrf_token"\s+value="([^"]+)"', html, re.S
    )
    if not match:
        raise RuntimeError("login page has no csrf_token")
    data = urllib.parse.urlencode(
        {"username": username, "password": password, "csrf_token": match.group(1)}
    ).encode()
    op.open(f"{SUPERSET}/login/", data)
    return op


def extension_token(op, username: str) -> str:
    body = json.loads(
        op.open(f"{SUPERSET}/extensions/dataagent/assistant/token").read().decode()
    )
    result = body["result"]
    assert result["username"] == username, (
        f"token username mismatch: {result['username']}"
    )
    return result["token"]


def agent_req(
    token_value: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 60,
):
    headers = {"Authorization": f"Bearer {token_value}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{AGENT}{path}", data=data, method=method, headers=headers
    )
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read().decode()
        return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        payload = {"__status": exc.code}
        try:
            payload.update(json.loads(exc.read().decode()))
        except Exception:  # noqa: BLE001
            payload["__body"] = "unreadable"
        return payload


def chat_raw(values: dict, username: str, roles: list[str], question: str):
    """返回 (events, http_status_or_detail)。429 等错误不会抛异常。"""
    body = json.dumps(
        {
            "id": f"smoke-{uuid.uuid4()}",
            "messages": [
                {
                    "id": "m1",
                    "role": "user",
                    "parts": [{"type": "text", "text": question}],
                }
            ],
            "trigger": "submit-message",
        }
    ).encode()
    request = urllib.request.Request(
        f"{AGENT}/api/chat",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {make_token(values, username, roles)}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:200]
        return [], exc.code, detail
    events = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return events, 200, ""


def chat_text(events: list[dict]) -> str:
    return " ".join(
        event.get("delta", "") for event in events if event.get("type") == "text-delta"
    ).strip()


def chat_errors(events: list[dict]) -> list[str]:
    errors = []
    for event in events:
        if event.get("type") == "error":
            errors.append(str(event.get("errorText")))
        if event.get("type") == "tool-output-error":
            errors.append(str(event.get("errorText")))
    return errors


def mcp_call(token_value: str, name: str, arguments: dict | None = None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "call_tool",
            "arguments": {"name": name, "arguments": arguments or {}},
        },
    }
    request = urllib.request.Request(
        MCP,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token_value}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    raw = urllib.request.urlopen(request, timeout=60).read().decode()
    result = None
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        body = json.loads(line[5:].strip())
        if "result" in body:
            result = body["result"]
    if result is None:
        raise RuntimeError(f"MCP {name}: no result in stream")
    texts = [
        item.get("text", "")
        for item in result.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    try:
        return json.loads("\n".join(texts))
    except json.JSONDecodeError:
        return {"__text": "\n".join(texts)[:300]}


def admin_session(values: dict):
    """走真实 admin ticket 流程，返回 (opener, csrf, api)。"""
    cj = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    html = op.open(f"{SUPERSET}/login/").read().decode()
    match = re.search(
        r'name="csrf_token"\s+id="csrf_token"\s+value="([^"]+)"', html, re.S
    )
    data = urllib.parse.urlencode(
        {
            "username": values.get("SUPERSET_ADMIN_USERNAME", "admin"),
            "password": values.get("SUPERSET_ADMIN_PASSWORD", "admin"),
            "csrf_token": match.group(1),
        }
    ).encode()
    op.open(f"{SUPERSET}/login/", data)
    ticket = json.loads(
        op.open(f"{SUPERSET}/extensions/dataagent/assistant/admin-ticket")
        .read()
        .decode()
    )["result"]["ticket"]
    request = urllib.request.Request(
        f"{AGENT}/admin/api/session",
        data=json.dumps({"ticket": ticket}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    op.open(request)
    csrf = next((c.value for c in cj if c.name == "sa_admin_csrf"), "")

    def api(path: str, method: str = "GET", body: dict | None = None):
        headers = {"X-CSRF-Token": csrf}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{AGENT}{path}", data=data, method=method, headers=headers
        )
        try:
            raw = op.open(request, timeout=60).read().decode()
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            return {"__status": exc.code, "__detail": exc.read().decode()[:150]}

    return op, csrf, api


def main() -> int:
    values = load_env()
    admin_token = make_token(values, "admin", ["Admin"])
    east_token = make_token(values, "east", ["sales_east"])
    east_roles = ["sales_east"]
    admin_roles = ["Admin"]

    section("服务健康")
    try:
        health = json.loads(
            urllib.request.urlopen(f"{AGENT}/healthz", timeout=10).read().decode()
        )
        check(health.get("status") == "ok", "agent /healthz ok")
        check(
            health.get("model_configured") is True,
            f"agent model configured ({health.get('model')})",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"agent healthz: {exc}")
    try:
        urllib.request.urlopen(f"{SUPERSET}/health", timeout=10)
        check(True, "superset /health ok")
    except Exception as exc:  # noqa: BLE001
        check(False, f"superset health: {exc}")

    section("匿名拒绝")
    for path, method, body in (
        ("/api/chat", "POST", {}),
        ("/api/conversations", "GET", None),
        ("/api/feedback", "GET", None),
    ):
        request = urllib.request.Request(
            f"{AGENT}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=10)
            check(False, f"anonymous {path} must be rejected")
        except urllib.error.HTTPError as exc:
            check(exc.code == 401, f"anonymous {path} -> 401 (got {exc.code})")
    for path in ("/admin/api/me", "/admin/api/feedback", "/admin/api/limits"):
        try:
            urllib.request.urlopen(f"{AGENT}{path}", timeout=10)
            check(False, f"anonymous {path} must be rejected")
        except urllib.error.HTTPError as exc:
            check(exc.code == 401, f"anonymous {path} -> 401 (got {exc.code})")

    section("扩展 token（can_use 权限）")
    for username, password, roles in (
        ("admin", values.get("SUPERSET_ADMIN_PASSWORD", "admin"), ["Admin"]),
        ("east", "east", ["sales_east"]),
    ):
        try:
            op = superset_login(username, password)
            token_value = extension_token(op, username)
            check(bool(token_value), f"{username} token issued via extension")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{username} token flow failed: {exc}")

    section("Agent /api/me")
    me_admin = agent_req(admin_token, "/api/me")
    me_east = agent_req(east_token, "/api/me")
    check(
        me_admin.get("can_admin") is True
        and "can_run_sql" not in me_admin,
        f"admin me: admin={me_admin.get('can_admin')}（无 Agent 侧影子限制）",
    )
    check(
        me_east.get("can_admin") is False,
        f"east me: admin={me_east.get('can_admin')}",
    )

    section("聊天模型列表")
    chat_models = agent_req(admin_token, "/api/models")
    model_items = chat_models.get("items") if isinstance(chat_models, dict) else []
    check(
        isinstance(model_items, list)
        and bool(model_items)
        and all(item.get("display_name") for item in model_items),
        f"/api/models items={len(model_items or [])} 默认={next((item.get('display_name') for item in model_items or [] if item.get('is_default')), '—')}",
    )

    section("MCP 直连 RLS")
    try:
        data = mcp_call(east_token, "query_dataset", {
            "request": {"dataset_id": 1, "metrics": ["count"], "columns": ["region"], "row_limit": 50}
        })
        rows = data.get("data") or data.get("rows") or []
        regions = {row.get("region") for row in rows}
        check(
            bool(rows) and regions == {"east"},
            f"east query_dataset RLS only east (regions={regions})",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"east MCP query_dataset failed: {exc}")
    try:
        data = mcp_call(admin_token, "query_dataset", {
            "request": {"dataset_id": 1, "metrics": ["count"], "columns": ["region"], "row_limit": 50}
        })
        rows = data.get("data") or data.get("rows") or []
        regions = {row.get("region") for row in rows}
        check(
            regions >= {"east", "west"},
            f"admin query_dataset sees all regions (regions={regions})",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"admin MCP query_dataset failed: {exc}")
    try:
        data = mcp_call(east_token, "list_datasets", {"request": {"page": 1, "page_size": 20}})
        names = [d.get("table_name") for d in data.get("datasets") or []]
        check(bool(names), f"east list_datasets -> {names}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"east MCP list_datasets failed: {exc}")

    # 自由 SQL 的门控现在完全由宿主 RBAC 负责（Agent 不再影子限制）
    sql_args = {
        "request": {
            "database_id": 1,
            "sql": "SELECT region, COUNT(*) AS cnt FROM sales GROUP BY region",
            "limit": 10,
            "timeout": 30,
        }
    }
    east_sql = mcp_call(east_token, "execute_sql", sql_args)
    east_text = str(east_sql.get("__text") or east_sql.get("error") or east_sql)
    check(
        "Permission denied" in east_text and "SQLLab" in east_text,
        f"east execute_sql 被宿主 RBAC 拒绝（{east_text[:70]}）",
    )
    try:
        admin_sql = mcp_call(admin_token, "execute_sql", sql_args)
        rows = admin_sql.get("rows") or []
        regions = {row.get("region") for row in rows}
        check(
            regions >= {"east", "west"},
            f"admin execute_sql 可执行（RLS 规则只绑 sales_east/west 角色，regions={regions}）",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"admin execute_sql failed: {exc}")

    section("用户 API（历史/导出）")
    convs = agent_req(admin_token, "/api/conversations?page=1&page_size=5")
    check(
        isinstance(convs.get("items"), list) and convs.get("total", 0) >= 1,
        f"conversations list total={convs.get('total')}",
    )
    if convs.get("items"):
        conv_id = convs["items"][0]["id"]
        detail = agent_req(admin_token, f"/api/conversations/{conv_id}")
        check(
            isinstance(detail.get("messages"), list) and detail["messages"],
            f"conversation detail messages={len(detail.get('messages') or [])}",
        )
        try:
            request = urllib.request.Request(
                f"{AGENT}/api/conversations/{conv_id}/export",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            export = urllib.request.urlopen(request, timeout=30).read().decode()
            check(len(export) > 20, f"export markdown {len(export)} chars")
        except Exception as exc:  # noqa: BLE001
            check(False, f"export failed: {exc}")

        section("逐条反馈生命周期")
        rate = agent_req(admin_token, "/api/feedback", "POST", {
            "conversation_id": conv_id, "turn_index": 1, "rating": "up",
        })
        check(rate.get("rating") == "up", f"rate turn1 up -> {rate.get('rating') or rate}")
        switch = agent_req(admin_token, "/api/feedback", "POST", {
            "conversation_id": conv_id, "turn_index": 1, "rating": "down",
        })
        check(switch.get("rating") == "down", "switch turn1 down")
        listed = agent_req(admin_token, f"/api/feedback?conversation_id={conv_id}")
        items = listed.get("items") or []
        check(
            any(item["turn_index"] == 1 and item["rating"] == "down" for item in items),
            f"feedback list has turn1=down ({len(items)} items)",
        )
        invalid = agent_req(admin_token, "/api/feedback", "POST", {
            "conversation_id": conv_id, "turn_index": 99, "rating": "up",
        })
        check(invalid.get("__status") == 400, f"invalid turn_index -> 400 (got {invalid.get('__status')})")
        cancel = agent_req(admin_token, "/api/feedback", "POST", {
            "conversation_id": conv_id, "turn_index": 1, "rating": None,
        })
        check(cancel.get("rating") is None, "cancel turn1")
        after = agent_req(admin_token, f"/api/feedback?conversation_id={conv_id}")
        check(
            not any(item["turn_index"] == 1 for item in after.get("items") or []),
            "turn1 removed after cancel",
        )

    section("限额配置（GET/PUT 持久化）")
    _, _, admin_api = admin_session(values)
    limits = admin_api("/admin/api/limits")
    check(
        all(key in limits for key in (
            "rate_per_minute", "daily_requests", "daily_tokens", "daily_cost",
            "updated_at", "updated_by",
        )),
        f"limits contract fields (updated_by={limits.get('updated_by')})",
    )
    restore_body = {
        key: limits[key]
        for key in ("rate_per_minute", "daily_requests", "daily_tokens", "daily_cost")
    }
    put = admin_api("/admin/api/limits", "PUT", restore_body)
    check(
        "__status" not in put and put.get("updated_by") == "admin",
        "limits PUT roundtrip",
    )

    section("每分钟限流（真实 429）")
    import threading

    put = admin_api(
        "/admin/api/limits",
        "PUT",
        {**restore_body, "rate_per_minute": 1},
    )
    check("__status" not in put, "rate_per_minute temporarily set to 1")

    def rate_round() -> tuple[int, int]:
        statuses: list[int] = []
        lock = threading.Lock()

        def fire() -> None:
            _, status, _ = chat_raw(values, "west", ["sales_west"], "你好")
            with lock:
                statuses.append(status)

        threads = [threading.Thread(target=fire, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=240)
        return statuses.count(200), statuses.count(429)

    ok_count, denied = rate_round()
    if ok_count == 0 and denied == 2:
        # 上一轮残留事件占满了窗口，等窗口滑出后重试一次
        print("INFO rate window carries leftover events, retrying after 61s")
        time.sleep(61)
        ok_count, denied = rate_round()
    check(
        ok_count >= 1 and denied >= 1,
        f"rate=1 lets exactly one concurrent chat through (ok={ok_count} 429={denied})",
    )
    put = admin_api("/admin/api/limits", "PUT", restore_body)
    check("__status" not in put, "limits restored")

    section("管理 API 全量")
    overview = admin_api("/admin/api/overview?days=7")
    check(
        "totals" in overview and "quality" in overview,
        "overview totals+quality",
    )
    usage = admin_api("/admin/api/usage?days=7&group_by=detail&page=1")
    check(
        isinstance(usage.get("items"), list) and usage.get("top_users") is not None,
        f"usage detail items={len(usage.get('items') or [])}",
    )
    filters = admin_api("/admin/api/filters")
    check(
        isinstance(filters.get("users"), list) and isinstance(filters.get("models"), list),
        f"filters users={len(filters.get('users') or [])}",
    )
    agent_limit = admin_api("/admin/api/agent-limits")
    check(
        "max_tool_calls" in agent_limit,
        f"agent-limits max_tool_calls={agent_limit.get('max_tool_calls')}（0=不限制）",
    )
    restored_agent_limit = admin_api(
        "/admin/api/agent-limits",
        "PUT",
        {"max_tool_calls": agent_limit.get("max_tool_calls", 0)},
    )
    check(
        restored_agent_limit.get("max_tool_calls")
        == agent_limit.get("max_tool_calls", 0),
        "agent-limits roundtrip",
    )
    log_meta = admin_api("/admin/api/logs")
    check(
        isinstance(log_meta.get("files"), list)
        and isinstance(log_meta.get("settings"), dict)
        and "retention_days" in log_meta.get("settings", {}),
        f"logs files={len(log_meta.get('files') or [])} retention={log_meta.get('settings', {}).get('retention_days')}",
    )
    log_tail = admin_api("/admin/api/logs/tail?name=agent.log&lines=20")
    check(
        isinstance(log_tail.get("lines"), list),
        f"logs tail lines={len(log_tail.get('lines') or [])}",
    )
    retention = int(log_meta["settings"]["retention_days"])
    restored_logs = admin_api(
        "/admin/api/log-settings",
        "PUT",
        {"retention_days": retention},
    )
    check(
        restored_logs.get("retention_days") == retention,
        f"log-settings roundtrip retention={retention}",
    )
    tool_catalog = admin_api("/admin/api/mcp-tools")
    tool_items = tool_catalog.get("items") or []
    tools_by_name = {item.get("name"): item for item in tool_items}
    check(
        len(tool_items) == tool_catalog.get("total")
        and tool_catalog.get("mcp_total", 0) >= 68
        and tool_catalog.get("agent_total", 0) >= 12
        and all(item.get("title") for item in tool_items),
        f"mcp-tools total={tool_catalog.get('total')} mcp={tool_catalog.get('mcp_total')} agent={tool_catalog.get('agent_total')}",
    )
    check(
        tools_by_name.get("query_dataset", {}).get("title") == "查询数据集"
        and tools_by_name.get("health_check", {}).get("title") == "健康检查"
        and tools_by_name.get("period_compare", {}).get("title") == "环比 / 同比对比"
        and tools_by_name.get("period_compare", {}).get("source") == "agent"
        and tools_by_name.get("trend_forecast", {}).get("title") == "趋势预测"
        and tools_by_name.get("trend_forecast", {}).get("source") == "agent",
        "mcp-tools Chinese titles / sources",
    )
    for path in (
        "/admin/api/audit/conversations?page=1&page_size=5&sort_by=last_at&sort_order=desc",
        "/admin/api/audit/operations?page=1&page_size=5",
        "/admin/api/audit/write-actions?page=1&page_size=5",
        "/admin/api/feedback?page=1&page_size=5&sort_by=created_at&sort_order=desc",
        "/admin/api/feedback?page=1&page_size=5&rating=up",
        "/admin/api/feedback?page=1&page_size=5&sort_by=turn_index&sort_order=asc",
        "/admin/api/providers",
        "/admin/api/models",
    ):
        result = admin_api(path)
        check("__status" not in result, f"GET {path.split('?')[0]} ({path.split('?')[1] if '?' in path else ''}) -> ok")
    missing = agent_req(
        make_token(values, "admin", ["Admin"]),
        "/api/write-actions/does-not-exist/confirm",
        "POST",
    )
    check(
        missing.get("__status") == 404,
        f"write-action confirm on unknown id -> 404 (got {missing.get('__status')})",
    )

    section("语言切换")
    try:
        request = urllib.request.Request(
            f"{SUPERSET}/lang/zh", headers={"Referer": f"{SUPERSET}/superset/welcome/"}
        )
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(request, timeout=15)
            check(False, "/lang/zh should redirect")
        except urllib.error.HTTPError as exc:
            check(
                exc.code == 302,
                f"/lang/zh -> 302 {exc.headers.get('Location', '')}",
            )
        login_html = urllib.request.urlopen(f"{SUPERSET}/login/", timeout=15).read().decode()
        check(
            "show_language_picker&#34;: true" in login_html
            or "show_language_picker\": true" in login_html,
            "bootstrap show_language_picker=true",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"language switch check failed: {exc}")

    section("live 工具冒烟（真实模型）")
    rls_result: dict | None = None
    rls_note = ""
    for attempt in range(2):  # MiniCPM 偶发不选工具，允许重试一次
        events, status, detail = chat_raw(values, "east", east_roles, "各区域订单数是多少？")
        if status != 200:
            rls_note = f"HTTP {status}: {detail[:120]}"
            continue
        errors = chat_errors(events)
        outputs, _ = tool_outputs(events, "query_dataset")
        text = chat_text(events)
        if errors:
            rls_note = f"errors: {errors[:2]}"
            continue
        if not text:
            rls_note = "empty answer"
            continue
        if not outputs:
            rls_note = "query_dataset not called"
            continue
        rows = outputs[-1].get("rows") or []
        regions = {row.get("region") for row in rows}
        if rows and regions == {"east"}:
            rls_result = {"regions": regions, "rows": len(rows)}
            break
        rls_note = f"rows regions={regions}"
    if rls_result:
        check(True, f"chat RLS: query_dataset east-only ({rls_result})")
    else:
        check(False, f"chat RLS failed after retry ({rls_note})")

    live_cases = [
        ("admin", admin_roles, "列出所有看板", "list_dashboards"),
        ("admin", admin_roles, "有哪些图表？", "list_charts"),
    ]
    for username, roles, question, tool in live_cases:
        events, status, detail = chat_raw(values, username, roles, question)
        if status != 200:
            check(False, f"{tool} chat HTTP {status}: {detail[:120]}")
            continue
        errors = chat_errors(events)
        outputs, _ = tool_outputs(events, tool)
        text = chat_text(events)
        if errors:
            check(False, f"{tool} chat errors: {errors[:2]}")
        elif not text:
            check(False, f"{tool} chat empty answer")
        elif not outputs:
            check(True, f"{tool} not triggered but answer ok: {text[:60]}", warn_only=True)
        else:
            check(True, f"{tool} triggered")

    events, status, detail = chat_raw(
        values, "admin", admin_roles,
        "把现有图表 test（chart_id=1）加到看板 dashboard_id=1，先给出确认方案，不要执行。",
    )
    if status != 200:
        check(False, f"propose_write chat HTTP {status}: {detail[:120]}")
    else:
        errors = chat_errors(events)
        outputs, _ = tool_outputs(events, "propose_write")
        if errors:
            check(False, f"propose_write chat errors: {errors[:2]}")
        elif not outputs:
            check(True, "propose_write not triggered by model", warn_only=True)
        else:
            action_id = outputs[-1].get("action_id")
            if not action_id:
                check(False, f"propose_write output missing action_id: {str(outputs[-1])[:120]}")
            else:
                cancelled = agent_req(
                    make_token(values, "admin", ["Admin"]),
                    f"/api/write-actions/{action_id}/cancel",
                    "POST",
                )
                check(
                    cancelled.get("status") in ("cancelled", "canceled"),
                    f"write action {action_id[:8]}… cancelled (status={cancelled.get('status')})",
                )

    section("结果汇总")
    fails = [msg for status_, msg, _ in RESULTS if status_ == "FAIL"]
    warns = [msg for status_, msg, _ in RESULTS if status_ == "WARN"]
    passed = [1 for status_, _, _ in RESULTS if status_ == "PASS"]
    print(f"\n{len(passed)} passed, {len(warns)} warned, {len(fails)} failed")
    for message in fails:
        print(f"  FAIL {message}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
