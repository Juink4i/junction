"""Read-only, per-account views of the trade server's state.db.

The trade server owns and writes state.db. These functions only read it, and every query
is scoped to one buyer_id, so one account never sees another account's orders, approvals
or log rows. Mandate tokens are read from disk to check them, but never returned.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import jwt

from server.mandate import MandateError, verify_mandate

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


def list_accounts(conn: sqlite3.Connection, mandate_dir: Path, today: date) -> list[dict]:
    rows = conn.execute("SELECT buyer_id, name FROM buyers").fetchall()
    rank = {b: i for i, b in enumerate(ACCOUNT_ORDER)}
    rows.sort(key=lambda r: (rank.get(r["buyer_id"], len(rank)), r["buyer_id"]))
    return [_account(conn, row, Path(mandate_dir), today) for row in rows]


def _account(conn: sqlite3.Connection, row: sqlite3.Row, mandate_dir: Path, today: date) -> dict:
    account = {"buyer_id": row["buyer_id"], "name": row["name"], "mandate": None,
               "mandate_verified": False, "mandate_problem": None}
    path = mandate_dir / f"{row['buyer_id']}.jwt"
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        account["mandate_problem"] = "No mandate file for this buyer."
        return account
    try:
        account["mandate"] = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
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

_ORDER_SQL = (
    "SELECT o.*, q.body_json, a.approval_id AS a_id, a.status AS a_status, a.approvers_json, "
    "a.decided_by, a.decided_at FROM orders o LEFT JOIN quotes q ON q.quote_id = o.quote_id "
    "LEFT JOIN approvals a ON a.order_id = o.order_id WHERE o.buyer_id = ?"
)


def _order(row: sqlite3.Row) -> dict:
    quote = json.loads(row["body_json"]) if row["body_json"] else {}
    lines = quote.get("lines", [])
    dates = [l["available_date"] for l in lines if l.get("available_date")]
    approval = None
    if row["a_id"]:
        approval = {"approval_id": row["a_id"], "status": row["a_status"],
                    "approvers": json.loads(row["approvers_json"]),
                    "decided_by": row["decided_by"], "decided_at": row["decided_at"]}
    return {
        "order_id": row["order_id"],
        "quote_id": row["quote_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "rationale": row["rationale"],
        "reasons": json.loads(row["reasons_json"]),
        "question": row["question"],
        "total_eur": quote.get("total_eur"),
        "total_with_tax_eur": quote.get("total_with_tax_eur"),
        "lines": lines,
        "expires_at": quote.get("expires_at"),
        "delivery_date": max(dates) if dates else None,
        "approval": approval,
    }


def list_orders(conn: sqlite3.Connection, buyer_id: str) -> list[dict]:
    rows = conn.execute(_ORDER_SQL + " ORDER BY o.created_at DESC, o.rowid DESC", (buyer_id,))
    return [_order(row) for row in rows]


def get_order(conn: sqlite3.Connection, buyer_id: str, order_id: str, catalog: Any) -> dict | None:
    """One of this buyer's orders with its log and product details, or None.

    Another buyer's order gives None too, so its existence is never revealed."""
    row = conn.execute(_ORDER_SQL + " AND o.order_id = ?", (buyer_id, order_id)).fetchone()
    if row is None:
        return None
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
    """Log rows tied to this buyer's orders or the quotes those orders used."""
    rows = conn.execute(
        "SELECT * FROM log WHERE order_id IN (SELECT order_id FROM orders WHERE buyer_id = ?) "
        "OR quote_id IN (SELECT quote_id FROM orders WHERE buyer_id = ?) ORDER BY seq",
        (buyer_id, buyer_id),
    )
    return [{**{f: r[f] for f in LOG_FIELDS}, "order_id": r["order_id"], "quote_id": r["quote_id"]}
            for r in rows]
