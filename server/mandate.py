"""The buyer's signed mandate: what their agent may do alone."""

import sqlite3
from datetime import date

import jwt

from server import signing

REQUIRED = ("mandate_id", "buyer", "agent_id", "valid_until", "auto_approve", "hard_rules")


class MandateError(Exception):
    pass


def verify_mandate(token: str, conn: sqlite3.Connection, today: date) -> tuple[str, dict]:
    """Returns (buyer_id, mandate), or raises MandateError with a plain reason."""
    try:
        buyer_id = jwt.get_unverified_header(token).get("kid")
    except jwt.InvalidTokenError:
        raise MandateError("The mandate is not a readable signed token.")
    row = conn.execute("SELECT public_pem FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()
    if row is None:
        raise MandateError("The mandate's signing key is not registered with Valio Aimo.")
    try:
        mandate = signing.verify(token, signing.load_public(row["public_pem"]))
    except jwt.InvalidTokenError:
        raise MandateError("The mandate's signature is not valid. It was not signed by the buyer, "
                           "or it was changed after signing.")
    missing = [f for f in REQUIRED if f not in mandate]
    if missing:
        raise MandateError(f"The mandate is missing: {', '.join(missing)}.")
    try:
        valid_until = date.fromisoformat(mandate["valid_until"])
    except (TypeError, ValueError):
        raise MandateError("The mandate's valid_until date is not readable.")
    if today > valid_until:
        raise MandateError(f"The mandate expired on {valid_until.isoformat()}.")
    return buyer_id, mandate
