#!/usr/bin/env python3
"""Run the golden question set against a live Agent and report tool selection."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from smoke_chat import chat, env

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "scripts" / "golden_questions.json"
REPORT = ROOT / "infra" / "runtime" / "golden-eval-latest.json"


def tool_names(events: list[dict]) -> list[str]:
    names: list[str] = []
    for event in events:
        name = event.get("toolName")
        if event.get("type") in ("tool-input-start", "tool-input-available") and name:
            if name not in names:
                names.append(name)
    return names


def answer_text(events: list[dict]) -> str:
    return "".join(
        event.get("delta", "")
        for event in events
        if event.get("type") == "text-delta"
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--username", default="")
    parser.add_argument("--roles", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    values = env()
    questions = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if args.limit:
        questions = questions[: args.limit]

    results = []
    failures = 0
    for item in questions:
        username = args.username or item.get("username") or "admin"
        roles = (
            [role.strip() for role in args.roles.split(",") if role.strip()]
            if args.roles
            else item.get("roles") or ["Admin"]
        )
        try:
            events = chat(values, username, roles, item["question"])
            used = tool_names(events)
            expected = item.get("expected_tools") or []
            passed = all(name in used for name in expected)
            errors = [
                event.get("errorText")
                for event in events
                if event.get("type") in ("error", "tool-output-error")
            ]
            results.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "username": username,
                    "expected_tools": expected,
                    "used_tools": used,
                    "passed": passed,
                    "errors": [error for error in errors if error],
                    "answer_preview": answer_text(events)[:300],
                }
            )
            if not passed:
                failures += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            results.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "username": username,
                    "expected_tools": item.get("expected_tools") or [],
                    "used_tools": [],
                    "passed": False,
                    "errors": [str(exc)],
                    "answer_preview": "",
                }
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": len(results) - failures,
        "failed": failures,
        "results": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in results:
            status = "PASS" if item["passed"] else "FAIL"
            print(
                f"{status} {item['id']}: used={item['used_tools']} "
                f"expected={item['expected_tools']} errors={item['errors']}"
            )
        print(
            f"\n{report['passed']}/{report['total']} passed; report: {REPORT}"
        )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
