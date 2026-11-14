"""Turn a kitchen's onboarding answers into a mandate, a profile and plain sentences.

Every answer lands on one side. A rule goes into the mandate, which the kitchen signs and
the trade server enforces. A preference goes into the profile, which only the kitchen's own
agent reads. Plain code, no AI.
"""

from __future__ import annotations

import math
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

from onboarding.options import (ALLERGENS, CATEGORIES, PACK_SIZES, PERIODS, PRIORITIES, TAGS,
                                UNKNOWN_ALLERGEN_CHOICES, WEEKDAYS)

RULE, PREFERENCE = "rule", "preference"
UNUSUAL_FACTOR = 5  # the server asks about an order above this many times the usual amount
DEFAULT_SUBSTITUTION = {"allowed": True, "max_price_increase_pct": 10}


@dataclass
class Built:
    mandate: dict[str, Any]
    profile: dict[str, Any]
    sentences: list[dict[str, str]]


def new_buyer_id(name: str) -> str:
    """A slug of the kitchen name plus four random hex characters, e.g. paivakoti-aurinko-3f2a."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40].strip("-")
    return f"{slug or 'kitchen'}-{secrets.token_hex(2)}"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _unknown(values: Any, known: dict[str, str]) -> list[str]:
    return [str(v) for v in values or [] if v not in known]


def problems(answers: dict[str, Any]) -> list[str]:
    """What is wrong with the answers, in plain language. An empty list means they can be signed."""
    kitchen = answers.get("kitchen") or {}
    safety = answers.get("safety") or {}
    money = answers.get("money") or {}
    delivery = answers.get("delivery") or {}
    found = []

    if not str(kitchen.get("name") or "").strip():
        found.append("Give the kitchen a name.")
    if not str(kitchen.get("approver") or "").strip():
        found.append("Name the person who approves what the agent may not order alone.")

    for values, known, word in ((safety.get("blocked_allergens"), ALLERGENS, "allergen"),
                                (safety.get("must_be"), TAGS, "product property"),
                                (money.get("allowed_categories"), CATEGORIES, "category"),
                                (delivery.get("days"), WEEKDAYS, "weekday")):
        unknown = _unknown(values, known)
        if unknown:
            found.append(f"Unknown {word}: {', '.join(unknown)}.")
    if safety.get("unknown_allergens", "human") not in UNKNOWN_ALLERGEN_CHOICES:
        found.append("For a product without allergen information, choose: a person checks it, "
                     "or refuse it.")
    if delivery.get("pack_size", "small") not in PACK_SIZES:
        found.append("Pack size must be small or large.")

    max_order = money.get("max_order_eur")
    if not _number(max_order) or max_order < 0:
        found.append("Say how many euros the agent may spend on one order by itself.")
    budget = money.get("budget")
    if budget:
        if budget.get("period") not in PERIODS:
            found.append("The budget must be per week or per month.")
        if not _number(budget.get("max_eur")) or budget["max_eur"] <= 0:
            found.append("The budget must be a number of euros above zero.")
        elif _number(max_order) and budget["max_eur"] < max_order:
            found.append("The budget is smaller than what the agent may spend on one order.")
    if sorted(map(str, money.get("priorities") or [])) != sorted(PRIORITIES):
        found.append("Rank each of the four priorities once: price, reliable delivery, "
                     "Finnish origin, sustainability.")

    allowed = money.get("allowed_categories") or []
    for number, order in enumerate(answers.get("usual_orders") or [], 1):
        if not _number(order.get("amount")) or order["amount"] <= 0:
            found.append(f"Usual order {number} needs an amount above zero.")
        if order.get("unit") not in ("L", "KG"):
            found.append(f"Usual order {number} must be in L or KG.")
        if order.get("every") not in PERIODS:
            found.append(f"Usual order {number} must be every week or every month.")
        if order.get("category") not in CATEGORIES:
            found.append(f"Usual order {number} is in an unknown category.")
        elif allowed and order["category"] not in allowed:
            found.append(f"Usual order {number} is in a category the agent may not buy.")
    return found


def _eur(amount: float) -> str:
    return f"€{amount:,.0f}" if float(amount).is_integer() else f"€{amount:,.2f}"


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year + 1, day=28)


def build(answers: dict[str, Any], buyer_id: str, today: date,
          agent_public_pem: str | None = None) -> Built:
    """The mandate to sign, the profile to keep, and the review sentences.

    Raises ValueError with the plain-language problems if the answers cannot be signed.
    """
    found = problems(answers)
    if found:
        raise ValueError(" ".join(found))
    kitchen, money = answers["kitchen"], answers["money"]
    safety, delivery = answers.get("safety") or {}, answers.get("delivery") or {}
    usual = answers.get("usual_orders") or []
    name, approver = kitchen["name"].strip(), kitchen["approver"].strip()
    blocked = list(safety.get("blocked_allergens") or [])
    unknown = safety.get("unknown_allergens", "human")
    must_be = list(safety.get("must_be") or [])
    categories = list(money.get("allowed_categories") or [])
    budget = money.get("budget") or None
    days = [day for day in WEEKDAYS if day in (delivery.get("days") or [])]
    pack = delivery.get("pack_size", "small")

    auto_approve: dict[str, Any] = {"max_order_eur": money["max_order_eur"]}
    if categories:
        auto_approve["allowed_categories"] = categories
    mandate: dict[str, Any] = {
        "mandate_id": f"mnd_{buyer_id}_001",
        "buyer": name,
        "agent_id": f"agent-{buyer_id}",
        "valid_until": _one_year_after(today).isoformat(),
        "auto_approve": auto_approve,
        "substitution": {**(answers.get("substitution") or DEFAULT_SUBSTITUTION), "must_keep": must_be},
        "hard_rules": {"blocked_allergens": blocked, "unknown_allergens": unknown,
                       "no_delivery_after": "need_by_date"},
        "approvers": [approver],
    }
    if budget:
        mandate["budget"] = {"period": budget["period"], "max_eur": budget["max_eur"]}
    if usual:
        mandate["usual_orders"] = [{"category": o["category"], "amount": o["amount"],
                                    "content_unit": o["unit"], "every": o["every"]} for o in usual]
    if agent_public_pem:
        mandate["agent_key"] = agent_public_pem

    profile = {
        "buyer_id": buyer_id,
        "name": name,
        "kitchen_type": kitchen.get("type") or "other",
        "priorities": list(money["priorities"]),
        "pack_size": pack,
        "delivery_days": days,
        "usual_orders": [{"what": (o.get("what") or "").strip() or CATEGORIES[o["category"]],
                          "amount": o["amount"], "unit": o["unit"], "every": o["every"]}
                         for o in usual],
    }

    rows: list[dict[str, str]] = []

    def say(kind: str, text: str) -> None:
        rows.append({"kind": kind, "text": text})

    then = "a person must check it." if unknown == "human" else "the order is refused."
    if blocked:
        say(RULE, "Never deliver products that contain or may contain: "
                  f"{', '.join(ALLERGENS[c] for c in blocked)}.")
        say(RULE, f"If a product does not say whether it has those allergens, {then}")
    else:
        say(RULE, f"If a product has no allergen information at all, {then}")
    if must_be:
        say(RULE, f"Every product must be {_and([TAGS[t] for t in must_be])}. "
                  "Anything else needs a person's approval.")
    say(RULE, f"The agent may buy only: {', '.join(CATEGORIES[c] for c in categories)}."
        if categories else "The agent may buy from any product category.")
    say(RULE, f"The agent may spend up to {_eur(money['max_order_eur'])} on one order by itself. "
              "Above that, a person approves.")
    if budget:
        say(RULE, f"Spending is capped at {_eur(budget['max_eur'])} per {budget['period']}. "
                  "An order that would pass it goes to a person.")
    for order in profile["usual_orders"]:
        say(RULE, f"An order more than {UNUSUAL_FACTOR} times the usual ({order['amount']:g} "
                  f"{order['unit']} of {order['what']} each {order['every']}) is checked with the "
                  "kitchen first.")
    say(RULE, "A delivery after the date the goods are needed by needs a person's approval.")
    if agent_public_pem:
        say(RULE, "Orders must be signed by this kitchen's agent. A copy of this mandate alone "
                  "cannot place an order.")
    if str(kitchen.get("enrolment_code") or "").strip():
        say(RULE, "Valio Aimo ties this registration to your customer account through your "
                  "enrolment code.")
    say(RULE, f"Orders that need a person go to {approver}.")
    say(PREFERENCE, "When several products fit, prefer "
                    f"{', then '.join(PRIORITIES[p] for p in money['priorities'])}.")
    say(PREFERENCE, f"Prefer {PACK_SIZES[pack]}.")
    if days:
        say(PREFERENCE, f"Prefer deliveries on {_and([WEEKDAYS[d] for d in days])}.")
    return Built(mandate, profile, rows)
