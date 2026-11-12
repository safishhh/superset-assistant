from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

from starlette.requests import Request

from assistant_agent.admin.crypto import SecretBox
from assistant_agent.admin.db import AdminDB, utcnow
from assistant_agent.admin.store import AdminStore
from assistant_agent.auth import UserContext
from assistant_agent.api_shared import (
    CONTINUATION_MARKER,
    _mark_continuation,
)
import assistant_agent.routes.writes as writes_routes
from assistant_agent.routes.writes import (
    ConfirmAllWriteActionsRequest,
    confirm_all_write_actions,
)


def make_request(payload: dict) -> Request:
    body = json.dumps(payload, ensure_ascii=False).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/api/chat", "headers": []},
        receive,
    )


def user(text: str, *, continuation: bool = False) -> dict:
    message = {
        "id": "u1",
        "role": "user",
        "parts": [{"type": "text", "text": text}],
    }
    if continuation:
        message["metadata"] = {"custom": {"continuation": True}}
    return message


def test_mark_continuation_strips_marker_and_flags() -> None:
    request = make_request(
        {
            "messages": [
                user("原问题"),
                {"id": "a1", "role": "assistant", "parts": [{"type": "text", "text": "答"}]},
                user(f"{CONTINUATION_MARKER}继续执行下一步", continuation=True),
            ]
        }
    )
    assert asyncio.run(_mark_continuation(request)) is True
    body = json.loads(request._body)
    assert body["messages"][-1]["parts"][0]["text"] == "继续执行下一步"


def test_mark_continuation_plain_turn_untouched() -> None:
    request = make_request({"messages": [user("普通问题")]})
    assert asyncio.run(_mark_continuation(request)) is False
    body = json.loads(request._body)
    assert body["messages"][0]["parts"][0]["text"] == "普通问题"


def test_mark_continuation_strips_stale_marker_in_history() -> None:
    request = make_request(
        {
            "messages": [
                user(f"{CONTINUATION_MARKER}继续执行"),
                {"id": "a1", "role": "assistant", "parts": [{"type": "text", "text": "答"}]},
                user("新的问题"),
            ]
        }
    )
    assert asyncio.run(_mark_continuation(request)) is False
    body = json.loads(request._body)
    assert body["messages"][0]["parts"][0]["text"] == "继续执行"
    assert body["messages"][-1]["parts"][0]["text"] == "新的问题"


def test_confirm_all_stops_at_failure_and_keeps_remaining(tmp_path, monkeypatch) -> None:
    db = AdminDB(f"sqlite:///{tmp_path}/admin.db")
    db.create_all()
    store = AdminStore(db, SecretBox("0123456789abcdef0123456789abcdef"))
    now = utcnow()

    def create(action_type: str, summary: str) -> dict:
        return store.create_write_action(
            username="east",
            conversation_id="conv-batch-1",
            run_id=f"run-{summary}",
            action_type=action_type,
            risk_level="medium",
            summary=summary,
            plan={},
            snapshot={},
            expires_at=now + timedelta(minutes=10),
        )

    first = create("create_chart", "第一张")
    second = create("fail", "第二张")
    third = create("create_chart", "第三张")

    async def fake_execute(client, action_type, plan, snapshot):
        if action_type == "fail":
            raise RuntimeError("boom")
        return {"chart_id": 1}, {"tool": "delete_chart", "arguments": {"chart_id": 1}}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

    class DummyAudit:
        def log(self, *args, **kwargs):
            pass

    monkeypatch.setattr(writes_routes, "execute_plan", fake_execute)
    monkeypatch.setattr(
        writes_routes, "_write_client", lambda settings, user: DummyClient()
    )
    app = SimpleNamespace(
        state=SimpleNamespace(admin_store=store, audit=DummyAudit())
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/write-actions/confirm-all",
            "headers": [],
            "app": app,
        }
    )
    user = UserContext("east", (), "token", {})
    payload = ConfirmAllWriteActionsRequest(
        conversation_id="conv-batch-1",
        action_ids=[first["id"], second["id"], third["id"]],
    )
    result = asyncio.run(confirm_all_write_actions(payload, request, user))
    assert [item["status"] for item in result["results"]] == ["executed", "failed"]
    assert result["executed"] == 1
    assert result["failed"] == 1
    assert result["remaining"] == 1
    assert store.get_write_action(first["id"])["status"] == "executed"
    assert store.get_write_action(second["id"])["status"] == "failed"
    assert store.get_write_action(third["id"])["status"] == "pending"
