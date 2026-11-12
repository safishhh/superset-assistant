"""查询结果字段的中文别名：数据集备注优先，缺备注时让模型翻译。

图表图例、明细表头、口径说明都用同一份别名，保证界面不出现裸英文列名。
翻译失败只丢别名，不影响查询本身。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

MAX_LABEL_CHARS = 20
_CACHE_LIMIT = 800
_CACHE: dict[str, str] = {}

_JSON_RE = re.compile(r"\{.*\}", re.S)
_LINE_RE = re.compile(
    r"^[\s\-*\d.]*([A-Za-z_][\w.]*)\s*[:=：]\s*(.+)$",
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def build_label_prompt(
    names: list[str],
    *,
    sql: str | None = None,
    dataset: str | None = None,
    sample: dict[str, Any] | None = None,
) -> str:
    context: list[str] = []
    if dataset:
        context.append(f"数据集：{dataset}")
    if sql:
        context.append(f"SQL：{sql[:800]}")
    if sample:
        text = json.dumps(sample, ensure_ascii=False, default=str)
        context.append(f"参数示例：{text[:600]}")
    lines = [
        "把下面查询结果的英文字段名翻译成简洁的中文业务名，用于图表表头。",
        *context,
        f"字段名：{json.dumps(names, ensure_ascii=False)}",
        (
            "只输出一个 JSON 对象，不要解释、不要代码块；"
            "值为 2-10 个汉字，保留口径含义"
            "（total_amount → 销售额、order_count → 订单数、market → 市场）；"
            "已经是中文的字段原样返回。"
        ),
    ]
    return "\n".join(lines)


def clean_labels(raw: str, names: list[str]) -> dict[str, str]:
    """从模型输出里取出 {字段名: 中文名}，过滤未知字段、英文回显和超长值。"""
    text = (raw or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text).strip()
    data: Any = None
    match = _JSON_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        data = {}
        for line in text.splitlines():
            found = _LINE_RE.match(line)
            if found:
                data[found.group(1)] = found.group(2)
    wanted = {name.lower(): name for name in names}
    labels: dict[str, str] = {}
    for key, value in data.items():
        name = wanted.get(str(key).strip().lower())
        if not name or not isinstance(value, str):
            continue
        label = value.strip().strip("\"'“”「」『』").strip()
        if not label or len(label) > MAX_LABEL_CHARS:
            continue
        if not _CJK_RE.search(label):
            continue
        if label.lower() == name.lower():
            continue
        labels[name] = label
    return labels


def cached_labels(names: list[str]) -> dict[str, str]:
    return {name: _CACHE[name] for name in names if name in _CACHE}


async def translate_labels(
    names: list[str],
    *,
    settings: Settings,
    runtime: Any = None,
    sql: str | None = None,
    dataset: str | None = None,
    sample: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, str]:
    """缺失别名时调用一次模型；任何失败都退回空结果（保留原列名）。"""
    unique = [name for name in dict.fromkeys(names) if name]
    if not unique or settings.mock_llm:
        return cached_labels(unique)
    missing = [name for name in unique if name not in _CACHE]
    if not missing:
        return cached_labels(unique)
    # tools.py 与 agent.py 互相引用，延迟导入避免模块级循环依赖
    from .agent import build_oneshot_agent
    from . import llm_log

    try:
        agent = build_oneshot_agent(settings, runtime)
        if agent is None:
            return cached_labels(unique)
        with llm_log.scope(purpose="labels"):
            result = await asyncio.wait_for(
                agent.run(
                    build_label_prompt(
                        missing, sql=sql, dataset=dataset, sample=sample
                    )
                ),
                timeout=timeout,
            )
        parsed = clean_labels(result.output, missing)
    except Exception:  # noqa: BLE001 - 翻译失败不影响查询结果
        logger.warning("column label translation failed", exc_info=True)
        return cached_labels(unique)
    for name, label in parsed.items():
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[name] = label
    return cached_labels(unique)
