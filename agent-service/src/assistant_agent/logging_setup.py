from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_BASENAME = "agent.log"
LOG_NAME_RE = re.compile(r"^agent\.log(?:\.(\d{4}-\d{2}-\d{2}))?$")
AI_LOG_BASENAME = "ai-calls.log"
AI_LOG_NAME_RE = re.compile(r"^ai-calls\.log(?:\.(\d{4}-\d{2}-\d{2}))?$")
AI_LOGGER_NAME = "assistant_agent.ai_calls"
LOG_SPECS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (LOG_BASENAME, LOG_NAME_RE, "agent"),
    (AI_LOG_BASENAME, AI_LOG_NAME_RE, "ai"),
)
LOG_RECORD_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s"
)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_RETENTION_DAYS = 14

_file_handlers: list[TimedRotatingFileHandler] = []
_log_dir: Path | None = None

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # mysql+pymysql://user:password@host/... / https://token@host/...
    (re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s@]+)@", re.IGNORECASE), r"\1***@"),
    (
        re.compile(
            r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"
        ),
        r"\1***",
    ),
    (
        re.compile(
            r"(?i)(api[_-]?key|password|passwd|secret|token)\s*[=:]\s*[^\s,;]+"
        ),
        r"\1=***",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-***"),
)


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


class RedactionFilter(logging.Filter):
    """日志脱敏：连接串、Authorization、API Key、token 等。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            for pattern, replacement in _REDACTIONS:
                message = pattern.sub(replacement, message)
            record.msg = message
            record.args = ()
        except Exception:  # noqa: BLE001
            pass
        return True


def _retention_days(value: int | str | None) -> int:
    try:
        days = int(value or DEFAULT_RETENTION_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_RETENTION_DAYS
    return max(1, min(days, 365))


def _level(value: str | None) -> int:
    return getattr(logging, (value or "INFO").upper(), logging.INFO)


def configure_logging(
    log_dir: str | Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    level: str | None = None,
) -> Path:
    """Agent 文件日志：按 UTC 天切分，保留 N 天；同时保留 Docker stdout。"""
    global _log_dir
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    _log_dir = path
    days = _retention_days(retention_days)
    resolved_level = _level(level or os.environ.get("AGENT_LOG_LEVEL"))

    root = logging.getLogger()
    root.setLevel(resolved_level)
    for handler in list(root.handlers):
        if getattr(handler, "_assistant_file", False) or getattr(
            handler, "_assistant_console", False
        ):
            root.removeHandler(handler)
            handler.close()

    formatter = UTCFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = TimedRotatingFileHandler(
        path / LOG_BASENAME,
        when="midnight",
        interval=1,
        backupCount=days,
        encoding="utf-8",
        utc=True,
        delay=True,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.setLevel(resolved_level)
    file_handler.addFilter(RedactionFilter())
    file_handler._assistant_file = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    # AI 调用日志单独一份（每行 JSON），不混进 agent.log；Docker stdout 仍然可见。
    ai_formatter = UTCFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ai_file_handler = TimedRotatingFileHandler(
        path / AI_LOG_BASENAME,
        when="midnight",
        interval=1,
        backupCount=days,
        encoding="utf-8",
        utc=True,
        delay=True,
    )
    ai_file_handler.suffix = "%Y-%m-%d"
    ai_file_handler.setFormatter(ai_formatter)
    ai_file_handler.setLevel(logging.INFO)
    ai_file_handler.addFilter(RedactionFilter())
    ai_file_handler._assistant_file = True  # type: ignore[attr-defined]
    ai_console = logging.StreamHandler()
    ai_console.setFormatter(ai_formatter)
    ai_console.setLevel(logging.INFO)
    ai_console.addFilter(RedactionFilter())
    ai_logger = logging.getLogger(AI_LOGGER_NAME)
    for handler in list(ai_logger.handlers):
        ai_logger.removeHandler(handler)
        handler.close()
    ai_logger.addHandler(ai_file_handler)
    ai_logger.addHandler(ai_console)
    ai_logger.setLevel(logging.INFO)
    ai_logger.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(resolved_level)
    console.addFilter(RedactionFilter())
    console._assistant_console = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # uvicorn 默认会给自己挂 handler；统一走 root，避免文件日志重复。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(resolved_level)

    _file_handlers[:] = [file_handler, ai_file_handler]
    prune_log_files(path, days)
    return path


def set_log_retention(retention_days: int) -> int:
    """更新轮转保留天数，并立即删除超期文件。"""
    days = _retention_days(retention_days)
    seen: set[int] = set()
    for handler in _file_handlers:
        handler.backupCount = days
        seen.add(id(handler))
    for handler in logging.getLogger().handlers:
        if getattr(handler, "_assistant_file", False) and id(handler) not in seen:
            handler.backupCount = days  # type: ignore[attr-defined]
    return prune_log_files(_log_dir, days) if _log_dir else 0


def prune_log_files(log_dir: str | Path | None, retention_days: int) -> int:
    if not log_dir:
        return 0
    days = _retention_days(retention_days)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    removed = 0
    for base, pattern, _kind in LOG_SPECS:
        for path in Path(log_dir).glob(f"{base}.*"):
            match = pattern.match(path.name)
            if not match or not path.is_file():
                continue
            try:
                day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if day < cutoff:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def list_log_files(log_dir: str | Path) -> list[dict[str, object]]:
    path = Path(log_dir)
    if not path.exists():
        return []
    items: list[dict[str, object]] = []
    for base, pattern, kind in LOG_SPECS:
        for file in path.glob(f"{base}*"):
            match = pattern.match(file.name)
            if not match or not file.is_file():
                continue
            stat = file.stat()
            items.append(
                {
                    "name": file.name,
                    "date": match.group(1) or "",
                    "active": file.name == base,
                    "kind": kind,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat(),
                }
            )
    items.sort(key=lambda item: (bool(item["active"]), str(item["date"])), reverse=True)
    return items


def _resolve_log_file(log_dir: str | Path, name: str) -> Path:
    if not any(pattern.fullmatch(name or "") for _base, pattern, _kind in LOG_SPECS):
        raise ValueError("非法日志文件名")
    base = Path(log_dir).resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise ValueError("非法日志文件名")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def normalize_log_level(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    if not text or text in ("ALL", "全部"):
        return None
    if text == "WARN":
        text = "WARNING"
    elif text == "ERR":
        text = "ERROR"
    elif text == "FATAL":
        text = "CRITICAL"
    if text not in LOG_LEVELS:
        raise ValueError("不支持的日志级别")
    return text


def _read_level_lines(path: Path, level: str, limit: int) -> list[str]:
    """按日志记录分组读取，保留匹配级别记录的续行（如 traceback）。"""
    records: deque[list[str]] = deque(maxlen=limit)
    current_lines: list[str] = []
    current_level = ""

    def flush() -> None:
        if current_lines and current_level == level:
            records.append(list(current_lines))

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = LOG_RECORD_RE.match(line)
            if match:
                flush()
                current_level = match.group("level")
                current_lines = [line]
            elif current_lines:
                current_lines.append(line)
    flush()
    return [line for record in records for line in record]


def read_log_tail(
    log_dir: str | Path,
    name: str,
    lines: int = 500,
    level: str | None = None,
) -> dict[str, object]:
    path = _resolve_log_file(log_dir, name)
    limit = max(1, min(int(lines), 5000))
    selected_level = normalize_log_level(level)
    if selected_level:
        tail_lines = _read_level_lines(path, selected_level, limit)
    else:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            block = 8192
            data = b""
            while end > 0 and data.count(b"\n") <= limit:
                start = max(0, end - block)
                handle.seek(start)
                data = handle.read(end - start) + data
                end = start
        text = data.decode("utf-8", errors="replace")
        tail_lines = text.splitlines()[-limit:]
    stat = path.stat()
    return {
        "name": name,
        "lines": tail_lines,
        "level": selected_level or "",
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
    }


AI_CALL_LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (?P<level>[A-Z]+) "
    + re.escape(AI_LOGGER_NAME)
    + r" (?P<payload>\{.*\})\s*$"
)
AI_CALL_SCAN_LIMIT = 50000


def _ai_call_files(log_dir: str | Path) -> list[tuple[str, Path]]:
    path = Path(log_dir)
    if not path.exists():
        return []
    files: list[tuple[str, Path]] = []
    for file in path.glob(f"{AI_LOG_BASENAME}*"):
        match = AI_LOG_NAME_RE.match(file.name)
        if not match or not file.is_file():
            continue
        day = match.group(1) or "9999-99-99"
        files.append((day, file))
    files.sort(key=lambda item: item[0], reverse=True)
    return files


def read_ai_calls(
    log_dir: str | Path,
    *,
    limit: int = 200,
    username: str = "",
    model: str = "",
    status: str = "",
    keyword: str = "",
) -> dict[str, object]:
    """按新→旧读取 AI 调用日志（ai-calls.log*），返回解析后的 JSON 条目。"""
    limit = max(1, min(int(limit), 1000))
    wanted_user = (username or "").strip().lower()
    wanted_model = (model or "").strip().lower()
    wanted_status = (status or "").strip().lower()
    needle = (keyword or "").strip().lower()

    items: list[dict[str, object]] = []
    scanned = 0
    for _day, path in _ai_call_files(log_dir):
        if len(items) >= limit or scanned >= AI_CALL_SCAN_LIMIT:
            break
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = deque(handle, maxlen=AI_CALL_SCAN_LIMIT - scanned)
        scanned += len(lines)
        for line in reversed(lines):
            match = AI_CALL_LINE_RE.match(line)
            if not match:
                continue
            try:
                entry = json.loads(match.group("payload"))
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if wanted_user and wanted_user not in str(entry.get("user", "")).lower():
                continue
            if wanted_model and wanted_model not in str(entry.get("model", "")).lower():
                continue
            if wanted_status and wanted_status != str(entry.get("status", "")).lower():
                continue
            if needle and needle not in line.lower():
                continue
            items.append(entry)
            if len(items) >= limit:
                break
    return {
        "items": items,
        "scanned": scanned,
        "truncated": len(items) >= limit,
    }
