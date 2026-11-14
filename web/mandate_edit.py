"""The buyer edits its own mandate. web/ acts as the buyer's signing tool.

A change is merged into the current mandate, checked, given the next version number,
signed with the buyer's own key and written back to the file it came from (see
web.accounts.MandateFiles), so the agent picks it up on its next run. Every field the
editor does not touch (agent_key, no_delivery_after, ...) stays as it was.

Usual orders live in two files: their amounts in the mandate, their plain names ("what") in
the onboarded kitchen's profile.json. A change to them rewrites both, so they never drift.

Keys: a kitchen that signed up on the onboarding page keeps its key in
data/buyers/<id>/buyer_key.pem, which Valio Aimo already knows, so it is never rotated.
The demo buyers' keys were thrown away by server.make_mandate, so the first edit makes one
in data/buyer_keys/<id>.pem and registers its public half.

Then the buyer's public key (demo buyers, first edit only) and a "mandate:updated" log row
go into state.db. Those two are the only writes web/ ever makes to state.db; they are all
in register() below.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from catalog.names import CATEGORY_NAMES
from onboarding.build import usual_order_problems
from server import audit, signing
from server.db import connect, transaction
from server.mandate import UNKNOWN_ALLERGEN_RULES, WEEKDAYS, _shape_problems
from server.policy import WEEKDAY_NAMES, eur
from web.accounts import MandateFiles, decode_unverified, open_ro

# What a buyer may change. Everything else (mandate_id, buyer, agent_id, agent_key,
# no_delivery_after) stays as it was signed.
EDITABLE = {
    "auto_approve": {"max_order_eur", "max_line_eur", "allowed_categories"},
    "substitution": {"allowed", "must_keep", "max_price_increase_pct"},
    "hard_rules": {"blocked_allergens", "unknown_allergens"},
    "budget": {"period", "max_eur"},
    "delivery": {"days"},
    "approvers": None,
    "valid_until": None,
    "usual_orders": None,
}
USUAL_ORDER_FIELDS = {"what", "category", "amount", "content_unit", "every", "on"}
# Sections that null removes: no budget cap, goods may arrive any day.
REMOVABLE = {"budget", "delivery"}


class EditError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# Merge and check


def merge(current: dict, change: Any) -> dict:
    """The current mandate with the change applied. Raises EditError("bad_field")."""
    if not isinstance(change, dict):
        raise EditError("bad_field", "Send a JSON object with only the fields to change.")
    new = copy.deepcopy(current)
    for key, value in change.items():
        if key not in EDITABLE:
            raise EditError("bad_field", f"{key} cannot be changed here.")
        fields = EDITABLE[key]
        if (value is None and key in REMOVABLE) or (key == "usual_orders" and not value):
            new.pop(key, None)
            continue
        if fields is None:
            new[key] = value
            continue
        if not isinstance(value, dict):
            raise EditError("bad_field", f"{key} must be an object with the fields to change.")
        section = new.setdefault(key, {})
        if not isinstance(section, dict):
            section = new[key] = {}
        for field, field_value in value.items():
            if field not in fields:
                raise EditError("bad_field", f"{key}.{field} cannot be changed here.")
            if key == "auto_approve" and field == "allowed_categories" and not field_value:
                section.pop(field, None)  # no list means any category
            elif key == "delivery" and field == "days" and not field_value:
                section.pop(field, None)  # no days means any day
            elif key == "delivery" and field == "days" and _weekdays(field_value):
                section[field] = [d for d in WEEKDAYS if d in field_value]  # Monday first, no repeats
            else:
                section[field] = field_value
    if new.get("delivery") == {}:
        new.pop("delivery")
    return new


def split_names(change: Any) -> tuple[Any, list[str] | None]:
    """The change without the usual orders' names, and those names (None when the change
    leaves usual orders alone). Raises EditError("bad_field")."""
    if not isinstance(change, dict) or "usual_orders" not in change:
        return change, None
    orders = change["usual_orders"] or []
    if not isinstance(orders, list) or not all(isinstance(o, dict) for o in orders):
        raise EditError("bad_field", "usual_orders must be a list of orders.")
    stripped, names = [], []
    for number, order in enumerate(orders, 1):
        extra = set(order) - USUAL_ORDER_FIELDS
        if extra:
            raise EditError("bad_field", f"Usual order {number}: {', '.join(sorted(extra))} "
                            "cannot be set here.")
        if not isinstance(order.get("on"), (str, int, type(None))):
            raise EditError("bad_field", f"Usual order {number}: on must be a weekday or a day of the month.")
        names.append(str(order.get("what") or "").strip())
        stripped.append({k: v for k, v in order.items() if k != "what" and not (k == "on" and v is None)})
    return {**change, "usual_orders": stripped}, names


def _weekdays(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(d, str) and d in WEEKDAYS for d in value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def problems(mandate: dict, today: date) -> list[str]:
    """Everything wrong with a mandate a buyer wants to sign. Same shape rules as the server."""
    found = _shape_problems(mandate)
    limits = mandate.get("auto_approve") if isinstance(mandate.get("auto_approve"), dict) else {}
    for f in ("max_order_eur", "max_line_eur"):
        if _number(limits.get(f)) and limits[f] <= 0:
            found.append(f"auto_approve.{f} must be above zero")
    order, line = limits.get("max_order_eur"), limits.get("max_line_eur")
    if _number(order) and _number(line) and line > order:
        found.append(f"the limit per line ({eur(line)}) cannot be more than the limit per order "
                     f"({eur(order)})")

    substitution = mandate.get("substitution") if isinstance(mandate.get("substitution"), dict) else {}
    if "allowed" in substitution and not isinstance(substitution["allowed"], bool):
        found.append("substitution.allowed must be true or false")
    if "max_price_increase_pct" in substitution:
        pct = substitution["max_price_increase_pct"]
        if not (_number(pct) and 0 <= pct <= 100):
            found.append("substitution.max_price_increase_pct must be a number between 0 and 100")

    rules = mandate.get("hard_rules") if isinstance(mandate.get("hard_rules"), dict) else {}
    if rules.get("unknown_allergens", "human") not in UNKNOWN_ALLERGEN_RULES:
        if not any("unknown_allergens" in p for p in found):
            found.append("hard_rules.unknown_allergens must be one of: " + ", ".join(UNKNOWN_ALLERGEN_RULES))

    try:
        valid_until = date.fromisoformat(mandate.get("valid_until"))
    except (TypeError, ValueError):
        found.append("valid_until must be a date like 2026-12-31")
    else:
        if valid_until < today:
            found.append(f"valid_until {valid_until.isoformat()} is in the past")

    budget = mandate.get("budget") if isinstance(mandate.get("budget"), dict) else {}
    if _number(budget.get("max_eur")) and _number(order) and budget["max_eur"] < order:
        # Same rule as onboarding.build.problems.
        found.append(f"the budget ({eur(budget['max_eur'])} per {budget.get('period')}) cannot be "
                     f"less than the limit per order ({eur(order)})")

    if not mandate.get("approvers"):
        found.append("approvers needs at least one approver")

    usual = mandate.get("usual_orders")
    if isinstance(usual, list) and all(isinstance(o, dict) for o in usual):
        allowed = limits.get("allowed_categories") or []
        found += usual_order_problems([{**o, "unit": o.get("content_unit")} for o in usual],
                                      allowed if isinstance(allowed, list) else [])
    return found


def next_mandate_id(mandate_id: str) -> str:
    """mnd_hotel_helsinki_001 -> mnd_hotel_helsinki_002 (keeps the zero padding)."""
    m = re.fullmatch(r"(.*?)(\d+)", mandate_id)
    if not m:
        return f"{mandate_id}_002"
    prefix, number = m.groups()
    return prefix + str(int(number) + 1).zfill(len(number))


# Plain-language diff for the log

UNKNOWN_WORDS = {"human": "a person checks", "reject": "rejected", "allow": "allowed"}


def _tag(tag: str) -> str:
    if tag.startswith("FREE_FROM_"):
        return tag[len("FREE_FROM_"):].replace("_", " ").capitalize() + "-free"
    return tag.replace("_", " ").capitalize()


def _list(values: Any, show=str, empty: str = "(none)") -> str:
    return ", ".join(show(v) for v in values) if values else empty


FIELDS = [  # (section, field, label, how to show the value)
    ("auto_approve", "max_order_eur", "limit per order", lambda v: eur(v) if _number(v) else "none"),
    ("auto_approve", "max_line_eur", "limit per line", lambda v: eur(v) if _number(v) else "none"),
    ("auto_approve", "allowed_categories", "categories the agent may buy alone",
     lambda v: _list(v, empty="any")),
    ("substitution", "allowed", "substitutes allowed", lambda v: "yes" if v else "no"),
    ("substitution", "must_keep", "substitutes must stay", lambda v: _list(v, _tag)),
    ("substitution", "max_price_increase_pct", "substitutes may cost up to",
     lambda v: f"{v:g}% more" if _number(v) else "none"),
    ("hard_rules", "blocked_allergens", "blocked allergens", lambda v: _list(v)),
    ("hard_rules", "unknown_allergens", "unknown allergens",
     lambda v: UNKNOWN_WORDS.get(v, str(v))),
    (None, "budget", "budget", lambda v: (f"{eur(v['max_eur'])} per {v['period']}"
                                          if isinstance(v, dict) and _number(v.get("max_eur"))
                                          else "none")),
    ("delivery", "days", "delivery days",
     lambda v: _list(v, lambda d: WEEKDAY_NAMES.get(d, str(d)), empty="any day")),
    (None, "approvers", "approvers", lambda v: _list(v)),
    (None, "valid_until", "valid until", lambda v: str(v)),
]


def _usual_order(o: Any) -> str:
    if not isinstance(o, dict):
        return str(o)
    on = o.get("on")
    when = ("" if on is None else f" on {WEEKDAY_NAMES.get(on, on)}" if o.get("every") == "week"
            else f" on day {on}")
    category = CATEGORY_NAMES.get(o.get("category"), o.get("category"))
    return f"{o.get('amount'):g} {o.get('content_unit')} of {category} every {o.get('every')}{when}"


FIELDS.append((None, "usual_orders", "usual orders", lambda v: _list(v, _usual_order, empty="none")))


def changes(old: dict, new: dict) -> list[str]:
    def get(m: dict, section: str | None, field: str) -> Any:
        holder = m.get(section, {}) if section else m
        return holder.get(field) if isinstance(holder, dict) else None

    out = []
    for section, field, label, show in FIELDS:
        before, after = get(old, section, field), get(new, section, field)
        if before != after:
            out.append(f"{label} {show(before)} → {show(after)}")
    return out


# Keys and files


def _load_key(path: Path) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None)


def buyer_key(keys_dir: Path, buyer_id: str) -> Ed25519PrivateKey:
    """A demo buyer's private key, made and saved on first use (make_mandate.py throws its key away)."""
    path = Path(keys_dir) / f"{buyer_id}.pem"
    if path.exists():
        return _load_key(path)
    key = signing.generate_key()
    _write_atomic(path, signing.private_pem(key))
    return key


def _registered_pem(state_db: Path, buyer_id: str) -> str | None:
    conn = open_ro(state_db)
    try:
        row = conn.execute("SELECT public_pem FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()
        return row["public_pem"] if row else None
    finally:
        conn.close()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_profile(path: Path, profile: dict) -> None:
    _write_atomic(path, json.dumps(profile, ensure_ascii=False, indent=2))


def _profile_orders(mandate: dict, names: list[str]) -> list[dict]:
    """The profile's copy of the mandate's usual orders: same amounts, plus a plain name."""
    out = []
    for order, name in zip(mandate.get("usual_orders") or [], names):
        entry = {"what": name or CATEGORY_NAMES[order["category"]], "amount": order["amount"],
                 "unit": order["content_unit"], "every": order["every"]}
        out.append({**entry, "on": order["on"]} if order.get("on") is not None else entry)
    return out


def register(state_db: Path, buyer_id: str, new_key: Ed25519PrivateKey | None, actor: str,
             reason: str) -> None:
    """The only writes web/ makes to state.db (the trade server owns it):
    1. a demo buyer's public key, only when it changed (its first edit rotates the key);
       new_key is None for an onboarded kitchen, whose key is already registered,
    2. one "mandate:updated" row on the hash-chained log. audit.append takes its own
       BEGIN IMMEDIATE transaction, so it is safe next to the running trade server."""
    conn = connect(state_db)
    try:
        if new_key is not None:
            pem = signing.public_pem(new_key.public_key())
            with transaction(conn):
                conn.execute("UPDATE buyers SET public_pem = ? WHERE buyer_id = ? AND public_pem != ?",
                             (pem, buyer_id, pem))
        audit.append(conn, datetime.now(timezone.utc), actor, "mandate:updated", reason)
    finally:
        conn.close()


def update_mandate(*, buyer_id: str, buyer_name: str, change: Any, files: MandateFiles,
                   keys_dir: Path, state_db: Path, today: date) -> bool:
    """Apply a buyer's change to its mandate, and to its profile's usual orders.
    Returns False when nothing changed.

    Raises EditError for a field that cannot be changed or a mandate that would be wrong.
    The new token goes to disk only; it is never returned."""
    path = files.path(buyer_id)
    token = files.read_token(buyer_id)
    current = decode_unverified(token) if token else None
    if not isinstance(current, dict):
        raise EditError("mandate_missing", "This account has no readable mandate to change.")
    change, names = split_names(change)
    new = merge(current, change)
    found = problems(new, today)
    if found:
        raise EditError("bad_mandate", "The mandate cannot be signed: " + "; ".join(found) + ".")
    diff = changes(current, new)

    profile_path = files.profile(buyer_id) if names is not None else None
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path else None
    if profile is not None:
        orders = _profile_orders(new, names)
        profile = None if profile.get("usual_orders") == orders else {**profile, "usual_orders": orders}
    if not diff and profile is None:
        return False
    if diff:
        _sign_and_register(buyer_id, buyer_name, current, new, diff, path, files, keys_dir, state_db)
    if profile is not None:
        write_profile(profile_path, profile)  # after the mandate, which is the one that can fail
    return True


def _sign_and_register(buyer_id: str, buyer_name: str, current: dict, new: dict, diff: list[str],
                       path: Path, files: MandateFiles, keys_dir: Path, state_db: Path) -> None:
    onboarded = files.onboarded_key(buyer_id)
    if onboarded is not None:
        # The kitchen's own key, registered at sign-up. Never rotated: check it still matches.
        key, new_key = _load_key(onboarded), None
        try:
            registered = _registered_pem(state_db, buyer_id)
        except sqlite3.Error:
            registered = None
        if registered != signing.public_pem(key.public_key()):
            raise EditError("key_mismatch", "This kitchen's signing key in data/buyers is not the "
                            "one Valio Aimo has on file, so a new mandate would not be accepted.")
    else:
        key = new_key = buyer_key(keys_dir, buyer_id)

    new["mandate_id"] = next_mandate_id(str(current["mandate_id"]))
    new["issued_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_atomic(path, signing.sign(new, key, kid=buyer_id))  # the same file it was read from
    reason = (f"{buyer_name} changed its mandate to {new['mandate_id']}: {'; '.join(diff)}. "
              "The agent uses the new rules from its next order.")
    register(state_db, buyer_id, new_key, actor=new["approvers"][0], reason=reason)
    return True
