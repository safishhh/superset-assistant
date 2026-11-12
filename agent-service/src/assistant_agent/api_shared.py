from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

from fastapi import HTTPException, Request
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from . import llm_log
from .admin.db import utcnow
from .admin.store import AdminStore
from .agent import build_oneshot_agent
from .audit import AuditLogger
from .auth import UserContext, sign_mcp_token
from .condense import build_condense_prompt, clean_condensed
from .config import settings
from .mcp_client import MCPClient
from .titles import (
    build_title_prompt,
    clean_title,
    fallback_title,
    is_usable_title,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()
CONTINUATION_MARKER = "[[sa-continue]]"


async def _summarize_title(
    *,
    runtime,
    store: AdminStore,
    audit: AuditLogger,
    conversation_id: str,
    username: str,
    question: str,
    answer: str,
) -> None:
    """首轮回答完成后用模型生成会话标题；模型输出不可用时退回问题首句。"""
    title = ""
    source = "fallback"
    try:
        agent = build_oneshot_agent(settings, runtime)
        if agent is not None:
            with llm_log.scope(purpose="title", run_id=None):
                result = await asyncio.wait_for(
                    agent.run(build_title_prompt(question, answer)),
                    timeout=30,
                )
            candidate = clean_title(result.output)
            if is_usable_title(candidate):
                title, source = candidate, "model"
    except Exception:  # noqa: BLE001
        logger.warning("conversation title generation failed", exc_info=True)
    if not title:
        title = fallback_title(question)
    if not title:
        return
    store.update_conversation_title(conversation_id, title)
    audit.log(
        "title_generated",
        user=username,
        conversation_id=conversation_id,
        title=title,
        source=source,
    )


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content or "")


def _result_texts(result) -> tuple[str, str]:
    question = ""
    answer = ""
    try:
        messages = result.all_messages()
    except Exception:  # noqa: BLE001
        return question, answer
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    question = _content_text(part.content)
        elif isinstance(message, ModelResponse):
            texts = [
                part.content
                for part in message.parts
                if isinstance(part, TextPart) and part.content
            ]
            if texts:
                answer = "\n".join(texts)
    return question, answer


def _result_layout(result) -> tuple[str, list[dict] | None]:
    """本轮正文/工具的真实顺序：[(text,len),(tool,name)…]，供历史/导出还原图表位置。"""
    try:
        messages = result.new_messages()
    except Exception:  # noqa: BLE001
        return "", None
    layout: list[dict] = []
    texts: list[str] = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, TextPart) and part.content:
                layout.append({"type": "text", "len": len(part.content)})
                texts.append(part.content)
            elif isinstance(part, ToolCallPart):
                layout.append({"type": "tool", "name": part.tool_name})
    if not texts:
        return "", None
    return "\n\n".join(texts), layout


async def _question_from_request(request: Request) -> str:
    try:
        raw = await request.body()
        body = json.loads(raw or b"{}")
    except Exception:  # noqa: BLE001
        return ""
    messages = body.get("messages") or []
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        parts = message.get("parts") or []
        texts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if texts:
            return "\n".join(texts)
    return ""


async def _mark_continuation(request: Request) -> bool:
    """识别确认写操作后的静默续跑，并去掉内部标记。

    续跑请求的最后一条 user 消息带内部前缀；只在请求体内剥离标记，
    不落库为用户消息。
    """
    try:
        raw = await request.body()
        body = json.loads(raw or b"{}")
    except Exception:  # noqa: BLE001
        return False
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False
    continuation = False
    changed = False
    last_user = True
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        parts = message.get("parts")
        text_parts = (
            [
                part
                for part in parts
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            if isinstance(parts, list)
            else []
        )
        marked = any(
            str(part.get("text") or "").startswith(CONTINUATION_MARKER)
            for part in text_parts
        )
        if last_user:
            continuation = marked
            last_user = False
        for part in text_parts:
            text = str(part.get("text") or "")
            if text.startswith(CONTINUATION_MARKER):
                part["text"] = text[len(CONTINUATION_MARKER) :].lstrip()
                changed = True
    if changed:
        try:
            request._body = json.dumps(body, ensure_ascii=False).encode()
            request.scope["_cached_json"] = None
        except TypeError:
            return False
    return continuation


def _conversation_id(request: Request) -> str:
    value = (request.headers.get("x-conversation-id") or "").strip()
    if 8 <= len(value) <= 64:
        return value
    return str(uuid.uuid4())


def _employee_id(request: Request) -> int | None:
    raw = (request.headers.get("x-employee-id") or "").strip()
    value = int(raw) if raw.isdigit() else 0
    return value if value > 0 else None


def _model_id(request: Request) -> int | None:
    raw = (request.headers.get("x-model-id") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="模型参数无效") from exc
    return value if value > 0 else None


def _reasoning_effort(request: Request) -> str:
    raw = (request.headers.get("x-reasoning-effort") or "").strip().lower()
    return raw if raw in ("low", "medium", "high") else "default"


def _page_context(request: Request) -> dict:
    raw = request.headers.get("x-superset-context", "")
    if not raw or len(raw) > 20000:
        return {}
    try:
        value = json.loads(unquote(raw))
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def _selection_context(page_context: dict) -> list[dict] | None:
    raw = page_context.get("selection")
    if not isinstance(raw, list):
        return None
    items: list[dict] = []
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        raw_kind = item.get("kind")
        kind = raw_kind if raw_kind in ("chart", "filter", "block") else "block"
        entry = {
            "kind": kind,
            "title": str(item.get("title") or "")[:80],
        }
        chart_id = item.get("chart_id")
        if chart_id is not None:
            entry["chart_id"] = str(chart_id)[:32]
        text = item.get("text")
        if text:
            entry["text"] = str(text)[:500]
        items.append(entry)
    return items or None


def _limit_defaults(settings) -> dict[str, float | int]:
    return {
        "rate_per_minute": settings.user_rate_limit_per_minute,
        "daily_requests": settings.user_daily_requests,
        "daily_tokens": settings.user_daily_tokens,
        "daily_cost": settings.user_daily_cost,
    }


def _estimate_tokens(value: str) -> int:
    """粗估 token：CJK 字符 ~1.6 token/字，其余 ~0.25 token/字符。宁可略保守。"""
    if not value:
        return 0
    cjk = sum(1 for ch in value if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 1.6 + (len(value) - cjk) * 0.25)


def _history_budget(limit: int) -> int:
    """历史消息保留的 token 预算：档位的一定比例，给系统提示/工具/本轮输出留余量。"""
    if limit <= 0:
        return 60_000
    return max(4_000, int(limit * 0.55))


async def _trim_request_history(
    request: Request, limit: int
) -> None:
    """按 token 预算截断前端带来的历史消息，从最旧的轮次开始丢弃。

    只处理请求体里 messages 数组：保留最后一条 user 消息（本轮问题），
    其余按累计 token 超预算时从头部整对删除。直接改写 request._body。
    """
    try:
        raw = await request.body()
        body = json.loads(raw or b"{}")
    except Exception:  # noqa: BLE001
        return
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) <= 1:
        return
    budget = _history_budget(limit)
    # messages[-1] 是本轮要执行的用户输入，不参与截断
    history = messages[:-1]
    kept = []
    used = 0
    for message in reversed(history):
        used += _estimate_tokens(_message_text(message))
        if used > budget:
            break
        kept.append(message)
    kept.reverse()
    if len(kept) == len(history):
        return
    trimmed = [*kept, messages[-1]]
    try:
        payload = json.dumps(body | {"messages": trimmed}, ensure_ascii=False)
    except TypeError:
        return
    request._body = payload.encode()
    request.scope["_cached_json"] = None
    logger.info(
        "history trimmed: %d -> %d messages (budget %d tokens)",
        len(history),
        len(kept),
        budget,
    )


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts")
    if not isinstance(parts, list):
        return str(message.get("content") or "")
    chunks = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            chunks.append(str(part.get("text") or ""))
        elif isinstance(part, dict) and part.get("type", "").startswith("tool-"):
            chunks.append(json.dumps(part.get("output"), ensure_ascii=False)[:2000])
    return "\n".join(chunks)


def _agent_limit_defaults(settings) -> dict[str, int]:
    return {
        "max_tool_calls": settings.max_tool_calls,
        "max_rows": settings.max_rows,
    }


def _write_client(settings, user: UserContext) -> MCPClient:
    """写操作也走滑动续签：入口 token 只有 5 分钟，确认/回滚常发生在之后。"""
    return MCPClient(
        settings.mcp_url,
        sign_mcp_token(
            settings,
            user.username,
            user.roles,
            ttl=300,
            jti_prefix="write",
        ),
        timeout=120.0,
    )


async def _condense_content(
    store: AdminStore, title: str, content: str, username: str = ""
) -> tuple[str, bool]:
    """用户选了「AI 精简」：模型改写失败或输出不可信时退回原文。"""
    try:
        runtime = store.get_runtime_model()
        agent = build_oneshot_agent(settings, runtime)
        if agent is None:
            return content, False
        with llm_log.scope(
            purpose="knowledge",
            user=username or None,
            conversation_id=None,
            run_id=None,
        ):
            result = await asyncio.wait_for(
                agent.run(build_condense_prompt(title, content)),
                timeout=30,
            )
        candidate = clean_condensed(result.output, content)
    except Exception:  # noqa: BLE001 - 精简失败不阻塞保存
        logger.warning("knowledge condense failed", exc_info=True)
        return content, False
    if not candidate:
        return content, False
    return candidate, True


def _write_action_for_user(
    request: Request,
    action_id: str,
    user: UserContext,
) -> dict:
    store: AdminStore = request.app.state.admin_store
    action = store.get_write_action(action_id, username=user.username)
    if action is None:
        raise HTTPException(status_code=404, detail="写操作不存在")
    return action


def _ensure_pending(action: dict) -> None:
    if action["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"写操作当前状态为 {action['status']}，不能执行",
        )
    expires_at = datetime.fromisoformat(str(action["expires_at"]))
    if expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="写操作方案已过期，请重新提问")


def _sse_events(block: str) -> list[dict[str, Any]]:
    """一次解析一个 SSE 块里的全部 data 事件（同一块不再被重复 json.loads）。"""
    events: list[dict[str, Any]] = []
    for line in block.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


_TOOL_RETRY_RE = re.compile(
    r"Tool '([^']+)' exceeded max retries count of (\d+)"
)


def _friendly_model_error(error: str, last_tool_error: str = "") -> str:
    lowered = error.lower()
    if "tool_calls_limit" in lowered or "工具调用次数超过上限" in error:
        return "本次回答的工具调用次数超过上限，请缩小问题范围或分多次提问。"
    if "429" in lowered or "rate limit" in lowered:
        return "模型服务繁忙（429 限流），请稍后重试。"
    if "504" in lowered or "timeout" in lowered or "timed out" in lowered:
        return "模型服务响应超时，请稍后重试。"
    if "mcp rejected the token" in lowered:
        return "会话凭证已过期，请关闭助手面板后重新打开（或刷新页面）再继续。"
    if (
        "upstream stream terminated" in lowered
        or "stream terminated unexpectedly" in lowered
        or "stream ended before" in lowered
    ):
        return (
            "模型服务响应中断（上游流提前结束），请重试；"
            "若反复出现，请到管理后台「运行日志」查看完整原因。"
        )
    if "401" in lowered or "403" in lowered or "unauthorized" in lowered:
        return "模型服务鉴权失败，请联系管理员检查模型配置。"
    if "connection" in lowered or "connect" in lowered:
        return "模型服务连接失败，请稍后重试。"
    retry = _TOOL_RETRY_RE.search(error)
    if retry:
        tool, count = retry.group(1), retry.group(2)
        detail = last_tool_error.strip()
        if detail:
            return (
                f"工具「{tool}」执行失败：{detail[:200]}"
                f"（已重试 {count} 次）。可以补充可用指标/维度，或换个问法后重试。"
            )
        return (
            f"工具「{tool}」执行失败（常见原因：指标/维度参数不可用或数据不足），"
            f"已重试 {count} 次仍未成功，本次回答中止。"
            "可以补充可用指标/维度，或换个问法后重试。"
        )
    reason = (error.strip().splitlines()[0] if error.strip() else "").strip()
    if reason:
        return f"回答失败：{reason[:160]}"
    return "回答失败，请稍后重试。"
