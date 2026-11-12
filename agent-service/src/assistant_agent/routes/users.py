from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..admin.store import AdminStore
from ..auth import UserContext, get_user

router = APIRouter()


@router.get("/api/models")
async def list_chat_models(
    request: Request,
    _user: UserContext = Depends(get_user),
) -> dict:
    return {"items": request.app.state.admin_store.list_enabled_models()}


@router.get("/api/me")
async def me(
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    employees = store.list_employees_for_user(user.username, list(user.roles))
    return {
        "username": user.username,
        "roles": list(user.roles),
        "can_admin": "Admin" in user.roles,
        "ai_enabled": store.user_ai_enabled(user.username),
        "has_employees": bool(employees),
    }


@router.get("/api/employees")
async def list_employees(
    request: Request,
    user: UserContext = Depends(get_user),
) -> dict:
    store: AdminStore = request.app.state.admin_store
    items = store.list_employees_for_user(user.username, list(user.roles))
    return {
        "items": [
            {
                "id": item["id"],
                "username": item["username"],
                "nickname": item["nickname"],
                "title": item["title"],
                "avatar": item["avatar"],
                "intro": item["intro"],
                "greeting": item["greeting"],
                "model_id": item.get("model_id"),
                "model_ids": item.get("model_ids"),
            }
            for item in items
        ],
    }
