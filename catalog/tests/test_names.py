from catalog import api


def test_demo_category_names():
    assert api.category_name("10400") == "Milk and sour milk"
    assert api.category_name("10401") == "Cream"
    assert api.category_name("10402") == "Plant-based drinks"


def test_unknown_category_is_none():
    assert api.category_name("99999") is None


def test_the_14_eu_allergens_have_names():
    eu14 = ["AW", "AC", "AE", "AF", "AP", "AY", "AM", "AN", "BC", "BM", "AS", "AU", "NL", "UM"]
    assert all(api.allergen_name(code) for code in eu14)
    assert api.allergen_name("AM") == "Milk"
    assert api.allergen_name("AE") == "Eggs"


def test_unknown_allergen_code_is_none():
    assert api.allergen_name("X99") is None
