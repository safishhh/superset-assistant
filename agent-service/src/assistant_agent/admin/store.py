from __future__ import annotations

import json
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import case, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from .crypto import SecretBox, key_hint
from .db import (
    AdminAudit,
    AdminDB,
    AppSetting,
    Conversation,
    Employee,
    EmployeeKnowledge,
    Knowledge,
    Message,
    Model,
    Provider,
    RetentionArchive,
    Skill,
    ToolCall,
    TurnFeedback,
    UsageDaily,
    UsedTicket,
    UserAIAccess,
    WriteAction,
    utcnow,
)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        # 存的是裸 UTC，补 Z 让前端按 UTC 解析再转本地，否则会被当本地时间早 8 小时。
        return value.isoformat() + ("Z" if value.tzinfo is None else "")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>[\s\S]*$", re.IGNORECASE)
_THINK_LEAD_RE = re.compile(r"^[\s\S]*?</think>", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """去掉模型内联的思考片段（MiniCPM 会把思考拼在正文里）。"""
    value = _THINK_BLOCK_RE.sub("", text or "")
    value = _THINK_OPEN_RE.sub("", value)
    value = _THINK_LEAD_RE.sub("", value)
    return value.strip()


_FILENAME_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _export_filename(title: str, anchor: Any, ext: str) -> str:
    """导出文件名：会话标题 + 最后活动日期。"""
    base = _FILENAME_UNSAFE_RE.sub("_", str(title or "").strip()).strip(" ._")
    base = base[:60].strip() or "会话"
    day = ""
    if anchor:
        try:
            day = datetime.fromisoformat(str(anchor)).strftime("%Y-%m-%d")
        except ValueError:
            day = str(anchor)[:10]
    return f"{base}-{day or utcnow().strftime('%Y-%m-%d')}.{ext}"


def _selection_text(selection: Any) -> str:
    if not isinstance(selection, list):
        return ""
    labels: list[str] = []
    for block in selection:
        if not isinstance(block, dict):
            continue
        kind = "图表" if block.get("kind") == "chart" else "区块"
        title = str(block.get("title") or "未命名").strip()
        labels.append(f"{kind} · {title}")
    return "、".join(labels)


REASONING_EFFORTS = ("default", "low", "medium", "high")


def _clean_context_window(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 200000
    for tier in (200_000, 400_000, 600_000, 800_000, 1_000_000):
        if number <= tier:
            return tier
    return 1_000_000


def _clean_reasoning_effort(value: Any) -> str:
    effort = str(value or "default").strip().lower()
    return effort if effort in REASONING_EFFORTS else "default"


def _clean_role_names(value: Any, *, keep_none: bool = False) -> Any:
    """规范化员工可见角色列表；None 表示不按角色限制。"""
    if value is None:
        return None if keep_none else []
    seen: set[str] = set()
    names: list[str] = []
    for item in value:
        name = str(item or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name[:128])
    return _jsonable(names)


def _clean_user_names(value: Any, *, keep_none: bool = False) -> Any:
    """规范化员工可见用户列表；None 表示不限制（全员可见）。"""
    if value is None:
        return None if keep_none else []
    seen: set[str] = set()
    names: list[str] = []
    for item in value:
        name = str(item or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name[:64])
        if len(names) >= 500:
            break
    return _jsonable(names)


def _clean_model_ids(value: Any) -> Any:
    """员工可用模型列表；None/空列表都表示不限制（全部启用模型）。"""
    if value is None:
        return None
    seen: set[int] = set()
    ids: list[int] = []
    for item in value:
        try:
            model_id = int(item)
        except (TypeError, ValueError):
            continue
        if model_id <= 0 or model_id in seen:
            continue
        seen.add(model_id)
        ids.append(model_id)
    return _jsonable(ids) if ids else None


def employee_allows(
    employee: dict[str, Any], username: str, roles: list[str] | None
) -> bool:
    """Admin 始终可用；users/roles 都为 None 是全员，否则两者任一命中即可。"""
    if "Admin" in (roles or []):
        return True
    allowed_users = employee.get("users")
    allowed_roles = employee.get("roles")
    if allowed_users is None and allowed_roles is None:
        return True
    if allowed_users is not None and str(username or "").lower() in {
        str(item).lower() for item in allowed_users
    }:
        return True
    if allowed_roles is not None:
        granted = {str(item).lower() for item in allowed_roles}
        if any(str(role).lower() in granted for role in roles or []):
            return True
    return False


class KnowledgeQuotaError(ValueError):
    """知识库条数超限；API 层映射为 409 让用户去清理。"""


# 知识库治理参数：全部用户一致，管理员不豁免；Admin 后台「设置」页可改，热生效。
KNOWLEDGE_SETTINGS_DEFAULTS: dict[str, Any] = {
    "user_max_entries": 200,     # N：每人「手动」生效条目上限，超限拒绝写入
    "auto_max_entries": 500,     # M：每人「自动沉淀」上限，超限 LRU 进回收站
    "auto_ttl_days": 90,         # 自动条目长期零命中则进回收站；0 = 不过期
    "trash_retention_days": 30,  # 回收站保留期，到期归档并物理删除；0 = 不清理
    "auto_merge_enabled": True,  # 自动沉淀是否归并近义标题
}


@dataclass
class RuntimeModel:
    id: int | None
    provider_name: str
    model_name: str
    base_url: str
    api_key: str
    disable_thinking: bool
    reasoning_effort: str
    input_price_per_m: float
    output_price_per_m: float
    # 上下文档位（token），带默认值必须放在必填字段之后
    context_window: int = 200000


class AdminStore:
    def __init__(self, db: AdminDB, secret_box: SecretBox) -> None:
        self.db = db
        self.secret_box = secret_box

    # ---------- providers / models ----------

    @staticmethod
    def _provider_dict(provider: Provider) -> dict[str, Any]:
        return {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "has_api_key": bool(provider.api_key_encrypted),
            "api_key_hint": provider.api_key_hint,
            "enabled": provider.enabled,
            "created_by": provider.created_by,
            "created_at": _iso(provider.created_at),
            "updated_at": _iso(provider.updated_at),
        }

    @staticmethod
    def _model_dict(model: Model, provider_name: str = "") -> dict[str, Any]:
        return {
            "id": model.id,
            "provider_id": model.provider_id,
            "provider_name": provider_name,
            "model_name": model.model_name,
            "display_name": model.display_name,
            "supports_tools": model.supports_tools,
            "disable_thinking": model.disable_thinking,
            "reasoning_effort": model.reasoning_effort or "default",
            "context_window": model.context_window or 200000,
            "input_price_per_m": model.input_price_per_m,
            "output_price_per_m": model.output_price_per_m,
            "is_default": model.is_default,
            "enabled": model.enabled,
            "extra_json": model.extra_json,
            "created_at": _iso(model.created_at),
            "updated_at": _iso(model.updated_at),
        }

    def seed_default_provider(self, settings) -> None:
        with self.db.session() as session:
            if session.scalar(select(func.count()).select_from(Provider)):
                return
            if not settings.llm_model or not settings.llm_base_url:
                return
            provider = Provider(
                name="default",
                base_url=settings.llm_base_url,
                api_key_encrypted=(
                    self.secret_box.encrypt(settings.llm_api_key)
                    if settings.llm_api_key
                    else ""
                ),
                api_key_hint=key_hint(settings.llm_api_key or ""),
                created_by="system",
            )
            session.add(provider)
            session.flush()
            session.add(
                Model(
                    provider_id=provider.id,
                    model_name=settings.llm_model,
                    display_name=settings.llm_model,
                    disable_thinking=settings.llm_disable_thinking,
                    is_default=True,
                )
            )

    def list_providers(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            providers = session.scalars(
                select(Provider).order_by(Provider.id)
            ).all()
            return [self._provider_dict(provider) for provider in providers]

    def create_provider(
        self, data: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        key = (data.get("api_key") or "").strip()
        provider = Provider(
            name=str(data.get("name") or "").strip(),
            base_url=str(data.get("base_url") or "").strip().rstrip("/"),
            api_key_encrypted=self.secret_box.encrypt(key) if key else "",
            api_key_hint=key_hint(key),
            enabled=bool(data.get("enabled", True)),
            created_by=actor,
        )
        if not provider.name or not provider.base_url:
            raise ValueError("name and base_url are required")
        with self.db.session() as session:
            session.add(provider)
            session.flush()
            result = self._provider_dict(provider)
            self._audit(
                session,
                actor,
                "provider.create",
                "provider",
                str(provider.id),
                None,
                result,
            )
            return result

    def update_provider(
        self, provider_id: int, data: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        with self.db.session() as session:
            provider = session.get(Provider, provider_id)
            if provider is None:
                raise LookupError("provider not found")
            before = self._provider_dict(provider)
            if "name" in data:
                provider.name = str(data["name"]).strip()
            if "base_url" in data:
                provider.base_url = str(data["base_url"]).strip().rstrip("/")
            if "enabled" in data:
                provider.enabled = bool(data["enabled"])
            if data.get("clear_api_key"):
                provider.api_key_encrypted = ""
                provider.api_key_hint = ""
            elif (data.get("api_key") or "").strip():
                key = str(data["api_key"]).strip()
                provider.api_key_encrypted = self.secret_box.encrypt(key)
                provider.api_key_hint = key_hint(key)
            provider.updated_at = utcnow()
            session.flush()
            after = self._provider_dict(provider)
            self._audit(
                session,
                actor,
                "provider.update",
                "provider",
                str(provider.id),
                before,
                after,
            )
            return after

    def delete_provider(self, provider_id: int, actor: str) -> None:
        with self.db.session() as session:
            provider = session.get(Provider, provider_id)
            if provider is None:
                raise LookupError("provider not found")
            model_count = session.scalar(
                select(func.count())
                .select_from(Model)
                .where(Model.provider_id == provider_id)
            )
            if model_count:
                raise ValueError("delete its models first")
            before = self._provider_dict(provider)
            session.delete(provider)
            self._audit(
                session,
                actor,
                "provider.delete",
                "provider",
                str(provider_id),
                before,
                None,
            )

    def list_models(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(
                select(Model, Provider.name)
                .join(Provider, Provider.id == Model.provider_id)
                .order_by(Model.id)
            ).all()
            return [self._model_dict(model, name) for model, name in rows]

    def list_enabled_models(self) -> list[dict[str, Any]]:
        """聊天端可选的模型：只返回启用中的模型和 Provider，不含密钥/地址。"""
        with self.db.session() as session:
            rows = session.execute(
                select(Model, Provider.name)
                .join(Provider, Provider.id == Model.provider_id)
                .where(Model.enabled.is_(True), Provider.enabled.is_(True))
                .order_by(Model.is_default.desc(), Model.id.asc())
            ).all()
            return [
                {
                    "id": model.id,
                    "display_name": model.display_name or model.model_name,
                    "model_name": model.model_name,
                    "provider_name": provider_name,
                    "is_default": bool(model.is_default),
                    "supports_tools": bool(model.supports_tools),
                }
                for model, provider_name in rows
            ]

    def create_model(self, data: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.db.session() as session:
            provider = session.get(Provider, int(data.get("provider_id", 0)))
            if provider is None:
                raise LookupError("provider not found")
            model = Model(
                provider_id=provider.id,
                model_name=str(data.get("model_name") or "").strip(),
                display_name=str(
                    data.get("display_name") or data.get("model_name") or ""
                ).strip(),
                supports_tools=bool(data.get("supports_tools", True)),
                disable_thinking=bool(data.get("disable_thinking", False)),
                reasoning_effort=_clean_reasoning_effort(
                    data.get("reasoning_effort")
                ),
                context_window=_clean_context_window(data.get("context_window")),
                input_price_per_m=float(data.get("input_price_per_m") or 0),
                output_price_per_m=float(data.get("output_price_per_m") or 0),
                is_default=bool(data.get("is_default", False)),
                enabled=bool(data.get("enabled", True)),
                extra_json=data.get("extra_json"),
            )
            if not model.model_name:
                raise ValueError("model_name is required")
            if model.is_default:
                self._clear_default(session)
            session.add(model)
            session.flush()
            result = self._model_dict(model, provider.name)
            self._audit(
                session,
                actor,
                "model.create",
                "model",
                str(model.id),
                None,
                result,
            )
            return result

    def update_model(
        self, model_id: int, data: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        with self.db.session() as session:
            model = session.get(Model, model_id)
            if model is None:
                raise LookupError("model not found")
            provider = session.get(Provider, model.provider_id)
            before = self._model_dict(model, provider.name if provider else "")
            if "provider_id" in data:
                provider = session.get(Provider, int(data["provider_id"]))
                if provider is None:
                    raise LookupError("provider not found")
                model.provider_id = provider.id
            for key in (
                "model_name",
                "display_name",
            ):
                if key in data:
                    setattr(model, key, str(data[key]).strip())
            for key in ("supports_tools", "disable_thinking", "enabled"):
                if key in data:
                    setattr(model, key, bool(data[key]))
            if "reasoning_effort" in data:
                model.reasoning_effort = _clean_reasoning_effort(
                    data["reasoning_effort"]
                )
            if "context_window" in data:
                model.context_window = _clean_context_window(data["context_window"])
            for key in ("input_price_per_m", "output_price_per_m"):
                if key in data:
                    setattr(model, key, float(data[key] or 0))
            if "extra_json" in data:
                model.extra_json = data["extra_json"]
            if data.get("is_default"):
                self._clear_default(session, exclude_id=model.id)
                model.is_default = True
            model.updated_at = utcnow()
            session.flush()
            provider = session.get(Provider, model.provider_id)
            after = self._model_dict(model, provider.name if provider else "")
            self._audit(
                session,
                actor,
                "model.update",
                "model",
                str(model.id),
                before,
                after,
            )
            return after

    def set_default_model(self, model_id: int, actor: str) -> dict[str, Any]:
        return self.update_model(model_id, {"is_default": True}, actor)

    def delete_model(self, model_id: int, actor: str) -> None:
        with self.db.session() as session:
            model = session.get(Model, model_id)
            if model is None:
                raise LookupError("model not found")
            provider = session.get(Provider, model.provider_id)
            before = self._model_dict(model, provider.name if provider else "")
            session.delete(model)
            self._audit(
                session,
                actor,
                "model.delete",
                "model",
                str(model_id),
                before,
                None,
            )

    @staticmethod
    def _clear_default(session, exclude_id: int | None = None) -> None:
        query = select(Model).where(Model.is_default.is_(True))
        if exclude_id is not None:
            query = query.where(Model.id != exclude_id)
        for model in session.scalars(query).all():
            model.is_default = False

    def get_runtime_model(self, model_id: int | None = None) -> RuntimeModel | None:
        with self.db.session() as session:
            stmt = (
                select(Model, Provider)
                .join(Provider, Provider.id == Model.provider_id)
                .where(Model.enabled.is_(True), Provider.enabled.is_(True))
                .order_by(Model.is_default.desc(), Model.id.asc())
                .limit(1)
            )
            if model_id is not None:
                stmt = (
                    select(Model, Provider)
                    .join(Provider, Provider.id == Model.provider_id)
                    .where(
                        Model.id == model_id,
                        Model.enabled.is_(True),
                        Provider.enabled.is_(True),
                    )
                    .limit(1)
                )
            row = session.execute(stmt).first()
            if row is None:
                return None
            model, provider = row
            api_key = (
                self.secret_box.decrypt(provider.api_key_encrypted)
                if provider.api_key_encrypted
                else ""
            )
            return RuntimeModel(
                id=model.id,
                provider_name=provider.name,
                model_name=model.model_name,
                base_url=provider.base_url,
                api_key=api_key,
                disable_thinking=model.disable_thinking,
                reasoning_effort=model.reasoning_effort or "default",
                context_window=model.context_window or 200000,
                input_price_per_m=model.input_price_per_m,
                output_price_per_m=model.output_price_per_m,
            )

    def seed_employees(self) -> None:
        """首次启动时按产品文档写入 6 个示例 AI 员工（已有数据则跳过）。"""
        with self.db.session() as session:
            if session.scalar(select(func.count()).select_from(Employee)):
                return
        presets = [
            {
                "username": "atlas",
                "nickname": "Atlas",
                "title": "团队领导",
                "avatar": "🧑‍✈️",
                "intro": "我会优先亲自分析并处理请求，必要时再协调最合适的 AI 员工高效完成任务。",
                "greeting": "你好，我是 Atlas。告诉我你的需求，我会优先尝试直接处理，必要时再协调合适的 AI 专家并推动结果落地。",
                "persona": "你是团队领导型助手：先判断问题类型，能直接答就答；需要专业分工时说明该找哪位 AI 员工（dex 数据整理 / ellis 报表 / lexi 翻译 / vera 研究 / viz 洞察），并给出你已完成的判断。",
                "can_delegate": True,
                "tools": [
                    "list_datasets", "get_dataset_info", "query_dataset",
                    "list_dashboards", "get_dashboard_info", "list_charts", "get_chart_info",
                    "generate_chart", "add_chart_to_existing_dashboard", "list_queries",
                ],
            },
            {
                "username": "dex",
                "nickname": "Dex",
                "title": "数据整理专家",
                "avatar": "📊",
                "intro": "擅长梳理数据集、字段与指标口径，产出结构清晰的取数结果。",
                "greeting": "我是 Dex，负责数据整理与口径梳理，告诉我你要看的指标和时间范围。",
                "persona": "你是数据整理专家：先确认数据集、已保存指标与维度，再给结论；表格优先、口径写清。",
                "tools": [
                    "list_datasets", "get_dataset_info", "query_dataset",
                    "get_table", "list_metrics", "get_compatible_dimensions",
                    "get_compatible_metrics", "list_databases", "get_database_info",
                ],
            },
            {
                "username": "ellis",
                "nickname": "Ellis",
                "title": "电子邮件专家",
                "avatar": "✉️",
                "intro": "负责告警、订阅与报告类事项的查询与说明。",
                "greeting": "我是 Ellis，可以帮你查看告警与报告计划。",
                "persona": "你是邮件与报告专家：围绕 alerts / reports 提供查询与说明，不编造发送状态。",
                "tools": ["list_reports", "get_report_info"],
            },
            {
                "username": "lexi",
                "nickname": "Lexi",
                "title": "翻译助理",
                "avatar": "🌐",
                "intro": "负责中英文互译与文案润色，不接触业务数据。",
                "greeting": "我是 Lexi，把要翻译或润色的内容发给我就好。",
                "persona": "你是翻译助理：只做语言转换与润色，不查询数据库；被要求取数时说明这不在你的工具范围内。",
                "tools": [],
            },
            {
                "username": "vera",
                "nickname": "Vera",
                "title": "研究分析师",
                "avatar": "🔬",
                "intro": "擅长围绕指标做环比、贡献度与结构效应的系统分析。",
                "greeting": "我是 Vera，给我指标和时间范围，我来做对比与归因。",
                "persona": "你是研究分析师：环比/同比、维度贡献、结构效应必须调用对应分析工具，不心算。",
                "tools": [
                    "list_datasets", "get_dataset_info", "query_dataset",
                    "list_dashboards", "get_dashboard_info", "list_charts", "list_queries",
                ],
            },
            {
                "username": "viz",
                "nickname": "Viz",
                "title": "洞察分析师",
                "avatar": "🔭",
                "intro": "专注于把结果可视化，并维护图表与看板的呈现。",
                "greeting": "我是 Viz，帮你看图、改图、把结论讲清楚。",
                "persona": "你是可视化与洞察专家：优先使用图表类工具（预览、图表数据、图表 SQL），落库改动必须走 propose_write。",
                "tools": [
                    "list_charts", "get_chart_info", "get_chart_data", "get_chart_preview",
                    "get_chart_sql", "get_chart_type_schema", "list_dashboards",
                    "get_dashboard_info", "get_dashboard_layout", "get_dashboard_datasets",
                    "generate_explore_link",
                ],
            },
        ]
        for preset in presets:
            self.create_employee(actor="system", values=preset)


    def seed_skills(self) -> None:
        """首次启动写入 4 个示例技能（已有数据则跳过）。"""
        with self.db.session() as session:
            if session.scalar(select(func.count()).select_from(Skill)):
                return
        presets = [
            {
                "name": "data_discovery",
                "title": "数据发现",
                "description": "发现并定位工作区里的数据集、图表与看板：用户问『有哪些数据/找某个数据集/这个指标在哪/有哪些看板图表』时使用。",
                "instruction": "\n".join(
                    [
                        "目标：帮用户找到相关的数据集、图表、看板，并给出可直接使用的 ID / 名称 / 入口。",
                        "1. 数据集发现优先用 search_metadata（支持中文口径词与字段备注，一次返回数据集目录+字段+已保存指标）。不要用中文词去 list_datasets 的 search（只匹配表名/schema 等结构字段，几乎必 0 命中）。",
                        "2. 需要某数据集完整字段时用 mcp_call(\"get_dataset_info\", {\"request\":{\"identifier\":数据集数字ID或UUID}})；identifier 不能传表名。",
                        "3. 查看板/图表清单用 mcp_call 的 list_dashboards / list_charts（{\"request\":{\"page\":1,\"page_size\":20}}）；看单个看板结构用 get_dashboard_info。",
                        "4. 输出：列出命中对象（名称+ID+关键字段/指标）并说明用途；用户实际想取数时接着用 query_dataset，不要停在“我先看看”。",
                        "5. 可见性由当前用户权限决定，查不到就如实说看不到，不编造对象。",
                    ]
                ),
            },
            {
                "name": "analysis_and_chart_creation",
                "title": "分析和图表制作",
                "description": "用自然语言取数、做分析并生成/修改图表：用户问具体数字、要出图、建图改图加看板时使用。",
                "instruction": "\n".join(
                    [
                        "目标：把业务问题变成数据结果与图表。",
                        "1. 取数用 query_dataset（只接受已保存指标名+维度列名，不接受 SUM(x) 表达式）；值过滤用 filters、排序 order_by+order_desc、非主时间列用 time_column。",
                        "2. 图表类型用 chart_type：趋势/走势=line，比较/排名=bar，占比/构成(非负)=pie，不确定不传；多指标量级差远时拆单指标小图。",
                        "3. 归因/预测交给固定工具：period_compare / dimension_contribution / structure_effect / trend_forecast，不心算。",
                        "4. 真正建图/改图/加看板/新增原生筛选器必须 propose_write 出确认卡（create_chart / update_chart / add_chart_to_dashboard / create_chart_and_add_to_dashboard / add_native_filter 等），不直接落库、不声称已执行；mcp_call 的 generate_chart/update_chart 只是预览。",
                        "5. 数字必须来自本轮工具结果；回答写清数据集/指标/维度/时间区间口径。",
                    ]
                ),
            },
            {
                "name": "insight_generation",
                "title": "洞察力的生成/形成洞察力",
                "description": "主动发现数据里的趋势、规律与异常：用户问『有什么有趣/异常的、为什么变、未来会怎样』时使用。",
                "instruction": "\n".join(
                    [
                        "目标：给出有数据支撑的洞察，而不是泛泛而谈。",
                        "1. 变化归因：period_compare（环比/同比）、dimension_contribution（哪个维度成员拉动，dimensions 数组可多列交叉）、structure_effect（比率型指标拆结构/效率/交互）。",
                        "2. 趋势与预测：trend_forecast（未来 N 天），必须转述 backtest（模型 vs 朴素/季节朴素基线谁准）、interval 宽度与 assumptions；backtest 输给朴素法就说只作粗略参考。",
                        "3. 解读统计口径：significant=false 说“仍在日常波动范围内”；concentration/offsetting 有值要写进结论；总变化近 0 时贡献率失真要转述 warning。",
                        "4. 异常/离群：先用 query_dataset 取明细或按维度聚合，定位到具体成员/日期再解释，不凭空猜。",
                        "5. 结论一句话先行，再给关键数字与口径；所有数字来自本轮工具，没调工具就不写“贡献最大/预测”。",
                    ]
                ),
            },
            {
                "name": "sql_generation_and_execution",
                "title": "SQL 语句的生成与执行",
                "description": "按用户自身 SQL Lab 权限写并执行 SQL，或生成预填 SQL Lab 链接：用户明确要写 SQL/跑 SQL/在 SQL Lab 里细化时使用。",
                "instruction": "\n".join(
                    [
                        "目标：把分析需求翻译成 SQL 并执行，或交给 SQL Lab 让用户细化。",
                        "1. 执行用 run_sql；是否可用由用户自身 SQL Lab 权限决定，被 Superset 拒绝就如实说明，改用 query_dataset，不绕过不编造。",
                        "2. 只有 run_sql 调用成功才展示 SQL，且原样展示返回的 SQL；本地只拦多语句，只读由宿主+账号保证，不写 DDL/DML。",
                        "3. 想让用户自己审查/细化时，用 mcp_call 的 open_sql_lab_with_context 生成预填 SQL Lab 链接。",
                        "4. 写 SQL 前先用 search_metadata / get_dataset_info 确认真实表名与字段，不猜列名。",
                        "5. 结果受当前用户 RBAC/RLS 约束；行数被截断要说明。",
                    ]
                ),
            },
        ]
        for preset in presets:
            self.create_skill(actor="system", **preset)


    def migrate_employee_tool_catalog(self, extra_tools: tuple[str, ...]) -> int:
        """一次性把旧版不受限的助手工具补进已有员工白名单。

        旧版里 mcp_search/mcp_call/知识库工具对所有人开放，加入细粒度
        开关后要保留既有员工的原有能力，避免升级后静默失效。
        """
        with self.db.session() as session:
            if session.get(AppSetting, "employee_tool_catalog_v1") is not None:
                return 0
            changed = 0
            for row in session.scalars(select(Employee)).all():
                # None = 不限制；[] = 明确“一个都不给”，都不迁移
                if row.tools is None or not row.tools:
                    continue
                tools = [str(item) for item in (row.tools or [])]
                missing = [name for name in extra_tools if name not in tools]
                if missing:
                    row.tools = _jsonable([*tools, *missing])
                    changed += 1
            session.add(
                AppSetting(
                    key="employee_tool_catalog_v1",
                    value_json=_jsonable({"done": True}),
                    updated_by="system",
                )
            )
            session.flush()
            return changed

    async def test_provider(self, provider_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            provider = session.get(Provider, provider_id)
            if provider is None:
                raise LookupError("provider not found")
            model = session.scalar(
                select(Model)
                .where(Model.provider_id == provider_id)
                .order_by(Model.is_default.desc(), Model.id.asc())
            )
            base_url = provider.base_url.rstrip("/")
            api_key = (
                self.secret_box.decrypt(provider.api_key_encrypted)
                if provider.api_key_encrypted
                else ""
            )
            model_name = model.model_name if model else ""
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{base_url}/models", headers=headers)
                if response.status_code < 400:
                    return {
                        "ok": True,
                        "status": response.status_code,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "message": "models endpoint reachable",
                    }
                if model_name:
                    response = await client.post(
                        f"{base_url}/chat/completions",
                        headers={**headers, "Content-Type": "application/json"},
                        json={
                            "model": model_name,
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 1,
                        },
                    )
                return {
                    "ok": response.status_code < 400,
                    "status": response.status_code,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "message": "ok" if response.status_code < 400 else response.text[:300],
                }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "status": 0,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "message": str(exc),
            }

    # ---------- conversations / audit / usage ----------

    def ensure_conversation(
        self,
        conversation_id: str,
        username: str,
        title: str,
        model_name: str,
        employee_id: int | None = None,
    ) -> None:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                conversation = Conversation(
                    id=conversation_id,
                    username=username,
                    title=title[:500],
                    model_name=model_name,
                    employee_id=employee_id,
                )
                session.add(conversation)
                session.flush()
            else:
                if not conversation.title and title:
                    conversation.title = title[:500]
                if model_name:
                    conversation.model_name = model_name
                if employee_id is not None:
                    conversation.employee_id = employee_id

    def log_tool(
        self,
        *,
        conversation_id: str,
        run_id: str,
        username: str,
        model_name: str,
        sequence: int,
        tool_name: str,
        args: Any,
        result: Any,
        duration_ms: int,
        status: str,
        error: str = "",
    ) -> None:
        args_json = _jsonable(args)
        result_json = _jsonable(result)
        sql_text = ""
        row_count = 0
        if isinstance(args_json, dict):
            sql_text = str(
                args_json.get("sql")
                or (args_json.get("request") or {}).get("sql")
                or ""
            )
        if isinstance(result_json, dict):
            sql_text = str(result_json.get("sql") or sql_text)
            row_count = int(result_json.get("row_count") or 0)
            if not row_count and isinstance(result_json.get("rows"), list):
                row_count = len(result_json["rows"])
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                conversation = Conversation(
                    id=conversation_id,
                    username=username,
                    title="",
                    model_name=model_name,
                )
                session.add(conversation)
                session.flush()
            session.add(
                ToolCall(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    sequence=sequence,
                    tool_name=tool_name,
                    args_json=args_json,
                    result_json=result_json,
                    sql_text=sql_text,
                    row_count=row_count,
                    duration_ms=duration_ms,
                    status=status,
                    error=error[:2000],
                )
            )

    def log_turn(
        self,
        *,
        conversation_id: str,
        run_id: str,
        username: str,
        question: str,
        answer: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        tool_calls: int,
        cost: float,
        status: str = "ok",
        error: str = "",
        employee_id: int | None = None,
        selection: list[dict[str, Any]] | None = None,
        parts: list[dict[str, Any]] | None = None,
        include_question: bool = True,
        count_run: bool = True,
    ) -> int:
        """写入一轮问答，返回该会话累计轮次（首轮=1，用于触发标题生成）。"""
        now = utcnow()
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                conversation = Conversation(
                    id=conversation_id,
                    username=username,
                    title=question[:120],
                    model_name=model_name,
                    started_at=now,
                )
                session.add(conversation)
                session.flush()
            conversation.title = conversation.title or question[:120]
            conversation.last_at = now
            conversation.status = status
            if count_run:
                conversation.run_count += 1
            conversation.input_tokens += input_tokens
            conversation.output_tokens += output_tokens
            conversation.cost += cost
            if model_name:
                conversation.model_name = model_name
            if employee_id is not None:
                conversation.employee_id = employee_id
            rows: list[Message] = []
            if include_question:
                rows.append(
                    Message(
                        conversation_id=conversation_id,
                        run_id=run_id,
                        role="user",
                        content=question,
                        model_name=model_name,
                        status=status,
                        error=error[:2000],
                        selection_json=_jsonable(selection) if selection else None,
                    )
                )
            rows.append(
                Message(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    role="assistant",
                    content=answer,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    status=status,
                    error=error[:2000],
                    parts_json=_jsonable(parts) if parts else None,
                )
            )
            session.add_all(rows)
            self._bump_usage(
                session,
                now.date(),
                username,
                model_name,
                input_tokens,
                output_tokens,
                cost,
                tool_calls,
                status != "ok",
                employee_id if employee_id is not None else 0,
            )
            return int(conversation.run_count)

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        title = (title or "").strip()
        if not title:
            return
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return
            conversation.title = title[:200]
            session.flush()

    @staticmethod
    def _bump_usage(
        session,
        day: date,
        username: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        tool_calls: int,
        is_error: bool,
        employee_id: int = 0,
    ) -> None:
        usage = session.scalar(
            select(UsageDaily).where(
                UsageDaily.day == day,
                UsageDaily.username == username,
                UsageDaily.model_name == model_name,
                UsageDaily.employee_id == employee_id,
            )
        )
        if usage is None:
            usage = UsageDaily(
                day=day,
                username=username,
                model_name=model_name,
                employee_id=employee_id,
            )
            session.add(usage)
            session.flush()
        usage.requests += 1
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.cost += cost
        usage.tool_calls += tool_calls
        usage.errors += 1 if is_error else 0

    # ---- AI 员工（AI 牛马） ----

    def list_employees(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self.db.session() as session:
            stmt = select(Employee)
            if enabled_only:
                stmt = stmt.where(Employee.enabled.is_(True))
            rows = session.scalars(stmt.order_by(Employee.id)).all()
            return [self._employee_dict(row) for row in rows]

    def list_employees_for_user(
        self, username: str, roles: list[str] | None
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in self.list_employees(enabled_only=True)
            if employee_allows(item, username, roles)
        ]

    def list_employees_for_role(
        self, role_name: str, all_roles: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """角色授权页：返回全部员工及该角色是否可用（全员=users/roles 均 None）。"""
        target = role_name.strip().lower()
        items: list[dict[str, Any]] = []
        for item in self.list_employees():
            users = item.get("users")
            roles = item.get("roles")
            if users is None and roles is None:
                available = True
            elif roles is None:
                available = False
            else:
                available = any(str(role).lower() == target for role in roles)
            items.append({**item, "available": available})
        return items

    def set_role_employees(
        self,
        role_name: str,
        employee_ids: list[int],
        *,
        actor: str,
        all_roles: list[str],
    ) -> None:
        """按角色设置员工可用：勾选加入 roles，取消从 roles 移除。

        roles=None（全员）在首次取消某角色时物化为“除该角色外的全部角色”。
        """
        target = role_name.strip()
        target_key = target.lower()
        selected = {int(item) for item in employee_ids}
        names = [str(role).strip() for role in all_roles if str(role).strip()]
        with self.db.session() as session:
            rows = session.scalars(select(Employee).order_by(Employee.id)).all()
            changed: list[dict[str, Any]] = []
            for row in rows:
                current = None if row.roles is None else [str(r) for r in row.roles]
                if current is None:
                    available = row.users is None
                else:
                    available = any(r.lower() == target_key for r in current)
                desired = row.id in selected
                if available == desired:
                    continue
                base = list(names) if current is None else list(current)
                if desired:
                    if not any(r.lower() == target_key for r in base):
                        base.append(target)
                else:
                    base = [r for r in base if r.lower() != target_key]
                before = self._employee_dict(row)
                row.roles = _jsonable(base)
                row.updated_by = actor
                changed.append(
                    {
                        "id": row.id,
                        "before": before.get("roles"),
                        "after": base,
                    }
                )
            session.flush()
            if changed:
                self._audit(
                    session,
                    actor,
                    "employee.role_acl",
                    "role",
                    target,
                    {"employees": [c["before"] for c in changed]},
                    {"employee_ids": sorted(selected), "changes": changed},
                )

    def knowledge_counts_by_user(self) -> dict[str, dict[str, int]]:
        """每个用户生效中/回收站的知识库条数（后台用户目录用）。"""
        with self.db.session() as session:
            rows = session.execute(
                select(
                    Knowledge.username,
                    Knowledge.deleted_key,
                    func.count(),
                ).group_by(Knowledge.username, Knowledge.deleted_key)
            ).all()
        counts: dict[str, dict[str, int]] = {}
        for username, deleted_key, count in rows:
            entry = counts.setdefault(str(username), {"active": 0, "trash": 0})
            if int(deleted_key or 0) == 0:
                entry["active"] += int(count)
            else:
                entry["trash"] += int(count)
        return counts

    def user_ai_enabled(self, username: str) -> bool:
        """未配置的用户默认可用；只有显式关闭的记录才阻止使用助手。"""
        with self.db.session() as session:
            row = session.get(UserAIAccess, username)
            return True if row is None else bool(row.ai_enabled)

    def user_ai_access_map(self) -> dict[str, bool]:
        with self.db.session() as session:
            rows = session.scalars(select(UserAIAccess)).all()
            return {str(row.username): bool(row.ai_enabled) for row in rows}

    def set_user_ai_access(
        self,
        username: str,
        enabled: bool,
        *,
        actor: str,
    ) -> dict[str, Any]:
        username = username.strip()
        if not username:
            raise ValueError("用户名不能为空")
        with self.db.session() as session:
            row = session.get(UserAIAccess, username)
            before = None
            if row is None:
                row = UserAIAccess(
                    username=username,
                    ai_enabled=bool(enabled),
                    updated_by=actor,
                )
                session.add(row)
            else:
                before = {
                    "username": row.username,
                    "ai_enabled": bool(row.ai_enabled),
                    "updated_at": _iso(row.updated_at),
                    "updated_by": row.updated_by,
                }
                row.ai_enabled = bool(enabled)
                row.updated_by = actor
            session.flush()
            after = {
                "username": row.username,
                "ai_enabled": bool(row.ai_enabled),
                "updated_at": _iso(row.updated_at),
                "updated_by": row.updated_by,
            }
            self._audit(
                session,
                actor,
                "user.ai_access",
                "user",
                username,
                before,
                after,
            )
            return after

    def get_employee(self, employee_id: int) -> dict[str, Any] | None:
        with self.db.session() as session:
            row = session.get(Employee, employee_id)
            return self._employee_dict(row) if row is not None else None

    def create_employee(self, *, actor: str, values: dict[str, Any]) -> dict[str, Any]:
        username = str(values.get("username") or "").strip().lower()
        nickname = str(values.get("nickname") or "").strip()
        if not re.fullmatch(r"[a-z0-9_]{1,64}", username):
            raise ValueError("用户名仅允许小写字母/数字/下划线，最长 64")
        if not nickname:
            raise ValueError("昵称不能为空")
        with self.db.session() as session:
            exists = session.scalar(select(Employee).where(Employee.username == username))
            if exists is not None:
                raise LookupError(f"AI 员工 {username} 已存在")
            model_id = int(values["model_id"]) if values.get("model_id") else None
            model_ids = _clean_model_ids(values.get("model_ids"))
            if model_id and model_ids and model_id not in {
                int(item) for item in model_ids
            }:
                raise ValueError("默认模型必须在可用模型列表中")
            row = Employee(
                username=username,
                nickname=nickname[:64],
                title=str(values.get("title") or "")[:128],
                avatar=str(values.get("avatar") or "")[:256],
                intro=str(values.get("intro") or ""),
                greeting=str(values.get("greeting") or ""),
                persona=str(values.get("persona") or ""),
                model_id=model_id,
                model_ids=model_ids,
                can_delegate=bool(values.get("can_delegate", False)),
                delegate_employee_ids=_clean_model_ids(
                    values.get("delegate_employee_ids")
                ),
                skill_ids=_jsonable([int(i) for i in (values.get("skill_ids") or [])]),
                tools=None
                if values.get("tools") is None
                else _jsonable([str(i) for i in values.get("tools") or []]),
                users=_clean_user_names(values.get("users"), keep_none=True),
                roles=_clean_role_names(values.get("roles"), keep_none=True),
                enabled=bool(values.get("enabled", True)),
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            session.flush()
            after = self._employee_dict(row)
            self._audit(session, actor, "employee.create", "employee", str(row.id), None, after)
            return after

    def update_employee(
        self,
        employee_id: int,
        *,
        actor: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        fields = (
            "nickname",
            "title",
            "avatar",
            "intro",
            "greeting",
            "persona",
            "model_id",
            "model_ids",
            "can_delegate",
            "delegate_employee_ids",
            "skill_ids",
            "tools",
            "users",
            "roles",
            "enabled",
        )
        with self.db.session() as session:
            row = session.get(Employee, employee_id)
            if row is None:
                raise LookupError("AI 员工不存在")
            before = self._employee_dict(row)
            for key in fields:
                if key not in updates:
                    continue
                value = updates[key]
                if key == "nickname":
                    nickname = str(value or "").strip()
                    if not nickname:
                        raise ValueError("昵称不能为空")
                    row.nickname = nickname[:64]
                elif key == "title":
                    row.title = str(value or "")[:128]
                elif key == "avatar":
                    row.avatar = str(value or "")[:256]
                elif key in ("intro", "greeting", "persona"):
                    setattr(row, key, str(value or ""))
                elif key == "model_id":
                    row.model_id = int(value) if value else None
                elif key == "model_ids":
                    row.model_ids = _clean_model_ids(value)
                elif key == "can_delegate":
                    row.can_delegate = bool(value)
                elif key == "delegate_employee_ids":
                    row.delegate_employee_ids = _clean_model_ids(value)
                elif key == "skill_ids":
                    row.skill_ids = _jsonable([int(i) for i in value or []])
                elif key == "tools":
                    row.tools = (
                        None
                        if value is None
                        else _jsonable([str(i) for i in value or []])
                    )
                elif key == "users":
                    row.users = _clean_user_names(value, keep_none=True)
                elif key == "roles":
                    row.roles = _clean_role_names(value, keep_none=True)
                elif key == "enabled":
                    row.enabled = bool(value)
            if (
                row.model_id
                and row.model_ids
                and int(row.model_id) not in {int(item) for item in row.model_ids}
            ):
                raise ValueError("默认模型必须在可用模型列表中")
            row.updated_by = actor
            session.flush()
            after = self._employee_dict(row)
            self._audit(
                session, actor, "employee.update", "employee", row.username, before, after
            )
            return after

    def delete_employee(self, employee_id: int, *, actor: str) -> None:
        with self.db.session() as session:
            row = session.get(Employee, employee_id)
            if row is None:
                raise LookupError("AI 员工不存在")
            before = self._employee_dict(row)
            session.query(EmployeeKnowledge).filter(
                EmployeeKnowledge.employee_id == employee_id
            ).delete()
            session.delete(row)
            session.flush()
            self._audit(
                session, actor, "employee.delete", "employee", before["username"], before, None
            )

    @staticmethod
    def _employee_dict(row: Employee) -> dict[str, Any]:
        return {
            "id": row.id,
            "username": row.username,
            "nickname": row.nickname,
            "title": row.title,
            "avatar": row.avatar,
            "intro": row.intro,
            "greeting": row.greeting,
            "persona": row.persona,
            "model_id": row.model_id,
            "model_ids": (
                None if row.model_ids is None else list(row.model_ids)
            ),
            "can_delegate": bool(row.can_delegate),
            "delegate_employee_ids": (
                None
                if row.delegate_employee_ids is None
                else list(row.delegate_employee_ids)
            ),
            "skill_ids": list(row.skill_ids or []),
            "tools": None if row.tools is None else list(row.tools),
            "users": None if row.users is None else [str(item) for item in row.users],
            "roles": None if row.roles is None else [str(item) for item in row.roles],
            "enabled": row.enabled,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "updated_by": row.updated_by,
        }

    # ---- 员工知识库 ----

    def list_employee_knowledge(self, employee_id: int) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(EmployeeKnowledge)
                .where(EmployeeKnowledge.employee_id == employee_id)
                .order_by(EmployeeKnowledge.updated_at.desc())
            ).all()
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "content": row.content,
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows
            ]

    def upsert_employee_knowledge(
        self, employee_id: int, title: str, content: str
    ) -> dict[str, Any]:
        title = (title or "").strip()[:200]
        content = (content or "").strip()[:8000]
        if not title or not content:
            raise ValueError("title 与 content 不能为空")
        with self.db.session() as session:
            row = session.scalar(
                select(EmployeeKnowledge).where(
                    EmployeeKnowledge.employee_id == employee_id,
                    EmployeeKnowledge.title == title,
                )
            )
            if row is None:
                row = EmployeeKnowledge(
                    employee_id=employee_id, title=title, content=content
                )
                session.add(row)
            else:
                row.content = content
            session.flush()
            return {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "updated_at": _iso(row.updated_at),
            }

    def delete_employee_knowledge(self, employee_id: int, knowledge_id: int) -> None:
        with self.db.session() as session:
            row = session.get(EmployeeKnowledge, knowledge_id)
            if row is None or row.employee_id != employee_id:
                raise LookupError("知识条目不存在")
            session.delete(row)
            session.flush()

    def search_employee_knowledge(
        self, employee_id: int, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        words = [
            w for w in re.split(r"[\s,，。;；]+", (query or "").strip()) if len(w) >= 2
        ]
        if not words:
            return []
        conditions = or_(
            *[EmployeeKnowledge.content.ilike(f"%{w}%") for w in words],
            *[EmployeeKnowledge.title.ilike(f"%{w}%") for w in words],
        )
        with self.db.session() as session:
            rows = session.scalars(
                select(EmployeeKnowledge)
                .where(
                    EmployeeKnowledge.employee_id == employee_id,
                    conditions,
                )
                .order_by(EmployeeKnowledge.updated_at.desc())
                .limit(max(1, min(limit, 20)))
            ).all()
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "content": row.content,
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows
            ]

    @staticmethod
    def _conversation_dict(conversation: Conversation) -> dict[str, Any]:
        return {
            "id": conversation.id,
            "username": conversation.username,
            "title": conversation.title,
            "model_name": conversation.model_name,
            "started_at": _iso(conversation.started_at),
            "last_at": _iso(conversation.last_at),
            "status": conversation.status,
            "run_count": conversation.run_count,
            "input_tokens": conversation.input_tokens,
            "output_tokens": conversation.output_tokens,
            "cost": round(conversation.cost, 6),
            "deleted": conversation.deleted_at is not None,
            "deleted_at": _iso(conversation.deleted_at),
            "employee_id": conversation.employee_id,
        }

    @staticmethod
    def _model_provider_map(session) -> dict[str, str]:
        providers: dict[str, set[str]] = {}
        for model_name, provider_name in session.execute(
            select(Model.model_name, Provider.name).join(
                Provider, Provider.id == Model.provider_id
            )
        ).all():
            if model_name and provider_name:
                providers.setdefault(str(model_name), set()).add(
                    str(provider_name)
                )
        return {
            name: " / ".join(sorted(values))
            for name, values in providers.items()
        }

    @staticmethod
    def _provider_for(provider_map: dict[str, str], model_name: Any) -> str | None:
        if not model_name:
            return None
        name = str(model_name)
        return provider_map.get(name) or provider_map.get(name.casefold())

    def filter_options(self) -> dict[str, Any]:
        with self.db.session() as session:
            values = {
                "users": {
                    *session.scalars(select(Conversation.username).distinct()).all(),
                    *session.scalars(select(UsageDaily.username).distinct()).all(),
                    *session.scalars(select(Knowledge.username).distinct()).all(),
                },
                "models": {
                    *session.scalars(select(Conversation.model_name).distinct()).all(),
                    *session.scalars(select(UsageDaily.model_name).distinct()).all(),
                },
            }
            employees = [
                {"id": item.id, "name": item.nickname or item.username}
                for item in session.scalars(select(Employee).order_by(Employee.id)).all()
            ]
            base_providers = self._model_provider_map(session)
            model_providers = {
                str(name): provider
                for name in values["models"]
                if name
                for provider in [self._provider_for(base_providers, name)]
                if provider
            }
        return {
            "users": sorted(
                (value for value in values["users"] if value),
                key=str.casefold,
            ),
            "models": sorted(
                (value for value in values["models"] if value),
                key=str.casefold,
            ),
            "model_providers": model_providers,
            "employees": employees,
        }

    def list_conversations(
        self,
        *,
        username: str | None = None,
        model_name: str | None = None,
        search: str | None = None,
        status: str | None = None,
        employee_id: int | None = None,
        start: date | None = None,
        end: date | None = None,
        sort_by: str = "last_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
        include_deleted: bool = True,
    ) -> dict[str, Any]:
        filters = []
        if username:
            filters.append(Conversation.username == username)
        if model_name:
            filters.append(Conversation.model_name == model_name)
        if search:
            filters.append(
                or_(
                    Conversation.title.contains(search),
                    Conversation.id.contains(search),
                )
            )
        if status:
            filters.append(Conversation.status == status)
        if employee_id is not None:
            filters.append(
                Conversation.employee_id == (int(employee_id) or None)
                if int(employee_id)
                else Conversation.employee_id.is_(None)
            )
        if not include_deleted:
            filters.append(Conversation.deleted_at.is_(None))
        if start:
            filters.append(Conversation.last_at >= datetime.combine(start, datetime.min.time()))
        if end:
            filters.append(
                Conversation.last_at
                < datetime.combine(end + timedelta(days=1), datetime.min.time())
            )
        sort_columns = {
            "title": Conversation.title,
            "username": Conversation.username,
            "model_name": Conversation.model_name,
            "run_count": Conversation.run_count,
            "tokens": Conversation.input_tokens + Conversation.output_tokens,
            "cost": Conversation.cost,
            "status": Conversation.status,
            "started_at": Conversation.started_at,
            "last_at": Conversation.last_at,
        }
        order_column = sort_columns.get(sort_by, Conversation.last_at)
        order = order_column.asc() if sort_order == "asc" else order_column.desc()
        with self.db.session() as session:
            base = select(Conversation).where(*filters)
            total = session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            rows = session.scalars(
                base.order_by(order, Conversation.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            employee_names = {
                item.id: (item.nickname or item.username)
                for item in session.scalars(select(Employee)).all()
            }
            items = []
            for row in rows:
                item = self._conversation_dict(row)
                item["employee_name"] = (
                    employee_names.get(row.employee_id, "AI 员工")
                    if row.employee_id
                    else "默认助手"
                )
                items.append(item)
            return {
                "total": total or 0,
                "page": page,
                "page_size": page_size,
                "items": items,
            }

    def conversation_owner(self, conversation_id: str) -> str | None:
        """会话归属人；不存在返回 None（用于写入前校验，避免串写他人会话）。"""
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            return conversation.username if conversation is not None else None

    def get_conversation(
        self, conversation_id: str, *, include_deleted: bool = True
    ) -> dict[str, Any] | None:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            if not include_deleted and conversation.deleted_at is not None:
                return None
            employee_name = "默认助手"
            if conversation.employee_id:
                employee = session.get(Employee, conversation.employee_id)
                if employee is not None:
                    employee_name = employee.nickname or employee.username
            messages = session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id)
            ).all()
            tools = session.scalars(
                select(ToolCall)
                .where(ToolCall.conversation_id == conversation_id)
                .order_by(ToolCall.id)
            ).all()
            return {
                **self._conversation_dict(conversation),
                "employee_name": employee_name,
                "messages": [
                    {
                        "id": item.id,
                        "run_id": item.run_id,
                        "role": item.role,
                        "content": item.content,
                        "model_name": item.model_name,
                        "input_tokens": item.input_tokens,
                        "output_tokens": item.output_tokens,
                        "latency_ms": item.latency_ms,
                        "status": item.status,
                        "error": item.error,
                        "selection": item.selection_json,
                        "parts": item.parts_json,
                        "created_at": _iso(item.created_at),
                    }
                    for item in messages
                ],
                "tool_calls": [
                    {
                        "id": item.id,
                        "run_id": item.run_id,
                        "sequence": item.sequence,
                        "tool_name": item.tool_name,
                        "args_json": item.args_json,
                        "result_json": item.result_json,
                        "sql_text": item.sql_text,
                        "row_count": item.row_count,
                        "duration_ms": item.duration_ms,
                        "status": item.status,
                        "error": item.error,
                        "created_at": _iso(item.created_at),
                    }
                    for item in tools
                ],
            }

    def soft_delete_conversation(
        self, username: str, conversation_id: str
    ) -> bool:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if (
                conversation is None
                or conversation.username != username
                or conversation.deleted_at is not None
            ):
                return False
            conversation.deleted_at = utcnow()
            return True

    def export_markdown(
        self, username: str, conversation_id: str
    ) -> tuple[str, str] | None:
        """导出对话内容：按轮次只保留问答与选区，不含工具调用与思考。"""
        detail = self.get_conversation(conversation_id, include_deleted=False)
        if detail is None or detail["username"] != username:
            return None
        turns: list[dict[str, Any]] = []
        by_run: dict[str, dict[str, Any]] = {}
        for message in detail["messages"]:
            run_id = message["run_id"] or f"message-{message['id']}"
            turn = by_run.get(run_id)
            if turn is None:
                turn = {
                    "question": "",
                    "answer": "",
                    "error": "",
                    "selection": None,
                }
                by_run[run_id] = turn
                turns.append(turn)
            if message["role"] == "user":
                turn["question"] = message["content"] or ""
                turn["selection"] = message.get("selection")
            else:
                turn["answer"] = _strip_thinking(message["content"] or "")
                turn["error"] = message.get("error") or ""
        lines = [
            f"# {detail['title'] or detail['id']}",
            "",
            (
                f"> 用户：{detail['username']} · 模型：{detail['model_name'] or '—'}"
                f" · 轮次：{detail['run_count']}"
                f" · Token：{detail['input_tokens'] + detail['output_tokens']}"
            ),
            (
                f"> 会话：{detail['id']} · 开始：{detail['started_at']}"
                f" · 最后活动：{detail['last_at']}"
            ),
            "",
        ]
        for turn in turns:
            selection = _selection_text(turn["selection"])
            if selection:
                lines.extend([f"> 选中：{selection}", ""])
            if turn["question"]:
                lines.extend(["## 用户", "", turn["question"], ""])
            lines.extend(
                [
                    "## 助手",
                    "",
                    turn["answer"] or turn["error"] or "—",
                    "",
                ]
            )
        return "\n".join(lines), _export_filename(
            detail["title"] or detail["id"], detail["last_at"], "md"
        )

    @staticmethod
    def _limit_dict(row: AppSetting | None, defaults: dict[str, Any]) -> dict[str, Any]:
        values = dict(defaults)
        if row and isinstance(row.value_json, dict):
            values.update(row.value_json)
        values["updated_at"] = _iso(row.updated_at) if row else None
        values["updated_by"] = row.updated_by if row else ""
        return values

    def get_limit_config(self, defaults: dict[str, Any]) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(AppSetting, "user_limits")
            if row is None:
                row = AppSetting(
                    key="user_limits",
                    value_json=_jsonable(defaults),
                    updated_by="system",
                )
                session.add(row)
                session.flush()
            return self._limit_dict(row, defaults)

    def save_limit_config(
        self,
        values: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        defaults = {
            "rate_per_minute": 20,
            "daily_requests": 200,
            "daily_tokens": 1_000_000,
            "daily_cost": 5.0,
        }
        with self.db.session() as session:
            row = session.get(AppSetting, "user_limits")
            before = self._limit_dict(row, defaults) if row else None
            if row is None:
                row = AppSetting(
                    key="user_limits",
                    value_json=_jsonable(values),
                    updated_by=actor,
                )
                session.add(row)
            else:
                current = row.value_json if isinstance(row.value_json, dict) else {}
                row.value_json = _jsonable({**current, **values})
                row.updated_by = actor
            session.flush()
            after = self._limit_dict(row, defaults)
            self._audit(
                session,
                actor,
                "limits.update",
                "assistant",
                "user_limits",
                before,
                after,
            )
            return after

    def get_agent_limits(self, defaults: dict[str, Any]) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(AppSetting, "agent_limits")
            if row is None:
                row = AppSetting(
                    key="agent_limits",
                    value_json=_jsonable(defaults),
                    updated_by="system",
                )
                session.add(row)
                session.flush()
            return self._limit_dict(row, defaults)

    def save_agent_limits(
        self,
        values: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        defaults = {"max_tool_calls": 16}
        with self.db.session() as session:
            row = session.get(AppSetting, "agent_limits")
            before = self._limit_dict(row, defaults) if row else None
            if row is None:
                row = AppSetting(
                    key="agent_limits",
                    value_json=_jsonable(values),
                    updated_by=actor,
                )
                session.add(row)
            else:
                current = row.value_json if isinstance(row.value_json, dict) else {}
                row.value_json = _jsonable({**current, **values})
                row.updated_by = actor
            session.flush()
            after = self._limit_dict(row, defaults)
            self._audit(
                session,
                actor,
                "agent_limits.update",
                "assistant",
                "agent_limits",
                before,
                after,
            )
            return after

    def get_log_settings(self, default_days: int = 14) -> dict[str, Any]:
        defaults = {"retention_days": max(1, min(int(default_days or 14), 365))}
        with self.db.session() as session:
            row = session.get(AppSetting, "log_settings")
            if row is None:
                row = AppSetting(
                    key="log_settings",
                    value_json=_jsonable(defaults),
                    updated_by="system",
                )
                session.add(row)
                session.flush()
            return self._limit_dict(row, defaults)

    def save_log_settings(
        self,
        values: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        days = max(1, min(int(values.get("retention_days") or 14), 365))
        defaults = {"retention_days": 14}
        with self.db.session() as session:
            row = session.get(AppSetting, "log_settings")
            before = self._limit_dict(row, defaults) if row else None
            if row is None:
                row = AppSetting(
                    key="log_settings",
                    value_json=_jsonable({"retention_days": days}),
                    updated_by=actor,
                )
                session.add(row)
            else:
                row.value_json = _jsonable({"retention_days": days})
                row.updated_by = actor
            session.flush()
            after = self._limit_dict(row, defaults)
            self._audit(
                session,
                actor,
                "log_settings.update",
                "assistant",
                "log_settings",
                before,
                after,
            )
            return after

    def list_skills(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self.db.session() as session:
            stmt = select(Skill)
            if enabled_only:
                stmt = stmt.where(Skill.enabled.is_(True))
            rows = session.scalars(stmt.order_by(Skill.name)).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "title": row.title,
                    "description": row.description,
                    "instruction": row.instruction,
                    "enabled": row.enabled,
                    "created_by": row.created_by,
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                    "updated_by": row.updated_by,
                }
                for row in rows
            ]

    def create_skill(
        self,
        *,
        actor: str,
        name: str,
        title: str,
        description: str,
        instruction: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9_]{1,64}", name or ""):
            raise ValueError("name 仅允许小写字母/数字/下划线，最长 64")
        if not (title or "").strip() or not (instruction or "").strip():
            raise ValueError("title 与 instruction 不能为空")
        with self.db.session() as session:
            exists = session.scalar(select(Skill).where(Skill.name == name))
            if exists is not None:
                raise LookupError(f"技能 {name} 已存在")
            row = Skill(
                name=name,
                title=title.strip()[:128],
                description=(description or "").strip(),
                instruction=instruction,
                enabled=enabled,
                created_by=actor,
                updated_by=actor,
            )
            session.add(row)
            session.flush()
            after = self._skill_dict(row)
            self._audit(session, actor, "skill.create", "skill", name, None, after)
            return after

    def update_skill(
        self,
        skill_id: int,
        *,
        actor: str,
        title: str | None = None,
        description: str | None = None,
        instruction: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(Skill, skill_id)
            if row is None:
                raise LookupError("技能不存在")
            before = self._skill_dict(row)
            if title is not None:
                if not title.strip():
                    raise ValueError("title 不能为空")
                row.title = title.strip()[:128]
            if description is not None:
                row.description = description.strip()
            if instruction is not None:
                if not instruction.strip():
                    raise ValueError("instruction 不能为空")
                row.instruction = instruction
            if enabled is not None:
                row.enabled = enabled
            row.updated_by = actor
            session.flush()
            after = self._skill_dict(row)
            self._audit(session, actor, "skill.update", "skill", row.name, before, after)
            return after

    def delete_skill(self, skill_id: int, *, actor: str) -> None:
        with self.db.session() as session:
            row = session.get(Skill, skill_id)
            if row is None:
                raise LookupError("技能不存在")
            before = self._skill_dict(row)
            session.delete(row)
            session.flush()
            self._audit(session, actor, "skill.delete", "skill", row.name, before, None)

    @staticmethod
    def _skill_dict(row: Skill) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "title": row.title,
            "description": row.description,
            "instruction": row.instruction,
            "enabled": row.enabled,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "updated_by": row.updated_by,
        }

    # ---- 知识库（按用户隔离；manual=用户手填，auto=自动沉淀） ----

    def list_knowledge(
        self, username: str, *, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        with self.db.session() as session:
            stmt = select(Knowledge).where(Knowledge.username == username)
            stmt = (
                stmt.where(Knowledge.deleted_key == 0)
                if not include_deleted
                else stmt.where(Knowledge.deleted_key != 0)
            )
            order = (
                Knowledge.updated_at.desc()
                if not include_deleted
                else Knowledge.deleted_at.desc()
            )
            rows = session.scalars(stmt.order_by(order)).all()
            return [self._knowledge_dict(row) for row in rows]

    def get_knowledge(self, username: str, knowledge_id: int) -> dict[str, Any]:
        """取本人知识条目的完整正文（越权视为不存在）。"""
        with self.db.session() as session:
            row = session.get(Knowledge, knowledge_id)
            if row is None or row.username != username:
                raise LookupError("知识条目不存在")
            return self._knowledge_dict(row)

    def get_employee_knowledge(self, knowledge_id: int) -> dict[str, Any]:
        """取 AI 牛马知识条目（归属哪个牛马由调用方校验）。"""
        with self.db.session() as session:
            row = session.get(EmployeeKnowledge, knowledge_id)
            if row is None:
                raise LookupError("知识条目不存在")
            return {
                "id": row.id,
                "employee_id": row.employee_id,
                "title": row.title,
                "content": row.content,
                "content_chars": len(row.content or ""),
                "truncated": False,
                "source": "employee",
                "updated_at": _iso(row.updated_at),
            }

    def knowledge_directory(self, username: str, limit: int = 60) -> list[dict[str, Any]]:
        """给模型看的目录：只有标题和元信息，不带正文，避免整库灌进上下文。"""
        with self.db.session() as session:
            rows = session.scalars(
                select(Knowledge)
                .where(Knowledge.username == username, Knowledge.deleted_key == 0)
                .order_by(Knowledge.hits.desc(), Knowledge.updated_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [self._knowledge_dict(row, content="") for row in rows]

    def search_knowledge(
        self,
        username: str,
        query: str,
        limit: int = 5,
        max_chars: int = 600,
    ) -> dict[str, Any]:
        """检索生效中的条目；命中即计一次使用，正文按预算截断。"""
        words = [
            word
            for word in re.split(r"[\s,，。;；、/]+", (query or "").strip())
            if len(word) >= 2
        ][:6]
        if not words:
            return {"items": [], "total_matched": 0}
        limit = max(1, min(limit, 10))
        with self.db.session() as session:
            rows = self._knowledge_match(session, username, words, limit)
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(Knowledge)
                    .where(
                        Knowledge.username == username,
                        Knowledge.deleted_key == 0,
                        self._knowledge_predicate(words),
                    )
                )
                or 0
            )
            now = utcnow()
            for row in rows:
                row.hits = int(row.hits or 0) + 1
                row.last_used_at = now
            items = []
            for row in rows:
                body = row.content or ""
                items.append(
                    self._knowledge_dict(
                        row,
                        content=body[:max_chars],
                        truncated=len(body) > max_chars,
                    )
                )
            return {"items": items, "total_matched": total}

    @staticmethod
    def _knowledge_predicate(words: list[str]) -> Any:
        return or_(
            *[
                Knowledge.content.ilike(f"%{word}%")
                for word in words
            ]
            + [Knowledge.title.ilike(f"%{word}%") for word in words]
        )

    def _knowledge_match(
        self, session: Any, username: str, words: list[str], limit: int
    ) -> list[Knowledge]:
        """MySQL 走 ngram 全文索引（相关度排序），其他情况退回 LIKE。"""
        base = select(Knowledge).where(
            Knowledge.username == username, Knowledge.deleted_key == 0
        )
        if self.db.engine.dialect.name == "mysql":
            scored = "MATCH(title, content) AGAINST(:ftq IN NATURAL LANGUAGE MODE)"
            try:
                rows = session.scalars(
                    base.where(
                        text(scored).bindparams(ftq=" ".join(words))
                    )
                    .order_by(
                        text(scored.replace(":ftq", ":ftq2")).bindparams(ftq2=" ".join(words)),
                        Knowledge.hits.desc(),
                        Knowledge.updated_at.desc(),
                    )
                    .limit(limit)
                ).all()
                return list(rows)
            except Exception:  # noqa: BLE001 - 全文索引缺失时退回 LIKE
                session.rollback()
        rows = session.scalars(
            base.where(self._knowledge_predicate(words))
            .order_by(Knowledge.hits.desc(), Knowledge.updated_at.desc())
            .limit(limit)
        ).all()
        return list(rows)

    def upsert_knowledge(
        self,
        username: str,
        title: str,
        content: str,
        source: str = "auto",
    ) -> dict[str, Any]:
        title = (title or "").strip()
        content = (content or "").strip()
        if not title[:200] or not content:
            raise ValueError("title 与 content 不能为空")
        title = title[:200]
        if len(content) > 8000:
            content = content[:8000]
        source = "manual" if str(source) == "manual" else "auto"
        settings = self.get_knowledge_settings()
        with self.db.session() as session:
            row = session.scalar(
                select(Knowledge).where(
                    Knowledge.username == username,
                    Knowledge.title == title,
                    Knowledge.deleted_key == 0,
                )
            )
            if row is not None and row.source == "manual" and source == "auto":
                # 自动沉淀不得改写用户手填内容，另起一条带后缀的标题
                title = self._free_auto_title(session, username, title)
                row = None
            if row is None and source == "auto" and settings["auto_merge_enabled"]:
                row = self._find_merge_target(session, username, title, content)
            if row is None:
                self._enforce_knowledge_quota(session, username, source, settings)
                row = Knowledge(
                    username=username,
                    title=title,
                    content=content,
                    source=source,
                    deleted_key=0,
                )
                session.add(row)
            else:
                row.content = content
                # 用户手填过的条目保持 manual；其余跟随本次写入方
                if row.source != "manual":
                    row.source = source
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("已存在同名条目，请换个标题") from exc
            return self._knowledge_dict(row)

    def _free_auto_title(self, session: Any, username: str, title: str) -> str:
        for suffix in ("（AI 记录）", *(f"（AI 记录 {i}）" for i in range(2, 6))):
            candidate = f"{title[:190]}{suffix}"
            exists = session.scalar(
                select(Knowledge).where(
                    Knowledge.username == username,
                    Knowledge.title == candidate,
                    Knowledge.deleted_key == 0,
                )
            )
            if exists is None:
                return candidate
        return f"{title[:150]}（AI 记录 {int(time.time())}）"

    def _find_merge_target(
        self, session: Any, username: str, title: str, content: str
    ) -> Knowledge | None:
        """自动沉淀归并：同标题或关键词高度重叠的旧条目直接覆盖，避免线性膨胀。"""
        candidates = session.scalars(
            select(Knowledge)
            .where(
                Knowledge.username == username,
                Knowledge.deleted_key == 0,
                Knowledge.source == "auto",
            )
            .order_by(Knowledge.updated_at.desc())
            .limit(200)
        ).all()
        tokens = self._title_tokens(title)
        best: Knowledge | None = None
        best_score = 0.0
        for row in candidates:
            ratio = self._token_overlap(tokens, self._title_tokens(row.title))
            if ratio >= 0.6 and ratio > best_score:
                best, best_score = row, ratio
        return best

    @staticmethod
    def _title_tokens(title: str) -> set[str]:
        parts = re.split(r"[\s,，。;；、/（）()\-_]+", (title or "").strip())
        return {part.lower() for part in parts if len(part) >= 2}

    @staticmethod
    def _token_overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, min(len(left), len(right)))

    def _enforce_knowledge_quota(
        self,
        session: Any,
        username: str,
        source: str,
        settings: dict[str, Any],
    ) -> None:
        key = "user_max_entries" if source == "manual" else "auto_max_entries"
        limit = int(settings.get(key) or 0)
        if limit <= 0:
            return
        used = int(
            session.scalar(
                select(func.count())
                .select_from(Knowledge)
                .where(
                    Knowledge.username == username,
                    Knowledge.deleted_key == 0,
                    Knowledge.source == source,
                )
            )
            or 0
        )
        if used < limit:
            return
        if source == "manual":
            raise KnowledgeQuotaError(
                f"知识库手动条目已达上限 {limit} 条，请先在知识库中清理后再保存"
            )
        # 自动侧不拒绝写入：把最久未命中的条目挪进回收站腾位
        stale = session.scalars(
            select(Knowledge)
            .where(
                Knowledge.username == username,
                Knowledge.deleted_key == 0,
                Knowledge.source == "auto",
            )
            .order_by(Knowledge.hits.asc(), Knowledge.updated_at.asc())
            .limit(used - limit + 1)
        ).all()
        now = utcnow()
        for row in stale:
            row.deleted_at = now
            row.deleted_key = row.id
        session.flush()
        self._audit(
            session,
            "system",
            "knowledge.auto_prune",
            "knowledge",
            username,
            None,
            {"pruned": len(stale), "limit": limit},
        )

    def admin_list_knowledge(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        username: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        filters = [Knowledge.deleted_key == 0]
        if username:
            filters.append(Knowledge.username == username)
        if search:
            keyword = f"%{search.strip()}%"
            filters.append(
                or_(Knowledge.title.ilike(keyword), Knowledge.content.ilike(keyword))
            )
        sort_columns = {
            "username": Knowledge.username,
            "title": Knowledge.title,
            "created_at": Knowledge.created_at,
            "updated_at": Knowledge.updated_at,
        }
        order_column = sort_columns.get(sort_by, Knowledge.updated_at)
        order = order_column.asc() if sort_order == "asc" else order_column.desc()
        with self.db.session() as session:
            total = session.scalar(
                select(func.count()).select_from(Knowledge).where(*filters)
            )
            rows = session.scalars(
                select(Knowledge)
                .where(*filters)
                .order_by(order, Knowledge.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "total": int(total or 0),
                "page": page,
                "page_size": page_size,
                "items": [
                    {
                        **self._knowledge_dict(row),
                        "username": row.username,
                    }
                    for row in rows
                ],
            }

    def admin_delete_knowledge(self, knowledge_id: int, *, actor: str) -> dict[str, Any]:
        """管理员代删：同样进回收站（软删），保留改前快照与审计。"""
        with self.db.session() as session:
            row = session.get(Knowledge, knowledge_id)
            if row is None or row.deleted_key != 0:
                raise LookupError("知识条目不存在")
            before = {**self._knowledge_dict(row), "username": row.username}
            row.deleted_at = utcnow()
            row.deleted_key = row.id
            session.flush()
            self._audit(
                session,
                actor,
                "knowledge.delete",
                "knowledge",
                str(knowledge_id),
                before,
                None,
            )
            return before

    def update_knowledge(
        self, username: str, knowledge_id: int, title: str, content: str
    ) -> dict[str, Any]:
        title = (title or "").strip()[:200]
        content = (content or "").strip()[:8000]
        if not title or not content:
            raise ValueError("title 与 content 不能为空")
        with self.db.session() as session:
            row = session.get(Knowledge, knowledge_id)
            if row is None or row.username != username or row.deleted_key != 0:
                raise LookupError("知识条目不存在")
            row.title = title
            row.content = content
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("已存在同名条目，请换个标题") from exc
            return self._knowledge_dict(row)

    def delete_knowledge(self, username: str, knowledge_id: int) -> dict[str, Any]:
        """软删除：用户端与模型检索都不再可见，可在回收站恢复。"""
        with self.db.session() as session:
            row = session.get(Knowledge, knowledge_id)
            if row is None or row.username != username or row.deleted_key != 0:
                raise LookupError("知识条目不存在")
            before = self._knowledge_dict(row)
            row.deleted_at = utcnow()
            row.deleted_key = row.id
            session.flush()
            return before

    def restore_knowledge(self, username: str, knowledge_id: int) -> dict[str, Any]:
        settings = self.get_knowledge_settings()
        with self.db.session() as session:
            row = session.get(Knowledge, knowledge_id)
            if row is None or row.username != username or row.deleted_key == 0:
                raise LookupError("回收站里没有这条条目")
            clash = session.scalar(
                select(Knowledge).where(
                    Knowledge.username == username,
                    Knowledge.title == row.title,
                    Knowledge.deleted_key == 0,
                )
            )
            if clash is not None:
                raise ValueError("已有同名生效条目，请先处理冲突再恢复")
            self._enforce_knowledge_quota(
                session, username, row.source or "auto", settings
            )
            row.deleted_at = None
            row.deleted_key = 0
            session.flush()
            return self._knowledge_dict(row)

    def purge_knowledge(self, username: str, knowledge_id: int) -> None:
        """彻底删除：仅允许对回收站里的条目执行，避免误删生效内容。"""
        with self.db.session() as session:
            row = session.get(Knowledge, knowledge_id)
            if row is None or row.username != username or row.deleted_key == 0:
                raise LookupError("回收站里没有这条条目")
            session.delete(row)
            session.flush()

    def knowledge_usage(self, username: str) -> dict[str, Any]:
        settings = self.get_knowledge_settings()
        with self.db.session() as session:
            def count(source: str) -> int:
                return int(
                    session.scalar(
                        select(func.count())
                        .select_from(Knowledge)
                        .where(
                            Knowledge.username == username,
                            Knowledge.deleted_key == 0,
                            Knowledge.source == source,
                        )
                    )
                    or 0
                )

            trash = int(
                session.scalar(
                    select(func.count())
                    .select_from(Knowledge)
                    .where(
                        Knowledge.username == username,
                        Knowledge.deleted_key != 0,
                    )
                )
                or 0
            )
        return {
            "manual_used": count("manual"),
            "manual_max": int(settings.get("user_max_entries") or 0),
            "auto_used": count("auto"),
            "auto_max": int(settings.get("auto_max_entries") or 0),
            "trash": trash,
        }

    @staticmethod
    def _knowledge_settings_dict(
        row: AppSetting | None,
    ) -> dict[str, Any]:
        values = dict(KNOWLEDGE_SETTINGS_DEFAULTS)
        stored = (
            row.value_json
            if row is not None and isinstance(row.value_json, dict)
            else {}
        )
        for key in values:
            if key in stored:
                values[key] = stored[key]
        return {
            **values,
            "updated_at": _iso(row.updated_at) if row else None,
            "updated_by": row.updated_by if row else "",
        }

    def get_knowledge_settings(self) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(AppSetting, "knowledge_settings")
            if row is None:
                row = AppSetting(
                    key="knowledge_settings",
                    value_json=_jsonable(KNOWLEDGE_SETTINGS_DEFAULTS),
                    updated_by="system",
                )
                session.add(row)
                session.flush()
            return self._knowledge_settings_dict(row)

    def save_knowledge_settings(
        self, values: dict[str, Any], *, actor: str
    ) -> dict[str, Any]:
        clamped: dict[str, Any] = {}
        for key, default in KNOWLEDGE_SETTINGS_DEFAULTS.items():
            if key not in values:
                continue
            raw = values[key]
            if isinstance(default, bool):
                clamped[key] = bool(raw)
            else:
                try:
                    number = int(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} 需要整数") from None
                clamped[key] = max(0, min(number, 100000))
        # 前后值都在同一会话里算，不能再开 get_knowledge_settings（SQLite 会自锁）
        with self.db.session() as session:
            row = session.get(AppSetting, "knowledge_settings")
            before = self._knowledge_settings_dict(row)
            if row is None:
                row = AppSetting(
                    key="knowledge_settings",
                    value_json=_jsonable(clamped),
                    updated_by=actor,
                )
                session.add(row)
            else:
                current = row.value_json if isinstance(row.value_json, dict) else {}
                row.value_json = _jsonable({**current, **clamped})
                row.updated_by = actor
                row.updated_at = utcnow()
            session.flush()
            after = self._knowledge_settings_dict(row)
            self._audit(
                session,
                actor,
                "knowledge_settings.update",
                "assistant",
                "knowledge_settings",
                before,
                after,
            )
            return after

    def prune_knowledge_retention(self) -> dict[str, int]:
        """回收站超期物理清理 + 自动沉淀条目长期未命中归档。"""
        settings = self.get_knowledge_settings()
        now = utcnow()
        result = {"trashed": 0, "purged": 0}
        trash_days = int(settings.get("trash_retention_days") or 0)
        if trash_days > 0:
            cutoff = now - timedelta(days=trash_days)
            with self.db.session() as session:
                rows = session.scalars(
                    select(Knowledge).where(
                        Knowledge.deleted_key != 0,
                        Knowledge.deleted_at.is_not(None),
                        Knowledge.deleted_at < cutoff,
                    )
                ).all()
                for row in rows:
                    session.add(
                        RetentionArchive(
                            kind="knowledge",
                            source_id=str(row.id),
                            username=row.username,
                            original_created_at=row.created_at,
                            payload_json=_jsonable(self._knowledge_dict(row)),
                        )
                    )
                    session.delete(row)
                    result["purged"] += 1
        ttl_days = int(settings.get("auto_ttl_days") or 0)
        if ttl_days > 0:
            cutoff = now - timedelta(days=ttl_days)
            with self.db.session() as session:
                rows = session.scalars(
                    select(Knowledge).where(
                        Knowledge.deleted_key == 0,
                        Knowledge.source == "auto",
                        Knowledge.hits == 0,
                        Knowledge.updated_at < cutoff,
                    )
                ).all()
                for row in rows:
                    row.deleted_at = now
                    row.deleted_key = row.id
                    result["trashed"] += 1
        return result

    @staticmethod
    def _knowledge_dict(
        row: Knowledge, *, content: str | None = None, truncated: bool = False
    ) -> dict[str, Any]:
        body = row.content if content is None else content
        return {
            "id": row.id,
            "title": row.title,
            "content": body,
            "content_chars": len(row.content or ""),
            "truncated": truncated,
            "source": row.source or "auto",
            "hits": int(row.hits or 0),
            "last_used_at": _iso(row.last_used_at),
            "deleted_at": _iso(row.deleted_at),
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def get_feedback(self, username: str, conversation_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(TurnFeedback)
                .where(
                    TurnFeedback.username == username,
                    TurnFeedback.conversation_id == conversation_id,
                )
                .order_by(TurnFeedback.turn_index)
            ).all()
            return [
                {
                    "turn_index": row.turn_index,
                    "rating": row.rating,
                    "comment": row.comment,
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows
            ]

    def upsert_feedback(
        self,
        username: str,
        conversation_id: str,
        turn_index: int,
        rating: str | None,
        comment: str = "",
    ) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id, include_deleted=False)
        if conversation is None or conversation["username"] != username:
            raise LookupError("conversation not found")
        with self.db.session() as session:
            assistant_messages = session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == "assistant",
                )
                .order_by(Message.id)
            ).all()
            if turn_index < 1 or turn_index > len(assistant_messages):
                raise ValueError("turn_index 对应回答不存在")
            row = session.scalar(
                select(TurnFeedback).where(
                    TurnFeedback.username == username,
                    TurnFeedback.conversation_id == conversation_id,
                    TurnFeedback.turn_index == turn_index,
                )
            )
            if rating is None:
                if row is not None:
                    session.delete(row)
                return {
                    "conversation_id": conversation_id,
                    "turn_index": turn_index,
                    "rating": None,
                }
            if row is None:
                row = TurnFeedback(
                    username=username,
                    conversation_id=conversation_id,
                    turn_index=turn_index,
                    rating=rating,
                    comment=comment,
                )
                session.add(row)
            else:
                row.rating = rating
                row.comment = comment
            session.flush()
            return {
                "conversation_id": row.conversation_id,
                "turn_index": row.turn_index,
                "rating": row.rating,
                "comment": row.comment,
                "updated_at": _iso(row.updated_at),
            }

    def feedback_summary(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        filters = []
        if start is not None:
            filters.append(TurnFeedback.created_at >= start)
        if end is not None:
            filters.append(TurnFeedback.created_at < end)
        with self.db.session() as session:
            up, down = session.execute(
                select(
                    func.coalesce(
                        func.sum(case((TurnFeedback.rating == "up", 1), else_=0)),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((TurnFeedback.rating == "down", 1), else_=0)),
                        0,
                    ),
                ).where(*filters)
            ).one()
        up_count = int(up or 0)
        down_count = int(down or 0)
        total = up_count + down_count
        return {
            "up": up_count,
            "down": down_count,
            "total": total,
            "adoption_rate": round(up_count / total, 4) if total else None,
        }

    def list_feedback(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        username: str | None = None,
        rating: str | None = None,
        start: date | None = None,
        end: date | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        filters = []
        if username:
            filters.append(TurnFeedback.username == username)
        if rating:
            filters.append(TurnFeedback.rating == rating)
        # 时间范围按反馈时间（created_at）过滤
        if start:
            filters.append(
                TurnFeedback.created_at
                >= datetime.combine(start, datetime.min.time())
            )
        if end:
            filters.append(
                TurnFeedback.created_at
                < datetime.combine(end + timedelta(days=1), datetime.min.time())
            )
        sort_columns = {
            "created_at": TurnFeedback.created_at,
            "updated_at": TurnFeedback.updated_at,
            "username": TurnFeedback.username,
            "rating": TurnFeedback.rating,
            "turn_index": TurnFeedback.turn_index,
        }
        order_column = sort_columns.get(sort_by, TurnFeedback.created_at)
        order = order_column.asc() if sort_order == "asc" else order_column.desc()
        with self.db.session() as session:
            total = session.scalar(
                select(func.count()).select_from(TurnFeedback).where(*filters)
            )
            rows = session.scalars(
                select(TurnFeedback)
                .where(*filters)
                .order_by(order, TurnFeedback.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            conversation_ids = sorted({row.conversation_id for row in rows})
            titles: dict[str, str] = {}
            started: dict[str, Any] = {}
            last_at: dict[str, Any] = {}
            answers: dict[str, list[str]] = defaultdict(list)
            if conversation_ids:
                for conversation in session.scalars(
                    select(Conversation).where(Conversation.id.in_(conversation_ids))
                ).all():
                    titles[conversation.id] = conversation.title
                    started[conversation.id] = conversation.started_at
                    last_at[conversation.id] = conversation.last_at
                for message in session.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id.in_(conversation_ids),
                        Message.role == "assistant",
                    )
                    .order_by(Message.conversation_id, Message.id)
                ).all():
                    answers[message.conversation_id].append(message.content)
            items = []
            for row in rows:
                conversation_answers = answers.get(row.conversation_id, [])
                answer = (
                    conversation_answers[row.turn_index - 1]
                    if 0 < row.turn_index <= len(conversation_answers)
                    else ""
                )
                items.append(
                    {
                        "id": row.id,
                        "conversation_id": row.conversation_id,
                        "username": row.username,
                        "turn_index": row.turn_index,
                        "rating": row.rating,
                        "comment": row.comment,
                        "conversation_title": titles.get(row.conversation_id, ""),
                        "conversation_started_at": _iso(
                            started.get(row.conversation_id)
                        ),
                        "conversation_last_at": _iso(
                            last_at.get(row.conversation_id)
                        ),
                        "answer_preview": answer[:200],
                        "answer": answer,
                        "created_at": _iso(row.created_at),
                        "updated_at": _iso(row.updated_at),
                    }
                )
            return {
                "total": total or 0,
                "page": page,
                "page_size": page_size,
                "items": items,
            }

    def user_usage_for_day(
        self,
        username: str,
        day: date | None = None,
    ) -> dict[str, Any]:
        target = day or date.today()
        with self.db.session() as session:
            row = session.execute(
                select(
                    func.coalesce(func.sum(UsageDaily.requests), 0),
                    func.coalesce(func.sum(UsageDaily.input_tokens), 0),
                    func.coalesce(func.sum(UsageDaily.output_tokens), 0),
                    func.coalesce(func.sum(UsageDaily.cost), 0),
                ).where(
                    UsageDaily.day == target,
                    UsageDaily.username == username,
                )
            ).one()
        return {
            "day": _iso(target),
            "requests": int(row[0] or 0),
            "tokens": int((row[1] or 0) + (row[2] or 0)),
            "cost": round(float(row[3] or 0), 6),
        }

    def overview(
        self,
        days: int = 7,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, Any]:
        start_day = start or date.today() - timedelta(days=days - 1)
        usage_filters = [UsageDaily.day >= start_day]
        if end:
            usage_filters.append(UsageDaily.day <= end)
        tool_filters = [
            ToolCall.created_at
            >= datetime.combine(start_day, datetime.min.time())
        ]
        if end:
            tool_filters.append(
                ToolCall.created_at
                < datetime.combine(end + timedelta(days=1), datetime.min.time())
            )
        with self.db.session() as session:
            totals = session.execute(
                select(
                    func.coalesce(func.sum(UsageDaily.requests), 0),
                    func.coalesce(func.sum(UsageDaily.input_tokens), 0),
                    func.coalesce(func.sum(UsageDaily.output_tokens), 0),
                    func.coalesce(func.sum(UsageDaily.cost), 0),
                    func.coalesce(func.sum(UsageDaily.tool_calls), 0),
                    func.coalesce(func.sum(UsageDaily.errors), 0),
                ).where(*usage_filters)
            ).one()
            daily = session.execute(
                select(
                    UsageDaily.day,
                    func.sum(UsageDaily.requests),
                    func.sum(UsageDaily.input_tokens + UsageDaily.output_tokens),
                    func.sum(UsageDaily.cost),
                    func.sum(UsageDaily.errors),
                )
                .where(*usage_filters)
                .group_by(UsageDaily.day)
                .order_by(UsageDaily.day)
            ).all()
            top_users = session.execute(
                select(
                    UsageDaily.username,
                    func.sum(UsageDaily.requests),
                    func.sum(UsageDaily.input_tokens + UsageDaily.output_tokens),
                    func.sum(UsageDaily.cost),
                )
                .where(*usage_filters)
                .group_by(UsageDaily.username)
                .order_by(func.sum(UsageDaily.requests).desc())
                .limit(10)
            ).all()
            top_models = session.execute(
                select(
                    UsageDaily.model_name,
                    func.sum(UsageDaily.requests),
                    func.sum(UsageDaily.input_tokens + UsageDaily.output_tokens),
                )
                .where(*usage_filters)
                .group_by(UsageDaily.model_name)
                .order_by(func.sum(UsageDaily.requests).desc())
                .limit(10)
            ).all()
            top_tools = session.execute(
                select(
                    ToolCall.tool_name,
                    func.count(),
                )
                .where(*tool_filters)
                .group_by(ToolCall.tool_name)
                .order_by(func.count().desc())
                .limit(10)
            ).all()
            tool_total, tool_ok = session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(case((ToolCall.status == "ok", 1), else_=0)),
                        0,
                    ),
                ).where(*tool_filters)
            ).one()
            feedback_filters = [
                TurnFeedback.created_at
                >= datetime.combine(start_day, datetime.min.time())
            ]
            if end:
                feedback_filters.append(
                    TurnFeedback.created_at
                    < datetime.combine(
                        end + timedelta(days=1), datetime.min.time()
                    )
                )
            feedback_up, feedback_down = session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case((TurnFeedback.rating == "up", 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case((TurnFeedback.rating == "down", 1), else_=0)
                        ),
                        0,
                    ),
                ).where(*feedback_filters)
            ).one()
            recent = session.scalars(
                select(Conversation)
                .order_by(Conversation.last_at.desc())
                .limit(10)
            ).all()
            tool_total = int(tool_total or 0)
            tool_ok = int(tool_ok or 0)
            feedback_up = int(feedback_up or 0)
            feedback_down = int(feedback_down or 0)
            feedback_total = feedback_up + feedback_down
            return {
                "days": days,
                "start": _iso(start_day),
                "end": _iso(end),
                "totals": {
                    "requests": int(totals[0]),
                    "input_tokens": int(totals[1]),
                    "output_tokens": int(totals[2]),
                    "tokens": int(totals[1] + totals[2]),
                    "cost": round(float(totals[3]), 6),
                    "tool_calls": int(totals[4]),
                    "errors": int(totals[5]),
                },
                "quality": {
                    "tool_calls": tool_total,
                    "tool_ok": tool_ok,
                    "tool_success_rate": (
                        round(tool_ok / tool_total, 4) if tool_total else None
                    ),
                    "feedback_up": feedback_up,
                    "feedback_down": feedback_down,
                    "feedback_total": feedback_total,
                    "feedback_adoption_rate": (
                        round(feedback_up / feedback_total, 4)
                        if feedback_total
                        else None
                    ),
                },
                "daily": [
                    {
                        "day": _iso(row[0]),
                        "requests": int(row[1] or 0),
                        "tokens": int(row[2] or 0),
                        "cost": round(float(row[3] or 0), 6),
                        "errors": int(row[4] or 0),
                    }
                    for row in daily
                ],
                "top_users": [
                    {
                        "username": row[0],
                        "requests": int(row[1] or 0),
                        "tokens": int(row[2] or 0),
                        "cost": round(float(row[3] or 0), 6),
                    }
                    for row in top_users
                ],
                "top_models": [
                    {
                        "model_name": row[0],
                        "requests": int(row[1] or 0),
                        "tokens": int(row[2] or 0),
                    }
                    for row in top_models
                ],
                "top_tools": [
                    {"tool_name": row[0], "calls": int(row[1] or 0)}
                    for row in top_tools
                ],
                "recent_conversations": [
                    self._conversation_dict(row) for row in recent
                ],
            }

    def usage(
        self,
        days: int = 30,
        group_by: str = "day",
        *,
        username: str | None = None,
        model_name: str | None = None,
        employee_id: int | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, Any]:
        start_day = start or date.today() - timedelta(days=days - 1)
        filters = [UsageDaily.day >= start_day]
        if end:
            filters.append(UsageDaily.day <= end)
        if username:
            filters.append(UsageDaily.username == username)
        if model_name:
            filters.append(UsageDaily.model_name == model_name)
        if employee_id is not None:
            filters.append(UsageDaily.employee_id == int(employee_id))
        tokens = func.sum(UsageDaily.input_tokens + UsageDaily.output_tokens)
        with self.db.session() as session:
            employee_names = {
                row.id: (row.nickname or row.username)
                for row in session.scalars(select(Employee)).all()
            }
            provider_map = self._model_provider_map(session)
            if group_by == "detail":
                rows = session.execute(
                    select(
                        UsageDaily.day,
                        UsageDaily.username,
                        UsageDaily.model_name,
                        UsageDaily.employee_id,
                        func.sum(UsageDaily.requests),
                        func.sum(UsageDaily.input_tokens),
                        func.sum(UsageDaily.output_tokens),
                        func.sum(UsageDaily.cost),
                        func.sum(UsageDaily.tool_calls),
                        func.sum(UsageDaily.errors),
                    )
                    .where(*filters)
                    .group_by(
                        UsageDaily.day,
                        UsageDaily.username,
                        UsageDaily.model_name,
                        UsageDaily.employee_id,
                    )
                    .order_by(
                        UsageDaily.day.desc(),
                        UsageDaily.username,
                        UsageDaily.model_name,
                    )
                ).all()
                items = [
                    {
                        "key": f"{_iso(row[0])} · {row[1]} · {row[2]}"
                        f" · {employee_names.get(row[3], '默认助手')}",
                        "day": _iso(row[0]),
                        "username": row[1],
                        "model_name": row[2],
                        "provider_name": self._provider_for(provider_map, row[2]),
                        "employee_id": int(row[3] or 0),
                        "employee_name": employee_names.get(row[3], "默认助手"),
                        "requests": int(row[4] or 0),
                        "input_tokens": int(row[5] or 0),
                        "output_tokens": int(row[6] or 0),
                        "tokens": int((row[5] or 0) + (row[6] or 0)),
                        "cost": round(float(row[7] or 0), 6),
                        "tool_calls": int(row[8] or 0),
                        "errors": int(row[9] or 0),
                    }
                    for row in rows
                ]
            elif group_by == "employee":
                rows = session.execute(
                    select(
                        UsageDaily.employee_id,
                        func.sum(UsageDaily.requests),
                        func.sum(UsageDaily.input_tokens),
                        func.sum(UsageDaily.output_tokens),
                        func.sum(UsageDaily.cost),
                        func.sum(UsageDaily.tool_calls),
                        func.sum(UsageDaily.errors),
                    )
                    .where(*filters)
                    .group_by(UsageDaily.employee_id)
                    .order_by(tokens.desc())
                ).all()
                items = [
                    {
                        "key": employee_names.get(row[0], "默认助手"),
                        "employee_id": int(row[0] or 0),
                        "employee_name": employee_names.get(row[0], "默认助手"),
                        "requests": int(row[1] or 0),
                        "input_tokens": int(row[2] or 0),
                        "output_tokens": int(row[3] or 0),
                        "tokens": int((row[2] or 0) + (row[3] or 0)),
                        "cost": round(float(row[4] or 0), 6),
                        "tool_calls": int(row[5] or 0),
                        "errors": int(row[6] or 0),
                    }
                    for row in rows
                ]
            elif group_by == "user_model":
                rows = session.execute(
                    select(
                        UsageDaily.username,
                        UsageDaily.model_name,
                        func.sum(UsageDaily.requests),
                        func.sum(UsageDaily.input_tokens),
                        func.sum(UsageDaily.output_tokens),
                        func.sum(UsageDaily.cost),
                        func.sum(UsageDaily.tool_calls),
                        func.sum(UsageDaily.errors),
                    )
                    .where(*filters)
                    .group_by(UsageDaily.username, UsageDaily.model_name)
                    .order_by(
                        tokens.desc(),
                        UsageDaily.username,
                        UsageDaily.model_name,
                    )
                ).all()
                items = [
                    {
                        "key": f"{row[0]} · {row[1]}",
                        "username": row[0],
                        "model_name": row[1],
                        "provider_name": self._provider_for(provider_map, row[1]),
                        "requests": int(row[2] or 0),
                        "input_tokens": int(row[3] or 0),
                        "output_tokens": int(row[4] or 0),
                        "tokens": int((row[3] or 0) + (row[4] or 0)),
                        "cost": round(float(row[5] or 0), 6),
                        "tool_calls": int(row[6] or 0),
                        "errors": int(row[7] or 0),
                    }
                    for row in rows
                ]
            else:
                group_column = {
                    "day": UsageDaily.day,
                    "user": UsageDaily.username,
                    "model": UsageDaily.model_name,
                }.get(group_by, UsageDaily.day)
                rows = session.execute(
                    select(
                        group_column,
                        func.sum(UsageDaily.requests),
                        func.sum(UsageDaily.input_tokens),
                        func.sum(UsageDaily.output_tokens),
                        func.sum(UsageDaily.cost),
                        func.sum(UsageDaily.tool_calls),
                        func.sum(UsageDaily.errors),
                    )
                    .where(*filters)
                    .group_by(group_column)
                    .order_by(group_column)
                ).all()
                items = [
                    {
                        "key": _iso(row[0]),
                        "requests": int(row[1] or 0),
                        "input_tokens": int(row[2] or 0),
                        "output_tokens": int(row[3] or 0),
                        "tokens": int((row[2] or 0) + (row[3] or 0)),
                        "cost": round(float(row[4] or 0), 6),
                        "tool_calls": int(row[5] or 0),
                        "errors": int(row[6] or 0),
                    }
                    for row in rows
                ]
                if group_by == "model":
                    for item in items:
                        item["model_name"] = item["key"]
                        item["provider_name"] = self._provider_for(
                            provider_map, item["key"]
                        )
            top_users = session.execute(
                select(
                    UsageDaily.username,
                    func.sum(UsageDaily.requests),
                    tokens,
                    func.sum(UsageDaily.cost),
                )
                .where(*filters)
                .group_by(UsageDaily.username)
                .order_by(tokens.desc(), func.sum(UsageDaily.requests).desc())
                .limit(8)
            ).all()
            top_models = session.execute(
                select(
                    UsageDaily.model_name,
                    func.sum(UsageDaily.requests),
                    tokens,
                    func.sum(UsageDaily.cost),
                )
                .where(*filters)
                .group_by(UsageDaily.model_name)
                .order_by(tokens.desc(), func.sum(UsageDaily.requests).desc())
                .limit(8)
            ).all()
            top_employees = session.execute(
                select(
                    UsageDaily.employee_id,
                    func.sum(UsageDaily.requests),
                    tokens,
                    func.sum(UsageDaily.cost),
                )
                .where(*filters)
                .group_by(UsageDaily.employee_id)
                .order_by(tokens.desc(), func.sum(UsageDaily.requests).desc())
                .limit(8)
            ).all()
            return {
                "days": days,
                "group_by": group_by,
                "username": username,
                "model_name": model_name,
                "employee_id": employee_id,
                "start": _iso(start_day),
                "end": _iso(end),
                "items": items,
                "top_users": [
                    {
                        "username": row[0],
                        "requests": int(row[1] or 0),
                        "tokens": int(row[2] or 0),
                        "cost": round(float(row[3] or 0), 6),
                    }
                    for row in top_users
                ],
                "top_models": [
                    {
                        "model_name": row[0],
                        "provider_name": self._provider_for(provider_map, row[0]),
                        "requests": int(row[1] or 0),
                        "tokens": int(row[2] or 0),
                        "cost": round(float(row[3] or 0), 6),
                    }
                    for row in top_models
                ],
                "top_employees": [
                    {
                        "employee_id": int(row[0] or 0),
                        "employee_name": employee_names.get(row[0], "默认助手"),
                        "requests": int(row[1] or 0),
                        "tokens": int(row[2] or 0),
                        "cost": round(float(row[3] or 0), 6),
                    }
                    for row in top_employees
                ],
            }

    def list_admin_audit(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        filters = []
        if actor:
            filters.append(AdminAudit.actor == actor)
        if action:
            filters.append(AdminAudit.action == action)
        sort_columns = {
            "created_at": AdminAudit.created_at,
            "actor": AdminAudit.actor,
            "action": AdminAudit.action,
            "target_type": AdminAudit.target_type,
            "ip": AdminAudit.ip,
        }
        order_column = sort_columns.get(sort_by, AdminAudit.created_at)
        order = order_column.asc() if sort_order == "asc" else order_column.desc()
        with self.db.session() as session:
            base = select(AdminAudit).where(*filters)
            total = session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            rows = session.scalars(
                base.order_by(order, AdminAudit.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "total": total or 0,
                "page": page,
                "page_size": page_size,
                "items": [
                    {
                        "id": row.id,
                        "actor": row.actor,
                        "action": row.action,
                        "target_type": row.target_type,
                        "target_id": row.target_id,
                        "before_json": row.before_json,
                        "after_json": row.after_json,
                        "ip": row.ip,
                        "user_agent": row.user_agent,
                        "created_at": _iso(row.created_at),
                    }
                    for row in rows
                ],
            }

    def _audit(
        self,
        session,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        before: Any,
        after: Any,
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        session.add(
            AdminAudit(
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_json=_jsonable(before),
                after_json=_jsonable(after),
                ip=ip[:64],
                user_agent=user_agent[:500],
            )
        )

    def consume_ticket(self, jti: str) -> bool:
        try:
            with self.db.session() as session:
                session.add(UsedTicket(jti=jti))
                session.flush()
            return True
        except IntegrityError:
            return False

    def archive_audit_events(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        with self.db.session() as session:
            session.add(
                RetentionArchive(
                    kind="audit_event",
                    source_id="audit.jsonl",
                    payload_json=_jsonable(records),
                )
            )
        return len(records)

    def _write_action_dict(self, row: WriteAction) -> dict[str, Any]:
        return {
            "id": row.id,
            "username": row.username,
            "conversation_id": row.conversation_id,
            "run_id": row.run_id,
            "action_type": row.action_type,
            "risk_level": row.risk_level,
            "status": row.status,
            "summary": row.summary,
            "plan": row.plan_json,
            "snapshot": row.snapshot_json,
            "result": row.result_json,
            "rollback": row.rollback_json,
            "error": row.error,
            "created_at": _iso(row.created_at),
            "expires_at": _iso(row.expires_at),
            "executed_at": _iso(row.executed_at),
            "rolled_back_at": _iso(row.rolled_back_at),
        }

    def create_write_action(
        self,
        *,
        username: str,
        conversation_id: str,
        run_id: str,
        action_type: str,
        risk_level: str,
        summary: str,
        plan: dict[str, Any],
        snapshot: Any,
        expires_at: datetime,
    ) -> dict[str, Any]:
        row = WriteAction(
            id=str(uuid.uuid4()),
            username=username,
            conversation_id=conversation_id,
            run_id=run_id,
            action_type=action_type,
            risk_level=risk_level,
            status="pending",
            summary=summary,
            plan_json=_jsonable(plan),
            snapshot_json=_jsonable(snapshot),
            expires_at=expires_at,
        )
        with self.db.session() as session:
            session.add(row)
            session.flush()
            return self._write_action_dict(row)

    def get_write_action(
        self, action_id: str, username: str | None = None
    ) -> dict[str, Any] | None:
        with self.db.session() as session:
            row = session.get(WriteAction, action_id)
            if row is None or (username is not None and row.username != username):
                return None
            return self._write_action_dict(row)

    def find_pending_write_action(
        self,
        *,
        username: str,
        conversation_id: str,
        action_type: str,
        plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        """同一会话里已有相同待确认方案时复用它，避免模型重复出卡。"""
        target = json.dumps(
            _jsonable(plan), sort_keys=True, ensure_ascii=False
        )
        now = utcnow()
        with self.db.session() as session:
            rows = session.scalars(
                select(WriteAction).where(
                    WriteAction.username == username,
                    WriteAction.conversation_id == conversation_id,
                    WriteAction.action_type == action_type,
                    WriteAction.status == "pending",
                    WriteAction.expires_at > now,
                )
            ).all()
            for row in rows:
                try:
                    current = json.dumps(
                        _jsonable(row.plan_json),
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                except (TypeError, ValueError):
                    continue
                if current == target:
                    return self._write_action_dict(row)
        return None

    def update_write_action(
        self,
        action_id: str,
        *,
        status: str | None = None,
        result: Any = None,
        rollback: Any = None,
        snapshot: Any = None,
        error: str | None = None,
        executed_at: datetime | None = None,
        rolled_back_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        with self.db.session() as session:
            row = session.get(WriteAction, action_id)
            if row is None:
                return None
            if status is not None:
                row.status = status
            if result is not None:
                row.result_json = _jsonable(result)
            if rollback is not None:
                row.rollback_json = _jsonable(rollback)
            if snapshot is not None:
                row.snapshot_json = _jsonable(snapshot)
            if error is not None:
                row.error = error
            if executed_at is not None:
                row.executed_at = executed_at
            if rolled_back_at is not None:
                row.rolled_back_at = rolled_back_at
            session.flush()
            return self._write_action_dict(row)

    def list_pending_write_actions(
        self,
        *,
        username: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        now = utcnow()
        with self.db.session() as session:
            rows = session.scalars(
                select(WriteAction)
                .where(
                    WriteAction.username == username,
                    WriteAction.conversation_id == conversation_id,
                    WriteAction.status == "pending",
                    WriteAction.expires_at > now,
                )
                .order_by(WriteAction.created_at.asc(), WriteAction.id.asc())
            ).all()
            return [self._write_action_dict(row) for row in rows]

    def list_write_actions(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        sort_columns = {
            "created_at": WriteAction.created_at,
            "username": WriteAction.username,
            "risk_level": WriteAction.risk_level,
            "status": WriteAction.status,
            "action_type": WriteAction.action_type,
            "executed_at": WriteAction.executed_at,
            "rolled_back_at": WriteAction.rolled_back_at,
        }
        order_column = sort_columns.get(sort_by, WriteAction.created_at)
        order = order_column.asc() if sort_order == "asc" else order_column.desc()
        with self.db.session() as session:
            total = session.scalar(select(func.count()).select_from(WriteAction))
            rows = session.scalars(
                select(WriteAction)
                .order_by(order, WriteAction.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "total": total or 0,
                "page": page,
                "page_size": page_size,
                "items": [self._write_action_dict(row) for row in rows],
            }

    def purge_old(self, days: int) -> dict[str, int]:
        if days <= 0:
            return {
                "conversations": 0,
                "admin_audit": 0,
                "archived_conversations": 0,
                "archived_admin_audit": 0,
            }
        cutoff = utcnow() - timedelta(days=days)
        with self.db.session() as session:
            conversations = session.scalars(
                select(Conversation).where(Conversation.last_at < cutoff)
            ).all()
            conversation_ids = [item.id for item in conversations]
            messages_by_conversation: dict[str, list[Message]] = defaultdict(list)
            tools_by_conversation: dict[str, list[ToolCall]] = defaultdict(list)
            if conversation_ids:
                for item in session.scalars(
                    select(Message)
                    .where(Message.conversation_id.in_(conversation_ids))
                    .order_by(Message.id)
                ).all():
                    messages_by_conversation[item.conversation_id].append(item)
                for item in session.scalars(
                    select(ToolCall)
                    .where(ToolCall.conversation_id.in_(conversation_ids))
                    .order_by(ToolCall.id)
                ).all():
                    tools_by_conversation[item.conversation_id].append(item)

            for conversation in conversations:
                payload = {
                    **self._conversation_dict(conversation),
                    "messages": [
                        {
                            "id": item.id,
                            "run_id": item.run_id,
                            "role": item.role,
                            "content": item.content,
                            "model_name": item.model_name,
                            "input_tokens": item.input_tokens,
                            "output_tokens": item.output_tokens,
                            "latency_ms": item.latency_ms,
                            "status": item.status,
                            "error": item.error,
                            "created_at": _iso(item.created_at),
                        }
                        for item in messages_by_conversation[conversation.id]
                    ],
                    "tool_calls": [
                        {
                            "id": item.id,
                            "run_id": item.run_id,
                            "sequence": item.sequence,
                            "tool_name": item.tool_name,
                            "args_json": item.args_json,
                            "result_json": item.result_json,
                            "sql_text": item.sql_text,
                            "row_count": item.row_count,
                            "duration_ms": item.duration_ms,
                            "status": item.status,
                            "error": item.error,
                            "created_at": _iso(item.created_at),
                        }
                        for item in tools_by_conversation[conversation.id]
                    ],
                }
                session.add(
                    RetentionArchive(
                        kind="conversation",
                        source_id=conversation.id,
                        conversation_id=conversation.id,
                        username=conversation.username,
                        archived_at=utcnow(),
                        original_created_at=conversation.last_at,
                        payload_json=_jsonable(payload),
                    )
                )

            admin_audits = session.scalars(
                select(AdminAudit).where(AdminAudit.created_at < cutoff)
            ).all()
            for row in admin_audits:
                payload = {
                    "id": row.id,
                    "actor": row.actor,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "before_json": row.before_json,
                    "after_json": row.after_json,
                    "ip": row.ip,
                    "user_agent": row.user_agent,
                    "created_at": _iso(row.created_at),
                }
                session.add(
                    RetentionArchive(
                        kind="admin_audit",
                        source_id=str(row.id),
                        username=row.actor,
                        archived_at=utcnow(),
                        original_created_at=row.created_at,
                        payload_json=_jsonable(payload),
                    )
                )

            if conversation_ids:
                session.execute(
                    delete(ToolCall).where(
                        ToolCall.conversation_id.in_(conversation_ids)
                    )
                )
                session.execute(
                    delete(Message).where(
                        Message.conversation_id.in_(conversation_ids)
                    )
                )
                session.execute(
                    delete(Conversation).where(
                        Conversation.id.in_(conversation_ids)
                    )
                )
            if admin_audits:
                session.execute(
                    delete(AdminAudit).where(
                        AdminAudit.id.in_([row.id for row in admin_audits])
                    )
                )
            return {
                "conversations": len(conversation_ids),
                "admin_audit": len(admin_audits),
                "archived_conversations": len(conversations),
                "archived_admin_audit": len(admin_audits),
            }
