"""Ed25519 keys and JWS signing for quotes and mandates."""

import sqlite3
from datetime import date, datetime

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ALGORITHM = "EdDSA"


class QuoteError(Exception):
    pass


def generate_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def public_pem(key: Ed25519PublicKey) -> str:
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def load_public(pem: str) -> Ed25519PublicKey:
    return serialization.load_pem_public_key(pem.encode())


def is_ed25519_public(pem) -> bool:
    """True if pem is text that holds an Ed25519 public key."""
    try:
        return isinstance(pem, str) and isinstance(load_public(pem), Ed25519PublicKey)
    except Exception:
        return False


def server_key(conn: sqlite3.Connection) -> Ed25519PrivateKey:
    row = conn.execute("SELECT private_pem FROM keys WHERE name = 'server'").fetchone()
    if row:
        return serialization.load_pem_private_key(row["private_pem"].encode(), password=None)
    key = generate_key()
    conn.execute("INSERT INTO keys (name, private_pem) VALUES ('server', ?)", (private_pem(key),))
    return key


def sign(payload: dict, key: Ed25519PrivateKey, kid: str) -> str:
    return jwt.encode(payload, key, algorithm=ALGORITHM, headers={"kid": kid})


def verify(token: str, key: Ed25519PublicKey) -> dict:
    """Raises jwt.InvalidTokenError unless the token was signed by this key."""
    return jwt.decode(token, key, algorithms=[ALGORITHM])


def sign_quote(body: dict, need_by: date, key: Ed25519PrivateKey) -> str:
    return sign({**body, "need_by": need_by.isoformat()}, key, kid="valio-aimo-trade")


def check_quote(quote: dict, key: Ed25519PublicKey, now: datetime) -> date:
    """Returns the signed need-by date, or raises QuoteError with a plain reason."""
    body = {k: v for k, v in quote.items() if k != "signature"}
    try:
        signed = verify(quote.get("signature", ""), key)
    except jwt.InvalidTokenError:
        raise QuoteError("The quote was changed after it was issued: its signature is not valid.")
    need_by = signed.pop("need_by", None)
    if signed != body or need_by is None:
        raise QuoteError("The quote was changed after it was issued: it no longer matches its signature.")
    if now > datetime.fromisoformat(body["expires_at"]):
        raise QuoteError("The quote has expired. Quotes are valid for 15 minutes. Request a new one.")
    return date.fromisoformat(need_by)


UNSIGNED_ORDER = ("This mandate names an agent key, and the order was not signed by it. "
                  "A copy of the mandate alone cannot place orders.")


def order_signature_problem(signature, mandate: dict, quote_id: str, confirm_unusual: bool) -> str | None:
    """None if the agent key named in the mandate signed exactly this order, else a plain reason."""
    expected = {"quote_id": quote_id, "mandate_id": mandate["mandate_id"],
                "confirm_unusual": bool(confirm_unusual)}
    try:
        signed = verify(signature if isinstance(signature, str) else "",
                        load_public(mandate["agent_key"]))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return UNSIGNED_ORDER
    return None if signed == expected else UNSIGNED_ORDER
