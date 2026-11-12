from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

from assistant_agent import llm_log
from assistant_agent.llm_log import instrument_model
from assistant_agent.logging_setup import (
    configure_logging,
    read_ai_calls,
    read_log_tail,
)


class FakeUsage:
    input_tokens = 120
    output_tokens = 45
    cache_read_tokens = 7


class FakeResponse:
    usage = FakeUsage()
    tool_calls = [SimpleNamespace(tool_name="query_dataset")]
    finish_reason = "stop"
    state = "complete"


class FakeStreamed:
    def __init__(self, usage: FakeUsage | None = None) -> None:
        self.usage = usage or FakeUsage()
        self.finish_reason = "stop"

    def get(self):
        return FakeResponse()


class FakeModel:
    model_name = "fake-model"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def request(self, messages, model_settings, model_request_parameters):
        if self.error:
            raise self.error
        return FakeResponse()

    @asynccontextmanager
    async def request_stream(
        self, messages, model_settings, model_request_parameters, run_context=None
    ):
        if self.error:
            raise self.error
        yield FakeStreamed()


PARAMS = SimpleNamespace(tool_defs=["q", "r"])


def _flush() -> None:
    for handler in logging.getLogger(llm_log.logger.name).handlers:
        handler.flush()


def _setup(tmp_path):
    log_dir = tmp_path / "logs"
    configure_logging(log_dir, 7)
    llm_log.bind(user="alice", employee="Atlas", conversation_id="c1", run_id="r1", purpose="chat")
    return log_dir


def test_model_request_is_logged(tmp_path):
    log_dir = _setup(tmp_path)
    model = instrument_model(FakeModel())

    response = asyncio.run(model.request([{"a": 1}], None, PARAMS))
    assert isinstance(response, FakeResponse)
    _flush()

    result = read_ai_calls(log_dir, limit=10)
    assert result["scanned"] >= 1
    items = result["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["model"] == "fake-model"
    assert entry["status"] == "ok"
    assert entry["stream"] is False
    assert entry["messages"] == 1
    assert entry["tools"] == 2
    assert entry["input_tokens"] == 120
    assert entry["output_tokens"] == 45
    assert entry["tool_calls"] == ["query_dataset"]
    assert entry["user"] == "alice"
    assert entry["employee"] == "Atlas"
    assert entry["conversation_id"] == "c1"
    assert entry["run_id"] == "r1"
    assert entry["purpose"] == "chat"
    assert "ts" in entry
    tail = read_log_tail(log_dir, "ai-calls.log", 10)
    assert any("model_call" in line for line in tail["lines"])


def test_stream_is_logged_and_purpose_scope(tmp_path):
    log_dir = _setup(tmp_path)
    model = instrument_model(FakeModel())

    async def consume():
        with llm_log.scope(purpose="title", run_id=None):
            async with model.request_stream([], None, PARAMS):
                pass

    asyncio.run(consume())
    _flush()

    items = read_ai_calls(log_dir, limit=10)["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["stream"] is True
    assert entry["purpose"] == "title"
    assert "run_id" not in entry
    assert entry["input_tokens"] == 120
    assert entry["tool_calls"] == ["query_dataset"]


def test_stream_cancel_is_logged(tmp_path):
    log_dir = _setup(tmp_path)
    model = instrument_model(FakeModel())

    async def consume_one():
        try:
            async with model.request_stream([], None, PARAMS):
                raise asyncio.CancelledError()
        except asyncio.CancelledError:
            pass

    asyncio.run(consume_one())
    _flush()

    items = read_ai_calls(log_dir, limit=10)["items"]
    assert len(items) == 1
    assert items[0]["status"] == "canceled"


def test_model_error_is_logged(tmp_path):
    log_dir = _setup(tmp_path)
    model = instrument_model(FakeModel(error=RuntimeError("boom 429")))

    try:
        asyncio.run(model.request([], None, PARAMS))
    except RuntimeError:
        pass
    _flush()

    items = read_ai_calls(log_dir, limit=10)["items"]
    assert len(items) == 1
    assert items[0]["status"] == "error"
    assert "boom 429" in items[0]["error"]


def test_read_ai_calls_filters_and_order(tmp_path):
    log_dir = _setup(tmp_path)
    model = instrument_model(FakeModel())

    llm_log.bind(user="alice", purpose="chat")
    asyncio.run(model.request([], None, PARAMS))
    llm_log.bind(user="bob", purpose="knowledge")
    asyncio.run(model.request([], None, PARAMS))
    _flush()

    all_items = read_ai_calls(log_dir, limit=10)["items"]
    assert [item["user"] for item in all_items] == ["bob", "alice"]

    assert len(read_ai_calls(log_dir, username="ali")["items"]) == 1
    assert len(read_ai_calls(log_dir, status="error")["items"]) == 0
    assert len(read_ai_calls(log_dir, model="other")["items"]) == 0
    assert len(read_ai_calls(log_dir, keyword="knowledge")["items"]) == 1
    assert read_ai_calls(log_dir, limit=1)["truncated"] is True


def test_usage_accumulator_counts_chat_only(tmp_path):
    _setup(tmp_path)
    sink = llm_log.UsageAccumulator()
    llm_log.bind_usage(sink)
    model = instrument_model(FakeModel())

    asyncio.run(model.request([], None, PARAMS))
    with llm_log.scope(purpose="title", run_id=None):
        asyncio.run(model.request([], None, PARAMS))
    with llm_log.scope(purpose="delegate"):
        asyncio.run(model.request([], None, PARAMS))

    assert sink.requests == 2  # chat + delegate，标题不计入
    assert sink.input_tokens == 240
    assert sink.output_tokens == 90
