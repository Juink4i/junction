"""The buyer edits its own mandate. web/ acts as the buyer's signing tool.

A change is merged into the current mandate, checked, given the next version number,
signed with the buyer's own key and written to server/mandates/<buyer_id>.jwt. Then the
buyer's public key and a "mandate:updated" log row go into state.db. Those two are the
only writes web/ ever makes to state.db; they are all in register() below.
"""

from __future__ import annotations

import copy
import math
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server import audit, signing
from server.db import connect, transaction
from server.mandate import UNKNOWN_ALLERGEN_RULES, _shape_problems
from server.policy import eur
from web.accounts import decode_unverified, read_token

# What a buyer may change. Everything else (mandate_id, buyer, agent_id, no_delivery_after)
# stays as it was signed.
EDITABLE = {
    "auto_approve": {"max_order_eur", "max_line_eur", "allowed_categories"},
    "substitution": {"allowed", "must_keep", "max_price_increase_pct"},
    "hard_rules": {"blocked_allergens", "unknown_allergens"},
    "approvers": None,
    "valid_until": None,
}


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
            else:
                section[field] = field_value
    return new


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

    if not mandate.get("approvers"):
        found.append("approvers needs at least one approver")
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
    (None, "approvers", "approvers", lambda v: _list(v)),
    (None, "valid_until", "valid until", lambda v: str(v)),
]


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


def buyer_key(keys_dir: Path, buyer_id: str) -> Ed25519PrivateKey:
    """The buyer's private key, made and saved on first use (make_mandate.py throws its key away)."""
    path = Path(keys_dir) / f"{buyer_id}.pem"
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = signing.generate_key()
    _write_atomic(path, signing.private_pem(key))
    return key


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


def register(state_db: Path, buyer_id: str, key: Ed25519PrivateKey, actor: str, reason: str) -> None:
    """The only writes web/ makes to state.db (the trade server owns it):
    1. the buyer's public key, only when it changed (the first edit rotates the key),
    2. one "mandate:updated" row on the hash-chained log. audit.append takes its own
       BEGIN IMMEDIATE transaction, so it is safe next to the running trade server."""
    conn = connect(state_db)
    try:
        pem = signing.public_pem(key.public_key())
        with transaction(conn):
            conn.execute("UPDATE buyers SET public_pem = ? WHERE buyer_id = ? AND public_pem != ?",
                         (pem, buyer_id, pem))
        audit.append(conn, datetime.now(timezone.utc), actor, "mandate:updated", reason)
    finally:
        conn.close()


def update_mandate(*, buyer_id: str, buyer_name: str, change: Any, mandate_dir: Path,
                   keys_dir: Path, state_db: Path, today: date) -> bool:
    """Apply a buyer's change to its mandate. Returns False when nothing changed.

    Raises EditError for a field that cannot be changed or a mandate that would be wrong.
    The new token goes to disk only; it is never returned."""
    token = read_token(mandate_dir, buyer_id)
    current = decode_unverified(token) if token else None
    if not isinstance(current, dict):
        raise EditError("mandate_missing", "This account has no readable mandate to change.")
    new = merge(current, change)
    found = problems(new, today)
    if found:
        raise EditError("bad_mandate", "The mandate cannot be signed: " + "; ".join(found) + ".")
    diff = changes(current, new)
    if not diff:
        return False

    new["mandate_id"] = next_mandate_id(str(current["mandate_id"]))
    new["issued_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    key = buyer_key(keys_dir, buyer_id)
    _write_atomic(Path(mandate_dir) / f"{buyer_id}.jwt", signing.sign(new, key, kid=buyer_id))
    reason = (f"{buyer_name} changed its mandate to {new['mandate_id']}: {'; '.join(diff)}. "
              "The agent uses the new rules from its next order.")
    register(state_db, buyer_id, key, actor=new["approvers"][0], reason=reason)
    return True
