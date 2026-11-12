from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any


class UserRateLimiter:
    """Per-process sliding-window limiter; DB daily quotas are the durable cap."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, username: str, per_minute: int) -> bool:
        if per_minute <= 0:
            return True
        now = time.monotonic()
        cutoff = now - 60
        async with self._lock:
            events = self._events[username]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= per_minute:
                return False
            events.append(now)
            return True


def daily_quota_error(
    usage: dict[str, Any],
    *,
    request_limit: int,
    token_limit: int,
    cost_limit: float,
) -> str | None:
    requests = int(usage.get("requests") or 0)
    tokens = int(usage.get("tokens") or 0)
    cost = float(usage.get("cost") or 0)
    if request_limit > 0 and requests >= request_limit:
        return f"今日请求额度已用完（{request_limit} 次），请明天再试或联系管理员"
    if token_limit > 0 and tokens >= token_limit:
        return f"今日 Token 额度已用完（{token_limit:,}），请明天再试或联系管理员"
    if cost_limit > 0 and cost >= cost_limit:
        return f"今日成本额度已用完（${cost_limit:.2f}），请明天再试或联系管理员"
    return None
