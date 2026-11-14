"""The agent's connection to the trade server, over MCP (Streamable HTTP).

Every tool result comes back as plain Python data. Every failure comes back as
{"error": {"code", "message", "retryable"}} so the agent can explain it, never as a crash.

The trade server only lets a registered kitchen's agent in. Every HTTP request carries the
kitchen's mandate (X-Mandate) and a short session token signed with the agent's own key
(Authorization: Bearer). Both are added here, below the model, which never sees them.
"""

from __future__ import annotations

import json
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable

import httpx
import httpx2
import jwt
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from agent.identity import session_token

CLIENT_INFO = Implementation(name="valio-buyer-agent", version="0.1.0")
REFRESH_BEFORE_S = 60  # make a new session token when the current one has less than this left


class TradeServerUnreachable(RuntimeError):
    pass


class TradeServerRefused(TradeServerUnreachable):
    """The trade server answered, but would not let this agent in (401)."""


class AgentCredentials(httpx2.Auth):
    """Puts X-Mandate and a fresh Authorization: Bearer session token on every request.

    The token lives ttl_s seconds and is renewed before it runs out, so a long run (waiting
    for a person to approve) keeps working. on_token sees each new token, so the caller can
    add it to the values that are scrubbed from anything printed."""

    def __init__(self, mandate_token: str, key_file: Path, *, ttl_s: int = 600,
                 clock: Callable[[], float] = time.time,
                 on_token: Callable[[str], None] | None = None):
        self.mandate_token = mandate_token
        self.key_file = Path(key_file)
        self.ttl_s = ttl_s
        self.clock = clock
        self.on_token = on_token
        self._token: str | None = None
        self._expires = 0.0

    def headers(self) -> dict[str, str]:
        now = self.clock()
        if self._token is None or now >= self._expires - REFRESH_BEFORE_S:
            self._token = session_token(self.key_file, self.mandate_token, now=now, ttl_s=self.ttl_s)
            self._expires = jwt.decode(self._token, options={"verify_signature": False})["exp"]
            if self.on_token:
                self.on_token(self._token)
        return {"X-Mandate": self.mandate_token, "Authorization": f"Bearer {self._token}"}

    def auth_flow(self, request: httpx2.Request):
        try:
            request.headers.update(self.headers())
        except Exception:  # an unreadable key or mandate: the server refuses with a plain reason
            request.headers["X-Mandate"] = self.mandate_token
        yield request


class RefusalCatcher:
    """Remembers the trade server's plain reason when it answers 401. The MCP SDK only reports
    "Server returned an error response", which would hide why this agent was not let in."""

    def __init__(self):
        self.reason: str | None = None

    async def __call__(self, response: httpx2.Response) -> None:
        if response.status_code != 401:
            return
        try:
            await response.aread()
            body = response.json()
            self.reason = f"{body['message']} ({body['code']})"
        except Exception:
            self.reason = "The trade server refused this agent (401 Unauthorized)."


class MandateRefused(RuntimeError):
    """The trade server did not accept the mandate. Carries its reason and the onboarding link."""

    def __init__(self, code: str, message: str, onboarding_url: str | None = None):
        super().__init__(message)
        self.code, self.message, self.onboarding_url = code, message, onboarding_url


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
    """`async with TradeLink(url, mandate_token) as link: await link.call("search_products", {...})`

    The kitchen's mandate travels in X-Mandate on every request. With the agent's key file,
    a short session token signed by that key goes beside it as Authorization: Bearer, which
    the trade server requires. The AI model never sees either.
    """

    def __init__(self, url: str, mandate_token: str = "", *, timeout_s: float = 60,
                 agent_key_file: Path | None = None, on_token: Callable[[str], None] | None = None):
        self.url = url
        self.token = mandate_token
        self.timeout_s = timeout_s
        self.credentials = (AgentCredentials(mandate_token, agent_key_file, on_token=on_token)
                            if mandate_token and agent_key_file else None)
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Mandate": self.token} if self.token else {}

    async def _check_mandate(self) -> None:
        """Ask the server whether it accepts the mandate, to learn why if it does not.

        The MCP client only reports that the connection failed. A server without this
        endpoint, or one that is down, is left for the connection attempt to report.
        """
        base = self.url.rstrip("/").removesuffix("/mcp")
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                response = await http.get(f"{base}/mandate", headers=self._headers())
        except httpx.HTTPError:
            return
        if response.status_code != 401:
            return
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("code"):
            raise MandateRefused(str(body["code"]),
                                 str(body.get("message") or "The mandate was not accepted."),
                                 body.get("onboarding_url"))

    async def __aenter__(self) -> "TradeLink":
        await self._check_mandate()
        self._stack = AsyncExitStack()
        refusal = RefusalCatcher()
        try:
            http = await self._stack.enter_async_context(httpx2.AsyncClient(
                headers=self._headers(), auth=self.credentials,
                timeout=httpx2.Timeout(30.0, read=300.0)))
            http.event_hooks["response"].append(refusal)
            client = Client(streamable_http_client(self.url, http_client=http),
                            client_info=CLIENT_INFO, read_timeout_seconds=self.timeout_s)
            self._client = await self._stack.enter_async_context(client)
        except BaseException as exc:  # connection errors arrive wrapped in exception groups
            await self._stack.aclose()
            if refusal.reason:
                raise TradeServerRefused(f"The trade server at {self.url} refused this agent: "
                                         f"{refusal.reason}") from exc
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
