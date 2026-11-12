from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def purge_old(
        self,
        days: int,
        archive: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> dict[str, int]:
        if days <= 0 or not self.path.exists():
            return {"removed": 0, "kept": 0}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self._lock:
            kept: list[str] = []
            removed: list[dict[str, Any]] = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                timestamp = record.get("ts")
                parsed: datetime | None = None
                if isinstance(timestamp, str):
                    try:
                        parsed = datetime.fromisoformat(
                            timestamp.replace("Z", "+00:00")
                        )
                    except ValueError:
                        parsed = None
                if parsed is not None and parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed is not None and parsed < cutoff:
                    removed.append(record)
                else:
                    kept.append(line)

            if not removed:
                return {"removed": 0, "kept": len(kept)}
            if archive is not None:
                archive(removed)
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                for line in kept:
                    handle.write(line.rstrip("\n") + "\n")
            temporary.replace(self.path)
            return {"removed": len(removed), "kept": len(kept)}
