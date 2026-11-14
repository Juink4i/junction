"""Does a product have a must-have property? Its own claim, or for a free-from property its
allergen data, can prove it. Plain code, three answers: yes, no, unknown."""

import pytest

from server.claims import NO, UNKNOWN, YES, status
from server.fake_catalog import Product


def product(tags=(), contains=(), may=(), free=(), missing=False) -> Product:
    return Product(id="1", name_en="x", name_fi="x", category="10590", sales_unit="ST",
                   tags=list(tags), allergens_contains=list(contains), allergens_may_contain=list(may),
                   allergens_free_from=list(free), allergen_info_missing=missing)


@pytest.mark.parametrize("p,expected", [
    (product(tags=["FREE_FROM_LACTOSE"], contains=["AM"]), YES),  # lactose-free milk: its claim
    (product(contains=["AE"], free=["AM", "AW"]), YES),           # liquid egg: free from milk
    (product(contains=["AE"], free=["ML"]), YES),                 # free from lactose itself
    (product(contains=["AM"]), NO),                               # ordinary milk
    (product(may=["ML"]), NO),
    (product(contains=["AE"]), UNKNOWN),                          # shell eggs: milk not mentioned
    (product(missing=True), UNKNOWN),                             # no allergen data at all
])
def test_lactose_free(p, expected):
    assert status(p, "FREE_FROM_LACTOSE") == expected


@pytest.mark.parametrize("p,expected", [
    (product(free=["AW"]), YES),
    (product(contains=["UW"]), NO),  # wheat has gluten, even when AW itself is not listed
    (product(contains=["NR"]), NO),  # rye
    (product(free=["AE"]), UNKNOWN),
])
def test_gluten_free(p, expected):
    assert status(p, "FREE_FROM_GLUTEN") == expected


def test_eggs_and_soy_follow_their_allergen():
    assert status(product(free=["AE", "AY"]), "FREE_FROM_EGGS") == YES
    assert status(product(contains=["AY"]), "FREE_FROM_SOY") == NO


@pytest.mark.parametrize("tag", ["HIGH_PROTEIN", "FREE_FROM_COLOURING_AGENTS", "LOW_SODIUM_SALT"])
def test_a_property_allergen_data_cannot_prove_needs_the_claim(tag):
    full_data = product(contains=["AE"], free=["AM", "AW", "AY"])
    assert status(full_data, tag) == NO
    assert status(product(tags=[tag]), tag) == YES


# Vegan and vegetarian: allergen data can rule a product out, but never prove it. An unclaimed
# product is unknown, so a person checks it, instead of every vegetable being hidden.

@pytest.mark.parametrize("p,expected", [
    (product(tags=["VEGAN"]), YES),
    (product(contains=["AM"]), NO),     # milk
    (product(contains=["AE"]), NO),     # eggs
    (product(may=["AF"]), NO),          # fish
    (product(free=["AM", "AE"]), UNKNOWN),  # could still be meat
    (product(missing=True), UNKNOWN),
])
def test_vegan(p, expected):
    assert status(p, "VEGAN") == expected


@pytest.mark.parametrize("p,expected", [
    (product(tags=["VEGETARIAN"]), YES),
    (product(tags=["VEGAN"]), YES),     # vegan is vegetarian too
    (product(contains=["AE", "AM"]), UNKNOWN),  # eggs and milk are fine; meat is not in the data
    (product(contains=["AC"]), NO),     # crustaceans
    (product(contains=["UM"]), NO),     # molluscs
])
def test_vegetarian(p, expected):
    assert status(p, "VEGETARIAN") == expected


def test_the_rules_a_kitchen_can_set_for_every_product():
    from server.claims import RULES
    assert set(RULES) == {"FREE_FROM_LACTOSE", "FREE_FROM_GLUTEN", "FREE_FROM_WHEAT",
                          "FREE_FROM_EGGS", "FREE_FROM_SOY", "VEGAN", "VEGETARIAN"}
