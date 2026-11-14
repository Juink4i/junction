from catalog import api
from catalog.models import Product


def test_tomberry_has_no_allergen_info(catalog):
    p = api.get_product("460004")
    assert isinstance(p, Product)
    assert p.allergen_info_missing is True


def test_potato_salad_contains_egg_and_mustard(catalog):
    p = api.get_product("460000")
    assert set(p.allergens_contains) >= {"AE", "BM"}
    assert p.allergen_info_missing is False
    assert "AM" in p.allergens_free_from


def test_product_details(catalog):
    p = api.get_product("464201")
    assert p.name_en == "Valio semi skimmed milk 1 l lactose free UHT"
    assert p.sales_unit == "ST"
    assert p.vendor == "VALIO OY TUORE"
    assert p.country == "fi"
    assert p.official_substitutes == ["464440"]
    assert "Lactose free" in p.description


def test_unknown_product_is_none(catalog):
    assert api.get_product("000000") is None


def test_allergen_status_four_states(catalog):
    assert api.allergen_status("460000", "AE") == "contains"
    assert api.allergen_status("460000", "AM") == "free_from"
    # 463038 says it contains milk and nothing else, so gluten is unknown, not safe.
    assert api.allergen_status("463038", "AM") == "contains"
    assert api.allergen_status("463038", "AW") == "unknown"
    assert api.allergen_status("460004", "AM") == "unknown"
