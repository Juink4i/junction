import json
from datetime import date

import pytest

from catalog import api
from catalog.models import Offer

MONDAY = date(2026, 11, 16)
LF = ["FREE_FROM_LACTOSE"]


def write_overrides(path, offers=None, products=None):
    path.write_text(json.dumps({"offers": offers or {}, "products": products or {}}), encoding="utf-8")


def test_candidates_keep_tags_category_price_cap_and_date(priced):
    subs = api.substitute_candidates("464201", LF, 10, MONDAY)
    assert subs and all(isinstance(s, Offer) for s in subs)
    cap = 1.56 * 1.10
    for s in subs:
        p = api.get_product(s.product_id)
        assert p.category == "10400"
        assert "FREE_FROM_LACTOSE" in p.tags
        assert s.comparison_unit == "L" and s.comparison_price_eur <= cap + 1e-9
        assert s.orderable and not s.cutoff_passed and s.available_date <= MONDAY
        assert s.product_id != "464201"


def test_exact_candidates_from_recorded_answers(priced):
    # Valio Aimo's own stock (cut-off Sun 17:00) at or under EUR 1.716/L. Supplier products
    # missed their Thursday cut-off; 464440 can't be delivered at all.
    ids = {s.product_id for s in api.substitute_candidates("464201", LF, 10, MONDAY)}
    assert ids == {"463335", "464073", "464237", "464306", "464398", "464401", "476957", "477050"}


def test_cheapest_first(priced):
    prices = [s.comparison_price_eur for s in api.substitute_candidates("464201", LF, 10, MONDAY)]
    assert prices == sorted(prices)


def test_uses_one_price_and_one_availability_call(priced):
    api.substitute_candidates("464201", LF, 10, MONDAY)
    assert priced.fake.calls("price") == 1 and priced.fake.calls("availability") == 1


def test_official_substitute_comes_first(priced):
    # Make 464201's official substitute 464440 deliverable on Monday.
    write_overrides(priced.overrides, offers={"464440": {
        "orderable": True, "available_date": "2026-11-16", "logistic_model": "Stock"}})
    subs = api.substitute_candidates("464201", LF, 20, MONDAY)
    assert subs[0].product_id == "464440"


def test_different_comparison_unit_is_left_out(priced):
    # 472492 sour milk is lactose free and in 10400 but priced per kg, so can't be compared.
    write_overrides(priced.overrides, offers={"472492": {
        "cutoff_passed": False, "comparison_price_eur": 1.0}})
    ids = {s.product_id for s in api.substitute_candidates("464201", LF, 10, MONDAY)}
    assert "472492" not in ids


def test_must_keep_tag_filters(priced):
    ids = {s.product_id for s in api.substitute_candidates("464201", ["FREE_FROM_LACTOSE", "VEGAN"], 50, MONDAY)}
    assert ids == set()


def test_original_without_price_is_an_error(priced):
    with pytest.raises(ValueError):
        api.substitute_candidates("460025", [], 10, MONDAY)
