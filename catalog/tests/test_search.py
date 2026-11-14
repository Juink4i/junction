from catalog import api
from catalog.models import ProductSummary


def test_milk_category_plus_lactose_free_tag_gives_35(catalog):
    hits = api.search_products(text="", category="10400", must_have_tags=["FREE_FROM_LACTOSE"], limit=100)
    assert len(hits) == 35
    assert all(isinstance(h, ProductSummary) for h in hits)
    assert all("FREE_FROM_LACTOSE" in h.tags and h.category == "10400" for h in hits)


def test_finnish_word_found_inside_compound(catalog):
    # "maito" (milk) only appears inside "kevytmaito" (semi-skimmed milk).
    ids = {h.id for h in api.search_products(text="maito laktoositon", limit=100)}
    assert "464201" in ids


def test_english_words_all_must_match(catalog):
    hits = api.search_products(text="lactose free milk 10 l", category="10400", limit=50)
    assert {h.id for h in hits} >= {"463038", "464179"}
    # Words match separately, so "10" may come from "10 l" or "100x2 cl"; each word must appear.
    assert all("10" in h.name_en.lower() and "lactose" in h.name_en.lower() for h in hits)


def test_text_is_case_insensitive(catalog):
    a = {h.id for h in api.search_products(text="ARLA Novobox", limit=50)}
    b = {h.id for h in api.search_products(text="arla novobox", limit=50)}
    assert a == b and "464179" in a


def test_several_tags_must_all_be_present(catalog):
    hits = api.search_products(text="", must_have_tags=["FREE_FROM_LACTOSE", "VEGAN"], limit=100)
    assert hits and all({"FREE_FROM_LACTOSE", "VEGAN"} <= set(h.tags) for h in hits)


def test_limit_is_respected(catalog):
    assert len(api.search_products(text="milk", limit=5)) == 5


def test_no_match_returns_empty_list(catalog):
    assert api.search_products(text="zzzz-no-such-product") == []
    assert api.search_products(text="", category="00000") == []
