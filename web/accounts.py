"""Read-only, per-account views of the trade server's state.db.

The trade server owns and writes state.db. These functions only read it, and every query
is scoped to one buyer_id, so one account never sees another account's orders, approvals
or log rows. Mandate tokens are read from disk to check them, but never returned.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import jwt

from server.mandate import MandateError, verify_mandate
from server.service import WITHDRAWN

ACCOUNT_ORDER = ("hotel", "cafe", "school")
LOG_FIELDS = ("seq", "time", "actor", "action", "reason", "prev_hash", "hash")
PRODUCT_FIELDS = ("category", "tags", "delivery_reliability", "carbon_kg_per_kg",
                  "allergen_info_missing", "allergens_contains")


def open_ro(path: str | Path) -> sqlite3.Connection:
    """A fresh read-only connection, so each request sees the trade server's latest writes."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


# Accounts


def buyer_exists(conn: sqlite3.Connection, buyer_id: str) -> bool:
    return conn.execute("SELECT 1 FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone() is not None


# A buyer id becomes a file name, so only ids that are safe as one are looked up.
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class MandateFiles:
    """Where buyers' mandates live, in the same order as agent.config.load_mandate:
    1. data/buyers/<id>/mandate.jwt  (a kitchen signed up on the onboarding page; its own
       signing key is next to it as buyer_key.pem),
    2. server/mandates/<id>.jwt      (the demo buyers from server.make_mandate)."""

    mandate_dir: Path
    buyers_dir: Path

    def path(self, buyer_id: str) -> Path | None:
        """The file holding this buyer's mandate, or None if there is none."""
        if not SAFE_ID.fullmatch(buyer_id):
            return None
        for candidate in (Path(self.buyers_dir) / buyer_id / "mandate.jwt",
                          Path(self.mandate_dir) / f"{buyer_id}.jwt"):
            if candidate.is_file():
                return candidate
        return None

    def onboarded_key(self, buyer_id: str) -> Path | None:
        """The buyer's own signing key, kept by onboarding, or None for a demo buyer."""
        if not SAFE_ID.fullmatch(buyer_id):
            return None
        path = Path(self.buyers_dir) / buyer_id / "buyer_key.pem"
        return path if path.is_file() else None

    def profile(self, buyer_id: str) -> Path | None:
        """The kitchen's preferences from onboarding, or None for a demo buyer."""
        if not SAFE_ID.fullmatch(buyer_id):
            return None
        path = Path(self.buyers_dir) / buyer_id / "profile.json"
        return path if path.is_file() else None

    def read_token(self, buyer_id: str) -> str | None:
        """The buyer's mandate token. Only for checking and signing; never returned."""
        path = self.path(buyer_id)
        try:
            return path.read_text(encoding="utf-8").strip() if path else None
        except OSError:
            return None


def buyer_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every buyer: hotel, cafe, school first, then the rest by name."""
    rows = conn.execute("SELECT buyer_id, name FROM buyers").fetchall()
    rank = {b: i for i, b in enumerate(ACCOUNT_ORDER)}
    rows.sort(key=lambda r: (rank.get(r["buyer_id"], len(rank)), r["name"].casefold(), r["buyer_id"]))
    return rows


def list_accounts(conn: sqlite3.Connection, files: MandateFiles, today: date) -> list[dict]:
    return [_account(conn, row, files, today) for row in buyer_rows(conn)]


def get_account(conn: sqlite3.Connection, buyer_id: str, files: MandateFiles, today: date) -> dict | None:
    row = conn.execute("SELECT buyer_id, name FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()
    return _account(conn, row, files, today) if row else None


def decode_unverified(token: str) -> dict | None:
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        return None


def _account(conn: sqlite3.Connection, row: sqlite3.Row, files: MandateFiles, today: date) -> dict:
    account = {"buyer_id": row["buyer_id"], "name": row["name"], "mandate": None,
               "mandate_verified": False, "mandate_problem": None}
    token = files.read_token(row["buyer_id"])
    if token is None:
        account["mandate_problem"] = "No mandate file for this buyer."
        return account
    account["mandate"] = decode_unverified(token)
    if account["mandate"] is None:
        account["mandate_problem"] = "The mandate is not a readable signed token."
        return account
    try:
        buyer_id, _ = verify_mandate(token, conn, today)
    except MandateError as e:
        account["mandate_problem"] = str(e)
        return account
    if buyer_id != row["buyer_id"]:
        account["mandate_problem"] = f"The mandate file is signed for buyer {buyer_id}, not this one."
        return account
    account["mandate_verified"] = True
    return account


# Orders

_ORDER_SELECT = (
    "SELECT o.*, b.name AS buyer_name, q.body_json, a.approval_id AS a_id, a.status AS a_status, "
    "a.approvers_json, a.decided_by, a.decided_at FROM orders o "
    "LEFT JOIN buyers b ON b.buyer_id = o.buyer_id LEFT JOIN quotes q ON q.quote_id = o.quote_id "
    "LEFT JOIN approvals a ON a.order_id = o.order_id"
)
_ORDER_SQL = _ORDER_SELECT + " WHERE o.buyer_id = ?"
NEWEST_FIRST = " ORDER BY o.created_at DESC, o.rowid DESC"


def _order(row: sqlite3.Row) -> dict:
    quote = json.loads(row["body_json"]) if row["body_json"] else {}
    lines = quote.get("lines", [])
    dates = [l["available_date"] for l in lines if l.get("available_date")]
    reasons = json.loads(row["reasons_json"])
    # The server stores a replaced order as rejected, with its approval closed by the agent.
    # Shown as rejected, it would read as a person's or a rule's no.
    withdrawn = row["status"] == "rejected" and WITHDRAWN in reasons
    approval = None
    if row["a_id"]:
        approval = {"approval_id": row["a_id"], "status": "withdrawn" if withdrawn else row["a_status"],
                    "approvers": json.loads(row["approvers_json"]),
                    "decided_by": row["decided_by"], "decided_at": row["decided_at"]}
    return {
        "order_id": row["order_id"],
        "quote_id": row["quote_id"],
        "status": "withdrawn" if withdrawn else row["status"],
        "created_at": row["created_at"],
        "rationale": row["rationale"],
        "reasons": reasons,
        "total_eur": quote.get("total_eur"),
        "total_with_tax_eur": quote.get("total_with_tax_eur"),
        "lines": lines,
        "expires_at": quote.get("expires_at"),
        "delivery_date": max(dates) if dates else None,
        "approval": approval,
    }


def list_orders(conn: sqlite3.Connection, buyer_id: str) -> list[dict]:
    rows = conn.execute(_ORDER_SQL + NEWEST_FIRST, (buyer_id,))
    return [_order(row) for row in rows]


def get_order(conn: sqlite3.Connection, buyer_id: str, order_id: str, catalog: Any) -> dict | None:
    """One of this buyer's orders with its log and product details, or None.

    Another buyer's order gives None too, so its existence is never revealed."""
    row = conn.execute(_ORDER_SQL + " AND o.order_id = ?", (buyer_id, order_id)).fetchone()
    return None if row is None else order_detail(conn, row, catalog)


def order_detail(conn: sqlite3.Connection, row: sqlite3.Row, catalog: Any) -> dict:
    """An order row (from _ORDER_SELECT) with its log rows and each line's product details."""
    order = _order(row)
    order["lines"] = [{**line, "product": product_details(catalog, line.get("product_id"))}
                      for line in order["lines"]]
    rows = conn.execute("SELECT * FROM log WHERE order_id = ? OR quote_id = ? ORDER BY seq",
                        (order["order_id"], order["quote_id"]))
    order["log"] = [{f: r[f] for f in LOG_FIELDS} for r in rows]
    return order


def product_details(catalog: Any, product_id: str | None) -> dict | None:
    if catalog is None or not product_id:
        return None
    try:
        product = catalog.get_product(product_id)
        if product is None:
            return None
        return {f: getattr(product, f, None) for f in PRODUCT_FIELDS}
    except Exception:
        return None


# Approvals


def pending_approvals(conn: sqlite3.Connection, buyer_id: str) -> list[dict]:
    """Same shape as Service.list_approvals(), for one buyer."""
    rows = conn.execute(
        "SELECT a.*, o.quote_id, o.reasons_json, o.rationale, o.created_at, b.name AS buyer, "
        "q.body_json FROM approvals a JOIN orders o ON o.order_id = a.order_id "
        "JOIN buyers b ON b.buyer_id = o.buyer_id JOIN quotes q ON q.quote_id = o.quote_id "
        "WHERE a.status = 'pending' AND o.buyer_id = ? ORDER BY o.created_at",
        (buyer_id,),
    ).fetchall()
    approvals = []
    for row in rows:
        quote = json.loads(row["body_json"])
        approvals.append({
            "approval_id": row["approval_id"],
            "order_id": row["order_id"],
            "quote_id": row["quote_id"],
            "status": row["status"],
            "buyer": row["buyer"],
            "approvers": json.loads(row["approvers_json"]),
            "reasons": json.loads(row["reasons_json"]),
            "agent_rationale": row["rationale"],
            "lines": quote["lines"],
            "total_eur": quote["total_eur"],
            "total_with_tax_eur": quote["total_with_tax_eur"],
            "created_at": row["created_at"],
        })
    return approvals


def approval_belongs(conn: sqlite3.Connection, buyer_id: str, approval_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM approvals a JOIN orders o ON o.order_id = a.order_id "
        "WHERE a.approval_id = ? AND o.buyer_id = ?", (approval_id, buyer_id),
    ).fetchone() is not None


# Log


def buyer_log(conn: sqlite3.Connection, buyer_id: str) -> list[dict]:
    """Log rows tied to this buyer's orders or to any quote issued to it, ordered or not."""
    rows = conn.execute(
        "SELECT * FROM log WHERE order_id IN (SELECT order_id FROM orders WHERE buyer_id = ?) "
        "OR quote_id IN (SELECT quote_id FROM orders WHERE buyer_id = ?) "
        "OR quote_id IN (SELECT quote_id FROM quotes WHERE buyer_id = ?) ORDER BY seq",
        (buyer_id, buyer_id, buyer_id),
    )
    return [{**{f: r[f] for f in LOG_FIELDS}, "order_id": r["order_id"], "quote_id": r["quote_id"]}
            for r in rows]
