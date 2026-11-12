from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator

from .logging_setup import AI_LOGGER_NAME

logger = logging.getLogger(AI_LOGGER_NAME)

_AI_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("ai_call_context", default={})
_USAGE_SINK: ContextVar["UsageAccumulator | None"] = ContextVar(
    "ai_usage_sink", default=None
)


class UsageAccumulator:
    """累计一次聊天 run 里真实发生的模型用量（失败/中断时也能记到审计）。"""

    __slots__ = ("input_tokens", "output_tokens", "cache_read_tokens", "requests")

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.requests = 0


def bind_usage(accumulator: UsageAccumulator) -> None:
    _USAGE_SINK.set(accumulator)


def _accumulate(payload: dict[str, Any]) -> None:
    sink = _USAGE_SINK.get()
    if sink is None:
        return
    # 只统计这一轮问答本身（聊天 + 委派子牛马）；标题/知识精简/列名翻译不计入
    if _AI_CONTEXT.get().get("purpose") not in ("chat", "delegate"):
        return
    sink.input_tokens += int(payload.get("input_tokens") or 0)
    sink.output_tokens += int(payload.get("output_tokens") or 0)
    sink.cache_read_tokens += int(payload.get("cache_read_tokens") or 0)
    sink.requests += 1


def bind(**fields: Any) -> None:
    """为当前请求绑定 AI 调用日志的公共字段（用户/牛马/会话/轮次）。"""
    _AI_CONTEXT.set({key: value for key, value in fields.items() if value is not None})


@contextmanager
def scope(**fields: Any) -> Iterator[None]:
    """临时覆盖公共字段（如把一次模型调用标记为 title/labels/delegate）；None 表示移除。"""
    merged = dict(_AI_CONTEXT.get())
    for key, value in fields.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    token = _AI_CONTEXT.set(merged)
    try:
        yield
    finally:
        _AI_CONTEXT.reset(token)


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, float):
            value = round(value, 3)
        cleaned[key] = value
    return cleaned


def log_call(**fields: Any) -> None:
    """写一条 AI 调用日志（单行 JSON，带 UTC 时间戳和当前上下文）。"""
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        **_AI_CONTEXT.get(),
        **fields,
    }
    try:
        logger.info(json.dumps(_clean(payload), ensure_ascii=False, separators=(",", ":")))
    except Exception:  # noqa: BLE001
        logger.exception("failed to write ai call log")


def _usage_fields(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read_tokens", 0) or 0),
    }


def _tool_names(response: Any) -> list[str]:
    names: list[str] = []
    for call in getattr(response, "tool_calls", None) or []:
        name = getattr(call, "tool_name", None) or getattr(call, "name", None)
        if name:
            names.append(str(name))
    return names


def instrument_model(model: Any) -> Any:
    """包装模型的 request/request_stream，把每次模型调用写进 ai-calls.log。"""
    if model is None or getattr(model, "_assistant_instrumented", False):
        return model
    original_request = model.request
    original_stream = model.request_stream
    model_name = getattr(model, "model_name", "")

    def _log(
        *,
        messages: Any,
        request_parameters: Any,
        started: float,
        stream: bool,
        response: Any = None,
        usage: Any = None,
        finish_reason: Any = None,
        state: str | None = None,
        ttft_ms: int | None = None,
        error: Exception | None = None,
        status: str | None = None,
    ) -> None:
        tool_defs = getattr(request_parameters, "tool_defs", None) or []
        payload: dict[str, Any] = {
            "kind": "model_call",
            "model": model_name,
            "stream": stream,
            "messages": len(messages) if isinstance(messages, list) else None,
            "tools": len(tool_defs),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "status": status or ("error" if error is not None else "ok"),
        }
        if ttft_ms is not None:
            payload["ttft_ms"] = ttft_ms
        if response is not None:
            payload.update(_usage_fields(getattr(response, "usage", None)))
            payload["tool_calls"] = _tool_names(response)
            payload["finish_reason"] = getattr(response, "finish_reason", None)
            payload["state"] = getattr(response, "state", None)
        elif usage is not None:
            payload.update(_usage_fields(usage))
        if finish_reason is not None:
            payload["finish_reason"] = finish_reason
        if state is not None:
            payload["state"] = state
        if error is not None:
            payload["error"] = f"{type(error).__name__}: {error}"[:400]
        _accumulate(payload)
        log_call(**payload)

    async def request(messages, model_settings, model_request_parameters):
        started = time.perf_counter()
        try:
            response = await original_request(
                messages, model_settings, model_request_parameters
            )
        except Exception as exc:  # noqa: BLE001
            _log(
                messages=messages,
                request_parameters=model_request_parameters,
                started=started,
                stream=False,
                error=exc,
            )
            raise
        _log(
            messages=messages,
            request_parameters=model_request_parameters,
            started=started,
            stream=False,
            response=response,
        )
        return response

    @asynccontextmanager
    async def request_stream(
        messages, model_settings, model_request_parameters, run_context=None
    ):
        # pydantic-ai 的 request_stream 是 @asynccontextmanager，产出单个 StreamedResponse
        started = time.perf_counter()
        ttft: float | None = None
        logged = False

        def elapsed_first() -> int | None:
            return int((ttft - started) * 1000) if ttft else None

        try:
            async with original_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as streamed:
                ttft = time.perf_counter()
                yield streamed
        except BaseException as exc:  # noqa: BLE001 - 取消也要留痕
            logged = True
            _log(
                messages=messages,
                request_parameters=model_request_parameters,
                started=started,
                stream=True,
                ttft_ms=elapsed_first(),
                error=exc,
                status="canceled"
                if isinstance(exc, asyncio.CancelledError)
                else None,
            )
            raise
        else:
            logged = True
            final = None
            try:
                final = streamed.get()
            except Exception:  # noqa: BLE001
                final = None
            _log(
                messages=messages,
                request_parameters=model_request_parameters,
                started=started,
                stream=True,
                response=final,
                usage=getattr(streamed, "usage", None),
                finish_reason=getattr(streamed, "finish_reason", None),
                ttft_ms=elapsed_first(),
            )
        finally:
            if not logged:
                _log(
                    messages=messages,
                    request_parameters=model_request_parameters,
                    started=started,
                    stream=True,
                    ttft_ms=elapsed_first(),
                    status="canceled",
                )

    model.request = request
    model.request_stream = request_stream
    model._assistant_instrumented = True
    return model
