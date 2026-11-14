"""Contract A: the five catalog functions Runner 2's server calls.

Static questions (search, details) read data/catalog.db only. Prices and availability go to
the Valio Aimo API, for a shortlist only, through catalog.valio_client.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Literal

from catalog.load import DB_PATH
from catalog.models import Offer, Product, ProductSummary
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
