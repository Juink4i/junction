"""Hash-chained log. Each row stores the hash of the row before it."""

import hashlib
import json
import sqlite3
from datetime import datetime

from server.db import transaction

GENESIS = "0" * 64
PUBLIC_FIELDS = ("seq", "time", "actor", "action", "reason", "prev_hash", "hash")
HASHED_FIELDS = ("seq", "time", "actor", "action", "reason", "order_id", "quote_id", "prev_hash")


def _hash(row) -> str:
    content = json.dumps([row[f] for f in HASHED_FIELDS], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def append(conn: sqlite3.Connection, time: datetime, actor: str, action: str, reason: str,
           order_id: str | None = None, quote_id: str | None = None) -> None:
    # Read the last hash and write the new row in one transaction, or two writers could
    # chain to the same row.
    with transaction(conn):
        last = conn.execute("SELECT seq, hash FROM log ORDER BY seq DESC LIMIT 1").fetchone()
        row = {
            "seq": last["seq"] + 1 if last else 1,
            "time": time.isoformat(),
            "actor": actor,
            "action": action,
            "reason": reason,
            "order_id": order_id,
            "quote_id": quote_id,
            "prev_hash": last["hash"] if last else GENESIS,
        }
        row["hash"] = _hash(row)
        conn.execute(
            "INSERT INTO log (seq, time, actor, action, reason, order_id, quote_id, prev_hash, hash) "
            "VALUES (:seq, :time, :actor, :action, :reason, :order_id, :quote_id, :prev_hash, :hash)",
            row,
        )


def entries(conn: sqlite3.Connection, order_id: str | None = None,
            quote_id: str | None = None) -> list[dict]:
    where, args = [], []
    if order_id:
        where.append("order_id = ?")
        args.append(order_id)
    if quote_id:
        where.append("quote_id = ?")
        args.append(quote_id)
    sql = "SELECT * FROM log" + (" WHERE " + " OR ".join(where) if where else "") + " ORDER BY seq"
    return [{f: row[f] for f in PUBLIC_FIELDS} for row in conn.execute(sql, args)]


def verify(conn: sqlite3.Connection) -> dict:
    prev_hash, expected_seq = GENESIS, 1
    for row in conn.execute("SELECT * FROM log ORDER BY seq"):
        if row["seq"] != expected_seq or row["prev_hash"] != prev_hash or row["hash"] != _hash(row):
            return {"ok": False, "broken_at_seq": row["seq"]}
        prev_hash, expected_seq = row["hash"], expected_seq + 1
    return {"ok": True}
