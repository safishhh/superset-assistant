from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx


class MCPError(RuntimeError):
    pass


class MCPAuthError(MCPError):
    pass


class MCPToolError(MCPError):
    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(f"{tool_name}: {message}")
        self.tool_name = tool_name
        self.message = message


def _parse_body(text: str, content_type: str) -> dict[str, Any]:
    if "text/event-stream" in content_type:
        candidates: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                candidates.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
        if not candidates:
            raise MCPError("MCP returned an empty event stream")
        return candidates[-1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPError(f"MCP returned non-JSON body: {text[:200]}") from exc


class MCPClient:
    """Thin per-request MCP client for the Superset MCP service.

    A new client is created for every tool call so the bearer token and
    connection state can never leak between users.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 120.0,
        on_call: Callable[[str, dict[str, Any], Any, str | None, int], None]
        | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.on_call = on_call
        self._request_id = 0

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        timeout = httpx.Timeout(
            connect=5.0,
            read=self.timeout,
            write=30.0,
            pool=5.0,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(self.url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise MCPError(f"MCP request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise MCPAuthError(f"MCP rejected the token ({response.status_code})")
        if response.status_code >= 400:
            raise MCPError(
                f"MCP HTTP {response.status_code}: {response.text[:300]}"
            )

        body = _parse_body(
            response.text,
            response.headers.get("content-type", ""),
        )
        if "error" in body:
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise MCPError(f"MCP error: {message}")
        return body.get("result")

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        log_extra: dict[str, Any] | None = None,
    ) -> Any:
        started = time.perf_counter()
        try:
            result = await self._rpc(
                "tools/call",
                {
                    "name": "call_tool",
                    "arguments": {
                        "name": name,
                        "arguments": arguments or {},
                    },
                },
            )
            data = self._unwrap(name, result)
            audit_data = data
            if log_extra:
                # 只写进审计副本（如中文别名），不改模型看到的结果
                audit_data = (
                    {**data, **log_extra}
                    if isinstance(data, dict)
                    else {"result": data, **log_extra}
                )
            # 宿主把语义失败放在返回体里（HTTP 200 + {"error": ...}），
            # 不判一下就会在审计里记成成功
            audit_error = (
                str(data["error"])
                if isinstance(data, dict) and data.get("error")
                else None
            )
            self._notify(name, arguments or {}, audit_data, audit_error, started)
            return data
        except Exception as exc:
            self._notify(name, arguments or {}, None, str(exc), started)
            raise

    def _notify(
        self,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        error: str | None,
        started: float,
    ) -> None:
        if self.on_call is None:
            return
        try:
            self.on_call(
                name,
                arguments,
                result,
                error,
                int((time.perf_counter() - started) * 1000),
            )
        except Exception:  # noqa: BLE001
            # Audit failures must not break the actual tool call.
            pass

    async def list_tools(self) -> list[dict[str, Any]]:
        """标准 tools/list：包含 search_tools 不返回的常驻工具（如 health_check）。"""
        result = await self._rpc("tools/list", {})
        if isinstance(result, dict):
            tools = result.get("tools")
            if isinstance(tools, list):
                return [item for item in tools if isinstance(item, dict)]
        return []

    async def search_tools(self, query: str | None = None) -> Any:
        result = await self._rpc(
            "tools/call",
            {
                "name": "search_tools",
                "arguments": {"query": query} if query else {},
            },
        )
        data = self._unwrap("search_tools", result)
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return data

    @staticmethod
    def _unwrap(tool_name: str, result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        content = result.get("content") or []
        texts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        text = "\n".join(part for part in texts if part)
        if result.get("isError"):
            raise MCPToolError(tool_name, text or "tool returned an error")
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
