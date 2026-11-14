"""The buyer's signed mandate: what their agent may do alone."""

import math
import sqlite3
from datetime import date

import jwt

from server import signing

UNKNOWN_ALLERGEN_RULES = ("human", "reject", "allow")


class MandateError(Exception):
    pass


def _text(value) -> bool:
    return isinstance(value, str) and value != ""


def _texts(value) -> bool:
    return isinstance(value, list) and all(_text(v) for v in value)


def _amount(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _shape_problems(mandate: dict) -> list[str]:
    """A typo in a signed mandate must stop the order, not quietly switch a rule off."""
    problems = [f"{f} must be text" for f in ("mandate_id", "buyer", "agent_id") if not _text(mandate.get(f))]

    limits = mandate.get("auto_approve")
    if not isinstance(limits, dict):
        problems.append("auto_approve must be an object")
    else:
        for f in ("max_order_eur", "max_line_eur"):
            if f in limits and not _amount(limits[f]):
                problems.append(f"auto_approve.{f} must be a number of euros")
        if "allowed_categories" in limits and not _texts(limits["allowed_categories"]):
            problems.append("auto_approve.allowed_categories must be a list of category codes")

    rules = mandate.get("hard_rules")
    if not isinstance(rules, dict):
        problems.append("hard_rules must be an object")
    else:
        if "blocked_allergens" in rules and not _texts(rules["blocked_allergens"]):
            problems.append("hard_rules.blocked_allergens must be a list of allergen codes")
        if "unknown_allergens" in rules and rules["unknown_allergens"] not in UNKNOWN_ALLERGEN_RULES:
            problems.append("hard_rules.unknown_allergens must be one of: "
                            + ", ".join(UNKNOWN_ALLERGEN_RULES))

    if "substitution" in mandate:
        substitution = mandate["substitution"]
        if not isinstance(substitution, dict):
            problems.append("substitution must be an object")
        elif "must_keep" in substitution and not _texts(substitution["must_keep"]):
            problems.append("substitution.must_keep must be a list of tags")
    if "approvers" in mandate and not _texts(mandate["approvers"]):
        problems.append("approvers must be a list of names or addresses")
    return problems


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
    problems = _shape_problems(mandate)
    if problems:
        raise MandateError(f"The mandate is not filled in correctly: {'; '.join(problems)}.")
    try:
        valid_until = date.fromisoformat(mandate["valid_until"])
    except (KeyError, TypeError, ValueError):
        raise MandateError("The mandate's valid_until date is missing or not readable.")
    if today > valid_until:
        raise MandateError(f"The mandate expired on {valid_until.isoformat()}.")
    return buyer_id, mandate
