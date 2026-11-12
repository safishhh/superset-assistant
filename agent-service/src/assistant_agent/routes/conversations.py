from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..auth import UserContext, get_user

router = APIRouter()


class FeedbackRequest(BaseModel):
    conversation_id: str
    turn_index: int = Field(ge=1)
    rating: Literal["up", "down"] | None = None
    comment: str = ""


@router.get("/api/conversations")
async def list_user_conversations(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: UserContext = Depends(get_user),
) -> dict:
    return request.app.state.admin_store.list_conversations(
        username=user.username,
        include_deleted=False,
        page=page,
        page_size=page_size,
    )


@router.get("/api/conversations/{conversation_id}/export")
async def export_user_conversation(
    conversation_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
):
    exported = request.app.state.admin_store.export_markdown(
        user.username, conversation_id
    )
    if exported is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    markdown, filename = exported
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="conversation-{conversation_id}.md"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/api/runs/active")
async def active_run(
    conversation_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    run = request.app.state.runs.active_for(conversation_id, user.username)
    return {"run": run.snapshot() if run else None}


@router.get("/api/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    run = request.app.state.runs.get(run_id)
    if run is None or run.username != user.username:
        raise HTTPException(status_code=404, detail="run not found")
    return run.snapshot()


@router.post("/api/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    run = request.app.state.runs.get(run_id)
    if run is None or run.username != user.username:
        raise HTTPException(status_code=404, detail="run not found")
    stopped = False
    if run.status == "running" and run.task is not None and not run.task.done():
        run.task.cancel()
        stopped = True
        request.app.state.audit.log(
            "chat_stop",
            user=user.username,
            conversation_id=run.conversation_id,
            run_id=run.run_id,
        )
    return {"stopped": stopped, "status": run.status, "run": run.snapshot()}


@router.get("/api/conversations/{conversation_id}")
async def get_user_conversation(
    conversation_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    detail = request.app.state.admin_store.get_conversation(
        conversation_id, include_deleted=False
    )
    if detail is None or detail["username"] != user.username:
        raise HTTPException(status_code=404, detail="conversation not found")
    return detail


@router.delete("/api/conversations/{conversation_id}")
async def delete_user_conversation(
    conversation_id: str,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    deleted = request.app.state.admin_store.soft_delete_conversation(
        user.username, conversation_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")
    request.app.state.audit.log(
        "conversation.deleted",
        user=user.username,
        conversation_id=conversation_id,
        soft=True,
    )
    return {"ok": True}


@router.get("/api/feedback")
async def get_feedback(
    request: Request,
    conversation_id: str = Query(..., min_length=1),
    user: UserContext = Depends(get_user),
) -> dict:
    return {
        "items": request.app.state.admin_store.get_feedback(
            user.username, conversation_id
        )
    }


@router.post("/api/feedback")
async def save_feedback(
    payload: FeedbackRequest,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    try:
        result = request.app.state.admin_store.upsert_feedback(
            user.username,
            payload.conversation_id,
            payload.turn_index,
            payload.rating,
            payload.comment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit.log(
        "feedback",
        user=user.username,
        conversation_id=payload.conversation_id,
        turn_index=payload.turn_index,
        rating=payload.rating,
    )
    return result
