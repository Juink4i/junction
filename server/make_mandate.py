"""Create signed demo mandates for a hotel, a café and a school.

    uv run python -m server.make_mandate

For each demo buyer this:
- gives its agent a key pair (data/buyers/<id>/agent_key.pem) and names the public half in
  the mandate as agent_key, because the trade server only lets in agents a mandate names;
- keeps the kitchen's own signing key in data/buyer_keys/<id>.pem, where the web mandate
  editor looks, so later edits do not change keys again (an existing key there is reused);
- keeps the rules of an existing server/mandates/<id>.jwt (for example the café's edits on
  the web page) and bumps its version, or starts from DEMO_MANDATES;
- registers the kitchen's public key and made-up order history in data/state.db and writes
  the token to server/mandates/<id>.jwt.
Tokens signed with a key that is no longer registered stop working.
"""

import copy
import re
import sqlite3
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server import signing
from server.db import connect

ROOT = Path(__file__).resolve().parent.parent
MANDATE_DIR = Path(__file__).resolve().parent / "mandates"
BUYERS_DIR = ROOT / "data" / "buyers"
BUYER_KEYS_DIR = ROOT / "data" / "buyer_keys"

DEMO_MANDATES = {
    "hotel": {
        "mandate_id": "mnd_hotel_helsinki_001",
        "buyer": "Hotel Chain Oy / Helsinki Central",
        "agent_id": "buyer-agent-01",
        "valid_until": "2026-12-31",
        "auto_approve": {"max_order_eur": 1500, "max_line_eur": 800},
        "substitution": {"allowed": True, "must_keep": ["FREE_FROM_LACTOSE"], "max_price_increase_pct": 10},
        "hard_rules": {"blocked_allergens": [], "unknown_allergens": "human", "no_delivery_after": "need_by_date"},
        "approvers": ["procurement.manager@hotel.example"],
    },
    "cafe": {
        "mandate_id": "mnd_cafe_kallio_001",
        "buyer": "Café Kallio",
        "agent_id": "buyer-agent-02",
        "valid_until": "2026-12-31",
        "auto_approve": {"max_order_eur": 500, "max_line_eur": 400},
        "substitution": {"allowed": True, "must_keep": [], "max_price_increase_pct": 15},
        "hard_rules": {"blocked_allergens": [], "unknown_allergens": "human", "no_delivery_after": "need_by_date"},
        "approvers": ["owner@cafe.example"],
    },
    "school": {
        "mandate_id": "mnd_school_espoo_001",
        "buyer": "Espoo School Kitchens",
        "agent_id": "buyer-agent-03",
        "valid_until": "2026-12-31",
        "auto_approve": {"max_order_eur": 800, "max_line_eur": 500},
        "substitution": {"allowed": False, "must_keep": [], "max_price_increase_pct": 0},
        "hard_rules": {"blocked_allergens": ["AP", "AN", "AE"], "unknown_allergens": "human",
                       "no_delivery_after": "need_by_date"},
        "approvers": ["kitchen.lead@school.example"],
    },
}

# Simulated: Valio Aimo gives us no order history. Litres of milk (category 10400) per order.
DEMO_HISTORY = {
    "hotel": [900, 1000, 950, 1100],
    "cafe": [20, 20, 25, 15],
    "school": [200, 220, 180],
}


# Simulated: customers Valio Aimo already knows. Each one sees its enrolment code in its
# Valio Aimo webshop account, and uses it to register an agent's key.
DEMO_CUSTOMERS = [("100234", "Päiväkoti Aurinko", "AIMO-7Q4K-2M9X")]


def seed_demo_customers(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO customers (customer_no, name, enrolment_code) VALUES (?, ?, ?) "
        "ON CONFLICT (customer_no) DO UPDATE SET name = excluded.name, "
        "enrolment_code = excluded.enrolment_code", DEMO_CUSTOMERS)


def _register(conn: sqlite3.Connection, buyer_id: str, name: str, key: Ed25519PrivateKey) -> None:
    """The buyer's public key and its made-up order history."""
    conn.execute(
        "INSERT INTO buyers (buyer_id, name, public_pem) VALUES (?, ?, ?) "
        "ON CONFLICT (buyer_id) DO UPDATE SET name = excluded.name, public_pem = excluded.public_pem",
        (buyer_id, name, signing.public_pem(key.public_key())),
    )
    conn.execute("DELETE FROM order_history WHERE buyer_id = ?", (buyer_id,))
    conn.executemany(
        "INSERT INTO order_history (buyer_id, category, amount, content_unit, ordered_on) "
        "VALUES (?, '10400', ?, 'L', ?)",
        [(buyer_id, litres, f"2026-10-{5 + 7 * week:02d}")
         for week, litres in enumerate(DEMO_HISTORY[buyer_id])],
    )


def issue_demo_mandates(conn: sqlite3.Connection) -> dict[str, str]:
    """Fresh keys and the plain demo mandates, without agent keys. For tests that do not go
    through the HTTP endpoint; the command line uses refresh_demo_buyers."""
    tokens = {}
    for buyer_id, mandate in DEMO_MANDATES.items():
        key = signing.generate_key()
        _register(conn, buyer_id, mandate["buyer"], key)
        tokens[buyer_id] = signing.sign(mandate, key, kid=buyer_id)
    return tokens


def next_mandate_id(mandate_id: str) -> str:
    """mnd_hotel_helsinki_001 -> mnd_hotel_helsinki_002 (keeps the zero padding)."""
    m = re.fullmatch(r"(.*?)(\d+)", mandate_id)
    if not m:
        return f"{mandate_id}_002"
    prefix, number = m.groups()
    return prefix + str(int(number) + 1).zfill(len(number))


def _kitchen_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = signing.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(signing.private_pem(key))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def refresh_demo_buyers(conn: sqlite3.Connection, mandate_dir: Path = MANDATE_DIR,
                        buyers_dir: Path = BUYERS_DIR,
                        buyer_keys_dir: Path = BUYER_KEYS_DIR) -> dict[str, str]:
    """Give each demo buyer an agent key and a mandate that names it. Returns the tokens."""
    from agent.identity import ensure_agent_key  # the agent's side makes its own key

    tokens = {}
    Path(mandate_dir).mkdir(parents=True, exist_ok=True)
    for buyer_id, demo in DEMO_MANDATES.items():
        path = Path(mandate_dir) / f"{buyer_id}.jwt"
        mandate = None
        if path.exists():
            try:
                mandate = jwt.decode(path.read_text().strip(), options={"verify_signature": False})
            except jwt.InvalidTokenError:
                mandate = None
        if isinstance(mandate, dict) and mandate.get("mandate_id"):
            mandate["mandate_id"] = next_mandate_id(str(mandate["mandate_id"]))  # keep its rules
        else:
            mandate = copy.deepcopy(demo)
        mandate["agent_key"] = ensure_agent_key(buyer_id, Path(buyers_dir))
        key = _kitchen_key(Path(buyer_keys_dir) / f"{buyer_id}.pem")
        _register(conn, buyer_id, mandate.get("buyer") or demo["buyer"], key)
        tokens[buyer_id] = signing.sign(mandate, key, kid=buyer_id)
        path.write_text(tokens[buyer_id])
    return tokens


if __name__ == "__main__":
    conn = connect()
    for buyer_id, token in refresh_demo_buyers(conn).items():
        mandate = jwt.decode(token, options={"verify_signature": False})
        print(f"{mandate['buyer']}: {MANDATE_DIR / f'{buyer_id}.jwt'} ({mandate['mandate_id']}, "
              f"agent key in {BUYERS_DIR / buyer_id / 'agent_key.pem'})")
    seed_demo_customers(conn)
    for customer_no, name, code in DEMO_CUSTOMERS:
        print(f"Demo enrolment code for customer {customer_no} ({name}): {code}")
