"""Answer a buying request from the catalog alone, with live prices. A check, not the product.

    uv run python -m catalog 1000 L 2026-11-16 --category 10400 --tags FREE_FROM_LACTOSE
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from catalog import api
from catalog.units import UnitMismatch


def options(amount: float, unit: str, need_by: date, text: str = "", category: str | None = None,
            tags: list[str] | None = None, limit: int = 200) -> list[dict]:
    hits = api.search_products(text, category=category, must_have_tags=tags or [], limit=limit)
    offers = api.price_and_availability([h.id for h in hits], need_by) if hits else {}
    rows = []
    for h in hits:
        o = offers.get(h.id)
        row = {"product_id": h.id, "name": h.name_en, "units": None, "sales_unit": h.sales_unit,
               "content_per_unit": None, "unit_price_eur": o.unit_price_eur if o else None,
               "price_per_unit_of_measure": o.comparison_price_eur if o else None,
               "total_eur": None, "available_date": o.available_date if o else None,
               "on_time": False, "why_not": None}
        try:
            plan = api.units_needed(h.id, amount, unit)
            row.update(units=plan.units, content_per_unit=plan.content_per_unit)
        except UnitMismatch:
            plan = None
            row["why_not"] = f"priced per {o.comparison_unit if o else '?'}, not per {unit}"
        if o and plan:
            row["total_eur"] = round(plan.units * o.unit_price_eur, 2)
        if row["why_not"]:
            pass
        elif o is None:
            row["why_not"] = "no price"
        elif not o.orderable or o.available_date is None:
            row["why_not"] = "cannot be delivered"
        elif o.cutoff_passed:
            row["why_not"] = f"order cut-off passed ({o.closing_time:%a %d %b %H:%M})"
        elif o.available_date > need_by:
            row["why_not"] = f"arrives {o.available_date:%a %d %b}"
        elif o.available_units is not None and plan and o.available_units < plan.units:
            row["why_not"] = f"only {o.available_units} {h.sales_unit} in stock"
        else:
            row["on_time"] = True
        rows.append(row)
    return sorted(rows, key=lambda r: (not r["on_time"], r["total_eur"] is None, r["total_eur"] or 0))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m catalog", description=__doc__.splitlines()[0])
    ap.add_argument("amount", type=float)
    ap.add_argument("unit", choices=["L", "KG"])
    ap.add_argument("need_by", type=date.fromisoformat)
    ap.add_argument("--text", default="")
    ap.add_argument("--category")
    ap.add_argument("--tags", nargs="*", default=[])
    a = ap.parse_args(argv)
    for r in options(a.amount, a.unit, a.need_by, a.text, a.category, a.tags):
        total = f"EUR {r['total_eur']:>9,.2f}" if r["total_eur"] is not None else " " * 13
        units = f"{r['units']:>5} x {r['sales_unit']:<3}" if r["units"] else " " * 11
        status = "ON TIME" if r["on_time"] else r["why_not"]
        print(f"{r['product_id']}  {total}  {units}  {r['name'][:52]:<52}  {status}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # product names have ®, ä, ö
    sys.exit(main())
