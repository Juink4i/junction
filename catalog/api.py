"""Contract A: the five catalog functions Runner 2's server calls.

Static questions (search, details) read data/catalog.db only. Prices and availability go to
the Valio Aimo API, for a shortlist only, through catalog.valio_client.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Literal

from catalog import units
from catalog.load import DB_PATH
from catalog.models import Offer, Product, ProductSummary, UnitPlan
from catalog.names import allergen_name, category_name, tag_name  # noqa: F401  (re-exported)
from catalog.overrides import Overrides

AllergenStatus = Literal["contains", "may_contain", "free_from", "unknown"]


class _State:
    db_path: Path = Path(os.environ.get("CATALOG_DB", DB_PATH))
    overrides: Overrides = Overrides(os.environ.get("CATALOG_OVERRIDES") or None)
    client = None  # created on first use, see _client()


_state = _State()


def configure(db_path: Path | None = None, overrides_path: Path | None = None, client=None) -> None:
    """Point the catalog at a database, overrides file and API client. No arguments = defaults."""
    _state.db_path = Path(db_path) if db_path else Path(os.environ.get("CATALOG_DB", DB_PATH))
    _state.overrides = Overrides(overrides_path or os.environ.get("CATALOG_OVERRIDES") or None)
    _state.client = client


def _connect() -> sqlite3.Connection:
    if not _state.db_path.exists():
        raise FileNotFoundError(f"{_state.db_path} not found. Run: uv run python -m catalog.load")
    con = sqlite3.connect(f"file:{_state.db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _row(product_id: str) -> sqlite3.Row | None:
    with _connect() as con:
        return con.execute("SELECT * FROM products WHERE id = ?", (str(product_id),)).fetchone()


def _summary(r: sqlite3.Row) -> ProductSummary:
    s = ProductSummary(
        id=r["id"], name_en=r["name_en"], name_fi=r["name_fi"], category=r["category"],
        sales_unit=r["sales_unit"], tags=json.loads(r["tags"]), labels=json.loads(r["labels"]),
    )
    return _state.overrides.product(s, r["id"])


def _product(r: sqlite3.Row) -> Product:
    p = Product(
        id=r["id"], name_en=r["name_en"], name_fi=r["name_fi"], category=r["category"],
        sales_unit=r["sales_unit"], tags=json.loads(r["tags"]), labels=json.loads(r["labels"]),
        allergens_contains=json.loads(r["allergens_contains"]),
        allergens_may_contain=json.loads(r["allergens_may_contain"]),
        allergens_free_from=json.loads(r["allergens_free_from"]),
        allergen_info_missing=bool(r["allergen_info_missing"]),
        vendor=r["vendor"], country=r["country"], description=r["description"],
        carbon_kg_per_kg=r["carbon_kg_per_kg"], delivery_reliability=r["delivery_reliability"],
        official_substitutes=json.loads(r["official_substitutes"]),
    )
    return _state.overrides.product(p, r["id"])


def search_products(text: str, category: str | None = None,
                    must_have_tags: list[str] = [], limit: int = 20) -> list[ProductSummary]:
    """Every word of `text` must appear somewhere in the product's fi/en/sv name or brand.

    Substring matching, not word matching, because Finnish compounds hide words:
    "maito" (milk) is inside "kevytmaito". Tags and category are exact filters.
    """
    where, args = [], []
    for word in (text or "").lower().split():
        where.append("instr(search_text, ?) > 0")
        args.append(word)
    if category:
        where.append("category = ?")
        args.append(str(category))
    for tag in must_have_tags or []:
        where.append("EXISTS (SELECT 1 FROM json_each(products.tags) WHERE value = ?)")
        args.append(tag)
    phrase = " ".join((text or "").lower().split())
    sql = (
        "SELECT * FROM products"
        + (" WHERE " + " AND ".join(where) if where else "")
        # Whole phrase in a name first, then shorter (more generic) names, then id for stability.
        + " ORDER BY (instr(lower(name_en), ?) = 0 AND instr(lower(name_fi), ?) = 0),"
        " length(name_en), id LIMIT ?"
    )
    with _connect() as con:
        rows = con.execute(sql, [*args, phrase, phrase, max(0, int(limit))]).fetchall()
    return [_summary(r) for r in rows]


def get_product(product_id: str) -> Product | None:
    r = _row(product_id)
    return _product(r) if r else None


def _client():
    if _state.client is None:
        from catalog.valio_client import ValioClient
        _state.client = ValioClient()
    return _state.client


def price_and_availability(product_ids: list[str], delivery_date: date) -> dict[str, Offer]:
    """Live price and availability for a shortlist. Products without a price are left out.

    Calls POST /api/price and POST /api/availability once each for ids not cached in the last
    5 minutes. Demo overrides are applied on top.
    """
    offers = _client().offers(product_ids, delivery_date)
    return {pid: _state.overrides.offer(o, pid) for pid, o in offers.items()}


def units_needed(product_id: str, amount: float, unit: str) -> UnitPlan:
    """How many sales units cover `amount` litres, kilos or pieces. Always rounds up.

    Uses the product file when it gives a clean volume/weight/piece count. Otherwise, for
    litres and kilos, uses Valio Aimo's own unit price / comparison price (one cached price
    call, any date: pack size doesn't change). Raises UnitMismatch when the product is
    measured in another unit; no density guessing.
    """
    unit = unit.upper()
    if unit not in ("L", "KG", "PCS"):
        raise ValueError(f"unit must be 'L', 'KG' or 'PCS', not {unit!r}")
    if not amount or amount <= 0:
        raise ValueError("amount must be positive")
    r = _row(product_id)
    if r is None:
        raise KeyError(product_id)

    content = units.content_from_product(r).get(unit)
    if unit == "PCS" and content is None:
        raise units.UnitMismatch(f"{r['id']}: no piece count in the product data")
    price = _state.client.cached_price(r["id"]) if _state.client and unit != "PCS" else None
    if unit != "PCS" and (content is None or price is not None):
        if price is None:
            _client().offers([r["id"]], date.today())
            price = _client().cached_price(r["id"])
        if price and price.get("comparisonPrice") and price.get("comparisonUnit"):
            if price["comparisonUnit"] != unit and content is None:
                raise units.UnitMismatch(
                    f"{r['id']} is priced per {price['comparisonUnit']}, not per {unit}")
            if price["comparisonUnit"] == unit:
                from_prices = units.content_from_prices(
                    price["catalogPrice"]["value"], price["comparisonPrice"]["value"])
                # Valio Aimo's own price per litre/kilo wins when the supplier data disagrees.
                if content is None or abs(content - from_prices) > 0.02 * from_prices:
                    content = from_prices
    if content is None:
        raise units.UnitMismatch(f"{r['id']}: no {unit} size in product data or prices")

    n = math.ceil(amount / content - 1e-9)
    return UnitPlan(product_id=r["id"], sales_unit=r["sales_unit"], content_per_unit=content,
                    content_unit=unit, units=n, covers=round(n * content, 4))


def substitute_candidates(product_id: str, must_keep_tags: list[str],
                          max_price_increase_pct: float, delivery_date: date) -> list[Offer]:
    """Products that can replace `product_id`, decided by code. The AI only ranks what's left.

    A candidate is in the same category, has every must-keep tag, can be ordered and arrive by
    `delivery_date` with its cut-off not passed, and costs at most `max_price_increase_pct`
    more per litre/kilo (comparison price, so a 1 l carton and a 2 x 10 l case compare fairly).
    Valio Aimo's official substitutes come first, then cheapest per litre/kilo first.
    One price call and one availability call for the whole shortlist.
    """
    original = get_product(product_id)
    if original is None:
        raise KeyError(product_id)
    where = ["category = ?", "id != ?"]
    args: list = [original.category, original.id]
    for tag in must_keep_tags or []:
        where.append("EXISTS (SELECT 1 FROM json_each(products.tags) WHERE value = ?)")
        args.append(tag)
    with _connect() as con:
        ids = [r["id"] for r in con.execute(
            f"SELECT id FROM products WHERE {' AND '.join(where)} ORDER BY id", args)]

    offers = price_and_availability([original.id, *ids], delivery_date)
    ref = offers.get(original.id)
    if ref is None or ref.comparison_price_eur is None:
        raise ValueError(f"{original.id} has no price per litre/kilo to compare substitutes against")
    cap = ref.comparison_price_eur * (1 + max_price_increase_pct / 100) + 1e-9

    official = set(original.official_substitutes)
    keep = [
        o for pid, o in offers.items()
        if pid in ids
        and o.orderable and not o.cutoff_passed
        and o.available_date is not None and o.available_date <= delivery_date
        and o.comparison_unit == ref.comparison_unit
        and o.comparison_price_eur is not None and o.comparison_price_eur <= cap
    ]
    return sorted(keep, key=lambda o: (o.product_id not in official, o.comparison_price_eur, o.product_id))


def allergen_status(product_id: str, allergen_code: str) -> AllergenStatus:
    """What the product data says about one allergen. "unknown" is never safe.

    A product can list what it contains without listing what it is free from, so an allergen
    that appears in neither list is "unknown", even when allergen_info_missing is False.
    """
    p = get_product(product_id)
    if p is None:
        raise KeyError(product_id)
    if allergen_code in p.allergens_contains:
        return "contains"
    if allergen_code in p.allergens_may_contain:
        return "may_contain"
    if allergen_code in p.allergens_free_from:
        return "free_from"
    return "unknown"
