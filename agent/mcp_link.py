"""The agent's connection to the trade server, over MCP (Streamable HTTP).

Every tool result comes back as plain Python data. Every failure comes back as
{"error": {"code", "message", "retryable"}} so the agent can explain it, never as a crash.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp import Client
from mcp.types import Implementation

CLIENT_INFO = Implementation(name="valio-buyer-agent", version="0.1.0")


class TradeServerUnreachable(RuntimeError):
    pass


def _error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _as_error(data: Any) -> dict[str, Any] | None:
    """Contract B errors look like {code, message, retryable}, possibly wrapped in "error"."""
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        data = data["error"]
    if isinstance(data, dict) and {"code", "message"} <= data.keys() and len(data) <= 4:
        return _error(str(data["code"]), str(data["message"]), bool(data.get("retryable", False)))
    return None


def _text_of(result) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content if getattr(c, "text", None))


def parse_result(result) -> Any:
    text = _text_of(result)
    if result.is_error:
        # The SDK prefixes messages ("Error executing tool x: {...}"), so look for the JSON part.
        start = text.find("{")
        if start >= 0:
            try:
                return _as_error(json.loads(text[start:])) or _error("tool_error", text)
            except ValueError:
                pass
        return _error("tool_error", text or "The tool failed without a message.")
    data = result.structured_content
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            return text
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]  # MCP wraps non-object results as {"result": ...}
    return _as_error(data) or data


class TradeLink:
    """`async with TradeLink(url) as link: await link.call("search_products", {...})`"""

    def __init__(self, url: str, *, timeout_s: float = 60):
        self.url = url
        self.timeout_s = timeout_s
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None

    async def __aenter__(self) -> "TradeLink":
        self._stack = AsyncExitStack()
        try:
            client = Client(self.url, client_info=CLIENT_INFO, read_timeout_seconds=self.timeout_s)
            self._client = await self._stack.enter_async_context(client)
        except BaseException as exc:  # connection errors arrive wrapped in exception groups
            await self._stack.aclose()
            raise TradeServerUnreachable(
                f"Cannot reach the trade server at {self.url}. Is it running? ({type(exc).__name__})"
            ) from exc
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack:
            await self._stack.aclose()

    async def tool_names(self) -> list[str]:
        listing = await self._client.list_tools()
        return [t.name for t in listing.tools]

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        """Call one tool. Retries once if the server says the error is retryable."""
        out: Any = None
        for _attempt in range(2):
            try:
                out = parse_result(await self._client.call_tool(tool, args))
            except Exception as exc:  # transport or protocol failure
                out = _error("transport_error", f"{type(exc).__name__}: {exc}", retryable=True)
            if not (isinstance(out, dict) and out.get("error", {}).get("retryable")):
                return out
        return out
