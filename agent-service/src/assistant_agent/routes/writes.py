from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..admin.db import utcnow
from ..api_shared import (
    _ensure_pending,
    _write_action_for_user,
    _write_client,
)
from ..audit import AuditLogger
from ..auth import UserContext, get_user
from ..config import settings
from ..write_actions import execute_plan

router = APIRouter()


class ConfirmAllWriteActionsRequest(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=64)
    action_ids: list[str] = Field(default_factory=list, max_length=50)


@router.get("/api/write-actions/pending")
async def list_pending_write_actions(
    request: Request,
    conversation_id: str = Query(..., min_length=8, max_length=64),
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    items = store.list_pending_write_actions(
        username=user.username,
        conversation_id=conversation_id,
    )
    return {
        "items": [
            {
                "id": item["id"],
                "action_type": item["action_type"],
                "risk_level": item["risk_level"],
                "summary": item["summary"],
                "expires_at": item["expires_at"],
            }
            for item in items
        ]
    }


@router.post("/api/write-actions/confirm-all")
async def confirm_all_write_actions(
    payload: ConfirmAllWriteActionsRequest,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    pending = store.list_pending_write_actions(
        username=user.username,
        conversation_id=payload.conversation_id,
    )
    if payload.action_ids:
        wanted = set(payload.action_ids)
        actions = [item for item in pending if item["id"] in wanted]
        if len(actions) != len(wanted):
            raise HTTPException(
                status_code=409,
                detail="有写操作已变更状态或已过期，请刷新后重试",
            )
    else:
        actions = pending
    if not actions:
        raise HTTPException(status_code=409, detail="没有可执行的待确认写操作")

    batch_id = str(uuid.uuid4())
    audit: AuditLogger = request.app.state.audit
    audit.log(
        "write_batch_started",
        user=user.username,
        conversation_id=payload.conversation_id,
        batch_id=batch_id,
        action_ids=[item["id"] for item in actions],
    )
    client = _write_client(settings, user)
    results: list[dict[str, Any]] = []
    executed = 0
    failed = 0
    for action in actions:
        action_id = action["id"]
        current = store.get_write_action(action_id, username=user.username)
        if current is None or current["status"] != "pending":
            failed += 1
            results.append(
                {
                    "action_id": action_id,
                    "status": "skipped",
                    "error": "写操作状态已变化，未执行",
                }
            )
            audit.log(
                "write_batch_skipped",
                user=user.username,
                batch_id=batch_id,
                action_id=action_id,
            )
            break
        try:
            result, rollback = await execute_plan(
                client,
                current["action_type"],
                current["plan"],
                current["snapshot"] or {},
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or "写操作执行失败"
            updated = store.update_write_action(
                action_id,
                status="failed",
                error=message,
                executed_at=utcnow(),
            )
            failed += 1
            results.append(
                {
                    "action_id": action_id,
                    "status": "failed",
                    "error": message,
                    "expires_at": (updated or current).get("expires_at"),
                }
            )
            audit.log(
                "write_failed",
                user=user.username,
                batch_id=batch_id,
                action_id=action_id,
                error=message,
            )
            break
        updated = store.update_write_action(
            action_id,
            status="executed",
            result=result,
            rollback=rollback,
            executed_at=utcnow(),
        )
        executed += 1
        results.append(
            {
                "action_id": action_id,
                "status": "executed",
                "result": result,
                "rollback": rollback,
                "expires_at": (updated or current).get("expires_at"),
            }
        )
        audit.log(
            "write_executed",
            user=user.username,
            batch_id=batch_id,
            action_id=action_id,
            action_type=current["action_type"],
            risk_level=current["risk_level"],
            rollback_available=rollback is not None,
        )
    remaining = len(actions) - len(results)
    audit.log(
        "write_batch_completed",
        user=user.username,
        conversation_id=payload.conversation_id,
        batch_id=batch_id,
        executed=executed,
        failed=failed,
        remaining=remaining,
    )
    return {
        "results": results,
        "executed": executed,
        "failed": failed,
        "remaining": remaining,
    }


@router.get("/api/write-actions/{action_id}")
async def get_write_action(
    action_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    return _write_action_for_user(request, action_id, user)


@router.post("/api/write-actions/{action_id}/confirm")
async def confirm_write_action(
    action_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    action = _write_action_for_user(request, action_id, user)
    _ensure_pending(action)
    client = _write_client(settings, user)
    try:
        result, rollback = await execute_plan(
            client,
            action["action_type"],
            action["plan"],
            action["snapshot"] or {},
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "写操作执行失败"
        store.update_write_action(
            action_id,
            status="failed",
            error=message,
            executed_at=utcnow(),
        )
        request.app.state.audit.log(
            "write_failed",
            user=user.username,
            action_id=action_id,
            error=message,
        )
        raise HTTPException(status_code=400, detail=message) from exc

    updated = store.update_write_action(
        action_id,
        status="executed",
        result=result,
        rollback=rollback,
        executed_at=utcnow(),
    )
    request.app.state.audit.log(
        "write_executed",
        user=user.username,
        action_id=action_id,
        action_type=action["action_type"],
        risk_level=action["risk_level"],
        rollback_available=rollback is not None,
    )
    return updated or action


@router.post("/api/write-actions/{action_id}/cancel")
async def cancel_write_action(
    action_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    action = _write_action_for_user(request, action_id, user)
    _ensure_pending(action)
    updated = store.update_write_action(
        action_id,
        status="cancelled",
        error="cancelled by user",
    )
    request.app.state.audit.log(
        "write_cancelled",
        user=user.username,
        action_id=action_id,
    )
    return updated or action


@router.post("/api/write-actions/{action_id}/rollback")
async def rollback_write_action(
    action_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    action = _write_action_for_user(request, action_id, user)
    if action["status"] != "executed":
        raise HTTPException(
            status_code=409,
            detail=f"写操作当前状态为 {action['status']}，不能回滚",
        )
    rollback = action.get("rollback")
    if not isinstance(rollback, dict):
        raise HTTPException(status_code=409, detail="该写操作没有可用的回滚方案")
    # 回滚有两种形状：单步 {tool, arguments} 与复合 {steps: [...]}
    steps: list[dict[str, Any]] = []
    if isinstance(rollback.get("steps"), list):
        steps = [step for step in rollback["steps"] if isinstance(step, dict) and step.get("tool")]
    elif rollback.get("tool"):
        steps = [{"tool": rollback["tool"], "arguments": rollback.get("arguments") or {}}]
    if not steps:
        raise HTTPException(status_code=409, detail="该写操作没有可用的回滚方案")
    client = _write_client(settings, user)
    results: list[Any] = []
    try:
        for index, step in enumerate(steps, start=1):
            result = await client.call_tool(
                str(step["tool"]),
                step.get("arguments") or {},
            )
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(f"第 {index} 步 {step['tool']} 失败：{result['error']}")
            results.append({"tool": step["tool"], "result": result})
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or "回滚失败"
        store.update_write_action(
            action_id,
            status="rollback_failed",
            error=f"{message}（已完成 {len(results)}/{len(steps)} 步）",
        )
        request.app.state.audit.log(
            "write_rollback_failed",
            user=user.username,
            action_id=action_id,
            error=message,
            completed_steps=len(results),
            total_steps=len(steps),
        )
        raise HTTPException(status_code=400, detail=message) from exc

    updated = store.update_write_action(
        action_id,
        status="rolled_back",
        result={"rollback_steps": results},
        rolled_back_at=utcnow(),
    )
    request.app.state.audit.log(
        "write_rolled_back",
        user=user.username,
        action_id=action_id,
        action_type=action["action_type"],
    )
    return updated or action
