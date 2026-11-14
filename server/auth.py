"""Reading who is calling: the kitchen's mandate in X-Mandate, the agent's token as a bearer.

AgentAuth in server/app.py lets a request reach /mcp only when the agent's session token was
signed by the key the mandate names. A copied mandate alone cannot connect.
Production path: OAuth 2.1 with proof of possession.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

ONBOARDING_URL = os.environ.get("ONBOARDING_URL", "http://localhost:8080/onboarding")


def bearer_token(headers: Mapping[str, str] | None) -> str | None:
    """The token in an Authorization header, or None."""
    value = (headers.get("authorization") if headers else None) or ""
    scheme, _, token = value.partition(" ")
    return (token.strip() or None) if scheme.lower() == "bearer" else None


def mandate_token(headers: Mapping[str, str] | None) -> str | None:
    """The kitchen's signed mandate in an X-Mandate header, or None."""
    return ((headers.get("x-mandate") if headers else None) or "").strip() or None


def refusal(code: str, message: str) -> dict[str, Any]:
    """What an agent gets when it is not let in: the reason and where to fix it."""
    return {"code": code, "message": message, "retryable": False, "onboarding_url": ONBOARDING_URL}
