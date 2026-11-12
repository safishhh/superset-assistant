"""Deterministic model for end-to-end tests without an LLM endpoint.

It only understands a few demo questions, but it drives the real tools, MCP
client, RLS checks, and AI SDK stream generation.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    FunctionModel,
)

DEMO_DATASET_ID = 1


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content)


def _last_user_prompt(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                return _text(part.content)
    return ""


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    results: list[ToolReturnPart] = []
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            if any(isinstance(part, UserPromptPart) for part in message.parts):
                break
            results.extend(
                part for part in message.parts if isinstance(part, ToolReturnPart)
            )
        elif isinstance(message, ModelResponse):
            continue
    return list(reversed(results))


def _decode(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    if isinstance(content, dict):
        return content
    if hasattr(content, "model_dump"):
        return content.model_dump()
    return content


def _answer(tool: ToolReturnPart) -> str:
    data = _decode(tool.content)
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False)
    if data.get("summary"):
        return str(data["summary"])
    if data.get("datasets") is not None:
        names = [
            item.get("name") or item.get("table_name")
            for item in data.get("datasets", [])
            if isinstance(item, dict)
        ]
        return f"可用数据集：{', '.join(str(name) for name in names) or '无'}"
    if data.get("row_count") is not None:
        return f"查询完成，返回 {data.get('row_count')} 行。"
    if data.get("error"):
        return f"工具执行失败：{data['error']}"
    return "工具执行完成，结果见上方卡片。"


def mock_function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    prompt = _last_user_prompt(messages)
    returns = _tool_returns(messages)
    if returns:
        last = returns[-1]
        if last.outcome != "success":
            return ModelResponse(
                parts=[TextPart(f"工具执行失败：{_text(last.content)}")]
            )
        return ModelResponse(parts=[TextPart(_answer(last))])

    if "SQL" in prompt.upper() or "sql" in prompt:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "run_sql",
                    {
                        "database_id": 1,
                        "sql": (
                            "SELECT region, COUNT(*) AS orders, "
                            "SUM(amount) AS total_amount "
                            "FROM sales GROUP BY region ORDER BY region"
                        ),
                        "limit": 50,
                    },
                )
            ]
        )

    if "结构" in prompt or "效率" in prompt:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "structure_effect",
                    {
                        "dataset_id": DEMO_DATASET_ID,
                        "numerator_metric": "total_amount",
                        "denominator_metric": "count",
                        "dimension": "category",
                        "base_start": "2026-09-01",
                        "base_end": "2026-09-24",
                        "current_start": "2026-10-01",
                        "current_end": "2026-10-24",
                        "time_column": "order_date",
                    },
                )
            ]
        )

    if "为什么" in prompt or "下降" in prompt or "贡献" in prompt:
        dimension = "category" if "品类" in prompt else "region"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "dimension_contribution",
                    {
                        "dataset_id": DEMO_DATASET_ID,
                        "metric": "total_amount",
                        "dimension": dimension,
                        "base_start": "2026-09-01",
                        "base_end": "2026-09-24",
                        "current_start": "2026-10-01",
                        "current_end": "2026-10-24",
                    },
                )
            ]
        )

    if "环比" in prompt or "同比" in prompt or "同期" in prompt or "相比" in prompt:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "period_compare",
                    {
                        "dataset_id": DEMO_DATASET_ID,
                        "metric": "total_amount",
                        "base_start": "2026-09-01",
                        "base_end": "2026-09-24",
                        "current_start": "2026-10-01",
                        "current_end": "2026-10-24",
                        "dimension": "region" if "区域" in prompt else None,
                    },
                )
            ]
        )

    if "数据集" in prompt:
        return ModelResponse(
            parts=[ToolCallPart("search_metadata", {"query": "销售额 区域"})]
        )

    metric = "count" if "订单" in prompt or "数量" in prompt else "total_amount"
    return ModelResponse(
        parts=[
            ToolCallPart(
                "query_dataset",
                {
                    "dataset_id": DEMO_DATASET_ID,
                    "metrics": [metric],
                    "columns": ["region"] if "区域" in prompt else ["category"],
                    "row_limit": 50,
                },
            )
        ]
    )


def mock_model() -> FunctionModel:
    return FunctionModel(
        mock_function,
        stream_function=stream_mock_function,
        model_name="mock-demo",
    )


async def stream_mock_function(messages: list[ModelMessage], info: AgentInfo):
    response = mock_function(messages, info)
    for part in response.parts:
        if isinstance(part, TextPart):
            yield part.content
        elif isinstance(part, ToolCallPart):
            yield {
                0: DeltaToolCall(
                    name=part.tool_name,
                    json_args=json.dumps(part.args, ensure_ascii=False),
                    tool_call_id=part.tool_call_id,
                )
            }
