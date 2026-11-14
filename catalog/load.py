"""Load the Valio Aimo product file and the two CSVs into data/catalog.db.

Run once: `uv run python -m catalog.load`
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "catalog.db"

PRODUCT_FILE = "valio_aimo_junction26_product_data.json"
CARBON_FILE = "valio_aimo_junction26_carbon_footprint.csv"
RELIABILITY_FILE = "valio_aimo_junction26_delivery_reliability.csv"

SCHEMA = """
CREATE TABLE products (
    id                    TEXT PRIMARY KEY,
    name_en               TEXT NOT NULL,
    name_fi               TEXT NOT NULL,
    name_sv               TEXT NOT NULL,
    brand                 TEXT,
    category              TEXT NOT NULL,
    sales_unit            TEXT NOT NULL,
    base_unit             TEXT NOT NULL,
    vendor                TEXT,
    country               TEXT,
    description           TEXT NOT NULL,
    tags                  TEXT NOT NULL,  -- JSON list: nutritionalClaim ids, e.g. FREE_FROM_LACTOSE
    labels                TEXT NOT NULL,  -- JSON list: packagingMarkedLabel ids
    allergens_contains    TEXT NOT NULL,  -- JSON list of allergen codes
    allergens_may_contain TEXT NOT NULL,
    allergens_free_from   TEXT NOT NULL,
    allergen_info_missing INTEGER NOT NULL,
    carbon_kg_per_kg      REAL,
    delivery_reliability  REAL,
    official_substitutes  TEXT NOT NULL,  -- JSON list of product ids
    units                 TEXT NOT NULL,  -- JSON packaging ladder [{unitId, sizeInBaseUnits}]
    unit_conversions      TEXT NOT NULL,  -- JSON synkkaData.unitConversions
    search_text           TEXT NOT NULL,  -- lower-case names + brand, for substring search
    raw                   TEXT NOT NULL   -- the original product JSON
);
CREATE INDEX products_category ON products(category);
"""


def _text(entries: list[dict], lang: str) -> str | None:
    for e in entries or []:
        if e.get("language") == lang and e.get("value"):
            return e["value"]
    return None


def _classification(synkka: dict, name: str) -> list[dict]:
    for c in synkka.get("classifications") or []:
        if c.get("name") == name:
            return c.get("values") or []
    return []


def _read_csv(path: Path, column: str) -> dict[str, float]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["productId"].strip(): float(r[column]) for r in csv.DictReader(f) if r[column].strip()}


def product_row(p: dict, carbon: dict[str, float], reliability: dict[str, float]) -> tuple:
    s = p.get("synkkaData") or {}
    names = s.get("names") or []
    name_fi = _text(names, "fi") or _text(names, "en") or ""
    name_en = _text(names, "en") or name_fi
    name_sv = _text(names, "sv") or ""
    texts = s.get("marketingTexts") or []
    description = _text(texts, "en") or _text(texts, "fi") or ""

    allergens = _classification(s, "allergen")
    contains = [a["id"] for a in allergens if a.get("unit") == "CONTAINS"]
    may_contain = [a["id"] for a in allergens if a.get("unit") == "MAY_CONTAIN"]
    free_from = [a["id"] for a in _classification(s, "nonAllergen")]
    tags = [c["id"] for c in _classification(s, "nutritionalClaim")]
    labels = [c["id"] for c in _classification(s, "packagingMarkedLabel")]
    subs = [x["substituteProduct"] for x in p.get("substitutions") or []]
    brand = s.get("brand")

    pid = p["id"]
    return (
        pid, name_en, name_fi, name_sv, brand, p["category"], p["salesUnit"], p["baseUnit"],
        p.get("vendorName"), p.get("countryOfOrigin"), description,
        json.dumps(tags), json.dumps(labels),
        json.dumps(contains), json.dumps(may_contain), json.dumps(free_from),
        int(not allergens and not free_from),
        carbon.get(pid), reliability.get(pid), json.dumps(subs),
        json.dumps(p.get("units") or []), json.dumps(s.get("unitConversions") or []),
        " | ".join(x for x in (name_en, name_fi, name_sv, brand) if x).lower(),
        json.dumps(p, ensure_ascii=False),
    )


def load(raw_dir: Path = RAW_DIR, db_path: Path = DB_PATH) -> int:
    """Build a fresh catalog database. Returns the number of products loaded."""
    raw_dir, db_path = Path(raw_dir), Path(db_path)
    products = json.loads((raw_dir / PRODUCT_FILE).read_text(encoding="utf-8"))
    carbon = _read_csv(raw_dir / CARBON_FILE, "AVG kg CO2-eq/kg")
    reliability = _read_csv(raw_dir / RELIABILITY_FILE, "deliveryReliability")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    rows = [product_row(p, carbon, reliability) for p in products]
    con.executemany(f"INSERT INTO products VALUES ({','.join('?' * len(rows[0]))})", rows)
    con.commit()
    con.close()
    tmp.replace(db_path)  # swap in atomically so readers never see a half-built db
    return len(rows)


def main() -> None:
    start = time.perf_counter()
    n = load()
    print(f"Loaded {n} products into {DB_PATH} in {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
