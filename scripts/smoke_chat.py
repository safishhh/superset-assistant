#!/usr/bin/env python3
"""Smoke test the agent with the deterministic mock model.

Requires the new stack to be running and AGENT_MOCK_LLM=true.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "infra" / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


AGENT_URL = (
    f"http://localhost:{env().get('AGENT_HTTP_PORT') or '28088'}/api/chat"
)


def b64(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def token(values: dict[str, str], username: str, roles: list[str]) -> str:
    now = int(time.time())
    header = b64(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = b64(
        json.dumps(
            {
                "sub": username,
                "roles": roles,
                "iss": values.get("MCP_JWT_ISSUER", "assistant"),
                "aud": values.get("MCP_JWT_AUDIENCE", "superset-mcp"),
                "iat": now,
                "exp": now + 300,
                "jti": str(uuid.uuid4()),
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = b64(
        hmac.new(
            values["MCP_JWT_SECRET"].encode(),
            header + b"." + payload,
            hashlib.sha256,
        ).digest()
    )
    return b".".join([header, payload, signature]).decode()


def chat(values: dict[str, str], username: str, roles: list[str], question: str):
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
        AGENT_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token(values, username, roles)}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode()[:300]}") from exc

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
    return events


def tool_outputs(events, tool_name: str):
    call_ids = set()
    for event in events:
        if event.get("type") not in ("tool-input-start", "tool-input-available"):
            continue
        if event.get("toolName") == tool_name:
            call_ids.add(event.get("toolCallId"))
        elif event.get("toolName") == "mcp_call":
            # 没有专用包装的工具经 mcp_call 直调，按内层 MCP 工具名匹配
            args = event.get("input")
            if isinstance(args, dict) and args.get("tool_name") == tool_name:
                call_ids.add(event.get("toolCallId"))
    outputs = []
    errors = []
    for event in events:
        if (
            event.get("type") == "tool-output-available"
            and event.get("toolCallId") in call_ids
        ):
            outputs.append(event.get("output"))
        if (
            event.get("type") == "tool-output-error"
            and event.get("toolCallId") in call_ids
        ):
            errors.append(event.get("errorText"))
        if event.get("type") == "error":
            errors.append(event.get("errorText"))
    return outputs, errors


def check(condition: bool, message: str) -> None:
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        raise SystemExit(1)


def main() -> int:
    values = env()
    print("== east: dataset query must be RLS-filtered")
    events = chat(values, "east", ["sales_east"], "各区域订单数是多少？")
    outputs, errors = tool_outputs(events, "query_dataset")
    check(bool(outputs), f"query_dataset returned output (errors={errors})")
    rows = outputs[-1].get("rows", [])
    check(bool(rows), "rows are not empty")
    check(all(row.get("region") == "east" for row in rows), f"east only: {rows}")

    print("== west: dataset query must be RLS-filtered")
    events = chat(values, "west", ["sales_west"], "各区域订单数是多少？")
    outputs, errors = tool_outputs(events, "query_dataset")
    check(bool(outputs), f"query_dataset returned output (errors={errors})")
    rows = outputs[-1].get("rows", [])
    check(all(row.get("region") == "west" for row in rows), f"west only: {rows}")

    print("== admin: raw SQL must run")
    events = chat(values, "admin", ["Admin"], "用 SQL 查各区域销售额")
    outputs, errors = tool_outputs(events, "run_sql")
    check(bool(outputs), f"run_sql returned output (errors={errors})")
    rows = outputs[-1].get("rows", [])
    check(len({row.get("region") for row in rows}) >= 2, f"admin sees all regions: {rows}")

    print("== east: raw SQL must be denied")
    events = chat(values, "east", ["sales_east"], "用 SQL 查各区域销售额")
    outputs, errors = tool_outputs(events, "run_sql")
    check(not outputs, f"run_sql must not succeed for east (outputs={outputs})")
    text = " ".join(
        event.get("delta", "")
        for event in events
        if event.get("type") == "text-delta"
    )
    check("Admin" in text or "仅" in text or bool(errors), f"denial is visible: {text or errors}")

    print("== east: period comparison stays inside RLS")
    events = chat(values, "east", ["sales_east"], "各区域环比怎么样？")
    outputs, errors = tool_outputs(events, "period_compare")
    check(bool(outputs), f"period_compare returned output (errors={errors})")
    rows = outputs[-1].get("rows", [])
    check(
        bool(rows) and all(row.get("member") in (None, "east") for row in rows),
        f"period rows are east only: {rows}",
    )

    print("== east: structure effect uses two metrics")
    events = chat(values, "east", ["sales_east"], "按品类看销售额结构效应")
    outputs, errors = tool_outputs(events, "structure_effect")
    check(bool(outputs), f"structure_effect returned output (errors={errors})")
    output = outputs[-1]
    check(
        all(key in output for key in ("structure_effect", "efficiency_effect", "interaction_effect")),
        f"structure components present: {output}",
    )

    print("all smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
