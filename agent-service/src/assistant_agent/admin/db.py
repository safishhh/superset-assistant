from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Provider(Base):
    __tablename__ = "ai_provider"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    api_key_hint: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class Model(Base):
    __tablename__ = "ai_model"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_name", name="uq_model_provider_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_provider.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    disable_thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    # default / low / medium / high，透传给 OpenAI 兼容接口的 reasoning_effort
    reasoning_effort: Mapped[str] = mapped_column(String(16), default="default")
    # 对话上下文档位（token）：200000/400000/600000/800000/1000000
    context_window: Mapped[int] = mapped_column(Integer, default=200000)
    input_price_per_m: Mapped[float] = mapped_column(Float, default=0.0)
    output_price_per_m: Mapped[float] = mapped_column(Float, default=0.0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class Conversation(Base):
    __tablename__ = "ai_conversation"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    model_name: Mapped[str] = mapped_column(String(256), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Message(Base):
    __tablename__ = "ai_message"
    __table_args__ = (Index("ix_message_conversation_time", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(256), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str] = mapped_column(Text, default="")
    # 该轮用户点选的页面区块（仅 user 消息写入），供历史与聊天内标注
    selection_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    # assistant 消息的正文/工具顺序（[{"type":"text","len":N},{"type":"tool","name":...}]）
    parts_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ToolCall(Base):
    __tablename__ = "ai_tool_call"
    __table_args__ = (Index("ix_tool_conversation_time", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    args_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    sql_text: Mapped[str] = mapped_column(Text, default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TurnFeedback(Base):
    __tablename__ = "ai_turn_feedback"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "username",
            "turn_index",
            name="uq_feedback_conv_user_turn",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(String(128), index=True)
    turn_index: Mapped[int] = mapped_column(Integer)
    rating: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class UsageDaily(Base):
    __tablename__ = "ai_usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "day", "username", "model_name", "employee_id",
            name="uq_usage_day_user_model_employee",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    username: Mapped[str] = mapped_column(String(128), index=True)
    model_name: Mapped[str] = mapped_column(String(256), index=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    # 0 = 默认助手；>0 = AI 员工 id（用量按员工拆分）
    employee_id: Mapped[int] = mapped_column(Integer, default=0)


class WriteAction(Base):
    __tablename__ = "ai_write_action"
    __table_args__ = (
        Index("ix_write_action_user_time", "username", "created_at"),
        Index("ix_write_action_status_time", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    run_id: Mapped[str] = mapped_column(String(64), default="")
    action_type: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    plan_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    snapshot_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    rollback_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class UserAIAccess(Base):
    __tablename__ = "ai_user_ai_access"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str] = mapped_column(String(128), default="")


class AppSetting(Base):
    __tablename__ = "ai_app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str] = mapped_column(String(128), default="")


class Skill(Base):
    __tablename__ = "ai_skill"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    instruction: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str] = mapped_column(String(128), default="")


class Knowledge(Base):
    __tablename__ = "ai_knowledge"
    __table_args__ = (
        # deleted_key = 0 表示生效中；软删时写入自身 id，从而允许回收站里同名多条
        UniqueConstraint(
            "username", "title", "deleted_key", name="uq_knowledge_user_title_key"
        ),
        Index("ix_knowledge_user", "username"),
        Index("ix_knowledge_deleted", "username", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    # manual = 用户在知识库手填；auto = 模型/后台自动沉淀
    source: Mapped[str] = mapped_column(String(32), default="auto")
    hits: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_key: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class RetentionArchive(Base):
    __tablename__ = "ai_retention_archive"
    __table_args__ = (
        Index("ix_archive_kind_time", "kind", "archived_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(64), default="")
    conversation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(128), default="")
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    original_created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    payload_json: Mapped[Any] = mapped_column(JSON, nullable=True)


class AdminAudit(Base):
    __tablename__ = "ai_admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    before_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    after_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class UsedTicket(Base):
    __tablename__ = "ai_used_ticket"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminDB:
    def __init__(self, url: str) -> None:
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite:"):
            connect_args = {"check_same_thread": False, "timeout": 30}
        self.engine: Engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        if url.startswith("sqlite:"):
            event.listen(self.engine, "connect", self._sqlite_pragmas)
        self.Session = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )

    @staticmethod
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def ensure_schema(self) -> None:
        self.create_all()
        inspector = inspect(self.engine)
        if "ai_conversation" not in inspector.get_table_names():
            return
        columns = {
            column["name"]
            for column in inspector.get_columns("ai_conversation")
        }
        with self.engine.begin() as connection:
            if "deleted_at" not in columns:
                connection.execute(
                    text("ALTER TABLE ai_conversation ADD COLUMN deleted_at DATETIME")
                )
            if "employee_id" not in columns:
                connection.execute(
                    text("ALTER TABLE ai_conversation ADD COLUMN employee_id INTEGER")
                )
        if "ai_message" in inspector.get_table_names():
            message_columns = {
                column["name"]
                for column in inspector.get_columns("ai_message")
            }
            if "selection_json" not in message_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE ai_message ADD COLUMN selection_json JSON")
                    )
            if "parts_json" not in message_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE ai_message ADD COLUMN parts_json JSON")
                    )
        if "ai_model" in inspector.get_table_names():
            model_columns = {
                column["name"]
                for column in inspector.get_columns("ai_model")
            }
            if "context_window" not in model_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE ai_model ADD COLUMN context_window INTEGER")
                    )
                    connection.execute(
                        text(
                            "UPDATE ai_model SET context_window = 200000 "
                            "WHERE context_window IS NULL"
                        )
                    )
            if "reasoning_effort" not in model_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE ai_model ADD COLUMN reasoning_effort "
                            "VARCHAR(16) NOT NULL DEFAULT 'default'"
                        )
                    )
        if "ai_employee" in inspector.get_table_names():
            employee_columns = {
                column["name"]
                for column in inspector.get_columns("ai_employee")
            }
            if "users" not in employee_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE ai_employee ADD COLUMN users JSON")
                    )
            if "roles" not in employee_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE ai_employee ADD COLUMN roles JSON")
                    )
            if "model_ids" not in employee_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE ai_employee ADD COLUMN model_ids JSON")
                    )
            if "can_delegate" not in employee_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE ai_employee ADD COLUMN can_delegate "
                            "BOOLEAN NOT NULL DEFAULT 0"
                        )
                    )
                    connection.execute(
                        text(
                            "UPDATE ai_employee SET can_delegate = 1 "
                            "WHERE username = 'atlas'"
                        )
                    )
            if "delegate_employee_ids" not in employee_columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE ai_employee "
                            "ADD COLUMN delegate_employee_ids JSON"
                        )
                    )
        self._migrate_knowledge(inspector)
        usage_columns = {
            column["name"]
            for column in inspector.get_columns("ai_usage_daily")
        }
        if "employee_id" not in usage_columns:
            # 唯一约束要加上员工维度，SQLite 只能重建表
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE ai_usage_daily_new ("
                        "id INTEGER PRIMARY KEY, day DATE NOT NULL, "
                        "username VARCHAR(128) NOT NULL, "
                        "model_name VARCHAR(256) NOT NULL, "
                        "requests INTEGER, input_tokens INTEGER, "
                        "output_tokens INTEGER, cost FLOAT, "
                        "tool_calls INTEGER, errors INTEGER, "
                        "employee_id INTEGER NOT NULL DEFAULT 0, "
                        "UNIQUE (day, username, model_name, employee_id))"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO ai_usage_daily_new (id, day, username, "
                        "model_name, requests, input_tokens, output_tokens, "
                        "cost, tool_calls, errors) SELECT id, day, username, "
                        "model_name, requests, input_tokens, output_tokens, "
                        "cost, tool_calls, errors FROM ai_usage_daily"
                    )
                )
                connection.execute(text("DROP TABLE ai_usage_daily"))
                connection.execute(
                    text("ALTER TABLE ai_usage_daily_new RENAME TO ai_usage_daily")
                )
                for index, column in (
                    ("ix_ai_usage_daily_day", "day"),
                    ("ix_ai_usage_daily_username", "username"),
                    ("ix_ai_usage_daily_model_name", "model_name"),
                ):
                    connection.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS {index} "
                            f"ON ai_usage_daily ({column})"
                        )
                    )

    def _migrate_knowledge(self, inspector: Any) -> None:
        """知识库分层治理所需的列、唯一索引替换与中文全文索引。"""
        if "ai_knowledge" not in inspector.get_table_names():
            return
        columns = {
            column["name"] for column in inspector.get_columns("ai_knowledge")
        }
        with self.engine.begin() as connection:
            if "hits" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE ai_knowledge ADD COLUMN hits "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "last_used_at" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE ai_knowledge ADD COLUMN last_used_at DATETIME"
                    )
                )
            if "deleted_key" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE ai_knowledge ADD COLUMN deleted_key "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "deleted_at" not in columns:
                connection.execute(
                    text("ALTER TABLE ai_knowledge ADD COLUMN deleted_at DATETIME")
                )
            connection.execute(
                text(
                    "UPDATE ai_knowledge SET deleted_key = id "
                    "WHERE deleted_at IS NOT NULL AND deleted_key = 0"
                )
            )
            # 旧的 chat/manual 两值改为 auto/manual：对话里让模型记 = 自动沉淀
            connection.execute(
                text("UPDATE ai_knowledge SET source = 'auto' WHERE source = 'chat'")
            )

        existing = {item["name"] for item in inspector.get_indexes("ai_knowledge")}
        existing |= {
            item["name"] for item in inspector.get_unique_constraints("ai_knowledge")
        }
        if "uq_knowledge_user_title" in existing:
            with self.engine.begin() as connection:
                if self.engine.dialect.name == "mysql":
                    connection.execute(
                        text("ALTER TABLE ai_knowledge DROP INDEX uq_knowledge_user_title")
                    )
                else:
                    connection.execute(text("DROP INDEX uq_knowledge_user_title"))
        if "uq_knowledge_user_title_key" not in existing:
            with self.engine.begin() as connection:
                if self.engine.dialect.name == "mysql":
                    connection.execute(
                        text(
                            "ALTER TABLE ai_knowledge ADD UNIQUE "
                            "uq_knowledge_user_title_key (username, title, deleted_key)"
                        )
                    )
                else:
                    connection.execute(
                        text(
                            "CREATE UNIQUE INDEX uq_knowledge_user_title_key "
                            "ON ai_knowledge (username, title, deleted_key)"
                        )
                    )
        if "ix_knowledge_deleted" not in existing:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE INDEX ix_knowledge_deleted "
                        "ON ai_knowledge (username, deleted_at)"
                    )
                )
        if self.engine.dialect.name == "mysql":
            with self.engine.begin() as connection:
                fulltext = connection.execute(
                    text(
                        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "AND TABLE_NAME = 'ai_knowledge' "
                        "AND INDEX_TYPE = 'FULLTEXT'"
                    )
                ).fetchall()
                if not fulltext:
                    # ngram 分词，中文关键词才能走索引而不是 LIKE 全扫
                    connection.execute(
                        text(
                            "ALTER TABLE ai_knowledge ADD FULLTEXT INDEX "
                            "ft_knowledge (title, content) WITH PARSER ngram"
                        )
                    )

    @contextmanager
    def session(self) -> Iterator[Any]:
        db = self.Session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


class Employee(Base):
    """AI 员工（AI 牛马）：独立人物设定、模型、技能、MCP 工具白名单与知识库。"""

    __tablename__ = "ai_employee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(128), default="")
    avatar: Mapped[str] = mapped_column(String(256), default="")  # emoji 或 URL
    intro: Mapped[str] = mapped_column(Text, default="")
    greeting: Mapped[str] = mapped_column(Text, default="")
    persona: Mapped[str] = mapped_column(Text, default="")
    # 默认模型；model_ids 为可用模型白名单（None/空=全部启用模型）
    model_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    skill_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    # None = 未配置（不限制）；[] = 一个都不允许；列表 = 白名单
    tools: Mapped[Any] = mapped_column(JSON, nullable=True)
    # 可见/可用该员工的 Superset 用户名：None = 全员，[] = 仅管理员，列表 = 白名单
    users: Mapped[Any] = mapped_column(JSON, nullable=True)
    # 可见/可用该员工的 Superset 角色：与 users 取并集；两者都为 None 才是全员
    roles: Mapped[Any] = mapped_column(JSON, nullable=True)
    # 是否允许协调其他 AI 牛马；delegate_employee_ids None/空 = 全部可用牛马
    can_delegate: Mapped[bool] = mapped_column(Boolean, default=False)
    delegate_employee_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str] = mapped_column(String(128), default="")


class EmployeeKnowledge(Base):
    __tablename__ = "ai_employee_knowledge"
    __table_args__ = (
        UniqueConstraint("employee_id", "title", name="uq_employee_knowledge_title"),
        Index("ix_employee_knowledge_employee", "employee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
