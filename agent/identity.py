"""The agent's own key pair.

The private half never leaves the agent's side, and the AI model never sees it: tool code
signs each order. The public half goes into the kitchen's mandate, so the kitchen's own
signature says which agent may act for it.
"""

from __future__ import annotations

import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent import config

KEY_FILE = "agent_key.pem"


def key_path(buyer: str, buyers_dir: Path | None = None) -> Path:
    return (buyers_dir or config.BUYERS_DIR) / buyer / KEY_FILE


def ensure_agent_key(buyer: str, buyers_dir: Path | None = None) -> str:
    """Create this buyer's agent key if there is none. Returns the public half (PEM)."""
    path = key_path(buyer, buyers_dir)
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        path.chmod(0o600)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def sign_order(key_file: Path, mandate_token: str, quote_id: str) -> str:
    """The agent's signature over exactly this order."""
    key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
    mandate = jwt.decode(mandate_token, options={"verify_signature": False})
    payload = {"quote_id": quote_id, "mandate_id": mandate["mandate_id"]}
    return jwt.encode(payload, key, algorithm="EdDSA", headers={"kid": mandate["agent_id"]})


AUDIENCE = "valio-aimo-trade"  # the trade server checks this, see server/agent_auth.py
MAX_TTL_S = 15 * 60


def session_token(key_file: Path, mandate_token: str, now: float | None = None, ttl_s: int = 600) -> str:
    """A short-lived token that proves this agent is calling. Sent as Authorization: Bearer on
    every request to the trade server's /mcp, next to the mandate in X-Mandate. Never shown to
    the model."""
    key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
    mandate = jwt.decode(mandate_token, options={"verify_signature": False})
    iat = int(time.time() if now is None else now)
    payload = {"aud": AUDIENCE, "mandate_id": mandate["mandate_id"], "iat": iat,
               "exp": iat + min(int(ttl_s), MAX_TTL_S)}
    return jwt.encode(payload, key, algorithm="EdDSA", headers={"kid": mandate["agent_id"]})
