from __future__ import annotations

import logging

import pytest

from assistant_agent.logging_setup import (
    configure_logging,
    list_log_files,
    read_log_tail,
    set_log_retention,
)


def test_log_file_tail_rotation_and_retention(tmp_path):
    log_dir = tmp_path / "logs"
    configure_logging(log_dir, 7)
    logging.getLogger("assistant.test").info("hello 日志")
    for handler in logging.getLogger().handlers:
        handler.flush()

    tail = read_log_tail(log_dir, "agent.log", 20)
    assert any("hello 日志" in line for line in tail["lines"])
    assert tail["name"] == "agent.log"

    old = log_dir / "agent.log.2020-01-01"
    old.write_text("old rotated log\n", encoding="utf-8")
    set_log_retention(7)
    assert not old.exists()

    files = list_log_files(log_dir)
    assert any(item["active"] for item in files)
    assert all(
        item["name"].startswith(("agent.log", "ai-calls.log")) for item in files
    )
    assert {item.get("kind") for item in files} <= {"agent", "ai"}

    with pytest.raises(ValueError):
        read_log_tail(log_dir, "../agent.log", 10)
    with pytest.raises(FileNotFoundError):
        read_log_tail(log_dir, "agent.log.2099-01-01", 10)


def test_log_tail_level_filter(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "agent.log").write_text(
        "\n".join(
            [
                "2026-10-29 01:00:00 DEBUG app debug detail",
                "2026-10-29 01:00:01 INFO app info detail",
                "2026-10-29 01:00:02 ERROR app boom",
                "Traceback (most recent call last):",
                '  File "x.py", line 1',
                "ValueError: bad",
                "2026-10-29 01:00:03 INFO app after",
                "",
            ]
        ),
        encoding="utf-8",
    )
    error_tail = read_log_tail(log_dir, "agent.log", 10, "error")
    assert error_tail["level"] == "ERROR"
    assert any("boom" in line for line in error_tail["lines"])
    assert any("Traceback" in line for line in error_tail["lines"])
    assert any("ValueError: bad" in line for line in error_tail["lines"])
    assert not any("INFO" in line or "DEBUG" in line for line in error_tail["lines"])

    warn_tail = read_log_tail(log_dir, "agent.log", 10, "WARN")
    assert warn_tail["level"] == "WARNING"
    assert warn_tail["lines"] == []

    raw_tail = read_log_tail(log_dir, "agent.log", 10)
    assert raw_tail["level"] == ""
    assert any("debug detail" in line for line in raw_tail["lines"])

    with pytest.raises(ValueError):
        read_log_tail(log_dir, "agent.log", 10, "NOPE")


def test_redaction_filter():
    from assistant_agent.logging_setup import RedactionFilter

    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "mysql+pymysql://root:root@host/db Authorization: Bearer abc123 "
        "api_key=secret sk-1234567890",
        (),
        None,
    )
    RedactionFilter().filter(record)
    text = record.getMessage()
    assert "root:root" not in text
    assert "abc123" not in text
    assert "secret" not in text
    assert "sk-1234567890" not in text
    assert "mysql+pymysql://***@host/db" in text
