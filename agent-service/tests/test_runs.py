from __future__ import annotations

import time

from assistant_agent.runs import ActiveRun, RunRegistry


def make_run(run_id: str = "r1", conversation_id: str = "c1", status: str = "running"):
    run = ActiveRun(
        run_id=run_id,
        conversation_id=conversation_id,
        username="alice",
        model="m",
        employee="Atlas",
        question="q",
    )
    if status != "running":
        run.finish(status)
    return run


def test_active_for_matches_running_only():
    registry = RunRegistry()
    done = make_run("done", "c1", "ok")
    registry.add(done)
    assert registry.active_for("c1", "alice") is None

    running = make_run("live", "c1")
    registry.add(running)
    assert registry.active_for("c1", "alice") is running
    assert registry.active_for("c1", "bob") is None
    assert registry.active_for("c2", "alice") is None


def test_snapshot_fields():
    run = make_run("r1")
    run.text = "半句"
    run.tool_calls = 2
    snapshot = run.snapshot()
    assert snapshot["run_id"] == "r1"
    assert snapshot["status"] == "running"
    assert snapshot["text"] == "半句"
    assert snapshot["tool_calls"] == 2
    assert snapshot["question"] == "q"
    assert snapshot["elapsed_ms"] >= 0

    run.finish("ok")
    after = run.snapshot()
    assert after["status"] == "ok"
    assert after["finished_at"] > 0


def test_purge_drops_stale_and_overflow():
    registry = RunRegistry()
    old = make_run("old")
    old.finish("ok")
    old.finished_at = time.monotonic() - registry.keep_seconds - 5
    registry.add(old)
    registry.purge()
    assert registry.get("old") is None

    registry.max_runs = 3
    for index in range(5):
        run = make_run(f"r{index}")
        run.finish("ok")
        run.finished_at = time.monotonic() - 10 + index
        registry._runs[run.run_id] = run
    registry.purge()
    assert len(registry._runs) == 3
    assert "r0" not in registry._runs and "r1" not in registry._runs
