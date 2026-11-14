"""Enrol a kitchen: make its key, sign its mandate, register with the trade server, save the files.

The private key is made here, on the kitchen's side, and is never sent anywhere. The trade
server only ever receives the public key and the signed mandate.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from onboarding.build import Built, build

ROOT = Path(__file__).resolve().parent.parent
BUYERS_DIR = ROOT / "data" / "buyers"


class EnrollError(Exception):
    """The trade server did not accept the registration. Carries the server's error shape."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def _register(trade_http: str, body: dict[str, Any], client: Any) -> None:
    owned = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        response = client.post(f"{trade_http.rstrip('/')}/buyers", json=body)
    except httpx.HTTPError as exc:
        raise EnrollError("server_unreachable",
                          f"Valio Aimo's trade server at {trade_http} is not answering "
                          f"({type(exc).__name__}). Nothing was registered.", retryable=True)
    finally:
        if owned:
            client.close()
    if response.status_code == 201:
        return
    try:
        refused = response.json()
    except ValueError:
        refused = {}
    if not isinstance(refused, dict):
        refused = {}
    raise EnrollError(str(refused.get("code") or "registration_refused"),
                      str(refused.get("message") or f"The trade server answered {response.status_code}."),
                      bool(refused.get("retryable", False)))


def enroll(answers: dict[str, Any], buyer_id: str, agent_public_pem: str | None, trade_http: str, *,
           today: date | None = None, buyers_dir: Path | None = None, client: Any = None) -> Built:
    """Sign up one kitchen and return what was built.

    Raises ValueError for answers that cannot be signed, and EnrollError when the trade server
    does not accept the registration. Either way, no folder is left behind.
    """
    built = build(answers, buyer_id, today or date.today(), agent_public_pem)
    key = Ed25519PrivateKey.generate()
    token = jwt.encode(built.mandate, key, algorithm="EdDSA", headers={"kid": buyer_id})
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()

    folder = (buyers_dir or BUYERS_DIR) / buyer_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        key_file = folder / "buyer_key.pem"
        key_file.write_text(private_pem)
        key_file.chmod(0o600)
        _register(trade_http, {"public_pem": public_pem, "mandate_token": token}, client)
        (folder / "mandate.jwt").write_text(token)
        (folder / "profile.json").write_text(json.dumps(built.profile, ensure_ascii=False, indent=2))
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return built
