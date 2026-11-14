"""Who may call the MCP endpoint: only the agent of a registered kitchen.

Every HTTP request to /mcp carries two headers:

    X-Mandate: <the kitchen's signed mandate>
    Authorization: Bearer <agent session token>

The session token is a short EdDSA JWT signed with the agent's own key, the one whose public
half the mandate names in agent_key. Header kid = the mandate's agent_id. Claims:
aud "valio-aimo-trade", mandate_id (the mandate's), iat, and exp at most 15 minutes after iat.
Clocks may differ by up to 60 seconds. Plain code, no AI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import jwt

from server import signing

AUDIENCE = "valio-aimo-trade"
MAX_TTL_S = 15 * 60
LEEWAY_S = 60


class AgentTokenError(Exception):
    """The session token is not valid. The message is plain and never contains the token."""


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_session_token(token: str, mandate: dict, now: datetime) -> None:
    """Raises AgentTokenError unless the mandate's agent key signed a current token for it."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise AgentTokenError("the agent token is not a readable signed token")
    if header.get("alg") != signing.ALGORITHM:
        raise AgentTokenError("the agent token must be signed with EdDSA")
    if header.get("kid") != mandate.get("agent_id"):
        raise AgentTokenError("the agent token names a different agent from the mandate")
    try:
        claims = jwt.decode(token, signing.load_public(mandate["agent_key"]),
                            algorithms=[signing.ALGORITHM], audience=AUDIENCE,
                            options={"verify_exp": False, "verify_iat": False, "verify_nbf": False})
    except jwt.InvalidAudienceError:
        raise AgentTokenError(f"the agent token is not meant for {AUDIENCE}")
    except jwt.MissingRequiredClaimError:
        raise AgentTokenError(f"the agent token must name its audience, {AUDIENCE}")
    except jwt.InvalidTokenError:
        raise AgentTokenError("the agent token was not signed by the agent key in the mandate")

    iat, exp = claims.get("iat"), claims.get("exp")
    if not (_number(iat) and _number(exp)):
        raise AgentTokenError("the agent token must say when it was made and when it expires")
    if exp - iat > MAX_TTL_S:
        raise AgentTokenError("the agent token is valid for more than 15 minutes")
    t = now.timestamp()
    if iat > t + LEEWAY_S:
        raise AgentTokenError("the agent token was made in the future")
    if exp < t - LEEWAY_S:
        raise AgentTokenError("the agent token has expired")
    if claims.get("mandate_id") != mandate.get("mandate_id"):
        raise AgentTokenError("the agent token is for a different mandate")
