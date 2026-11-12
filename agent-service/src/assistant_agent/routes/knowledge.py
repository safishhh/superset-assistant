from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..admin.store import KnowledgeQuotaError
from ..api_shared import _condense_content
from ..auth import UserContext, get_user

router = APIRouter()


class KnowledgeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    # raw = 原文照存；summarize = 先让模型精简再存（不合格自动退回原文）
    mode: Literal["raw", "summarize"] = "raw"


@router.get("/api/knowledge")
async def list_knowledge(
    request: Request,
    user: UserContext = Depends(get_user),
    tab: Literal["active", "trash"] = "active",
) -> dict:
    store: AdminStore = request.app.state.admin_store
    return {
        "items": store.list_knowledge(
            user.username, include_deleted=tab == "trash"
        ),
        "usage": store.knowledge_usage(user.username),
    }


@router.get("/api/knowledge/{knowledge_id}")
async def read_knowledge(
    knowledge_id: int,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    """取本人知识条目的完整正文（回答里点开“参考知识库”时用）。"""
    store: AdminStore = request.app.state.admin_store
    try:
        return store.get_knowledge(user.username, knowledge_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/employee-knowledge/{knowledge_id}")
async def read_employee_knowledge(
    knowledge_id: int,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    """取当前可用 AI 牛马的知识条目；该牛马不可用时视为不存在。"""
    store: AdminStore = request.app.state.admin_store
    try:
        item = store.get_employee_knowledge(knowledge_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="知识条目不存在") from exc
    allowed = {
        int(employee["id"])
        for employee in store.list_employees_for_user(
            user.username, list(user.roles or [])
        )
    }
    if int(item["employee_id"]) not in allowed:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    return item


@router.post("/api/knowledge")
async def save_knowledge(
    payload: KnowledgeRequest,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    content, condensed = (
        await _condense_content(store, payload.title, payload.content, user.username)
        if payload.mode == "summarize"
        else (payload.content, False)
    )
    try:
        item = store.upsert_knowledge(
            user.username, payload.title, content, source="manual"
        )
    except KnowledgeQuotaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit.log(
        "knowledge_saved",
        user=user.username,
        title=payload.title,
        source="manual",
        condensed=condensed,
    )
    return {**item, "condensed": condensed}


@router.put("/api/knowledge/{knowledge_id}")
async def update_knowledge(
    knowledge_id: int,
    payload: KnowledgeRequest,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    content, condensed = (
        await _condense_content(store, payload.title, payload.content, user.username)
        if payload.mode == "summarize"
        else (payload.content, False)
    )
    try:
        item = store.update_knowledge(
            user.username, knowledge_id, payload.title, content
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeQuotaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit.log(
        "knowledge_updated",
        user=user.username,
        knowledge_id=knowledge_id,
        condensed=condensed,
    )
    return {**item, "condensed": condensed}


@router.post("/api/knowledge/{knowledge_id}/restore")
async def restore_knowledge(
    knowledge_id: int,
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    try:
        item = store.restore_knowledge(user.username, knowledge_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeQuotaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit.log(
        "knowledge_restored",
        user=user.username,
        knowledge_id=knowledge_id,
    )
    return item


@router.delete("/api/knowledge/{knowledge_id}")
async def delete_knowledge(
    knowledge_id: int,
    request: Request,
    user: UserContext = Depends(get_user),
    purge: bool = False,
) -> dict:
    """默认软删（进回收站）；purge=true 只能对回收站里的条目彻底删除。"""
    store: AdminStore = request.app.state.admin_store
    try:
        if purge:
            store.purge_knowledge(user.username, knowledge_id)
        else:
            store.delete_knowledge(user.username, knowledge_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    request.app.state.audit.log(
        "knowledge_purged" if purge else "knowledge_deleted",
        user=user.username,
        knowledge_id=knowledge_id,
    )
    return {"deleted": True, "purged": purge}
