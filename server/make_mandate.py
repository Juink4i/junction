"""Create signed demo mandates for a hotel, a café and a school.

    uv run python -m server.make_mandate

Registers each buyer's public key and made-up order history in data/state.db and
writes the tokens to server/mandates/<buyer>.jwt. Running it again issues new keys,
so older tokens stop working.
"""

import sqlite3
from pathlib import Path

from server import signing
from server.db import connect

MANDATE_DIR = Path(__file__).resolve().parent / "mandates"

DEMO_MANDATES = {
    "hotel": {
        "mandate_id": "mnd_hotel_helsinki_001",
        "buyer": "Hotel Chain Oy / Helsinki Central",
        "agent_id": "buyer-agent-01",
        "valid_until": "2026-12-31",
        "auto_approve": {"max_order_eur": 1500, "max_line_eur": 800, "allowed_categories": ["10400"]},
        "substitution": {"allowed": True, "must_keep": ["FREE_FROM_LACTOSE"], "max_price_increase_pct": 10},
        "hard_rules": {"blocked_allergens": [], "unknown_allergens": "human", "no_delivery_after": "need_by_date"},
        "approvers": ["procurement.manager@hotel.example"],
    },
    "cafe": {
        "mandate_id": "mnd_cafe_kallio_001",
        "buyer": "Café Kallio",
        "agent_id": "buyer-agent-02",
        "valid_until": "2026-12-31",
        "auto_approve": {"max_order_eur": 500, "max_line_eur": 400, "allowed_categories": ["10400"]},
        "substitution": {"allowed": True, "must_keep": [], "max_price_increase_pct": 15},
        "hard_rules": {"blocked_allergens": [], "unknown_allergens": "human", "no_delivery_after": "need_by_date"},
        "approvers": ["owner@cafe.example"],
    },
    # No allowed_categories: the school kitchen may buy from any category.
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


def issue_demo_mandates(conn: sqlite3.Connection) -> dict[str, str]:
    tokens = {}
    for buyer_id, mandate in DEMO_MANDATES.items():
        key = signing.generate_key()
        conn.execute(
            "INSERT INTO buyers (buyer_id, name, public_pem) VALUES (?, ?, ?) "
            "ON CONFLICT (buyer_id) DO UPDATE SET name = excluded.name, public_pem = excluded.public_pem",
            (buyer_id, mandate["buyer"], signing.public_pem(key.public_key())),
        )
        conn.execute("DELETE FROM order_history WHERE buyer_id = ?", (buyer_id,))
        conn.executemany(
            "INSERT INTO order_history (buyer_id, category, amount, content_unit, ordered_on) "
            "VALUES (?, '10400', ?, 'L', ?)",
            [(buyer_id, litres, f"2026-10-{5 + 7 * week:02d}")
             for week, litres in enumerate(DEMO_HISTORY[buyer_id])],
        )
        tokens[buyer_id] = signing.sign(mandate, key, kid=buyer_id)
    return tokens


if __name__ == "__main__":
    MANDATE_DIR.mkdir(exist_ok=True)
    for buyer_id, token in issue_demo_mandates(connect()).items():
        path = MANDATE_DIR / f"{buyer_id}.jwt"
        path.write_text(token)
        print(f"{DEMO_MANDATES[buyer_id]['buyer']}: {path}")
