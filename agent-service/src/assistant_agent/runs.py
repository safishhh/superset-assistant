from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActiveRun:
    """一轮正在生成中的回答；与 HTTP 连接解耦，客户端断开不影响生成。"""

    run_id: str
    conversation_id: str
    username: str
    model: str
    employee: str
    question: str
    started_at: float = field(default_factory=time.monotonic)
    status: str = "running"  # running | ok | error | canceled
    text: str = ""
    tool_calls: int = 0
    error: str = ""
    finished_at: float | None = None
    chunks: list[str] = field(default_factory=list)
    buffering: bool = True
    attached: int = 0
    updated: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def append(self, chunk: str) -> None:
        if self.buffering:
            self.chunks.append(chunk)
        self.updated.set()

    def finish(self, status: str, error: str = "") -> None:
        self.status = status
        self.error = error
        self.finished_at = time.monotonic()
        self.done.set()
        self.updated.set()

    def snapshot(self) -> dict[str, Any]:
        end = self.finished_at or time.monotonic()
        return {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "status": self.status,
            "text": self.text,
            "tool_calls": self.tool_calls,
            "question": self.question,
            "model": self.model,
            "employee": self.employee,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at or 0,
            "elapsed_ms": int((end - self.started_at) * 1000),
        }


class RunRegistry:
    """进程内的运行注册表；只保留最近若干轮，完成的过一段时间自动清理。"""

    keep_seconds = 1800
    max_runs = 200

    def __init__(self) -> None:
        self._runs: dict[str, ActiveRun] = {}

    def add(self, run: ActiveRun) -> None:
        self.purge()
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> ActiveRun | None:
        return self._runs.get(run_id)

    def active_for(self, conversation_id: str, username: str) -> ActiveRun | None:
        for run in self._runs.values():
            if (
                run.status == "running"
                and run.conversation_id == conversation_id
                and run.username == username
            ):
                return run
        return None

    def purge(self) -> int:
        now = time.monotonic()
        stale = [
            run_id
            for run_id, run in self._runs.items()
            if run.finished_at is not None
            and now - run.finished_at > self.keep_seconds
        ]
        for run_id in stale:
            self._runs.pop(run_id, None)
        overflow = len(self._runs) - self.max_runs
        if overflow > 0:
            finished = sorted(
                (run for run in self._runs.values() if run.finished_at is not None),
                key=lambda run: run.finished_at or 0,
            )
            for run in finished[:overflow]:
                self._runs.pop(run.run_id, None)
        return len(stale)

    def shutdown(self) -> None:
        for run in list(self._runs.values()):
            if run.task is not None and not run.task.done():
                run.task.cancel()
        self._runs.clear()
