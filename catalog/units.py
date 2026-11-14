"""How many litres or kilos are in one sales unit.

Two sources, in this order:
1. The product file: base-unit volume (LTR/DLT/CLT/MLT) or net weight (KGM/GRM) times the
   size of the sales unit in the packaging ladder. Only clean volume/weight units are trusted:
   the file's "volume" field often holds grams or piece counts.
2. Valio Aimo's own prices: unit price / comparison price (EUR per L or KG). Both are rounded
   to the cent, so the ratio is noisy (31.31 / 1.57 = 19.94 for a 2 x 10 l case). The true
   size lies in a small interval around it; we pick the roundest number inside that interval.
"""

from __future__ import annotations

import json
import math

VOLUME_TO_L = {"LTR": 1.0, "DLT": 0.1, "CLT": 0.01, "MLT": 0.001}
WEIGHT_TO_KG = {"KGM": 1.0, "GRM": 0.001}
# Steps tried from roundest to finest when snapping a price ratio to a pack size.
SNAP_STEPS = (10, 5, 1, 0.5, 0.25, 0.1, 0.05, 0.01)
CENT = 0.005  # half a cent: the rounding error in each price


class UnitMismatch(ValueError):
    """The product is measured in a different unit than the one asked for (e.g. L vs KG)."""


def content_from_product(row) -> dict[str, float]:
    """{"L": litres, "KG": kilos} per sales unit, from the product file. Missing keys = unknown."""
    ladder = {u["unitId"]: u.get("sizeInBaseUnits") for u in json.loads(row["units"])}
    per_sales_unit = ladder.get(row["sales_unit"])
    if not per_sales_unit:
        return {}
    if row["base_unit"] == "KG":
        return {"KG": round(per_sales_unit, 4)}
    base = next((c for c in json.loads(row["unit_conversions"])
                 if c.get("synkkaPackagingType") == "BASE_UNIT_OR_EACH"), None)
    if not base:
        return {}
    out = {}
    vol = base.get("volume") or {}
    if vol.get("unit") in VOLUME_TO_L and vol.get("value"):
        out["L"] = round(vol["value"] * VOLUME_TO_L[vol["unit"]] * per_sales_unit, 4)
    weight = base.get("netWeight") or {}
    if weight.get("unit") in WEIGHT_TO_KG and weight.get("value"):
        out["KG"] = round(weight["value"] * WEIGHT_TO_KG[weight["unit"]] * per_sales_unit, 4)
    return out


def content_from_prices(unit_price: float, comparison_price: float) -> float:
    """Pack size from two cent-rounded prices: the roundest size that fits both."""
    if unit_price <= 0 or comparison_price <= 0:
        raise ValueError("prices must be positive")
    ratio = unit_price / comparison_price
    lo = max(unit_price - CENT, 0) / (comparison_price + CENT)
    hi = (unit_price + CENT) / max(comparison_price - CENT, 1e-9)
    for step in SNAP_STEPS:
        candidates = [k * step for k in range(math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9) + 1)]
        candidates = [c for c in candidates if c > 0]
        if candidates:
            return round(min(candidates, key=lambda c: abs(c - ratio)), 4)
    return round(ratio, 3)
