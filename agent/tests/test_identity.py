"""The agent's own key pair: made on the agent's side, used to sign each order."""

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent.identity import ensure_agent_key, key_path, sign_order


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
    assert path.stat().st_mode & 0o077 == 0  # readable by the owner only


def test_an_order_signature_verifies_with_the_public_half(tmp_path):
    public_pem = ensure_agent_key("k-0000", tmp_path)
    signature = sign_order(key_path("k-0000", tmp_path), mandate_token(), "q_1", True)
    public_key = serialization.load_pem_public_key(public_pem.encode())
    payload = jwt.decode(signature, public_key, algorithms=["EdDSA"])
    assert payload == {"quote_id": "q_1", "mandate_id": "mnd_k-0000_001", "confirm_unusual": True}
    assert jwt.get_unverified_header(signature)["kid"] == "agent-k-0000"
