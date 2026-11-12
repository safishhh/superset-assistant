import logging
import time
import uuid
from urllib.parse import quote

import jwt
from flask import current_app, g, redirect, request
from flask_appbuilder.api import expose, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

logger = logging.getLogger(__name__)


@api(
    id="assistant_api",
    name="Assistant API",
    description="Short-lived identity tokens for the Superset assistant",
)
class AssistantAPI(RestApi):
    openapi_spec_tag = "Assistant"
    # token 只要求登录态；是否可用 AI 助手由 AI 管理后台的用户开关决定，
    # 不再依赖 Superset 的 can_use on assistant 权限。
    class_permission_name = "assistant"
    method_permission_name = {
        "admin_ticket": "admin_ticket",
        "admin_redirect": "admin_redirect",
    }

    def _issue_admin_ticket(self, user):
        roles = sorted(role.name for role in user.roles)
        if "Admin" not in roles:
            return None, "Admin role required", 403
        secret = current_app.config.get("ADMIN_TICKET_SECRET", "")
        if not secret:
            return None, "ADMIN_TICKET_SECRET is not configured", 500
        now = int(time.time())
        claims = {
            "sub": user.username,
            "roles": roles,
            "scope": "admin",
            "iss": current_app.config.get("ADMIN_TICKET_ISSUER", "assistant"),
            "aud": current_app.config.get("ADMIN_TICKET_AUDIENCE", "assistant-admin"),
            "iat": now,
            "exp": now + 60,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(claims, secret, algorithm="HS256"), None, 200

    def _admin_url(self) -> str:
        configured = current_app.config.get("ASSISTANT_ADMIN_URL", "")
        if configured:
            return configured.rstrip("/")
        host = request.host.split(":")[0]
        port = current_app.config.get("ASSISTANT_AGENT_PORT", 28088)
        return f"{request.scheme}://{host}:{port}/admin"

    @expose("/token", methods=("GET",))
    @safe
    def token(self):
        """Issue a short-lived token bound to the current Superset user."""
        user = g.user
        if user is None or not getattr(user, "username", None):
            return self.response(401, message="Not authenticated")

        now = int(time.time())
        ttl = int(current_app.config.get("MCP_TOKEN_TTL", 300))
        roles = sorted(role.name for role in user.roles)
        claims = {
            "sub": user.username,
            "roles": roles,
            "iss": current_app.config.get("MCP_JWT_ISSUER", "assistant"),
            "aud": current_app.config.get("MCP_JWT_AUDIENCE", "superset-mcp"),
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(
            claims,
            current_app.config["MCP_JWT_SECRET"],
            algorithm=current_app.config.get("MCP_JWT_ALGORITHM", "HS256"),
        )
        logger.info("issued assistant token for user=%s roles=%s", user.username, roles)
        return self.response(
            200,
            result={
                "token": token,
                "expires_in": ttl,
                "username": user.username,
                "roles": roles,
                "agent_port": current_app.config.get("ASSISTANT_AGENT_PORT", 28088),
            },
        )

    @expose("/admin-ticket", methods=("GET",))
    @protect()
    @safe
    def admin_ticket(self):
        """Issue a one-time, 60-second ticket for the AI admin console."""
        user = g.user
        if user is None or not getattr(user, "username", None):
            return self.response(401, message="Not authenticated")
        ticket, error, status = self._issue_admin_ticket(user)
        if error:
            return self.response(status, message=error)
        logger.info("issued admin ticket for user=%s", user.username)
        return self.response(
            200,
            result={
                "ticket": ticket,
                "expires_in": 60,
                "admin_url": self._admin_url(),
            },
        )

    @expose("/admin-redirect", methods=("GET",))
    @protect()
    @safe
    def admin_redirect(self):
        """Mint a ticket and redirect the browser to the AI admin console."""
        user = g.user
        if user is None or not getattr(user, "username", None):
            return self.response(401, message="Not authenticated")
        ticket, error, status = self._issue_admin_ticket(user)
        if error:
            return self.response(status, message=error)
        logger.info("redirecting admin console for user=%s", user.username)
        return redirect(f"{self._admin_url()}#ticket={quote(ticket)}")

