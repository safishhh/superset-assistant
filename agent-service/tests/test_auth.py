from __future__ import annotations

import time

import jwt
import pytest

from assistant_agent.auth import AuthError, verify_token
from assistant_agent.config import Settings


TEST_SECRET = "0123456789abcdef0123456789abcdef"


def make_settings() -> Settings:
    return Settings(
        mcp_url="http://mcp/mcp",
        mcp_jwt_secret=TEST_SECRET,
        mcp_jwt_issuer="assistant",
        mcp_jwt_audience="superset-mcp",
        audit_path=pytest.importorskip("pathlib").Path("/tmp/audit.jsonl"),
    )


def token(**overrides):
    now = int(time.time())
    claims = {
        "sub": "east",
        "roles": ["sales_east"],
        "iss": "assistant",
        "aud": "superset-mcp",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, TEST_SECRET, algorithm="HS256")


def test_verify_token_roundtrip():
    user = verify_token(token(), make_settings())
    assert user.username == "east"
    assert user.roles == ("sales_east",)
    assert user.is_admin is False


def test_verify_token_rejects_wrong_audience():
    with pytest.raises(AuthError):
        verify_token(token(aud="other"), make_settings())


def test_verify_token_rejects_expired():
    with pytest.raises(AuthError):
        verify_token(token(exp=int(time.time()) - 1), make_settings())


def test_verify_token_admin():
    user = verify_token(token(sub="admin", roles=["Admin"]), make_settings())
    assert user.is_admin is True
