from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

from assistant_agent.admin.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AdminIdentity,
    create_session_cookie,
    read_session,
    verify_admin_ticket,
)
from assistant_agent.admin.crypto import SecretBox, key_hint
from assistant_agent.admin.db import (
    AdminDB,
    Conversation,
    RetentionArchive,
    utcnow,
)
from assistant_agent.admin.store import AdminStore
from assistant_agent.audit import AuditLogger
from assistant_agent.config import Settings
from assistant_agent.limits import UserRateLimiter, daily_quota_error
from assistant_agent.write_actions import build_plan, risk_level


class SeedSettings:
    llm_model = "test-model"
    llm_base_url = "https://example/v1"
    llm_api_key = "sk-test-1234"
    llm_disable_thinking = True


def make_store(tmp_path) -> AdminStore:
    db = AdminDB(f"sqlite:///{tmp_path}/admin.db")
    db.create_all()
    return AdminStore(db, SecretBox("0123456789abcdef0123456789abcdef"))


def make_settings() -> Settings:
    return Settings(
        mcp_url="http://mcp/mcp",
        mcp_jwt_secret="chat-secret",
        mcp_jwt_issuer="assistant",
        mcp_jwt_audience="superset-mcp",
        admin_db_url="sqlite://",
        admin_secret_key="0123456789abcdef0123456789abcdef",
        admin_ticket_secret="abcdef0123456789abcdef0123456789",
        admin_ticket_audience="assistant-admin",
        admin_ticket_issuer="assistant",
        admin_session_secret="9876543210abcdef9876543210abcdef",
        admin_session_ttl=1800,
        llm_model="test-model",
        llm_base_url="https://example.invalid/v1",
        llm_api_key="sk-test-1234",
    )


def ticket(roles: list[str], jti: str | None = None) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "admin",
            "roles": roles,
            "scope": "admin",
            "iss": "assistant",
            "aud": "assistant-admin",
            "iat": now,
            "exp": now + 60,
            "jti": jti or str(uuid.uuid4()),
        },
        "abcdef0123456789abcdef0123456789",
        algorithm="HS256",
    )


def test_crypto_roundtrip():
    box = SecretBox("0123456789abcdef0123456789abcdef")
    encrypted = box.encrypt("sk-secret-1234")
    assert encrypted != "sk-secret-1234"
    assert box.decrypt(encrypted) == "sk-secret-1234"
    assert key_hint("sk-secret-1234") == "sk-s...1234"


def test_seed_and_runtime_model(tmp_path):
    store = make_store(tmp_path)
    store.seed_default_provider(SeedSettings())
    providers = store.list_providers()
    models = store.list_models()
    assert providers[0]["name"] == "default"
    assert "api_key_encrypted" not in providers[0]
    assert providers[0]["has_api_key"] is True
    assert models[0]["is_default"] is True
    runtime = store.get_runtime_model()
    assert runtime is not None
    assert runtime.model_name == "test-model"
    assert runtime.api_key == "sk-test-1234"
    assert runtime.disable_thinking is True


def test_seed_skills(tmp_path):
    store = make_store(tmp_path)
    assert store.list_skills() == []
    store.seed_skills()
    skills = store.list_skills()
    assert len(skills) == 4
    assert {item["name"] for item in skills} == {
        "data_discovery",
        "analysis_and_chart_creation",
        "insight_generation",
        "sql_generation_and_execution",
    }
    assert all(item["enabled"] for item in skills)
    assert all("\n" in item["instruction"] for item in skills)
    # 已有数据时重复调用不重复写入
    store.seed_skills()
    assert len(store.list_skills()) == 4


def test_admin_ticket_one_time_and_role_check(tmp_path):
    store = make_store(tmp_path)
    settings = make_settings()
    identity = verify_admin_ticket(ticket(["Admin"], "fixed-jti"), settings, store)
    assert identity.username == "admin"
    with pytest.raises(HTTPException) as replay:
        verify_admin_ticket(ticket(["Admin"], "fixed-jti"), settings, store)
    assert replay.value.status_code == 401
    with pytest.raises(HTTPException) as denied:
        verify_admin_ticket(ticket(["Alpha"]), settings, store)
    assert denied.value.status_code == 403


def test_admin_session_cookie(tmp_path):
    settings = make_settings()
    response = Response()
    create_session_cookie(
        response, AdminIdentity("admin", ("Admin",)), settings
    )
    cookies = [
        value for name, value in response.headers.raw if name.lower() == b"set-cookie"
    ]
    assert any(value.startswith(SESSION_COOKIE.encode()) for value in cookies)
    assert any(value.startswith(CSRF_COOKIE.encode()) for value in cookies)
    session_cookie = next(
        value for value in cookies if value.startswith(SESSION_COOKIE.encode())
    )
    session = session_cookie.split(b";", 1)[0].split(b"=", 1)[1].decode()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "headers": [(b"cookie", f"{SESSION_COOKIE}={session}".encode())],
        }
    )
    identity = read_session(request, settings)
    assert identity is not None
    assert identity.username == "admin"


def test_full_audit_and_usage(tmp_path):
    store = make_store(tmp_path)
    provider = store.create_provider(
        {"name": "test-provider", "base_url": "https://example.invalid/v1"},
        "admin",
    )
    store.create_model(
        {
            "provider_id": provider["id"],
            "model_name": "m",
            "display_name": "模型 M",
            "enabled": True,
        },
        "admin",
    )
    store.ensure_conversation("conv-12345678", "admin", "question", "m")
    store.log_tool(
        conversation_id="conv-12345678",
        run_id="run-1",
        username="admin",
        model_name="m",
        sequence=1,
        tool_name="query_dataset",
        args={"request": {"dataset_id": 1}},
        result={"row_count": 2, "rows": [{"region": "east"}, {"region": "west"}]},
        duration_ms=25,
        status="ok",
    )
    store.log_turn(
        conversation_id="conv-12345678",
        run_id="run-1",
        username="admin",
        question="full question",
        answer="full answer",
        model_name="m",
        input_tokens=10,
        output_tokens=20,
        latency_ms=123,
        tool_calls=1,
        cost=0.01,
    )
    detail = store.get_conversation("conv-12345678")
    assert detail is not None
    assert detail["messages"][0]["content"] == "full question"
    assert detail["messages"][1]["content"] == "full answer"
    assert detail["tool_calls"][0]["result_json"]["rows"][1]["region"] == "west"
    overview = store.overview(7)
    assert overview["totals"]["requests"] == 1
    assert overview["totals"]["tokens"] == 30
    today = date.today()
    ranged = store.overview(7, start=today, end=today)
    assert ranged["totals"]["requests"] == 1
    future = store.overview(7, start=today + timedelta(days=1))
    assert future["totals"]["requests"] == 0
    usage = store.usage(7, "user")
    assert usage["items"][0]["key"] == "admin"
    assert usage["top_users"][0]["username"] == "admin"
    assert usage["top_models"][0]["model_name"] == "m"
    assert usage["top_models"][0]["provider_name"] == "test-provider"
    filtered = store.usage(7, "user", username="admin", model_name="m")
    assert filtered["items"][0]["tokens"] == 30
    assert store.usage(7, "user", username="nobody")["items"] == []
    detail = store.usage(7, "detail")
    assert detail["items"][0]["username"] == "admin"
    assert detail["items"][0]["model_name"] == "m"
    assert detail["items"][0]["provider_name"] == "test-provider"
    assert detail["items"][0]["day"]
    grouped = store.usage(7, "user_model")
    assert grouped["items"][0]["username"] == "admin"
    assert grouped["items"][0]["model_name"] == "m"
    assert grouped["items"][0]["provider_name"] == "test-provider"
    filters = store.filter_options()
    assert filters["users"] == ["admin"]
    assert filters["models"] == ["m"]
    assert filters["model_providers"]["m"] == "test-provider"
    assert store.list_conversations(model_name="m")["total"] == 1
    assert store.list_conversations(model_name="other")["total"] == 0


def test_conversation_sorting(tmp_path):
    store = make_store(tmp_path)
    for conversation_id, tokens in (("conv-low", 10), ("conv-high", 40)):
        store.ensure_conversation(conversation_id, "admin", conversation_id, "m")
        store.log_turn(
            conversation_id=conversation_id,
            run_id=f"run-{conversation_id}",
            username="admin",
            question=conversation_id,
            answer="answer",
            model_name="m",
            input_tokens=tokens,
            output_tokens=0,
            latency_ms=1,
            tool_calls=0,
            cost=0,
        )
    asc = store.list_conversations(
        sort_by="tokens", sort_order="asc", page_size=10
    )["items"]
    assert [row["input_tokens"] for row in asc] == [10, 40]
    desc = store.list_conversations(
        sort_by="tokens", sort_order="desc", page_size=10
    )["items"]
    assert [row["input_tokens"] for row in desc] == [40, 10]


def test_purge_old_conversations(tmp_path):
    store = make_store(tmp_path)
    store.log_tool(
        conversation_id="conv-old-1234",
        run_id="run-old",
        username="admin",
        model_name="m",
        sequence=1,
        tool_name="query_dataset",
        args={"request": {"dataset_id": 1}},
        result={"rows": [{"region": "east"}]},
        duration_ms=3,
        status="ok",
    )
    store.log_turn(
        conversation_id="conv-old-1234",
        run_id="run-old",
        username="admin",
        question="old",
        answer="old",
        model_name="m",
        input_tokens=1,
        output_tokens=2,
        latency_ms=3,
        tool_calls=0,
        cost=0,
    )
    with store.db.session() as session:
        conversation = session.get(Conversation, "conv-old-1234")
        conversation.last_at = utcnow() - timedelta(days=100)
    purged = store.purge_old(90)
    assert purged["conversations"] == 1
    assert purged["archived_conversations"] == 1
    assert store.get_conversation("conv-old-1234") is None
    with store.db.session() as session:
        archive = session.scalars(select(RetentionArchive)).one()
    assert archive.kind == "conversation"
    assert archive.payload_json["messages"][0]["content"] == "old"
    assert archive.payload_json["tool_calls"][0]["tool_name"] == "query_dataset"


def test_audit_jsonl_retention(tmp_path):
    path = tmp_path / "audit.jsonl"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    path.write_text(
        "\n".join(
            [
                json.dumps({"ts": old_ts, "event": "old"}),
                json.dumps({"ts": new_ts, "event": "new"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    archived: list[dict] = []
    result = AuditLogger(path).purge_old(90, archived.extend)
    assert result == {"removed": 1, "kept": 1}
    assert archived[0]["event"] == "old"
    remaining = path.read_text(encoding="utf-8")
    assert "old" not in remaining
    assert "new" in remaining


def test_user_quota_and_rate_limit(tmp_path):
    store = make_store(tmp_path)
    store.log_turn(
        conversation_id="conv-quota-1234",
        run_id="run-quota",
        username="admin",
        question="q",
        answer="a",
        model_name="m",
        input_tokens=1,
        output_tokens=2,
        latency_ms=3,
        tool_calls=0,
        cost=0.5,
    )
    usage = store.user_usage_for_day("admin")
    assert usage["requests"] == 1
    assert usage["tokens"] == 3
    assert daily_quota_error(
        usage, request_limit=1, token_limit=0, cost_limit=0
    )
    assert daily_quota_error(
        usage, request_limit=0, token_limit=3, cost_limit=0
    )
    assert daily_quota_error(
        usage, request_limit=0, token_limit=0, cost_limit=0.5
    )
    assert daily_quota_error(
        usage, request_limit=10, token_limit=10, cost_limit=10
    ) is None

    async def check_limiter() -> bool:
        limiter = UserRateLimiter()
        assert await limiter.allow("admin", 2)
        assert await limiter.allow("admin", 2)
        return await limiter.allow("admin", 2)

    assert asyncio.run(check_limiter()) is False


def test_soft_delete_and_export(tmp_path):
    store = make_store(tmp_path)
    store.log_tool(
        conversation_id="conv-user-1234",
        run_id="run-user",
        username="admin",
        model_name="m",
        sequence=1,
        tool_name="query_dataset",
        args={"request": {"dataset_id": 1}},
        result={"row_count": 1, "rows": [{"region": "east"}]},
        duration_ms=12,
        status="ok",
    )
    store.log_turn(
        conversation_id="conv-user-1234",
        run_id="run-user",
        username="admin",
        question="full question",
        answer="<think>hidden reasoning</think>full answer",
        model_name="m",
        input_tokens=1,
        output_tokens=2,
        latency_ms=3,
        tool_calls=1,
        cost=0,
        selection=[
            {"kind": "chart", "chart_id": "5", "title": "各区域销售额"}
        ],
    )
    visible = store.list_conversations(
        username="admin", include_deleted=False
    )
    assert visible["total"] == 1
    exported = store.export_markdown("admin", "conv-user-1234")
    assert exported is not None
    markdown, filename = exported
    assert "full question" in markdown
    assert "full answer" in markdown
    assert "hidden reasoning" not in markdown
    assert "query_dataset" not in markdown
    assert "选中：图表 · 各区域销售额" in markdown
    assert filename.startswith("full question-")
    assert filename.endswith(".md")
    assert store.soft_delete_conversation("admin", "conv-user-1234") is True
    assert (
        store.get_conversation("conv-user-1234", include_deleted=False)
        is None
    )
    assert store.export_markdown("admin", "conv-user-1234") is None
    hidden = store.get_conversation("conv-user-1234", include_deleted=True)
    assert hidden is not None and hidden["deleted"] is True
    assert (
        store.list_conversations(username="admin", include_deleted=False)[
            "total"
        ]
        == 0
    )


def test_feedback_quality_and_write_actions(tmp_path):
    store = make_store(tmp_path)
    store.log_turn(
        conversation_id="conv-feedback-1",
        run_id="run-feedback",
        username="admin",
        question="q",
        answer="a",
        model_name="m",
        input_tokens=1,
        output_tokens=2,
        latency_ms=3,
        tool_calls=0,
        cost=0,
    )
    feedback = store.upsert_feedback("admin", "conv-feedback-1", 1, "up")
    assert feedback["rating"] == "up"
    items = store.get_feedback("admin", "conv-feedback-1")
    assert len(items) == 1 and items[0]["rating"] == "up"
    quality = store.overview(7)["quality"]
    assert quality["feedback_up"] == 1
    assert quality["feedback_adoption_rate"] == 1.0
    with pytest.raises(LookupError):
        store.upsert_feedback("east", "conv-feedback-1", 1, "up")
    with pytest.raises(ValueError):
        store.upsert_feedback("admin", "conv-feedback-1", 5, "up")
    cancelled = store.upsert_feedback("admin", "conv-feedback-1", 1, None)
    assert cancelled["rating"] is None
    assert store.get_feedback("admin", "conv-feedback-1") == []
    assert store.overview(7)["quality"]["feedback_total"] == 0
    store.upsert_feedback("admin", "conv-feedback-1", 1, "down", "不满足需求")
    assert store.list_feedback(rating="down")["total"] == 1
    detail = store.list_feedback(rating="down")["items"][0]
    assert detail["answer"] == "a"
    assert detail["conversation_title"] == "q"

    action = store.create_write_action(
        username="admin",
        conversation_id="conv-feedback-1",
        run_id="run-feedback",
        action_type="create_chart",
        risk_level=risk_level("create_chart"),
        summary="test plan",
        plan={"tool": "generate_chart", "arguments": {"request": {}}},
        snapshot={"dataset_name": "sales"},
        expires_at=utcnow() + timedelta(minutes=5),
    )
    assert store.get_write_action(action["id"], username="admin")["plan"]
    assert store.list_write_actions()["total"] == 1

    found = store.find_pending_write_action(
        username="admin",
        conversation_id="conv-feedback-1",
        action_type="create_chart",
        plan={"arguments": {"request": {}}, "tool": "generate_chart"},
    )
    assert found is not None and found["id"] == action["id"]
    assert (
        store.find_pending_write_action(
            username="admin",
            conversation_id="conv-feedback-1",
            action_type="create_chart",
            plan={"tool": "generate_chart", "arguments": {"request": {"config": {}}}},
        )
        is None
    )


def test_log_settings(tmp_path):
    store = make_store(tmp_path)
    assert store.get_log_settings(14)["retention_days"] == 14
    saved = store.save_log_settings({"retention_days": 7}, actor="admin")
    assert saved["retention_days"] == 7
    assert store.get_log_settings(14)["retention_days"] == 7
    saved = store.save_log_settings({"retention_days": 999}, actor="admin")
    assert saved["retention_days"] == 365


def test_list_enabled_chat_models(tmp_path):
    store = make_store(tmp_path)
    provider = store.create_provider(
        {
            "name": "test-provider",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-test",
            "enabled": True,
        },
        "admin",
    )
    store.create_model(
        {
            "provider_id": provider["id"],
            "model_name": "model-a",
            "display_name": "模型 A",
            "is_default": True,
            "enabled": True,
        },
        "admin",
    )
    store.create_model(
        {
            "provider_id": provider["id"],
            "model_name": "model-b",
            "display_name": "模型 B",
            "enabled": False,
        },
        "admin",
    )
    items = store.list_enabled_models()
    assert [item["display_name"] for item in items] == ["模型 A"]
    assert items[0]["is_default"] is True
    assert "api_key" not in items[0]
    assert "base_url" not in items[0]


def test_write_plan_validation():
    plan = build_plan(
        "create_chart",
        {
            "dataset_id": 1,
            "metric": "total_amount",
            "chart_type": "bar",
            "dimension": "region",
            "chart_name": "区域销售额",
        },
    )
    assert plan["tool"] == "generate_chart"
    assert plan["arguments"]["request"]["save_chart"] is True
    assert plan["arguments"]["request"]["config"]["chart_type"] == "xy"
    assert risk_level("update_dataset_metric") == "high"
    assert risk_level("update_chart") == "medium"
    with pytest.raises(ValueError):
        build_plan("create_chart", {"dataset_id": 1})
    with pytest.raises(ValueError):
        build_plan(
            "update_dataset_metric",
            {"dataset_id": 1, "metric": "total_amount", "updates": {}},
        )

    update_plan = build_plan(
        "update_chart",
        {
            "chart_id": 5,
            "metric": "total_amount",
            "chart_type": "pie",
            "dimension": "region",
        },
    )
    assert update_plan["tool"] == "update_chart"
    request = update_plan["arguments"]["request"]
    assert request["identifier"] == 5
    assert request["generate_preview"] is False
    assert request["config"]["chart_type"] == "pie"
    assert request["config"]["dimension"]["name"] == "region"
    with pytest.raises(ValueError):
        build_plan(
            "update_chart",
            {"chart_id": 5, "metric": "total_amount", "chart_type": "pie"},
        )
    with pytest.raises(ValueError):
        build_plan(
            "update_chart",
            {"metric": "total_amount", "chart_type": "pie", "dimension": "region"},
        )

    # 仅改名：不带 config，仍直接落库
    rename_plan = build_plan(
        "update_chart", {"chart_id": 5, "chart_name": "区域销售额总览"}
    )
    assert rename_plan["arguments"]["request"] == {
        "identifier": 5,
        "chart_name": "区域销售额总览",
        "generate_preview": False,
    }
    with pytest.raises(ValueError):
        build_plan("update_chart", {"chart_id": 5})


def test_update_chart_rollback_from_form_data():
    from assistant_agent.write_actions import (
        _rollback_config_from_form_data,
        _update_chart_rollback,
    )

    bar = _rollback_config_from_form_data(
        {
            "viz_type": "echarts_timeseries_bar",
            "metrics": ["total_amount"],
            "x_axis": "region",
        }
    )
    assert bar == {
        "chart_type": "xy",
        "kind": "bar",
        "x": {"name": "region"},
        "y": [{"name": "total_amount", "saved_metric": True}],
    }
    pie = _rollback_config_from_form_data(
        {"viz_type": "pie", "metrics": ["total_amount"], "groupby": ["region"]}
    )
    assert pie["chart_type"] == "pie"
    assert pie["dimension"]["name"] == "region"
    assert pie["metric"]["saved_metric"] is True
    table = _rollback_config_from_form_data(
        {
            "viz_type": "table",
            "metrics": ["count"],
            "groupby": ["region"],
        }
    )
    assert table == {
        "chart_type": "table",
        "columns": [
            {"name": "region"},
            {"name": "count", "saved_metric": True},
        ],
    }
    # 未知 viz_type / adhoc 表达式指标 / 无维度饼图：不可回滚
    assert _rollback_config_from_form_data({"viz_type": "word_cloud"}) is None
    assert _rollback_config_from_form_data(
        {
            "viz_type": "echarts_timeseries_bar",
            "metrics": [{"expression": "SUM(x)"}],
            "x_axis": "region",
        }
    ) is None
    assert (
        _rollback_config_from_form_data(
            {"viz_type": "pie", "metrics": ["total_amount"]}
        )
        is None
    )
    rollback = _update_chart_rollback(
        {
            "chart_id": 5,
            "chart_name": "各区域销售额",
            "viz_type": "echarts_timeseries_bar",
            "form_data": {
                "viz_type": "echarts_timeseries_bar",
                "metrics": ["total_amount"],
                "x_axis": "region",
            },
        }
    )
    assert rollback["tool"] == "update_chart"
    assert rollback["arguments"]["request"]["chart_name"] == "各区域销售额"
    assert (
        _update_chart_rollback({"chart_id": 5, "form_data": {}}) is None
    )
    # 仅改名场景：form_data 不可解析时仍可回滚名称
    rename_only = _update_chart_rollback(
        {"chart_id": 5, "chart_name": "旧名字", "form_data": {"viz_type": "word_cloud"}}
    )
    assert rename_only["arguments"]["request"]["chart_name"] == "旧名字"
    assert "config" not in rename_only["arguments"]["request"]


def test_skill_crud_and_agent_registration(tmp_path):
    from assistant_agent.agent import build_agent
    from assistant_agent.mock_model import mock_model

    store = make_store(tmp_path)
    created = store.create_skill(
        actor="admin",
        name="region_report",
        title="区域报告",
        description="生成区域销售周报",
        instruction="按周汇总各区域 total_amount，输出环比与 Top 区域。",
    )
    assert created["name"] == "region_report"
    assert created["enabled"] is True

    # 重名拒绝 / 非法 name 拒绝
    with pytest.raises(LookupError):
        store.create_skill(
            actor="admin",
            name="region_report",
            title="重复",
            description="",
            instruction="x",
        )
    with pytest.raises(ValueError):
        store.create_skill(
            actor="admin", name="Bad-Name", title="t", description="", instruction="i"
        )

    items = store.list_skills()
    assert [item["name"] for item in items] == ["region_report"]
    assert store.list_skills(enabled_only=True)
    updated = store.update_skill(
        created["id"], actor="admin", enabled=False, title="区域报告（停用）"
    )
    assert updated["enabled"] is False
    assert store.list_skills(enabled_only=True) == []

    # agent 注册：启用时工具存在，停用/无技能时不存在
    skills = store.list_skills(enabled_only=True)
    agent = build_agent(
        make_settings(),
        None,
        skills=skills,
    )
    tool_names = set(agent._function_toolset.tools.keys())  # noqa: SLF001
    assert "run_skill_region_report" not in tool_names

    store.update_skill(created["id"], actor="admin", enabled=True)
    skills = store.list_skills(enabled_only=True)
    agent2 = build_agent(
        make_settings(),
        None,
        skills=skills,
    )
    tool_names2 = set(agent2._function_toolset.tools.keys())  # noqa: SLF001
    assert "run_skill_region_report" in tool_names2

    store.delete_skill(created["id"], actor="admin")
    assert store.list_skills() == []
    with pytest.raises(LookupError):
        store.delete_skill(created["id"], actor="admin")


def test_knowledge_store_isolation_and_search(tmp_path):
    store = make_store(tmp_path)
    item = store.upsert_knowledge(
        "east",
        "GMV 口径",
        "GMV = total_amount 含退款前口径，团队 A 规则。",
    )
    assert item["title"] == "GMV 口径"
    assert item["source"] == "auto"

    # 同标题覆盖
    updated = store.upsert_knowledge(
        "east", "GMV 口径", "GMV = total_amount（修正：不含退款）。"
    )
    assert updated["id"] == item["id"]
    assert "修正" in updated["content"]

    # 空值拒绝
    with pytest.raises(ValueError):
        store.upsert_knowledge("east", "", "content")
    with pytest.raises(ValueError):
        store.upsert_knowledge("east", "title", "  ")

    # 用户隔离：west 看不到 east 的条目
    assert store.list_knowledge("west") == []
    found = store.search_knowledge("east", "GMV 口径")
    assert found["items"] and "GMV" in found["items"][0]["title"]
    assert found["total_matched"] == 1
    assert store.search_knowledge("west", "GMV") == {"items": [], "total_matched": 0}
    # 关键词太短不触发检索
    assert store.search_knowledge("east", "口") == {"items": [], "total_matched": 0}
    # 命中即计入使用度（返回值已是本次命中后的状态）
    assert found["items"][0]["hits"] == 1
    assert found["items"][0]["last_used_at"]
    after = store.search_knowledge("east", "GMV 口径")
    assert after["items"][0]["hits"] == 2

    # 目录只给标题，不给正文
    directory = store.knowledge_directory("east")
    assert directory[0]["content"] == ""
    assert directory[0]["content_chars"] > 0

    # 越权删除拒绝；软删后生效列表为空
    with pytest.raises(LookupError):
        store.delete_knowledge("west", item["id"])
    store.delete_knowledge("east", item["id"])
    assert store.list_knowledge("east") == []


def test_knowledge_quota_and_trash(tmp_path):
    from assistant_agent.admin.store import KnowledgeQuotaError

    store = make_store(tmp_path)
    store.save_knowledge_settings(
        {
            "user_max_entries": 2,
            "auto_max_entries": 3,
            "auto_ttl_days": 0,
            "trash_retention_days": 0,
            "auto_merge_enabled": False,
        },
        actor="admin",
    )
    settings = store.get_knowledge_settings()
    assert settings["user_max_entries"] == 2
    assert settings["auto_max_entries"] == 3

    store.upsert_knowledge("east", "口径A", "内容A", source="manual")
    store.upsert_knowledge("east", "口径B", "内容B", source="manual")
    with pytest.raises(KnowledgeQuotaError):
        store.upsert_knowledge("east", "口径C", "内容C", source="manual")
    # 自动侧不受手动配额影响
    store.upsert_knowledge("east", "结论1", "内容1", source="auto")

    usage = store.knowledge_usage("east")
    assert usage["manual_used"] == 2 and usage["auto_used"] == 1

    # 自动沉淀不得改写用户手填的同名条目
    store.upsert_knowledge("east", "口径A", "模型想覆盖的内容", source="auto")
    assert store.search_knowledge("east", "内容A")["items"][0]["content"].startswith("内容A")

    # 软删除：用户端与检索都不可见，回收站可见，可恢复
    item = store.list_knowledge("east")[0]
    store.delete_knowledge("east", item["id"])
    assert item["title"] not in {row["title"] for row in store.list_knowledge("east")}
    assert store.search_knowledge("east", "内容A")["items"] == []
    trash = store.list_knowledge("east", include_deleted=True)
    assert [row["id"] for row in trash] == [item["id"]]
    # 同名可以重建（deleted_key 让回收站不占唯一键）
    store.upsert_knowledge("east", item["title"], "重建内容", source="manual")
    with pytest.raises(ValueError):
        store.restore_knowledge("east", item["id"])  # 同名冲突
    # 彻底删除回收站条目后可以恢复成功
    clash = store.list_knowledge("east")[0]
    store.delete_knowledge("east", clash["id"])
    store.purge_knowledge("east", clash["id"])
    restored = store.restore_knowledge("east", item["id"])
    assert restored["id"] == item["id"]
    with pytest.raises(LookupError):
        store.purge_knowledge("east", item["id"])  # 生效中的条目不允许彻底删除


def test_knowledge_auto_lru_and_retention(tmp_path):
    store = make_store(tmp_path)
    store.save_knowledge_settings(
        {
            "auto_max_entries": 3,
            "auto_merge_enabled": False,
            "auto_ttl_days": 0,
            "trash_retention_days": 0,
        },
        actor="admin",
    )
    for index in range(3):
        store.upsert_knowledge("east", f"结论{index}", f"正文{index}", source="auto")
    # 命中过第 0 条，写入第 4 条时应淘汰最久未命中的第 1 条
    store.search_knowledge("east", "正文0")
    store.upsert_knowledge("east", "结论3", "正文3", source="auto")
    alive = {row["title"] for row in store.list_knowledge("east")}
    assert alive == {"结论0", "结论2", "结论3"}
    trash = {row["title"] for row in store.list_knowledge("east", include_deleted=True)}
    assert trash == {"结论1"}

    # TTL：零命中且过期的自动条目进回收站
    store.save_knowledge_settings({"auto_ttl_days": 1}, actor="admin")
    with store.db.session() as session:
        from assistant_agent.admin.db import Knowledge

        row = session.scalar(
            select(Knowledge).where(
                Knowledge.username == "east", Knowledge.title == "结论2"
            )
        )
        row.updated_at = datetime(2020, 1, 1)
    result = store.prune_knowledge_retention()
    assert result["trashed"] == 1
    assert "结论2" not in {row["title"] for row in store.list_knowledge("east")}

    # 删除 + 越权删除拒绝（TTL 后仍生效的是结论0/结论3）
    alive_rows = store.list_knowledge("east")
    assert {row["title"] for row in alive_rows} == {"结论0", "结论3"}
    with pytest.raises(LookupError):
        store.delete_knowledge("west", alive_rows[0]["id"])
    for row in alive_rows:
        store.delete_knowledge("east", row["id"])
    assert store.list_knowledge("east") == []


def test_admin_knowledge_overview(tmp_path):
    store = make_store(tmp_path)
    a = store.upsert_knowledge("east", "GMV 口径", "GMV 含退款前金额。")
    b = store.upsert_knowledge("west", "大客户定义", "单笔订单 > 50000。")
    store.upsert_knowledge("admin", "财年口径", "财年起于 4 月。")

    result = store.admin_list_knowledge()
    assert result["total"] == 3
    assert {item["username"] for item in result["items"]} == {
        "east",
        "west",
        "admin",
    }

    # 用户筛选 + 搜索
    assert [i["username"] for i in store.admin_list_knowledge(username="east")["items"]] == [
        "east"
    ]
    hits = store.admin_list_knowledge(search="50000")
    assert hits["total"] == 1 and hits["items"][0]["id"] == b["id"]

    # 分页 + 排序
    page1 = store.admin_list_knowledge(sort_by="username", sort_order="asc", page=1, page_size=2)
    assert [i["username"] for i in page1["items"]] == ["admin", "east"]
    page2 = store.admin_list_knowledge(sort_by="username", sort_order="asc", page=2, page_size=2)
    assert [i["username"] for i in page2["items"]] == ["west"]

    # 代删 + 管理审计
    deleted = store.admin_delete_knowledge(a["id"], actor="admin")
    assert deleted["username"] == "east"
    assert store.list_knowledge("east") == []
    audit = store.list_admin_audit(action="knowledge.delete")
    assert audit["total"] == 1
    assert audit["items"][0]["before_json"]["title"] == "GMV 口径"
    with pytest.raises(LookupError):
        store.admin_delete_knowledge(a["id"], actor="admin")


def test_delete_write_plans_and_rollback_shapes():
    from assistant_agent.write_actions import _delete_chart_rollback, build_plan, risk_level

    plan = build_plan("delete_chart", {"chart_id": 5})
    assert plan == {"tool": "delete_chart", "arguments": {"request": {"identifier": 5}}}
    assert risk_level("delete_chart") == "high"
    assert risk_level("delete_dashboard") == "high"

    assert build_plan("delete_dashboard", {"dashboard_id": 3})["arguments"] == {
        "request": {"identifier": 3}
    }
    remove = build_plan(
        "remove_chart_from_dashboard", {"dashboard_id": 3, "chart_id": 5}
    )
    assert remove["tool"] == "remove_chart_from_dashboard"
    assert remove["arguments"]["request"] == {"dashboard_id": 3, "chart_id": 5}
    with pytest.raises(ValueError):
        build_plan("delete_chart", {})
    with pytest.raises(ValueError):
        build_plan("remove_chart_from_dashboard", {"chart_id": 5})

    # 软删除：restore_chart 一步即可（看板关联实测在恢复后仍保留）
    steps = _delete_chart_rollback({"soft_deleted": True}, {"identifier": 5})
    assert steps == [
        {"tool": "restore_chart", "arguments": {"request": {"identifier": 5}}}
    ]
    # 永久删除：没有回滚
    assert _delete_chart_rollback({"soft_deleted": False}, {"identifier": 5}) == []


def test_dashboard_write_plans_and_rejections():
    from assistant_agent.write_actions import build_plan, risk_level

    plan = build_plan(
        "update_dashboard",
        {"dashboard_id": 1, "updates": {"dashboard_title": "销售总览", "published": True}},
    )
    assert plan["tool"] == "update_dashboard"
    assert plan["arguments"]["request"] == {
        "identifier": 1,
        "dashboard_title": "销售总览",
        "published": True,
    }
    # css/布局/元数据读不到原值 → 拒绝
    with pytest.raises(ValueError):
        build_plan("update_dashboard", {"dashboard_id": 1, "updates": {"css": ".a{}"}})
    with pytest.raises(ValueError):
        build_plan("update_dashboard", {"dashboard_id": 1, "updates": {}})

    dup = build_plan("duplicate_dashboard", {"dashboard_id": 2, "dashboard_title": "副本"})
    assert dup["arguments"]["request"] == {
        "dashboard_id": 2,
        "dashboard_title": "副本",
    }
    with pytest.raises(ValueError):
        build_plan(
            "duplicate_dashboard", {"dashboard_id": 2, "duplicate_slices": True}
        )

    cert = build_plan("set_dashboard_certification", {"dashboard_id": 3})
    assert cert["tool"] == "manage_dashboard_certification"
    assert cert["arguments"]["request"] == {
        "identifier": 3,
        "certified_by": "",
        "certification_details": "",
    }
    assert build_plan("restore_chart", {"chart_id": 9})["tool"] == "restore_chart"
    assert build_plan("restore_dashboard", {"dashboard_id": 4})["tool"] == "restore_dashboard"
    with pytest.raises(ValueError):
        build_plan("restore_dashboard", {})
    assert risk_level("update_dashboard") == "medium"


def test_dashboard_rollback_uses_snapshot():
    from assistant_agent.write_actions import execute_plan  # noqa: F401  (回滚在 execute 内构造)
    from assistant_agent.write_actions import DASHBOARD_UPDATE_FIELDS

    # 回滚只回填快照里出现过的字段
    snapshot = {"dashboard_id": 1, "dashboard_title": "旧标题", "published": False}
    restore = {"identifier": 1}
    for field in DASHBOARD_UPDATE_FIELDS:
        if field in snapshot:
            restore[field] = snapshot.get(field)
    assert restore == {
        "identifier": 1,
        "dashboard_title": "旧标题",
        "published": False,
    }


def test_native_filter_write_plan():
    plan = build_plan(
        "add_native_filter",
        {
            "dashboard_id": 6,
            "filter_type": "filter_time",
            "name": "订单时间",
            "default_time_range": "Last year",
        },
    )
    assert plan["tool"] == "manage_native_filters"
    assert plan["arguments"]["request"] == {
        "dashboard_id": 6,
        "add": [
            {
                "filter_type": "filter_time",
                "name": "订单时间",
                "default_time_range": "Last year",
            }
        ],
    }
    assert risk_level("add_native_filter") == "medium"

    select = build_plan(
        "add_native_filter",
        {
            "dashboard_id": 6,
            "filter_type": "filter_select",
            "name": "区域",
            "dataset_id": 1,
            "column": "region",
            "multi_select": False,
            "scope_chart_ids": [5],
            # 不适用字段按类型白名单丢弃，不会混进 time/select spec
            "default_time_range": "Last week",
        },
    )
    spec = select["arguments"]["request"]["add"][0]
    assert spec == {
        "filter_type": "filter_select",
        "name": "区域",
        "dataset_id": 1,
        "column": "region",
        "multi_select": False,
        "scope_chart_ids": [5],
    }

    with pytest.raises(ValueError):
        build_plan(
            "add_native_filter",
            {"dashboard_id": 6, "filter_type": "filter_range", "name": "x"},
        )
    with pytest.raises(ValueError):
        build_plan(
            "add_native_filter",
            {"dashboard_id": 6, "filter_type": "filter_select", "name": "x"},
        )
    with pytest.raises(ValueError):
        build_plan(
            "add_native_filter", {"filter_type": "filter_time", "name": "x"}
        )


def test_native_filter_snapshot_and_rollback():
    from assistant_agent.write_actions import collect_snapshot, execute_plan

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def call_tool(self, tool, arguments):
            self.calls.append((tool, arguments))
            if tool == "get_dashboard_info":
                return {"dashboard_title": "销售看板", "error": None}
            assert tool == "manage_native_filters"
            return {
                "dashboard_id": 6,
                "added_filter_ids": ["NATIVE_FILTER-abc"],
                "filters": [],
                "error": None,
            }

    plan = build_plan(
        "add_native_filter",
        {"dashboard_id": 6, "filter_type": "filter_time", "name": "订单时间"},
    )
    client = FakeClient()
    snapshot = asyncio.run(collect_snapshot(client, "add_native_filter", plan))
    assert snapshot == {
        "dashboard_id": 6,
        "dashboard_title": "销售看板",
        "new_filters": [{"name": "订单时间", "filter_type": "filter_time"}],
    }

    result, rollback = asyncio.run(
        execute_plan(client, "add_native_filter", plan, snapshot)
    )
    assert result["added_filter_ids"] == ["NATIVE_FILTER-abc"]
    # 回滚＝对服务端返回的新筛选器 id 执行 remove，不触碰既有筛选器
    assert rollback == {
        "tool": "manage_native_filters",
        "arguments": {
            "request": {"dashboard_id": 6, "remove": ["NATIVE_FILTER-abc"]}
        },
    }


def test_clean_title_and_run_count(tmp_path):
    from assistant_agent.titles import build_title_prompt, clean_title

    assert clean_title('"各区域销售额对比"') == "各区域销售额对比"
    assert clean_title("标题：区域销售分析。") == "区域销售分析"
    assert clean_title("  会话标题: 大客户统计\n多余解释") == "大客户统计"
    assert clean_title("x" * 50) == "x" * 24
    assert clean_title("   ") == ""
    prompt = build_title_prompt("各区域销售额是多少？", "东区 2.7M，西区 2.6M")
    assert "各区域销售额是多少？" in prompt and "东区" in prompt

    store = make_store(tmp_path)
    for index in (1, 2):
        count = store.log_turn(
            conversation_id="conv-title",
            run_id=f"run-{index}",
            username="east",
            question=f"q{index}",
            answer=f"a{index}",
            model_name="m",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            tool_calls=0,
            cost=0,
        )
        assert count == index
    store.update_conversation_title("conv-title", "区域销售分析")
    assert store.get_conversation("conv-title")["title"] == "区域销售分析"
    # 空标题不覆盖
    store.update_conversation_title("conv-title", "  ")
    assert store.get_conversation("conv-title")["title"] == "区域销售分析"


def test_title_rejects_instruction_echo():
    from assistant_agent.titles import clean_title, is_usable_title

    echo = clean_title("用户要求生成一个不超过16个字的中文会话标题")
    assert not is_usable_title(echo)
    assert not is_usable_title(clean_title("只输出这个短语"))
    assert is_usable_title(clean_title("区域销售对比"))
    assert is_usable_title(clean_title("「大客户口径确认」"))


def test_fallback_title_from_question():
    from assistant_agent.titles import clean_title, fallback_title, is_usable_title

    assert fallback_title("帮我看看各区域销售额，按季度") == "各区域销售额"
    assert fallback_title("请分析一下大客户占比。谢谢") == "分析一下大客户占比"
    assert fallback_title("") == ""
    # markdown 残渣会被清洗，清洗后仍像句子则判废
    cleaned = clean_title("1.  **分析请求")
    assert cleaned == "分析请求"
    assert is_usable_title(clean_title("1. **区域销售分析**"))


def test_generic_title_rejected():
    from assistant_agent.titles import is_usable_title

    for generic in ("分析请求", "数据查询", "会话"):
        assert not is_usable_title(generic)
    assert is_usable_title("区域销售额对比")


def test_feedback_time_filter_and_conversation_times(tmp_path):
    from datetime import date, timedelta

    store = make_store(tmp_path)
    store.log_turn(
        conversation_id="conv-fb-range",
        run_id="run-1",
        username="east",
        question="q",
        answer="a",
        model_name="m",
        input_tokens=1,
        output_tokens=2,
        latency_ms=3,
        tool_calls=0,
        cost=0,
    )
    store.upsert_feedback("east", "conv-fb-range", 1, "up")
    item = store.list_feedback()["items"][0]
    assert item["conversation_started_at"]
    assert item["conversation_last_at"]
    today = date.today()
    assert store.list_feedback(start=today, end=today)["total"] == 1
    assert (
        store.list_feedback(start=today + timedelta(days=1))["total"] == 0
    )
    assert (
        store.list_feedback(end=today - timedelta(days=1))["total"] == 0
    )


def test_employee_crud_and_tool_gate(tmp_path):
    from assistant_agent.auth import UserContext
    from assistant_agent.auth import UserContext
    from assistant_agent.deps import AgentDeps

    store = make_store(tmp_path)
    emp = store.create_employee(
        actor="admin",
        values={
            "username": "dex2",
            "nickname": "Dex2",
            "tools": ["list_datasets", "query_dataset"],
            "skill_ids": [3],
        },
    )
    assert emp["tools"] == ["list_datasets", "query_dataset"]
    assert emp["skill_ids"] == [3]
    with pytest.raises(LookupError):
        store.create_employee(actor="admin", values={"username": "dex2", "nickname": "x"})
    with pytest.raises(ValueError):
        store.create_employee(actor="admin", values={"username": "Bad-Name", "nickname": "x"})
    with pytest.raises(ValueError):
        store.create_employee(actor="admin", values={"username": "ok_name", "nickname": ""})

    updated = store.update_employee(
        emp["id"], actor="admin", updates={"tools": None, "enabled": False}
    )
    assert updated["tools"] is None and updated["enabled"] is False

    knowledge = store.upsert_employee_knowledge(emp["id"], "口径A", "内容说明")
    assert store.search_employee_knowledge(emp["id"], "口径A")[0]["id"] == knowledge["id"]
    store.delete_employee_knowledge(emp["id"], knowledge["id"])
    assert store.list_employee_knowledge(emp["id"]) == []

    store.delete_employee(emp["id"], actor="admin")
    assert store.get_employee(emp["id"]) is None

    class _Audit:
        def log(self, *args, **kwargs):
            pass

    deps = AgentDeps(
        user=UserContext("u", ("r",), "t", {}),
        settings=make_settings(),
        audit=_Audit(),
    )
    assert deps.employee_tool_allowed("execute_sql") is True
    deps.employee = {"tools": ["query_dataset"]}
    assert deps.employee_tool_allowed("query_dataset") is True
    assert deps.employee_tool_allowed("execute_sql") is False
    assert deps.employee_tool_allowed("period_compare", "query_dataset") is True
    assert deps.employee_tool_allowed("run_sql", "execute_sql") is False
    deps.employee = {"tools": None}
    assert deps.employee_tool_allowed("execute_sql") is True


def test_employee_tool_catalog_migration(tmp_path):
    from assistant_agent.tool_catalog import LEGACY_UNRESTRICTED_AGENT_TOOLS

    store = make_store(tmp_path)
    legacy = store.create_employee(
        actor="admin",
        values={"username": "legacy", "nickname": "Legacy", "tools": ["query_dataset"]},
    )
    empty = store.create_employee(
        actor="admin",
        values={"username": "empty", "nickname": "Empty", "tools": []},
    )
    unlimited = store.create_employee(
        actor="admin",
        values={"username": "unlimited", "nickname": "Unlimited", "tools": None},
    )

    assert store.migrate_employee_tool_catalog(LEGACY_UNRESTRICTED_AGENT_TOOLS) == 1
    migrated = store.get_employee(legacy["id"])
    assert set(LEGACY_UNRESTRICTED_AGENT_TOOLS) <= set(migrated["tools"])
    assert "query_dataset" in migrated["tools"]
    assert store.get_employee(empty["id"])["tools"] == []
    assert store.get_employee(unlimited["id"])["tools"] is None
    # 标记写入后不重复迁移，避免管理员取消勾选后又被加回来
    assert store.migrate_employee_tool_catalog(LEGACY_UNRESTRICTED_AGENT_TOOLS) == 0


def test_agent_limits_and_runtime_tool_cap(tmp_path):
    from assistant_agent.auth import UserContext
    from assistant_agent.auth import UserContext
    from assistant_agent.deps import AgentDeps

    store = make_store(tmp_path)
    initial = store.get_agent_limits({"max_tool_calls": 16})
    assert initial["max_tool_calls"] == 16
    saved = store.save_agent_limits({"max_tool_calls": 24}, actor="admin")
    assert saved["max_tool_calls"] == 24
    assert saved["updated_by"] == "admin"
    reloaded = store.get_agent_limits({"max_tool_calls": 16})
    assert reloaded["max_tool_calls"] == 24
    assert store.save_agent_limits({"max_tool_calls": 0}, actor="admin")[
        "max_tool_calls"
    ] == 0
    assert store.get_agent_limits({"max_tool_calls": 16})["max_tool_calls"] == 0

    class _Audit:
        def log(self, *args, **kwargs):
            pass

    deps = AgentDeps(
        user=UserContext("u", ("r",), "t", {}),
        settings=make_settings(),
        audit=_Audit(),
        max_tool_calls=2,
    )
    deps.begin_tool("list_datasets")
    deps.begin_tool("get_dataset_info")
    with pytest.raises(RuntimeError, match="2"):
        deps.begin_tool("query_dataset")

    unlimited = AgentDeps(
        user=UserContext("u", ("r",), "t", {}),
        settings=make_settings(),
        audit=_Audit(),
        max_tool_calls=0,
    )
    for _ in range(100):
        unlimited.begin_tool("query_dataset")


def test_employee_user_acl(tmp_path):
    from assistant_agent.admin.store import employee_allows

    store = make_store(tmp_path)
    emp = store.create_employee(
        actor="admin", values={"username": "viz2", "nickname": "Viz2"}
    )
    assert emp["users"] is None
    assert employee_allows(emp, "east", ["Gamma"]) is True

    only_admin = store.update_employee(
        emp["id"], actor="admin", updates={"users": []}
    )
    assert only_admin["users"] == []
    assert employee_allows(only_admin, "east", ["Gamma"]) is False
    assert employee_allows(only_admin, "admin", ["Admin"]) is True

    whitelist = store.update_employee(
        emp["id"], actor="admin", updates={"users": [" East ", "east", "WEST"]}
    )
    assert whitelist["users"] == ["east", "west"]
    assert employee_allows(whitelist, "east", ["sales_east"]) is True
    assert employee_allows(whitelist, "nobody", ["Gamma"]) is False

    store.create_employee(
        actor="admin", values={"username": "open2", "nickname": "Open2"}
    )
    assert {item["username"] for item in store.list_employees_for_user("east", ["Gamma"])} == {
        "viz2",
        "open2",
    }
    assert {
        item["username"] for item in store.list_employees_for_user("nobody", ["Gamma"])
    } == {"open2"}
    assert {item["username"] for item in store.list_employees_for_user("admin", ["Admin"])} == {
        "viz2",
        "open2",
    }

    back = store.update_employee(emp["id"], actor="admin", updates={"users": None})
    assert back["users"] is None
    assert "viz2" in {item["username"] for item in store.list_employees_for_user("east", ["Gamma"])}


def test_update_knowledge_by_id(tmp_path):
    store = make_store(tmp_path)
    item = store.upsert_knowledge("east", "口径A", "内容A")
    updated = store.update_knowledge("east", item["id"], "口径B", "内容B")
    assert updated["title"] == "口径B" and updated["content"] == "内容B"
    with pytest.raises(LookupError):
        store.update_knowledge("west", item["id"], "X", "Y")
    with pytest.raises(ValueError):
        store.update_knowledge("east", item["id"], "", "Y")


def test_usage_employee_dimension(tmp_path):
    store = make_store(tmp_path)
    store.log_turn(
        conversation_id="conv-emp-1",
        run_id="run-emp-1",
        username="east",
        question="q",
        answer="a",
        model_name="m",
        input_tokens=10,
        output_tokens=20,
        latency_ms=5,
        tool_calls=1,
        cost=0.01,
        employee_id=7,
    )
    detail = store.usage(7, "detail")
    assert detail["items"][0]["employee_id"] == 7
    grouped = store.usage(7, "employee")
    assert grouped["items"][0]["employee_id"] == 7
    assert grouped["top_employees"][0]["employee_id"] == 7
    filtered = store.usage(7, "day", employee_id=7)
    assert filtered["items"][0]["tokens"] == 30
    assert store.usage(7, "day", employee_id=7)["employee_id"] == 7
    convs = store.list_conversations(employee_id=7)
    assert convs["total"] == 1
    assert convs["items"][0]["employee_name"] == "AI 员工"


def test_continuation_turn_has_no_user_message(tmp_path):
    store = make_store(tmp_path)
    store.log_turn(
        conversation_id="conv-cont-1",
        run_id="run-cont-0",
        username="east",
        question="原问题",
        answer="第一阶段",
        model_name="m",
        input_tokens=5,
        output_tokens=6,
        latency_ms=5,
        tool_calls=0,
        cost=0.0,
    )
    store.log_turn(
        conversation_id="conv-cont-1",
        run_id="run-cont-1",
        username="east",
        question="",
        answer="已继续完成",
        model_name="m",
        input_tokens=5,
        output_tokens=6,
        latency_ms=5,
        tool_calls=0,
        cost=0.0,
        include_question=False,
        count_run=False,
    )
    detail = store.get_conversation("conv-cont-1")
    assert detail is not None
    assert [item["role"] for item in detail["messages"]] == [
        "user",
        "assistant",
        "assistant",
    ]
    assert detail["run_count"] == 1
    md, _ = store.export_markdown("east", "conv-cont-1")
    assert md.count("## 用户") == 1
    assert md.count("## 助手") == 2
    assert "已继续完成" in md


def test_user_ai_access_default_and_toggle(tmp_path):
    store = make_store(tmp_path)
    assert store.user_ai_enabled("east") is True
    assert store.user_ai_access_map() == {}
    closed = store.set_user_ai_access("east", False, actor="admin")
    assert closed["ai_enabled"] is False
    assert store.user_ai_enabled("east") is False
    assert store.user_ai_access_map()["east"] is False
    opened = store.set_user_ai_access("east", True, actor="admin")
    assert opened["ai_enabled"] is True
    assert store.user_ai_enabled("east") is True


def test_list_pending_write_actions(tmp_path):
    store = make_store(tmp_path)
    now = utcnow()
    first = store.create_write_action(
        username="east",
        conversation_id="conv-batch-1",
        run_id="run-batch-1",
        action_type="create_chart",
        risk_level="medium",
        summary="第一张",
        plan={},
        snapshot={},
        expires_at=now + timedelta(minutes=10),
    )
    second = store.create_write_action(
        username="east",
        conversation_id="conv-batch-1",
        run_id="run-batch-2",
        action_type="update_chart",
        risk_level="medium",
        summary="第二张",
        plan={},
        snapshot={},
        expires_at=now + timedelta(minutes=10),
    )
    store.create_write_action(
        username="east",
        conversation_id="conv-batch-1",
        run_id="run-batch-3",
        action_type="create_chart",
        risk_level="medium",
        summary="已过期",
        plan={},
        snapshot={},
        expires_at=now - timedelta(minutes=1),
    )
    store.create_write_action(
        username="west",
        conversation_id="conv-batch-1",
        run_id="run-batch-4",
        action_type="create_chart",
        risk_level="medium",
        summary="别人的",
        plan={},
        snapshot={},
        expires_at=now + timedelta(minutes=10),
    )
    items = store.list_pending_write_actions(
        username="east",
        conversation_id="conv-batch-1",
    )
    assert [item["id"] for item in items] == [first["id"], second["id"]]
    store.update_write_action(first["id"], status="executed")
    assert [
        item["id"]
        for item in store.list_pending_write_actions(
            username="east",
            conversation_id="conv-batch-1",
        )
    ] == [second["id"]]


def test_employee_model_whitelist_and_default(tmp_path):
    store = make_store(tmp_path)
    emp = store.create_employee(
        actor="admin",
        values={
            "username": "model_emp",
            "nickname": "模型员工",
            "model_id": 2,
            "model_ids": [1, 2],
        },
    )
    assert emp["model_id"] == 2
    assert emp["model_ids"] == [1, 2]
    with pytest.raises(ValueError):
        store.create_employee(
            actor="admin",
            values={
                "username": "bad_model_emp",
                "nickname": "错误模型",
                "model_id": 3,
                "model_ids": [1, 2],
            },
        )
    with pytest.raises(ValueError):
        store.update_employee(
            emp["id"], actor="admin", updates={"model_ids": [1, 3]}
        )
    updated = store.update_employee(
        emp["id"], actor="admin", updates={"model_ids": [1, 3], "model_id": 3}
    )
    assert updated["model_ids"] == [1, 3]
    assert updated["model_id"] == 3
    cleared = store.update_employee(
        emp["id"], actor="admin", updates={"model_ids": None, "model_id": None}
    )
    assert cleared["model_ids"] is None
    assert cleared["model_id"] is None


def test_employee_delegate_config_and_tool(tmp_path):
    store = make_store(tmp_path)
    leader = store.create_employee(
        actor="admin",
        values={
            "username": "leader1",
            "nickname": "领导",
            "can_delegate": True,
            "delegate_employee_ids": [2, 3],
        },
    )
    assert leader["can_delegate"] is True
    assert leader["delegate_employee_ids"] == [2, 3]
    updated = store.update_employee(
        leader["id"], actor="admin", updates={"can_delegate": False}
    )
    assert updated["can_delegate"] is False

    from assistant_agent.agent import build_agent

    sub = {"id": 2, "username": "dex", "nickname": "Dex"}
    with_delegate = build_agent(
        make_settings(),
        None,
        employee={**leader, "can_delegate": True},
        delegates=[sub],
    )
    assert "delegate_to_employee" in with_delegate._function_toolset.tools
    without = build_agent(
        make_settings(),
        None,
        employee={**leader, "can_delegate": True},
        delegates=[],
    )
    assert "delegate_to_employee" not in without._function_toolset.tools


def test_employee_role_acl(tmp_path):
    from assistant_agent.admin.store import employee_allows

    store = make_store(tmp_path)
    emp = store.create_employee(
        actor="admin", values={"username": "role1", "nickname": "Role1"}
    )
    assert employee_allows(emp, "east", ["sales_east"]) is True

    only_admin = store.update_employee(
        emp["id"], actor="admin", updates={"roles": []}
    )
    assert employee_allows(only_admin, "east", ["sales_east"]) is False
    assert employee_allows(only_admin, "admin", ["Admin"]) is True

    by_role = store.update_employee(
        emp["id"], actor="admin", updates={"roles": ["sales_east"]}
    )
    assert employee_allows(by_role, "east", ["sales_east"]) is True
    assert employee_allows(by_role, "west", ["sales_west"]) is False

    union = store.update_employee(
        emp["id"], actor="admin", updates={"users": ["west"]}
    )
    assert employee_allows(union, "west", ["sales_west"]) is True
    assert employee_allows(union, "east", ["sales_east"]) is True
    assert employee_allows(union, "nobody", ["Gamma"]) is False

    rows = store.list_employees_for_role("sales_east")
    assert rows[0]["available"] is True
    store.set_role_employees(
        "sales_east",
        [],
        actor="admin",
        all_roles=["sales_east", "sales_west", "Gamma"],
    )
    assert store.list_employees_for_role("sales_east")[0]["available"] is False
    assert store.get_employee(emp["id"])["roles"] == []
    store.set_role_employees(
        "sales_east",
        [emp["id"]],
        actor="admin",
        all_roles=["sales_east", "sales_west", "Gamma"],
    )
    assert store.get_employee(emp["id"])["roles"] == ["sales_east"]

    # 全员（users/roles 均 None）首次取消某角色 -> 物化为“其余角色”
    open_emp = store.create_employee(
        actor="admin", values={"username": "role_open", "nickname": "Open"}
    )
    store.set_role_employees(
        "sales_east", [], actor="admin", all_roles=["sales_east", "sales_west"]
    )
    narrowed = store.get_employee(open_emp["id"])
    assert narrowed["roles"] == ["sales_west"]
    assert employee_allows(narrowed, "east", ["sales_east"]) is False
    assert employee_allows(narrowed, "west", ["sales_west"]) is True


def test_model_reasoning_effort(tmp_path):
    store = make_store(tmp_path)
    provider = store.create_provider(
        {"name": "p1", "base_url": "http://example/v1"}, "admin"
    )
    model = store.create_model(
        {
            "provider_id": provider["id"],
            "model_name": "m1",
            "reasoning_effort": "high",
        },
        "admin",
    )
    assert model["reasoning_effort"] == "high"
    updated = store.update_model(
        model["id"], {"reasoning_effort": "low"}, "admin"
    )
    assert updated["reasoning_effort"] == "low"
    fallback = store.update_model(
        model["id"], {"reasoning_effort": "bogus"}, "admin"
    )
    assert fallback["reasoning_effort"] == "default"


def test_chat_reasoning_effort_overrides_model_setting():
    from assistant_agent.admin.store import RuntimeModel
    from assistant_agent.agent import _model_settings

    runtime = RuntimeModel(
        id=1,
        provider_name="p",
        model_name="m",
        base_url="http://example/v1",
        api_key="sk",
        disable_thinking=False,
        reasoning_effort="high",
        input_price_per_m=0.0,
        output_price_per_m=0.0,
    )
    # 后台模型里的 reasoning_effort 不再生效
    assert _model_settings(make_settings(), runtime) is None
    low = _model_settings(make_settings(), runtime, reasoning_effort="low")
    assert low is not None
    assert low["extra_body"] == {"reasoning_effort": "low"}
    fallback = _model_settings(
        make_settings(), runtime, reasoning_effort="bogus"
    )
    assert fallback is None


def test_reasoning_effort_header():
    from assistant_agent.api_shared import _reasoning_effort

    def request(value: str = ""):
        headers = (
            [(b"x-reasoning-effort", value.encode())] if value else []
        )
        return Request({"type": "http", "headers": headers})

    assert _reasoning_effort(request("HIGH")) == "high"
    assert _reasoning_effort(request(" medium ")) == "medium"
    assert _reasoning_effort(request("low")) == "low"
    assert _reasoning_effort(request("bogus")) == "default"
    assert _reasoning_effort(request()) == "default"


def test_ensure_pending_handles_z_suffix_expiry():
    """expires_at 经 _iso 序列化后带 Z（aware）；与 naive utcnow() 直接比较曾抛
    TypeError → HTTP 500，导致写操作确认/取消全部失败。修复后应正确归一化。"""
    from assistant_agent.api_shared import _ensure_pending

    def z_suffix(dt: datetime) -> str:
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    future_z = z_suffix(utcnow() + timedelta(minutes=5))
    past_z = z_suffix(utcnow() - timedelta(minutes=1))

    # 未过期的 pending（Z 后缀）放行，不再因 aware/naive 比较报错
    _ensure_pending({"status": "pending", "expires_at": future_z})

    # 过期的 pending → 410
    with pytest.raises(HTTPException) as expired:
        _ensure_pending({"status": "pending", "expires_at": past_z})
    assert expired.value.status_code == 410

    # 非 pending → 409
    with pytest.raises(HTTPException) as wrong_state:
        _ensure_pending({"status": "executed", "expires_at": future_z})
    assert wrong_state.value.status_code == 409

    # naive（无 Z）也仍然工作
    _ensure_pending(
        {
            "status": "pending",
            "expires_at": (utcnow() + timedelta(minutes=5)).isoformat(),
        }
    )


def test_turn_selection_persisted(tmp_path):
    store = make_store(tmp_path)
    store.log_turn(
        conversation_id="conv-sel",
        run_id="run-sel",
        username="east",
        question="这个图表怎么样",
        answer="看起来不错",
        model_name="m",
        input_tokens=1,
        output_tokens=1,
        latency_ms=5,
        tool_calls=0,
        cost=0.0,
        selection=[{"kind": "chart", "chart_id": "5", "title": "各区域销售额"}],
    )
    detail = store.get_conversation("conv-sel")
    messages = {item["role"]: item for item in detail["messages"]}
    assert messages["user"]["selection"][0]["chart_id"] == "5"
    assert messages["assistant"]["selection"] is None


def test_effective_max_rows_capped_by_superset_limit():
    from dataclasses import replace

    from assistant_agent.auth import UserContext
    from assistant_agent.deps import AgentDeps

    class _Audit:
        def log(self, *args, **kwargs):
            pass

    base = make_settings()
    deps = AgentDeps(
        user=UserContext("u", ("r",), "t", {}),
        settings=replace(base, max_rows=500, superset_sql_max_row=2000),
        audit=_Audit(),
    )
    assert deps.effective_max_rows() == 500
    deps.max_rows = 900
    assert deps.effective_max_rows() == 900
    deps.max_rows = 99999
    assert deps.effective_max_rows() == 2000


def test_conversation_owner(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("c-owner", "alice", "t", "m")
    assert store.conversation_owner("c-owner") == "alice"
    assert store.conversation_owner("missing") is None


def test_agent_limits_include_max_rows(tmp_path):
    store = make_store(tmp_path)
    limits = store.get_agent_limits({"max_tool_calls": 16, "max_rows": 500})
    assert limits["max_rows"] == 500
    saved = store.save_agent_limits({"max_rows": 800}, "admin")
    assert saved["max_rows"] == 800
    # 只改工具次数时行数上限保持不变
    store.save_agent_limits({"max_tool_calls": 30}, "admin")
    assert store.get_agent_limits({"max_tool_calls": 16, "max_rows": 500})["max_rows"] == 800
