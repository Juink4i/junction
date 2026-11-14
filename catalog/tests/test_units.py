import json
import sqlite3

import pytest

from catalog import api, units
from catalog.models import UnitPlan
from catalog.tests.fake_valio import FIXTURES


@pytest.mark.parametrize("pid, expected", [("464201", 1000), ("465039", 200), ("463038", 50), ("464179", 100)])
def test_units_for_1000_litres(priced, pid, expected):
    plan = api.units_needed(pid, 1000, "L")
    assert isinstance(plan, UnitPlan)
    assert plan.units == expected
    assert plan.covers >= 1000
    assert plan.content_unit == "L"


def test_product_data_is_enough_when_it_has_a_volume(catalog):
    # 464201 (1 l) and 464179 (10 l) have a litre volume in the file: no API call needed.
    assert api.units_needed("464201", 1000, "L").content_per_unit == 1.0
    assert api.units_needed("464179", 1000, "L").content_per_unit == 10.0


def test_case_of_two_10_litre_boxes(priced):
    plan = api.units_needed("463038", 1000, "L")
    assert plan.sales_unit == "KI"
    assert plan.content_per_unit == 20.0


def test_rounds_up(priced):
    plan = api.units_needed("465039", 1001, "L")  # 5 l per case
    assert plan.units == 201 and plan.covers == 1005.0


def test_sold_by_the_kilo(catalog):
    plan = api.units_needed("460025", 12.5, "KG")  # courgettes, sales unit KG
    assert plan.units == 13 and plan.content_per_unit == 1.0


def test_litres_of_a_product_priced_per_kilo_is_refused(priced):
    # 472492 sour milk is sold and priced per kg; we don't convert by density.
    with pytest.raises(units.UnitMismatch):
        api.units_needed("472492", 1000, "L")


def test_unknown_product(catalog):
    with pytest.raises(KeyError):
        api.units_needed("000000", 10, "L")


def test_amount_must_be_positive(catalog):
    with pytest.raises(ValueError):
        api.units_needed("464201", 0, "L")


@pytest.mark.parametrize("unit_price, comparison_price, content", [
    (31.31, 1.57, 20.0),   # 463038: ratio 19.94, 2 x 10 l
    (6.86, 1.37, 5.0),     # 465039: ratio 5.007, 5 x 1 l
    (27.39, 1.30, 21.0),   # 469287: 12 x 1.75 l
    (10.71, 2.86, 3.75),   # 463779: 15 x 2.5 dl
    (10.44, 3.73, 2.8),    # 464399: 14 x 2 dl
    (15.09, 7.55, 2.0),    # 463203: 100 x 2 cl
    (30.42, 2.54, 12.0),   # 464768: 12 x 1 l
    (0.88, 1.76, 0.5),     # 464440: 0.5 l
])
def test_size_from_cent_rounded_prices(unit_price, comparison_price, content):
    assert units.content_from_prices(unit_price, comparison_price) == content


def test_product_data_and_prices_agree_for_every_lactose_free_milk(catalog_db):
    prices = json.loads((FIXTURES / "price_lf_milk_2026-11-16.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(catalog_db)
    con.row_factory = sqlite3.Row
    checked = 0
    for p in prices["products"]:
        row = con.execute("SELECT * FROM products WHERE id = ?", (p["productId"],)).fetchone()
        static = units.content_from_product(row).get(p["comparisonUnit"])
        if static is None:
            continue
        ratio = units.content_from_prices(p["catalogPrice"]["value"], p["comparisonPrice"]["value"])
        assert static == pytest.approx(ratio, rel=0.01), p["productId"]
        checked += 1
    assert checked >= 10
