"""给历史查询结果补中文列名（只补显示别名，不改数据本身）。

新查询在 run_sql/query_dataset 里已经自动写入 labels；这个脚本用于处理
上线前已有的 ai_tool_call 记录，让历史对话的明细表头、图例、口径说明
也显示中文。可重复执行（已有 labels 的列会跳过）。

用法（在 agent 容器里）：
  docker exec -i assistant-agent python - < scripts/backfill_tool_labels.py
  # 指定模型（例如默认模型不可用时）：
  docker exec -i assistant-agent python - --model-id 2 < scripts/backfill_tool_labels.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import select

from assistant_agent.admin.db import AdminDB, ToolCall
from assistant_agent.admin.store import AdminStore
from assistant_agent.admin.crypto import SecretBox
from assistant_agent.config import settings
from assistant_agent.labels import translate_labels

QUERY_TOOLS = ("query_dataset", "run_sql", "execute_sql")
BATCH = 6


def _data(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _columns(data: dict[str, Any]) -> list[str]:
    names: list[str] = []
    columns = data.get("columns")
    if isinstance(columns, list):
        for column in columns:
            if isinstance(column, str):
                names.append(column)
            elif isinstance(column, dict) and column.get("name"):
                names.append(str(column["name"]))
    rows = data.get("rows") or data.get("data") or []
    if not names and rows and isinstance(rows[0], dict):
        names = [str(key) for key in rows[0]]
    return names


def _sample(data: dict[str, Any], names: list[str]) -> dict[str, Any]:
    rows = data.get("rows") or data.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return {}
    first = rows[0]
    return {name: first.get(name) for name in names if name in first}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = AdminDB(settings.admin_db_url)
    store = AdminStore(db, SecretBox(settings.admin_secret_key or "x"))
    runtime = store.get_runtime_model(args.model_id)
    print(
        "model:",
        runtime.model_name if runtime else "default",
        "dry-run:" if args.dry_run else "",
    )

    pending: list[tuple[int, dict[str, Any], list[str]]] = []
    samples: dict[str, Any] = {}
    names: list[str] = []
    with db.session() as session:
        rows = session.scalars(
            select(ToolCall)
            .where(
                ToolCall.tool_name.in_(QUERY_TOOLS),
                ToolCall.status == "ok",
            )
            .order_by(ToolCall.id)
        ).all()
        for row in rows:
            data = _data(row.result_json)
            if not data:
                continue
            columns = _columns(data)
            labels = data.get("labels")
            labels = labels if isinstance(labels, dict) else {}
            missing = [name for name in columns if name and name not in labels]
            if not missing:
                continue
            pending.append((row.id, data, missing))
            for name in missing:
                if name not in samples:
                    samples[name] = _sample(data, [name]).get(name)
            names.extend(missing)
    unique = list(dict.fromkeys(names))
    print(f"tool calls missing labels: {len(pending)}, columns: {len(unique)}")
    if not pending or args.dry_run:
        return

    translated: dict[str, str] = {}
    for start in range(0, len(unique), BATCH):
        chunk = unique[start : start + BATCH]
        got: dict[str, str] = {}
        for attempt in (1, 2):
            got = await translate_labels(
                chunk,
                settings=settings,
                runtime=runtime,
                sample={name: samples.get(name) for name in chunk},
                timeout=120,
            )
            if got:
                break
            await asyncio.sleep(10)
        translated.update(got)
        print(f"  batch {start // BATCH + 1}: {len(got)}/{len(chunk)}")
        await asyncio.sleep(4)
    print(f"translated: {len(translated)} / {len(unique)}")
    if not translated:
        return

    updated = 0
    with db.session() as session:
        for tool_id, data, missing in pending:
            labels = {
                name: translated[name] for name in missing if name in translated
            }
            if not labels:
                continue
            row = session.get(ToolCall, tool_id)
            if row is None:
                continue
            current = _data(row.result_json)
            merged = {
                **(current.get("labels") if isinstance(current.get("labels"), dict) else {}),
                **labels,
            }
            row.result_json = {**current, "labels": merged}
            updated += 1
        session.flush()
    print(f"updated tool calls: {updated}")


if __name__ == "__main__":
    asyncio.run(main())
