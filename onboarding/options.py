"""The choices the onboarding page offers, and the four kitchen-type templates."""

from __future__ import annotations

import copy
from typing import Any

from catalog.names import ALLERGEN_NAMES, CATEGORY_NAMES

# The 14 allergens EU law requires on labels, as GS1 codes.
EU_ALLERGEN_CODES = ("AW", "AC", "AE", "AF", "AP", "AY", "AM", "AN", "BC", "BM", "AS", "AU", "NL", "UM")
ALLERGENS = {code: ALLERGEN_NAMES[code] for code in EU_ALLERGEN_CODES}
CATEGORIES = dict(CATEGORY_NAMES)
TAGS = {"FREE_FROM_LACTOSE": "lactose-free", "VEGAN": "vegan"}
WEEKDAYS = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday",
            "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}
PRIORITIES = {"price": "the lowest price", "reliability": "reliable delivery",
              "finnish": "Finnish origin", "sustainability": "sustainability"}
PACK_SIZES = {"small": "small packs", "large": "large packs"}
PERIODS = {"week": "week", "month": "month"}
UNKNOWN_ALLERGEN_CHOICES = {"human": "A person checks it", "reject": "Refuse it"}
KITCHEN_TYPES = {"daycare": "Day-care", "school": "School", "hotel": "Hotel", "cafe": "Café"}
# Which label the page shows beside delivery days. "preference" until the server enforces them.
DELIVERY_DAYS_SIDE = "preference"

_PRICE_FIRST = ["price", "reliability", "finnish", "sustainability"]
_WORKDAYS = ["MON", "TUE", "WED", "THU", "FRI"]


def _kitchen(kind: str, name: str, approver: str, *, blocked: list[str], must_be: list[str],
             categories: list[str], max_order: float, budget: tuple[str, float], days: list[str],
             pack: str, what: str, litres: float, substitution: tuple[bool, float],
             code: str = "") -> dict[str, Any]:
    return {
        "kitchen": {"name": name, "type": kind, "approver": approver, "enrolment_code": code},
        "safety": {"blocked_allergens": blocked, "unknown_allergens": "human", "must_be": must_be},
        "money": {"allowed_categories": categories, "max_order_eur": max_order,
                  "budget": {"period": budget[0], "max_eur": budget[1]},
                  "priorities": list(_PRICE_FIRST)},
        "delivery": {"days": days, "pack_size": pack},
        "usual_orders": [{"what": what, "category": "10400", "amount": litres, "unit": "L",
                          "every": "week"}],
        # Not asked on the page: the server does not enforce these two today.
        "substitution": {"allowed": substitution[0], "max_price_increase_pct": substitution[1]},
    }


TEMPLATES = {
    "daycare": _kitchen("daycare", "Päiväkoti Aurinko", "kitchen.lead@aurinko.example",
                        blocked=["AP", "AN"], must_be=["FREE_FROM_LACTOSE"], categories=["10400"],
                        max_order=100, budget=("week", 150), days=["MON", "THU"], pack="small",
                        what="lactose-free milk", litres=40, substitution=(True, 10),
                        code="AIMO-7Q4K-2M9X"),
    "school": _kitchen("school", "Tapiolan koulu", "kitchen.lead@tapiolankoulu.example",
                       blocked=["AP", "AN", "AE"], must_be=[], categories=[],
                       max_order=800, budget=("month", 3000), days=["MON", "WED", "FRI"], pack="large",
                       what="milk", litres=200, substitution=(False, 0)),
    "hotel": _kitchen("hotel", "Hotel Meri", "procurement@hotelmeri.example",
                      blocked=[], must_be=["FREE_FROM_LACTOSE"], categories=["10400"],
                      max_order=1500, budget=("month", 6000), days=list(_WORKDAYS), pack="large",
                      what="lactose-free milk", litres=1000, substitution=(True, 10)),
    "cafe": _kitchen("cafe", "Café Sointu", "owner@cafesointu.example",
                     blocked=[], must_be=[], categories=["10400"],
                     max_order=500, budget=("week", 600), days=list(_WORKDAYS), pack="small",
                     what="milk", litres=20, substitution=(True, 15)),
}


def template(kind: str) -> dict[str, Any]:
    """A fresh copy of one kitchen type's answers."""
    return copy.deepcopy(TEMPLATES[kind])


def _listed(names: dict[str, str]) -> list[dict[str, str]]:
    return [{"code": code, "name": name} for code, name in names.items()]


def options() -> dict[str, Any]:
    """Everything the page needs to draw the form, so the page hard-codes no list."""
    return {
        "kitchen_types": _listed(KITCHEN_TYPES),
        "templates": copy.deepcopy(TEMPLATES),
        "allergens": _listed(ALLERGENS),
        "categories": _listed(CATEGORIES),
        "tags": _listed(TAGS),
        "weekdays": _listed(WEEKDAYS),
        "priorities": _listed(PRIORITIES),
        "pack_sizes": _listed(PACK_SIZES),
        "periods": _listed(PERIODS),
        "unknown_allergens": _listed(UNKNOWN_ALLERGEN_CHOICES),
        "delivery_days_side": DELIVERY_DAYS_SIDE,
    }
