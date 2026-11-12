from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.usage import UsageLimits
from starlette.responses import StreamingResponse

from .. import llm_log
from ..admin.store import AdminStore, employee_allows
from ..agent import build_agent
from ..api_shared import (
    _agent_limit_defaults,
    _background_tasks,
    _conversation_id,
    _employee_id,
    _friendly_model_error,
    _limit_defaults,
    _mark_continuation,
    _model_id,
    _page_context,
    _question_from_request,
    _reasoning_effort,
    _result_layout,
    _result_texts,
    _selection_context,
    _sse_events,
    _summarize_title,
    _trim_request_history,
)
from ..auth import UserContext, get_user
from ..config import settings
from ..deps import AgentDeps
from ..limits import UserRateLimiter, daily_quota_error
from ..runs import ActiveRun

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/chat")
async def chat(
    request: Request,
    user: UserContext = Depends(get_user),
):
    store: AdminStore = request.app.state.admin_store
    conversation_id = _conversation_id(request)
    # 写入前校验会话归属：客户端自带 conversation id，不能往别人的会话里写
    owner = store.conversation_owner(conversation_id)
    if owner is not None and owner != user.username:
        return JSONResponse(
            status_code=403,
            content={"error": "会话不存在或无权访问"},
        )
    # 单次请求工具调用上限：后台「运行限制」每次请求读取，改完即时生效
    agent_limits = store.get_agent_limits(_agent_limit_defaults(settings))
    raw_limit = agent_limits.get("max_tool_calls")
    try:
        max_tool_calls = int(
            raw_limit if raw_limit is not None else settings.max_tool_calls
        )
    except (TypeError, ValueError):
        max_tool_calls = settings.max_tool_calls
    # 0 = 不限制；正整数才按次数截断
    max_tool_calls = max(0, max_tool_calls)
    # 单次查询行数上限：后台可配，且不超过 Superset 的 SQL_MAX_ROW 硬上限
    raw_rows = agent_limits.get("max_rows")
    try:
        max_rows = int(raw_rows if raw_rows is not None else settings.max_rows)
    except (TypeError, ValueError):
        max_rows = settings.max_rows
    max_rows = max(1, min(max_rows, max(1, settings.superset_sql_max_row)))
    if "Admin" not in user.roles:
        limits = store.get_limit_config(_limit_defaults(settings))
        limiter: UserRateLimiter = request.app.state.rate_limiter
        rate_limit = int(limits.get("rate_per_minute") or 0)
        if not await limiter.allow(user.username, rate_limit):
            raise HTTPException(
                status_code=429,
                detail=(
                    "请求过于频繁，请稍后再试"
                    f"（每分钟最多 {rate_limit} 次）"
                ),
            )
        quota_error = daily_quota_error(
            store.user_usage_for_day(user.username),
            request_limit=int(limits.get("daily_requests") or 0),
            token_limit=int(limits.get("daily_tokens") or 0),
            cost_limit=float(limits.get("daily_cost") or 0),
        )
        if quota_error:
            raise HTTPException(status_code=429, detail=quota_error)

    employee = None
    available_employees: list[dict[str, Any]] | None = None
    employee_id = _employee_id(request)
    if employee_id is None:
        available_employees = store.list_employees_for_user(
            user.username, list(user.roles)
        )
        # 未指定员工时取第一个可用牛马（不存在"无牛马的通用助手"）
        if available_employees:
            employee_id = int(available_employees[0]["id"])
        if employee_id is None:
            return JSONResponse(
                status_code=403,
                content={"error": "当前角色没有可用的 AI 牛马，请联系管理员"},
            )
    employee = store.get_employee(employee_id)
    if employee is None or not employee.get("enabled"):
        return JSONResponse(
            status_code=400,
            content={"error": "AI 员工不存在或已停用"},
        )
    if not employee_allows(employee, user.username, list(user.roles)):
        return JSONResponse(
            status_code=403,
            content={
                "error": f"你没有使用 AI 员工「{employee.get('nickname') or employee.get('username')}」的权限"
            },
        )

    requested_model_id = _model_id(request)
    allowed_model_ids = None
    raw_model_ids = employee.get("model_ids") or []
    if raw_model_ids:
        allowed_model_ids = {int(item) for item in raw_model_ids}
    if requested_model_id is not None:
        if (
            allowed_model_ids is not None
            and requested_model_id not in allowed_model_ids
        ):
            return JSONResponse(
                status_code=400,
                content={"error": "所选模型不在该 AI 员工的可用模型范围内"},
            )
        effective_model_id = requested_model_id
        explicit_model = True
    else:
        effective_model_id = None
        explicit_model = False
        employee_default = employee.get("model_id")
        if employee_default and (
            allowed_model_ids is None
            or int(employee_default) in allowed_model_ids
        ):
            effective_model_id = int(employee_default)
    runtime = store.get_runtime_model(effective_model_id)
    if effective_model_id is not None and runtime is None:
        if explicit_model:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "所选模型不可用或已停用，请刷新模型列表后重试",
                },
            )
        effective_model_id = None
        runtime = store.get_runtime_model(None)
    if (
        runtime is not None
        and runtime.id is not None
        and allowed_model_ids is not None
        and runtime.id not in allowed_model_ids
    ):
        fallback = next(
            (
                item
                for item in store.list_enabled_models()
                if int(item["id"]) in allowed_model_ids
            ),
            None,
        )
        if fallback is None:
            return JSONResponse(
                status_code=400,
                content={"error": "该 AI 员工没有可用模型，请联系管理员配置"},
            )
        effective_model_id = int(fallback["id"])
        runtime = store.get_runtime_model(effective_model_id)
    if runtime is None and not settings.llm_model and not settings.mock_llm:
        return JSONResponse(
            status_code=503,
            content={
                "error": "模型未配置：请在 AI 管理中配置 Provider 和默认模型",
            },
        )

    continuation = await _mark_continuation(request)
    reasoning_effort = _reasoning_effort(request)
    page_context = _page_context(request)
    selection = _selection_context(page_context)
    skills = store.list_skills(enabled_only=True)
    if employee is not None:
        wanted = set(employee.get("skill_ids") or [])
        skills = [item for item in skills if item["id"] in wanted]
    delegates: list[dict[str, Any]] = []
    if employee is not None and employee.get("can_delegate"):
        available = (
            available_employees
            if available_employees is not None
            else store.list_employees_for_user(user.username, list(user.roles))
        )
        allowed_ids = {
            int(item) for item in (employee.get("delegate_employee_ids") or [])
        }
        delegates = [
            item
            for item in available
            if int(item["id"]) != int(employee["id"])
            and (not allowed_ids or int(item["id"]) in allowed_ids)
        ]
    running = request.app.state.runs.active_for(conversation_id, user.username)
    if running is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "上一轮回答还在后台生成中，请等它完成或先点「停止」再提问",
            },
            headers={"X-Run-Id": running.run_id},
        )
    agent = build_agent(
        settings,
        runtime,
        page_context,
        skills=skills,
        employee=employee,
        delegates=delegates,
        reasoning_effort=reasoning_effort,
    )
    run_id = str(uuid.uuid4())
    model_name = (
        runtime.model_name
        if runtime is not None
        else (settings.llm_model or "mock")
    )
    llm_log.bind(
        user=user.username,
        employee=(employee or {}).get("nickname")
        or (employee or {}).get("username"),
        conversation_id=conversation_id,
        run_id=run_id,
        purpose="chat",
    )
    # 失败/中断时 on_complete 不会带 usage，用真实模型调用累加兜底
    usage = llm_log.UsageAccumulator()
    llm_log.bind_usage(usage)
    deps = AgentDeps(
        user=user,
        settings=settings,
        audit=request.app.state.audit,
        conversation_id=conversation_id,
        run_id=run_id,
        model_name=model_name,
        store=store,
        runtime=runtime,
        page_context=page_context,
        employee=employee,
        delegates=delegates,
        reasoning_effort=reasoning_effort,
        max_tool_calls=max_tool_calls,
        max_rows=max_rows,
    )
    started = time.perf_counter()
    # 按模型上下文档位截断前端带来的历史，避免长会话/继续对话把超限内容全量塞给模型
    context_limit = runtime.context_window if runtime is not None else 0
    if settings.mock_llm:
        context_limit = 0
    await _trim_request_history(request, context_limit)
    question_hint = "" if continuation else await _question_from_request(request)
    completed = False
    error_recorded = False
    cancel_recorded = False
    # 分片累积再 join，避免长回答用 += 拼接成 O(n²)
    text_chunks: list[str] = []

    def streamed_text() -> str:
        return "".join(text_chunks)

    def record(
        *,
        question: str,
        answer: str,
        input_tokens: int,
        output_tokens: int,
        status: str,
        error: str,
        selection: list[dict] | None = None,
        parts: list[dict] | None = None,
    ) -> None:
        cost = 0.0
        if runtime is not None:
            cost = (
                input_tokens / 1_000_000 * runtime.input_price_per_m
                + output_tokens / 1_000_000 * runtime.output_price_per_m
            )
        run_count = 0
        stored_question = "" if continuation else (question or question_hint)
        try:
            run_count = store.log_turn(
                conversation_id=conversation_id,
                run_id=run_id,
                username=user.username,
                question=stored_question,
                answer=answer,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
                tool_calls=deps.tool_calls,
                cost=cost,
                status=status,
                error=error,
                employee_id=employee["id"] if employee else None,
                selection=selection,
                parts=parts,
                include_question=not continuation,
                count_run=not continuation,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist chat audit")
        # 首轮成功后异步生成会话标题（不阻塞响应；失败保留原问题文本）
        if status == "ok" and run_count == 1 and stored_question:
            task = asyncio.create_task(
                _summarize_title(
                    runtime=runtime,
                    store=store,
                    audit=request.app.state.audit,
                    conversation_id=conversation_id,
                    username=user.username,
                    question=stored_question,
                    answer=answer,
                )
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    def record_cancel(reason: str, note: str = "回答中断（连接中断或超时），可以重新提问。") -> None:
        """断流/手动停止也要落库：保住用户问题和已流出的部分回答。"""
        nonlocal cancel_recorded
        if completed or error_recorded or cancel_recorded:
            return
        cancel_recorded = True
        partial = streamed_text().strip()
        answer = f"{partial}\n\n{note}" if partial else note
        record(
            question="",
            answer=answer,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            status="canceled",
            error=reason,
            selection=selection,
        )
        deps.audit.log(
            "chat_cancel",
            user=user.username,
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
        )

    async def on_complete(result) -> None:
        nonlocal completed
        completed = True
        usage = getattr(result, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        question, answer = _result_texts(result)
        layout_answer, layout = _result_layout(result)
        if layout_answer:
            answer = layout_answer
        record(
            question=question,
            answer=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status="ok",
            error="",
            selection=selection,
            parts=layout,
        )
        deps.audit.log(
            "chat_complete",
            user=user.username,
            conversation_id=conversation_id,
            run_id=run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=deps.tool_calls,
            mcp_calls=deps.mcp_calls,
        )

    async def on_cancel(_result) -> None:
        record_cancel("canceled by user")

    deps.audit.log(
        "chat_start",
        user=user.username,
        roles=list(user.roles),
        model=model_name,
        employee=employee["username"] if employee else None,
        conversation_id=conversation_id,
        run_id=run_id,
        continuation=continuation,
        reasoning_effort=reasoning_effort,
        page_context={
            key: page_context.get(key)
            for key in (
                "page",
                "path",
                "dashboard_id",
                "dataset_id",
                "chart_id",
                "permalink_key",
                "selection",
            )
            if page_context.get(key) is not None
        },
    )
    store.ensure_conversation(
        conversation_id,
        user.username,
        (question_hint or ("继续执行" if continuation else "新对话"))[:120],
        model_name,
        employee_id=employee["id"] if employee else None,
    )
    try:
        response = await VercelAIAdapter.dispatch_request(
            request,
            agent=agent,
            deps=deps,
            usage_limits=UsageLimits(
                # 0 = 不限制；正数留 8 次余量，让 begin_tool 的中文提示先到模型
                request_limit=(max_tool_calls + 8) if max_tool_calls else None,
                tool_calls_limit=(max_tool_calls + 8) if max_tool_calls else None,
            ),
            on_complete=on_complete,
            on_cancel=on_cancel,
        )
    except Exception as exc:
        logger.exception("chat failed for user=%s", user.username)
        if not completed:
            record(
                question="",
                answer="",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                status="error",
                error=str(exc),
                selection=selection,
            )
        deps.audit.log(
            "chat_error",
            user=user.username,
            conversation_id=conversation_id,
            run_id=run_id,
            error=str(exc),
        )
        raise

    if isinstance(response, StreamingResponse):
        original = response.body_iterator
        buffer = ""
        finished = False
        run = ActiveRun(
            run_id=run_id,
            conversation_id=conversation_id,
            username=user.username,
            model=model_name,
            employee=(employee or {}).get("nickname")
            or (employee or {}).get("username")
            or "",
            question=question_hint,
        )
        request.app.state.runs.add(run)
        response.headers["X-Run-Id"] = run_id

        last_snapshot = 0.0

        def handle_event(raw: str) -> None:
            """解析一条 SSE 事件：累计文本/工具数并写入运行缓冲，必要时补中文错误提示。"""
            nonlocal finished, error_recorded, last_snapshot
            events = _sse_events(raw)
            if any(event.get("type") == "finish" for event in events):
                finished = True
            error_text = next(
                (
                    str(event.get("errorText") or event.get("error") or "unknown error")
                    for event in events
                    if event.get("type") == "error"
                ),
                None,
            )
            if error_text is None:
                for event in events:
                    if event.get("type") == "text-delta":
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            text_chunks.append(delta)
                    elif event.get("type") == "tool-input-start":
                        run.tool_calls += 1
                now = time.monotonic()
                if now - last_snapshot > 0.4:
                    last_snapshot = now
                    run.text = streamed_text().strip()
                run.append(raw + "\n\n")
                return
            if completed or error_recorded:
                return
            error_recorded = True
            logger.error(
                "model stream error: user=%s conversation=%s run_id=%s error=%s raw=%s",
                user.username,
                conversation_id,
                run_id,
                error_text,
                raw[:2000],
            )
            friendly = _friendly_model_error(error_text, deps.last_tool_error)
            partial = streamed_text().strip()
            answer = f"{partial}\n\n{friendly}" if partial else friendly
            record(
                question="",
                answer=answer,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                status="error",
                error=error_text,
                selection=selection,
            )
            deps.audit.log(
                "chat_error",
                user=user.username,
                conversation_id=conversation_id,
                run_id=run_id,
                error=error_text,
            )
            run.error = error_text
            run.text = answer
            message_id = f"error-{run_id}"
            for event in (
                {"type": "text-start", "id": message_id},
                {"type": "text-delta", "id": message_id, "delta": friendly},
                {"type": "text-end", "id": message_id},
            ):
                run.append("data: " + json.dumps(event, ensure_ascii=False) + "\n\n")

        async def pump() -> None:
            """与 HTTP 连接解耦地消费 Agent 流：客户端断开也继续跑完并落库。"""
            nonlocal buffer
            try:
                async for chunk in original:
                    text = (
                        chunk.decode()
                        if isinstance(chunk, (bytes, bytearray))
                        else chunk
                    )
                    buffer += text
                    while "\n\n" in buffer:
                        raw, buffer = buffer.split("\n\n", 1)
                        handle_event(raw)
                if buffer:
                    handle_event(buffer)
                run.text = streamed_text().strip()
            except asyncio.CancelledError:
                record_cancel(
                    "canceled by user",
                    note="回答已停止（用户手动停止），可以重新提问。",
                )
                run.finish("canceled")
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "pump failed: user=%s conversation=%s", user.username, conversation_id
                )
                if not (completed or error_recorded):
                    record(
                        question="",
                        answer="",
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        status="error",
                        error=str(exc),
                        selection=selection,
                    )
                run.finish("error", str(exc))
            else:
                if not (completed or finished):
                    record_cancel("stream closed before finish")
                run.finish("ok" if completed else "canceled")
            finally:
                _background_tasks.discard(asyncio.current_task())

        task = asyncio.create_task(pump())
        run.task = task
        _background_tasks.add(task)

        async def tapped():
            """把 pump 写下的缓冲按序发给当前连接；断开只是停止转发，不取消生成。"""
            index = 0
            run.attached += 1
            try:
                while True:
                    while index < len(run.chunks):
                        yield run.chunks[index]
                        index += 1
                    if run.done.is_set():
                        break
                    run.updated.clear()
                    if index < len(run.chunks) or run.done.is_set():
                        continue
                    try:
                        await asyncio.wait_for(run.updated.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass
            finally:
                run.attached -= 1
                if run.attached <= 0:
                    run.buffering = False
                    run.chunks.clear()

        response.body_iterator = tapped()
    return response
