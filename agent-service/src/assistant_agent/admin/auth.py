from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import Settings
from .store import AdminStore

SESSION_COOKIE = "sa_admin_session"
CSRF_COOKIE = "sa_admin_csrf"
SESSION_SALT = "sa-admin-session"


@dataclass(frozen=True)
class AdminIdentity:
    username: str
    roles: tuple[str, ...]


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    if not settings.admin_session_secret:
        raise RuntimeError("ADMIN_SESSION_SECRET is required")
    return URLSafeTimedSerializer(settings.admin_session_secret, salt=SESSION_SALT)


def verify_admin_ticket(
    ticket: str,
    settings: Settings,
    store: AdminStore,
) -> AdminIdentity:
    if not settings.admin_ticket_secret:
        raise HTTPException(status_code=500, detail="admin ticket secret missing")
    try:
        claims = jwt.decode(
            ticket,
            settings.admin_ticket_secret,
            algorithms=["HS256"],
            audience=settings.admin_ticket_audience,
            issuer=settings.admin_ticket_issuer,
            options={"require": ["sub", "iss", "aud", "exp", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="admin ticket expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid admin ticket") from exc
    if claims.get("scope") != "admin":
        raise HTTPException(status_code=403, detail="admin scope required")
    roles = claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if "Admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    jti = str(claims.get("jti") or "")
    if not jti or not store.consume_ticket(jti):
        raise HTTPException(status_code=401, detail="admin ticket already used")
    return AdminIdentity(
        username=str(claims["sub"]),
        roles=tuple(str(role) for role in roles),
    )


def create_session_cookie(
    response: Response,
    identity: AdminIdentity,
    settings: Settings,
) -> str:
    serializer = _serializer(settings)
    value = serializer.dumps(
        {"sub": identity.username, "roles": list(identity.roles)}
    )
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=settings.admin_session_ttl,
        path="/admin",
        httponly=True,
        samesite="lax",
        secure=settings.admin_cookie_secure,
    )
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.admin_session_ttl,
        path="/admin",
        httponly=False,
        samesite="lax",
        secure=settings.admin_cookie_secure,
    )
    return csrf


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    response.delete_cookie(CSRF_COOKIE, path="/admin")


def read_session(request: Request, settings: Settings) -> AdminIdentity | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        payload = _serializer(settings).loads(
            raw, max_age=settings.admin_session_ttl
        )
    except (BadSignature, SignatureExpired):
        return None
    roles = payload.get("roles") or []
    if "Admin" not in roles:
        return None
    return AdminIdentity(username=str(payload["sub"]), roles=tuple(roles))


def get_store(request: Request) -> AdminStore:
    store = getattr(request.app.state, "admin_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="admin store unavailable")
    return store


def require_admin(
    request: Request,
    store: AdminStore = Depends(get_store),
) -> AdminIdentity:
    identity = read_session(request, request.app.state.settings)
    if identity is None:
        raise HTTPException(status_code=401, detail="admin session required")
    return identity


def require_csrf(
    request: Request,
    identity: AdminIdentity = Depends(require_admin),
) -> AdminIdentity:
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not header or not cookie or not secrets.compare_digest(header, cookie):
        raise HTTPException(status_code=403, detail="invalid csrf token")
    return identity


def as_dict(identity: AdminIdentity) -> dict[str, Any]:
    return {"username": identity.username, "roles": list(identity.roles)}
