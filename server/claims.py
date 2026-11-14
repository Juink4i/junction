"""Does a product have a must-have property? Plain code, no AI.

A supplier's own claim (a nutrition claim tag) always proves it. For the properties in RULES,
the allergen data speaks too. It can prove a free-from property: an egg whose data says
"free from milk" is lactose-free, though no egg claims it. It can rule a product out: milk is
never vegan. Data that does not mention the allergen proves nothing, so the answer is unknown,
never yes, and a person checks it.
"""

from __future__ import annotations

from typing import Any, NamedTuple

YES, NO, UNKNOWN = "yes", "no", "unknown"


class Check(NamedTuple):
    rules_out: frozenset[str]   # contains or may contain any of these allergens: no
    proves: frozenset[str] = frozenset()  # declared free from any of these allergens: yes
    claims: frozenset[str] = frozenset()  # another claim that also proves it


_GLUTEN_CEREALS = frozenset({"AW", "UW", "NR", "GB", "GS", "GK"})  # gluten cereals, wheat, rye, ...
_SEAFOOD = frozenset({"AF", "AC", "UM"})  # fish, crustaceans, molluscs

# The properties a kitchen may require of every product. Any other would rule out every
# product that does not claim it, like every egg, so it is a preference instead.
RULES = {
    "FREE_FROM_LACTOSE": Check(frozenset({"AM", "ML"}), frozenset({"AM", "ML"})),
    "FREE_FROM_GLUTEN": Check(_GLUTEN_CEREALS, frozenset({"AW"})),
    "FREE_FROM_WHEAT": Check(frozenset({"UW"}), frozenset({"UW", "AW"})),
    "FREE_FROM_EGGS": Check(frozenset({"AE"}), frozenset({"AE"})),
    "FREE_FROM_SOY": Check(frozenset({"AY"}), frozenset({"AY"})),
    "VEGAN": Check(_SEAFOOD | {"AM", "ML", "AE"}),
    "VEGETARIAN": Check(_SEAFOOD, claims=frozenset({"VEGAN"})),
}


def _codes(values: list[str]) -> set[str]:
    return {v.upper() for v in values}


def status(product: Any, tag: str) -> str:
    """YES, NO or UNKNOWN. A property not in RULES is YES only when claimed."""
    check = RULES.get(tag)
    if tag in product.tags or (check and check.claims & set(product.tags)):
        return YES
    if check is None:
        return NO
    if check.rules_out & _codes(product.allergens_contains + product.allergens_may_contain):
        return NO
    if check.proves & _codes(product.allergens_free_from):
        return YES
    return UNKNOWN
