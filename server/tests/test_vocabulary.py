"""Plain words to catalog tags. The buyer's agent never needs a tag code."""

import pytest

from catalog.names import TAG_NAMES
from server.vocabulary import known_names, names, understand


@pytest.mark.parametrize("product, must_have, text, tags", [
    ("lactose-free milk", None, "milk", ["FREE_FROM_LACTOSE"]),
    ("Lactose free MILK", [], "milk", ["FREE_FROM_LACTOSE"]),
    ("milk", ["lactose-free"], "milk", ["FREE_FROM_LACTOSE"]),
    ("milk", ["FREE_FROM_LACTOSE"], "milk", ["FREE_FROM_LACTOSE"]),
    ("laktoositon maito", None, "maito", ["FREE_FROM_LACTOSE"]),
    ("low-lactose milk", None, "milk", ["LOW_LACTOSE"]),
    ("cola no artificial sweeteners", None, "cola", ["FREE_FROM_ARTIFICIAL_SWEETENERS"]),
    ("milk", ["no lactose", "lactose-free"], "milk", ["FREE_FROM_LACTOSE"]),
    ("sugar-free cola", None, "sugar free cola", []),
    ("semi-skimmed milk", None, "semi skimmed milk", []),
])
def test_words_become_search_text_and_tags(product, must_have, text, tags):
    understood = understand(product, must_have)
    assert (understood.text, understood.tags, understood.unknown) == (text, tags, [])


def test_an_unknown_must_have_is_reported_not_guessed():
    understood = understand("milk", ["organic", "lactose-free"])
    assert understood.unknown == ["organic"]
    assert understood.tags == ["FREE_FROM_LACTOSE"]


def test_there_are_21_properties_with_distinct_names():
    assert len(known_names()) == len(set(known_names())) == 21
    assert names(["FREE_FROM_LACTOSE", "VEGAN"]) == ["lactose-free", "vegan"]


def test_every_name_and_code_maps_back_to_its_own_tag():
    for code, name in TAG_NAMES.items():
        assert understand("x", [name]).tags == [code], name
        assert understand("x", [code]).tags == [code], code
