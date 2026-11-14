import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

STATE_DB = Path(os.environ.get("STATE_DB") or Path(__file__).resolve().parent.parent / "data" / "state.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
    name TEXT PRIMARY KEY,
    private_pem TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS buyers (
    buyer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    public_pem TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    customer_no TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enrolment_code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS order_history (
    buyer_id TEXT NOT NULL,
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    content_unit TEXT NOT NULL,
    ordered_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (
    quote_id TEXT PRIMARY KEY,
    body_json TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL UNIQUE,
    buyer_id TEXT NOT NULL,
    mandate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_id TEXT,
    question TEXT,
    reasons_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    approvers_json TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS log (
    seq INTEGER PRIMARY KEY,
    time TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    order_id TEXT,
    quote_id TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""


def connect(path: str | Path = STATE_DB) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
