"""The buyer's signed mandate: what their agent may do alone."""

import math
import re
import sqlite3
from datetime import date

import jwt

from server import signing

UNKNOWN_ALLERGEN_RULES = ("human", "reject", "allow")
PERIODS = ("week", "month")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
BUYER_ID = re.compile(r"[a-z0-9-]{3,64}")


class MandateError(Exception):
    """Why a mandate was not accepted. `code` is mandate_missing, mandate_invalid or mandate_expired."""

    def __init__(self, message: str, code: str = "mandate_invalid"):
        super().__init__(message)
        self.code = code


def _text(value) -> bool:
    return isinstance(value, str) and value != ""


def _texts(value) -> bool:
    return isinstance(value, list) and all(_text(v) for v in value)


def _amount(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _usual_order(value) -> bool:
    return (isinstance(value, dict) and _text(value.get("category"))
            and _amount(value.get("amount")) and value["amount"] > 0
            and value.get("content_unit") in ("L", "KG") and value.get("every") in PERIODS)


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

    if "budget" in mandate:
        budget = mandate["budget"]
        if not (isinstance(budget, dict) and budget.get("period") in PERIODS
                and _amount(budget.get("max_eur")) and budget["max_eur"] > 0):
            problems.append("budget must have a period of week or month, and max_eur as a "
                            "number of euros above zero")
    if "usual_orders" in mandate:
        usual = mandate["usual_orders"]
        if not (isinstance(usual, list) and all(_usual_order(o) for o in usual)):
            problems.append("usual_orders must be a list of orders, each with a category, an amount "
                            "above zero, a content_unit of L or KG, and every as week or month")
    if "delivery" in mandate:
        delivery = mandate["delivery"]
        days = delivery.get("days") if isinstance(delivery, dict) else None
        if not (isinstance(days, list) and days and all(day in WEEKDAYS for day in days)):
            problems.append("delivery.days must be a non-empty list of weekdays from MON to SUN")
    if "agent_key" in mandate and not signing.is_ed25519_public(mandate["agent_key"]):
        problems.append("agent_key must be an Ed25519 public key in PEM form")
    return problems


def check_mandate(token: str, public_key, today: date) -> dict:
    """The mandate inside a token signed by this key, or MandateError with a plain reason."""
    try:
        mandate = signing.verify(token, public_key)
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
        raise MandateError(f"The mandate expired on {valid_until.isoformat()}.", code="mandate_expired")
    return mandate


def verify_mandate(token: str, conn: sqlite3.Connection, today: date) -> tuple[str, dict]:
    """Returns (buyer_id, mandate), or raises MandateError with a plain reason."""
    try:
        buyer_id = jwt.get_unverified_header(token).get("kid")
    except jwt.InvalidTokenError:
        raise MandateError("The mandate is not a readable signed token.")
    row = conn.execute("SELECT public_pem FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()
    if row is None:
        raise MandateError("The mandate's signing key is not registered with Valio Aimo.")
    return buyer_id, check_mandate(token, signing.load_public(row["public_pem"]), today)
