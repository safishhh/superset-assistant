from __future__ import annotations

from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from .admin.store import RuntimeModel
from .config import Settings
from .deps import AgentDeps
from .llm_log import instrument_model
from .mock_model import mock_model
from .prompts import (
    SYSTEM_PROMPT,
    delegation_prompt,
    employee_prompt,
    page_context_prompt,
)
from .tools import attach_skills, attach_tools


_MODEL_HTTP_CLIENT: httpx.AsyncClient | None = None


def _model_http_client(settings: Settings) -> httpx.AsyncClient:
    """模型请求显式超时：连接 10s、读取 LLM_TIMEOUT_SECONDS（默认 120s）。

    不设超时时 openai 客户端默认等 10 分钟且自动重试，模型端挂起会让
    会话一直“生成中”（2026-10-28 实测）。
    """
    global _MODEL_HTTP_CLIENT
    if _MODEL_HTTP_CLIENT is None or _MODEL_HTTP_CLIENT.is_closed:
        _MODEL_HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(settings.llm_timeout_seconds or 120),
                write=30.0,
                pool=10.0,
            ),
            limits=httpx.Limits(
                max_connections=20, max_keepalive_connections=10
            ),
        )
    return _MODEL_HTTP_CLIENT


def _provider(
    settings: Settings,
    *,
    base_url: str | None,
    api_key: str | None,
) -> OpenAIProvider:
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key or "not-needed",
        http_client=_model_http_client(settings),
        max_retries=1,
    )
    return OpenAIProvider(openai_client=client)


def build_model(settings: Settings, runtime: RuntimeModel | None = None):
    if runtime is not None:
        return instrument_model(
            OpenAIChatModel(
                runtime.model_name,
                provider=_provider(
                    settings,
                    base_url=runtime.base_url,
                    api_key=runtime.api_key,
                ),
            )
        )
    if settings.llm_model:
        model_name = settings.llm_model
        if model_name.startswith("openai:"):
            model_name = model_name.split(":", 1)[1]
        provider = None
        if settings.llm_base_url:
            provider = _provider(
                settings,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
            )
        elif settings.llm_api_key:
            provider = _provider(
                settings, base_url=None, api_key=settings.llm_api_key
            )
        return instrument_model(OpenAIChatModel(model_name, provider=provider))
    if settings.mock_llm:
        return mock_model()
    return None


def _model_settings(
    settings: Settings,
    runtime: RuntimeModel | None,
    *,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> ModelSettings | None:
    disable_thinking = (
        runtime.disable_thinking if runtime is not None else settings.llm_disable_thinking
    )
    # 思考强度由聊天端按次选择；后台模型配置不再提供该开关。
    effort = (reasoning_effort or "default").strip().lower()
    if effort not in ("default", "low", "medium", "high"):
        effort = "default"
    extra: dict[str, Any] = {}
    if disable_thinking:
        extra["chat_template_kwargs"] = {"enable_thinking": False}
    if effort != "default":
        # OpenAI 兼容接口的思考强度；DeepSeek/GLM 等用它控制 reasoning
        extra["reasoning_effort"] = effort
    if temperature is None and not extra:
        return None
    kwargs: dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if extra:
        kwargs["extra_body"] = extra
    return ModelSettings(**kwargs)


def build_oneshot_agent(
    settings: Settings,
    runtime: RuntimeModel | None = None,
) -> Agent[None, str] | None:
    """一次性无工具 Agent（temperature=0、零重试），供标题生成与知识精简复用。"""
    model = build_model(settings, runtime)
    if model is None:
        return None
    model_settings = _model_settings(settings, runtime, temperature=0)
    return Agent(
        model,
        output_type=str,
        retries=0,
        model_settings=model_settings,
    )


def build_agent(
    settings: Settings,
    runtime: RuntimeModel | None = None,
    page_context: dict[str, Any] | None = None,
    skills: list[Any] | None = None,
    employee: dict[str, Any] | None = None,
    delegates: list[dict[str, Any]] | None = None,
    reasoning_effort: str | None = None,
) -> Agent[AgentDeps, str]:
    model = build_model(settings, runtime)
    if model is None:
        raise RuntimeError("LLM_MODEL is not configured")
    model_settings = _model_settings(
        settings,
        runtime,
        reasoning_effort=reasoning_effort,
    )
    agent: Agent[AgentDeps, str] = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=SYSTEM_PROMPT
        + employee_prompt(employee)
        + delegation_prompt(employee, delegates)
        + page_context_prompt(page_context),
        output_type=str,
        # pydantic-ai 默认 1；放宽到 3 次，工具参数错时多给模型几次自我纠正机会
        retries=3,
        model_settings=model_settings,
    )
    attach_tools(agent, allow_delegation=bool(delegates))
    if skills:
        attach_skills(agent, skills)
    return agent
