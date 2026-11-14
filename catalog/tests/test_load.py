import json
import sqlite3


def row(db, product_id):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


def test_loads_every_product(catalog_db):
    con = sqlite3.connect(catalog_db)
    assert con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 17_546


def test_lactose_free_milk_has_tag_and_category(catalog_db):
    r = row(catalog_db, "463038")
    assert r["category"] == "10400"
    assert "FREE_FROM_LACTOSE" in json.loads(r["tags"])


def test_names_keep_finnish_and_trademark_characters(catalog_db):
    r = row(catalog_db, "463038")
    assert r["name_en"] == "Valio Eila® semi skimmed milk drink 10 l novobox lactose free"
    assert r["name_fi"] == "Valio Eila® kevytmaitojuoma 10 l novobox laktoositon"


def test_joins_carbon_and_delivery_reliability(catalog_db):
    assert row(catalog_db, "460000")["carbon_kg_per_kg"] == 2.315
    assert row(catalog_db, "460001")["delivery_reliability"] == 1.0


def test_missing_csv_values_stay_null(catalog_db):
    # 460000 is in the carbon file but not in the reliability file.
    assert row(catalog_db, "460000")["delivery_reliability"] is None
