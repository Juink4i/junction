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


def test_every_nutrition_claim_in_the_product_file_has_a_name(catalog_db):
    import sqlite3

    from catalog.names import TAG_NAMES

    con = sqlite3.connect(catalog_db)
    codes = {row[0] for row in con.execute(
        "SELECT DISTINCT value FROM products, json_each(products.tags)")}
    assert codes == set(TAG_NAMES)


def test_an_unlisted_tag_is_shown_in_lower_case_not_hidden():
    assert api.tag_name("FREE_FROM_LACTOSE") == "lactose-free"
    assert api.tag_name("SOME_NEW_CLAIM") == "some new claim"
