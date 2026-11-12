from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


class ColumnInfo(BaseModel):
    name: str
    type: str | None = None
    verbose_name: str | None = None


class DatasetFilter(BaseModel):
    """`query_dataset` 的维度值过滤条件；op 枚举与 Superset MCP 完全一致。"""

    col: str = Field(description="要过滤的列名，必须是数据集里存在的列")
    op: Literal[
        "==",
        "!=",
        ">",
        "<",
        ">=",
        "<=",
        "LIKE",
        "NOT LIKE",
        "ILIKE",
        "NOT ILIKE",
        "IN",
        "NOT IN",
        "IS NULL",
        "IS NOT NULL",
        "IS TRUE",
        "IS FALSE",
        "TEMPORAL_RANGE",
    ] = Field(description="比较符；IN/NOT IN 的 val 传列表，IS NULL/IS TRUE 类不传 val")
    val: Any | None = Field(default=None, description="过滤值")


class MetricInfo(BaseModel):
    name: str
    expression: str | None = None
    description: str | None = None
    verbose_name: str | None = None


class DatasetInfoResult(BaseModel):
    id: int | str
    name: str
    schema: str | None = None
    database: str | None = None
    database_id: int | None = None
    main_dttm_col: str | None = None
    columns: list[ColumnInfo] = Field(default_factory=list)
    metrics: list[MetricInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    matched_in: list[str] = Field(default_factory=list)


class DatasetCandidate(BaseModel):
    """数据集目录条目：详情之外的候选只给这些轻量信息。"""

    id: int | str
    name: str
    column_count: int = 0
    metric_count: int = 0
    matched_in: list[str] = Field(default_factory=list)


class MetadataSearchResult(BaseModel):
    query: str
    datasets: list[DatasetInfoResult] = Field(default_factory=list)
    candidates: list[DatasetCandidate] = Field(default_factory=list)
    total_visible: int = 0
    warnings: list[str] = Field(default_factory=list)


class QueryDatasetResult(BaseModel):
    dataset_id: int | str
    dataset_name: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    chart_type: str = "auto"
    row_count: int = 0
    from_dttm: str | None = None
    to_dttm: str | None = None
    applied_filters: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WriteProposalResult(BaseModel):
    action_id: str
    status: str
    action_type: str
    risk_level: str
    summary: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    snapshot_summary: dict[str, Any] = Field(default_factory=dict)
    expires_at: str


class RunSqlResult(BaseModel):
    sql: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    row_count: int = 0
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    chart_type: str = "auto"


class PeriodCompareResult(BaseModel):
    kind: Literal["period_compare"] = "period_compare"
    base_period: str
    current_period: str
    dimension: str = ""
    dimensions: list[str] = Field(default_factory=list)
    basis: str = "total"
    basis_reason: str = ""
    base_stats: dict[str, Any] = Field(default_factory=dict)
    current_stats: dict[str, Any] = Field(default_factory=dict)
    comparable: dict[str, Any] = Field(default_factory=dict)
    significance: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    warnings: list[str] = Field(default_factory=list)


class ContributionResult(BaseModel):
    kind: Literal["dimension_contribution"] = "dimension_contribution"
    dimension: str = ""
    dimensions: list[str] = Field(default_factory=list)
    basis: str = "total"
    basis_reason: str = ""
    base_stats: dict[str, Any] = Field(default_factory=dict)
    current_stats: dict[str, Any] = Field(default_factory=dict)
    total_delta: float = 0.0
    concentration: dict[str, Any] | None = None
    offsetting: dict[str, Any] = Field(default_factory=dict)
    dimension_ranking: list[dict[str, Any]] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    warnings: list[str] = Field(default_factory=list)


class StructureEffectResult(BaseModel):
    kind: Literal["structure_effect"] = "structure_effect"
    dimension: str = ""
    dimensions: list[str] = Field(default_factory=list)
    base_stats: dict[str, Any] = Field(default_factory=dict)
    current_stats: dict[str, Any] = Field(default_factory=dict)
    total_delta: float = 0.0
    structure_effect: float = 0.0
    efficiency_effect: float = 0.0
    interaction_effect: float = 0.0
    residual: float = 0.0
    dominant: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    warnings: list[str] = Field(default_factory=list)


class TrendForecastResult(BaseModel):
    kind: Literal["trend_forecast"] = "trend_forecast"
    metric: str
    history_start: str
    history_end: str
    horizon_days: int
    expected_days: int = 0
    observed_days: int = 0
    coverage_pct: float | None = None
    trend: dict[str, Any] = Field(default_factory=dict)
    decomposition: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    backtest: dict[str, Any] = Field(default_factory=dict)
    interval: dict[str, Any] = Field(default_factory=dict)
    history_tail: list[dict[str, Any]] = Field(default_factory=list)
    forecast: list[dict[str, Any]] = Field(default_factory=list)
    forecast_total: float | None = None
    forecast_daily_avg: float | None = None
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    method: str = ""
    assumptions: list[str] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    id: int
    title: str
    content: str
    source: str = "auto"
    updated_at: str = ""
    content_chars: int = 0
    truncated: bool = False
    hits: int = 0
    # 知识所属范围：user=用户个人知识库，employee=当前 AI 牛马的知识库
    scope: str = "user"


class KnowledgeListResult(BaseModel):
    kind: Literal["list_knowledge"] = "list_knowledge"
    items: list[KnowledgeItem] = Field(default_factory=list)
    count: int = 0
    total_matched: int = 0


class KnowledgeSaveResult(BaseModel):
    saved: bool
    title: str
    updated_at: str = ""
