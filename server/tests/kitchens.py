"""Shared test helpers: a registered kitchen with its own agent key, and the /mcp headers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from agent.identity import ensure_agent_key, key_path, session_token
from server import signing
from server.service import Service


@dataclass
class Kitchen:
    buyer_id: str
    mandate_token: str
    agent_key_file: Path
    mandate: dict

    def headers(self, **token_args) -> dict[str, str]:
        """The two headers every request to /mcp must carry."""
        return mcp_headers(self.mandate_token, self.agent_key_file, **token_args)


def mcp_headers(mandate_token: str, agent_key_file: Path, **token_args) -> dict[str, str]:
    return {"X-Mandate": mandate_token,
            "Authorization": f"Bearer {session_token(agent_key_file, mandate_token, **token_args)}"}


def register_kitchen(svc: Service, buyer_id: str, name: str, buyers_dir: Path,
                     agent_key: bool = True) -> Kitchen:
    """Sign a kitchen up the way onboarding does: its own key, a mandate naming its agent's key."""
    agent_pem = ensure_agent_key(buyer_id, buyers_dir)
    mandate = {
        "mandate_id": f"mnd_{buyer_id}_001",
        "buyer": name,
        "agent_id": f"agent-{buyer_id}",
        "valid_until": (date.today() + timedelta(days=365)).isoformat(),
        "auto_approve": {"max_order_eur": 500, "allowed_categories": ["10400"]},
        "substitution": {"allowed": True, "must_keep": [], "max_price_increase_pct": 10},
        "hard_rules": {"blocked_allergens": [], "unknown_allergens": "human",
                       "no_delivery_after": "need_by_date"},
        "approvers": [f"owner@{buyer_id}.example"],
    }
    if agent_key:
        mandate["agent_key"] = agent_pem
    key = signing.generate_key()
    token = signing.sign(mandate, key, kid=buyer_id)
    status, body = svc.register_buyer(signing.public_pem(key.public_key()), token)
    assert status == 201, body
    return Kitchen(buyer_id, token, key_path(buyer_id, buyers_dir), mandate)
