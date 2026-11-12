from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionIn(BaseModel):
    ticket: str


class ProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    enabled: bool | None = None


class ModelIn(BaseModel):
    provider_id: int
    model_name: str
    display_name: str | None = None
    supports_tools: bool = True
    disable_thinking: bool = False
    reasoning_effort: Literal["default", "low", "medium", "high"] = "default"
    context_window: int = Field(200000, ge=200000, le=1_000_000)
    input_price_per_m: float = Field(0.0, ge=0)
    output_price_per_m: float = Field(0.0, ge=0)
    is_default: bool = False
    enabled: bool = True
    extra_json: dict[str, Any] | None = None


class LimitsIn(BaseModel):
    rate_per_minute: int = Field(ge=0, le=10000)
    daily_requests: int = Field(ge=0, le=1_000_000)
    daily_tokens: int = Field(ge=0, le=10_000_000_000)
    daily_cost: float = Field(ge=0, le=1_000_000)


class AgentLimitsIn(BaseModel):
    # 0 = 不限制；正整数 = 单次请求工具调用上限
    max_tool_calls: int = Field(ge=0)
    # 单次工具返回行数上限（正整数，上限受 Superset SQL_MAX_ROW 约束）
    max_rows: int | None = Field(default=None, ge=1)


class LogSettingsIn(BaseModel):
    retention_days: int = Field(ge=1, le=365)


class RoleEmployeesIn(BaseModel):
    employee_ids: list[int] = Field(default_factory=list)


class UserAIAccessIn(BaseModel):
    enabled: bool


class KnowledgeSettingsIn(BaseModel):
    user_max_entries: int = Field(ge=0, le=100000)
    auto_max_entries: int = Field(ge=0, le=100000)
    auto_ttl_days: int = Field(ge=0, le=3650)
    trash_retention_days: int = Field(ge=0, le=3650)
    auto_merge_enabled: bool = True


class SkillCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    instruction: str = Field(min_length=1, max_length=20_000)
    enabled: bool = True


class SkillUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    instruction: str | None = Field(None, min_length=1, max_length=20_000)
    enabled: bool | None = None


class ModelUpdate(BaseModel):
    provider_id: int | None = None
    model_name: str | None = None
    display_name: str | None = None
    supports_tools: bool | None = None
    disable_thinking: bool | None = None
    reasoning_effort: Literal["default", "low", "medium", "high"] | None = None
    context_window: int | None = Field(None, ge=200000, le=1_000_000)
    input_price_per_m: float | None = Field(None, ge=0)
    output_price_per_m: float | None = Field(None, ge=0)
    is_default: bool | None = None
    enabled: bool | None = None
    extra_json: dict[str, Any] | None = None


class EmployeeIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    nickname: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=128)
    avatar: str = Field(default="", max_length=256)
    intro: str = Field(default="", max_length=2000)
    greeting: str = Field(default="", max_length=2000)
    persona: str = Field(default="", max_length=8000)
    model_id: int | None = None
    model_ids: list[int] | None = None
    can_delegate: bool = False
    delegate_employee_ids: list[int] | None = None
    skill_ids: list[int] = Field(default_factory=list)
    tools: list[str] | None = None
    users: list[str] | None = None
    roles: list[str] | None = None
    enabled: bool = True


class EmployeeUpdateIn(BaseModel):
    nickname: str | None = Field(None, min_length=1, max_length=64)
    title: str | None = Field(None, max_length=128)
    avatar: str | None = Field(None, max_length=256)
    intro: str | None = Field(None, max_length=2000)
    greeting: str | None = Field(None, max_length=2000)
    persona: str | None = Field(None, max_length=8000)
    model_id: int | None = None
    model_ids: list[int] | None = None
    can_delegate: bool | None = None
    delegate_employee_ids: list[int] | None = None
    skill_ids: list[int] | None = None
    tools: list[str] | None = None
    users: list[str] | None = None
    roles: list[str] | None = None
    enabled: bool | None = None


class EmployeeKnowledgeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
