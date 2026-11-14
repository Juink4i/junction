"""The agent's own key pair: made on the agent's side, used to sign each order."""

import sys
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.identity import ensure_agent_key, key_path, session_token, sign_order


def mandate_token(buyer="k-0000"):
    buyer_key = Ed25519PrivateKey.generate()
    return jwt.encode({"mandate_id": f"mnd_{buyer}_001", "agent_id": f"agent-{buyer}"}, buyer_key,
                      algorithm="EdDSA", headers={"kid": buyer})


def test_the_agent_key_is_made_once_and_kept_private(tmp_path):
    first = ensure_agent_key("k-0000", tmp_path)
    assert ensure_agent_key("k-0000", tmp_path) == first
    assert "PUBLIC KEY" in first and "PRIVATE" not in first
    path = key_path("k-0000", tmp_path)
    assert path == tmp_path / "k-0000" / "agent_key.pem"
    # Readable by the owner only. Windows ignores chmod's permission bits (it uses ACLs), so
    # the check only means something on POSIX systems.
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o077 == 0


def test_an_order_signature_verifies_with_the_public_half(tmp_path):
    public_pem = ensure_agent_key("k-0000", tmp_path)
    signature = sign_order(key_path("k-0000", tmp_path), mandate_token(), "q_1", True)
    public_key = serialization.load_pem_public_key(public_pem.encode())
    payload = jwt.decode(signature, public_key, algorithms=["EdDSA"])
    assert payload == {"quote_id": "q_1", "mandate_id": "mnd_k-0000_001", "confirm_unusual": True}
    assert jwt.get_unverified_header(signature)["kid"] == "agent-k-0000"


def test_a_session_token_proves_the_agent_for_this_mandate(tmp_path):
    public_pem = ensure_agent_key("k-0000", tmp_path)
    token = session_token(key_path("k-0000", tmp_path), mandate_token(), now=1_800_000_000)
    public_key = serialization.load_pem_public_key(public_pem.encode())
    claims = jwt.decode(token, public_key, algorithms=["EdDSA"], audience="valio-aimo-trade",
                        options={"verify_exp": False, "verify_iat": False})
    assert claims == {"aud": "valio-aimo-trade", "mandate_id": "mnd_k-0000_001",
                      "iat": 1_800_000_000, "exp": 1_800_000_600}
    header = jwt.get_unverified_header(token)
    assert header["kid"] == "agent-k-0000" and header["alg"] == "EdDSA"


def test_a_session_token_never_lives_longer_than_15_minutes(tmp_path):
    ensure_agent_key("k-0000", tmp_path)
    token = session_token(key_path("k-0000", tmp_path), mandate_token(), ttl_s=3600)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 900
    assert abs(claims["iat"] - time.time()) < 5
