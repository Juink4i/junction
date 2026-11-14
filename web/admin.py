"""Read-only views for Valio Aimo operations: every account, every order, the whole log.

Unlike web/accounts.py these are not scoped to one buyer. Only the server view uses them.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from web import accounts

RUN_IDLE = timedelta(minutes=10)


def parse_time(text: str) -> datetime:
    """An ISO time; one without a zone is taken as UTC. Raises ValueError."""
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _time(text: Any) -> datetime | None:
    try:
        return parse_time(text) if isinstance(text, str) else None
    except ValueError:
        return None


def _within(text: str, since: datetime | None, until: datetime | None) -> bool:
    t = _time(text)
    if t is None:
        return since is None and until is None
    return (since is None or t >= since) and (until is None or t <= until)


# Orders


def _with_buyer(row: sqlite3.Row, order: dict) -> dict:
    return {**order, "buyer_id": row["buyer_id"], "buyer_name": row["buyer_name"]}


def all_orders(conn: sqlite3.Connection, since: datetime | None = None,
               until: datetime | None = None) -> list[dict]:
    rows = conn.execute(accounts._ORDER_SELECT + accounts.NEWEST_FIRST)
    return [_with_buyer(row, accounts._order(row)) for row in rows
            if _within(row["created_at"], since, until)]


def any_order(conn: sqlite3.Connection, order_id: str, catalog: Any) -> dict | None:
    row = conn.execute(accounts._ORDER_SELECT + " WHERE o.order_id = ?", (order_id,)).fetchone()
    return None if row is None else _with_buyer(row, accounts.order_detail(conn, row, catalog))


# Who a log row belongs to


def mandates(conn: sqlite3.Connection, files: accounts.MandateFiles) -> dict[str, dict]:
    """buyer_id -> decoded mandate (unverified), for buyers that have a readable mandate file."""
    found = {}
    for row in accounts.buyer_rows(conn):
        token = files.read_token(row["buyer_id"])
        mandate = accounts.decode_unverified(token) if token else None
        if isinstance(mandate, dict):
            found[row["buyer_id"]] = mandate
    return found


def attributor(conn: sqlite3.Connection, by_buyer: dict[str, dict]) -> Callable[[sqlite3.Row], str | None]:
    """Which buyer a log row belongs to: by its order, then its quote's order, then its actor.

    The actor is matched against each mandate's agent_id, its approvers, and the buyer's
    name (a registration is logged under the kitchen's name). Search and
    get_product rows carry neither id, and their actor is the MCP client name, which is
    "valio-buyer-agent" for every buyer, so those stay unattributed (None)."""
    by_order, by_quote = {}, {}
    for o in conn.execute("SELECT order_id, quote_id, buyer_id FROM orders"):
        by_order[o["order_id"]] = o["buyer_id"]
        by_quote[o["quote_id"]] = o["buyer_id"]
    by_actor: dict[str, str] = {}
    names_on_file = {r["buyer_id"]: r["name"] for r in conn.execute("SELECT buyer_id, name FROM buyers")}
    for buyer_id, mandate in by_buyer.items():
        approvers = mandate.get("approvers") if isinstance(mandate.get("approvers"), list) else []
        names = ([mandate.get("agent_id")] + approvers
                 + [mandate.get("buyer"), names_on_file.get(buyer_id)])
        for name in names:
            if isinstance(name, str) and name:
                by_actor.setdefault(name, buyer_id)

    def buyer_of(row: sqlite3.Row) -> str | None:
        return (by_order.get(row["order_id"]) or by_quote.get(row["quote_id"])
                or by_actor.get(row["actor"]))

    return buyer_of


def full_log(conn: sqlite3.Connection, files: accounts.MandateFiles,
             since: datetime | None = None) -> list[dict]:
    buyer_of = attributor(conn, mandates(conn, files))
    return [{**{f: r[f] for f in accounts.LOG_FIELDS}, "order_id": r["order_id"],
             "quote_id": r["quote_id"], "buyer_id": buyer_of(r)}
            for r in conn.execute("SELECT * FROM log ORDER BY seq") if _within(r["time"], since, None)]


# Clients


def _latest(times: Iterable[str]) -> str | None:
    """The latest of some ISO times, as the original text."""
    best: tuple[datetime, str] | None = None
    for text in times:
        t = _time(text)
        if t is not None and (best is None or t > best[0]):
            best = (t, text)
    return best[1] if best else None


def agent_running(events: list[dict], now: datetime) -> bool:
    """events are one buyer's, oldest first. Running: its latest run has not ended and was
    heard from in the last 10 minutes (an agent that crashed never sends run_end)."""
    starts = [i for i, e in enumerate(events) if e.get("kind") == "run_start"]
    if not starts:
        return False
    run_id = events[starts[-1]].get("run_id")
    run = [e for e in events[starts[-1]:] if e.get("run_id") == run_id]
    if any(e.get("kind") == "run_end" for e in run):
        return False
    latest = _latest(e.get("ts") for e in run)
    return latest is not None and now - parse_time(latest) < RUN_IDLE


def clients(conn: sqlite3.Connection, files: accounts.MandateFiles, today: date,
            events: list[dict], now: datetime) -> list[dict]:
    by_buyer = mandates(conn, files)
    buyer_of = attributor(conn, by_buyer)
    log_times: dict[str, list[str]] = {}
    for r in conn.execute("SELECT * FROM log"):
        buyer_id = buyer_of(r)
        if buyer_id:
            log_times.setdefault(buyer_id, []).append(r["time"])
    counts = dict(conn.execute("SELECT buyer_id, count(*) FROM orders GROUP BY buyer_id").fetchall())

    rows = []
    for account in accounts.list_accounts(conn, files, today):
        buyer_id, mandate = account["buyer_id"], account["mandate"] or {}
        mine = [e for e in events if e.get("buyer") == buyer_id]
        rows.append({
            "buyer_id": buyer_id,
            "name": account["name"],
            "agent_id": mandate.get("agent_id"),
            "mandate_id": mandate.get("mandate_id"),
            "valid_until": mandate.get("valid_until"),
            "mandate_verified": account["mandate_verified"],
            "mandate_problem": account["mandate_problem"],
            "last_seen": _latest([e.get("ts") for e in mine] + log_times.get(buyer_id, [])),
            "agent_running": agent_running(mine, now),
            "orders_total": counts.get(buyer_id, 0),
        })
    return rows
