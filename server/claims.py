"""Does a product have a must-have property? Plain code, no AI.

A supplier's own claim (a nutrition claim tag) always proves it. For a free-from property
the allergen data can prove it too: an egg whose data says "free from milk" is lactose-free
even though no egg claims it. Data that does not mention the allergen proves nothing, so
the answer is unknown, never yes.
"""

from __future__ import annotations

from typing import Any, NamedTuple

YES, NO, UNKNOWN = "yes", "no", "unknown"


class FreeFrom(NamedTuple):
    rules_out: frozenset[str]  # contains or may contain any of these: not free from it
    proves: frozenset[str]     # declared free from any of these: free from it


_GLUTEN_CEREALS = frozenset({"AW", "UW", "NR", "GB", "GS", "GK"})  # gluten cereals, wheat, rye, ...

FREE_FROM = {
    "FREE_FROM_LACTOSE": FreeFrom(frozenset({"AM", "ML"}), frozenset({"AM", "ML"})),
    "FREE_FROM_GLUTEN": FreeFrom(_GLUTEN_CEREALS, frozenset({"AW"})),
    "FREE_FROM_WHEAT": FreeFrom(frozenset({"UW"}), frozenset({"UW", "AW"})),
    "FREE_FROM_EGGS": FreeFrom(frozenset({"AE"}), frozenset({"AE"})),
    "FREE_FROM_SOY": FreeFrom(frozenset({"AY"}), frozenset({"AY"})),
}


def _codes(values: list[str]) -> set[str]:
    return {v.upper() for v in values}


def status(product: Any, tag: str) -> str:
    """YES, NO or UNKNOWN. A property allergen data cannot speak to is YES only when claimed."""
    if tag in product.tags:
        return YES
    rule = FREE_FROM.get(tag)
    if rule is None:
        return NO
    if rule.rules_out & _codes(product.allergens_contains + product.allergens_may_contain):
        return NO
    if rule.proves & _codes(product.allergens_free_from):
        return YES
    return UNKNOWN
