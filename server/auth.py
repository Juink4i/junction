"""The mandate is shown to connect: every /mcp request carries it as a bearer token.

A copied token can search and quote. It cannot order when the mandate names an agent key,
because the agent signs each order. Production path: OAuth 2.1 with proof of possession.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

ONBOARDING_URL = os.environ.get("ONBOARDING_URL", "http://localhost:8080/onboarding")


def bearer_token(headers: Mapping[str, str] | None) -> str | None:
    """The token in an Authorization header, or None."""
    value = (headers.get("authorization") if headers else None) or ""
    scheme, _, token = value.partition(" ")
    return (token.strip() or None) if scheme.lower() == "bearer" else None


def refusal(code: str, message: str) -> dict[str, Any]:
    """What an agent gets when its mandate is not accepted: the reason and where to fix it."""
    return {"code": code, "message": message, "retryable": False, "onboarding_url": ONBOARDING_URL}


class RequireMandate:
    """ASGI middleware. A request to /mcp without a valid mandate gets 401 and the refusal.

    `check(token)` returns None when the mandate is accepted, or the refusal to send.
    """

    def __init__(self, app: ASGIApp, check: Callable[[str | None], dict[str, Any] | None],
                 path: str = "/mcp"):
        self.app, self.check, self.path = app, check, path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        guarded = (scope["type"] == "http" and scope["path"].rstrip("/") == self.path
                   and scope["method"] != "OPTIONS")
        if guarded:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            # In a thread: the check takes the service's lock, which a slow quote may hold.
            problem = await run_in_threadpool(self.check, bearer_token(headers))
            if problem:
                response = JSONResponse(problem, status_code=401,
                                        headers={"WWW-Authenticate": 'Bearer realm="valio-aimo-trade"'})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
