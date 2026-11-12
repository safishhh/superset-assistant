from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request

from .config import Settings


class AuthError(Exception):
    pass


def sign_mcp_token(
    settings: Settings,
    username: str,
    roles: tuple[str, ...] | list[str],
    *,
    ttl: int = 300,
    jti_prefix: str = "agent",
) -> str:
    """以某个 Superset 用户身份自签短命 MCP JWT（滑动续期，RBAC/RLS 不变）。"""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": username,
            "roles": list(roles),
            "iss": settings.mcp_jwt_issuer,
            "aud": settings.mcp_jwt_audience,
            "iat": now,
            "exp": now + max(30, int(ttl)),
            "jti": f"{jti_prefix}-{uuid.uuid4().hex[:12]}",
        },
        settings.mcp_jwt_secret,
        algorithm=settings.mcp_jwt_algorithm,
    )


@dataclass(frozen=True)
class UserContext:
    username: str
    roles: tuple[str, ...]
    token: str
    claims: dict[str, Any]

    @property
    def is_admin(self) -> bool:
        return "Admin" in self.roles


def verify_token(token: str, settings: Settings) -> UserContext:
    try:
        claims = jwt.decode(
            token,
            settings.mcp_jwt_secret,
            algorithms=[settings.mcp_jwt_algorithm],
            audience=settings.mcp_jwt_audience,
            issuer=settings.mcp_jwt_issuer,
            options={"require": ["sub", "iss", "aud", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    username = claims.get("sub")
    if not isinstance(username, str) or not username:
        raise AuthError("token has no subject")
    roles = claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return UserContext(
        username=username,
        roles=tuple(str(role) for role in roles),
        token=token,
        claims=claims,
    )


async def get_user(request: Request) -> UserContext:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return verify_token(token, request.app.state.settings)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
