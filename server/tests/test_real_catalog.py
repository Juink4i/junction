"""The server against Runner 1's real catalog, with recorded Valio Aimo answers. No network."""

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from catalog import api, load
from catalog.tests.fake_valio import FakeClock, FakeValio
from catalog.valio_client import ValioClient
from server.db import connect
from server.make_mandate import DEMO_MANDATES, issue_demo_mandates
from server.service import Service

RAW = load.ROOT / "data" / "raw"
MONDAY = "2026-11-16"


@pytest.fixture(scope="module")
def catalog_db(tmp_path_factory):
    if not (RAW / load.PRODUCT_FILE).exists():
        pytest.skip("Valio Aimo files are not in data/raw/")
    db = tmp_path_factory.mktemp("catalog") / "catalog.db"
    load.load(RAW, db)
    return db


@pytest.fixture
def valio(catalog_db, tmp_path):
    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"offers": {}, "products": {}}')
    fake = FakeValio()
    client = ValioClient(api_key="test-key", transport=fake.transport(), clock=FakeClock())
    api.configure(db_path=catalog_db, overrides_path=overrides, client=client)
    yield fake
    api.configure()


@pytest.fixture
def svc(valio):
    return Service(connect(":memory:"), api, lambda: datetime(2026, 11, 14, 10, tzinfo=timezone.utc))


def quote(svc, product_id, litres):
    return svc.quote_lines([{"product_id": product_id, "amount": litres, "unit": "L"}], MONDAY)


def test_search_screens_the_real_lactose_free_milks(svc, monkeypatch):
    monkeypatch.setitem(DEMO_MANDATES["hotel"]["auto_approve"], "allowed_categories", ["10400"])
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    found = svc.search_products(hotel, "lactose-free milk", amount=1000, unit="L")
    assert found["total_matches"] == 34
    assert (len(found["products"]), len(found["dropped"])) == (25, 9)
    assert {d["reason"] for d in found["dropped"]} == {
        "coffee milk or coffee drink", "sour milk", "portion pack"}
    assert set(svc.get_product("464201")) >= {"allergen_info_missing", "official_substitutes",
                                              "properties"}


def test_units_are_converted_with_real_pack_sizes(svc):
    line = quote(svc, "463038", 1000)["lines"][0]
    assert (line["units"], line["covers"], line["content_unit"]) == (50, 1000.0, "L")


def test_cheapest_on_time_milk_for_the_hotel_needs_a_human(svc):
    tokens = issue_demo_mandates(svc.conn)
    q = quote(svc, "464306", 1000)
    assert q["lines"][0]["cutoff_passed"] is False
    assert q["total_eur"] == pytest.approx(1010, abs=1)
    result = svc.place_order(q["quote_id"], tokens["hotel"], "Cheapest on-time option")
    assert result["status"] == "pending_approval"
    assert any("per line" in r for r in result["reasons"])


def test_product_past_its_cut_off_needs_a_human(svc):
    tokens = issue_demo_mandates(svc.conn)
    q = quote(svc, "463038", 1000)
    assert q["lines"][0]["cutoff_passed"] is True
    result = svc.place_order(q["quote_id"], tokens["hotel"], "Cheapest per litre")
    assert result["status"] == "pending_approval"
    assert any("cut-off" in r for r in result["reasons"])


def test_litres_for_a_product_sold_by_kilo_is_a_bad_unit(svc):
    assert quote(svc, "472492", 10)["code"] == "bad_unit"


def test_valio_api_failure_is_retryable_and_not_retried_again_by_the_server(svc, valio):
    valio.fail_next = [503] * 10
    error = quote(svc, "464201", 10)
    assert (error["code"], error["retryable"]) == ("valio_api_unavailable", True)
    assert valio.calls("price") + valio.calls("availability") <= 2


def test_missing_api_key_is_not_retryable(catalog_db, tmp_path, monkeypatch):
    monkeypatch.delenv("VALIO_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    api.configure(db_path=catalog_db, client=None)
    try:
        import catalog.valio_client as vc
        monkeypatch.setattr(vc, "_env_key", lambda: None)
        svc = Service(connect(":memory:"), api, lambda: datetime(2026, 11, 14, tzinfo=timezone.utc))
        error = quote(svc, "464201", 10)
        assert (error["code"], error["retryable"]) == ("valio_api_unavailable", False)
    finally:
        api.configure()


def test_pieces_of_real_milk_get_a_question_in_litres(svc):
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    asked = svc.request_quote(hotel, ["464306"], 200, "PCS", MONDAY)
    assert asked["status"] == "needs_clarification"
    assert "litres" in asked["question"]


def test_a_lactose_free_kitchen_finds_real_eggs(svc):
    school = svc.authenticate(issue_demo_mandates(svc.conn)["school"])
    mandate = {**school.mandate, "substitution": {**school.mandate["substitution"],
                                                  "must_keep": ["FREE_FROM_LACTOSE"]}}
    found = svc.search_products(replace(school, mandate=mandate), "egg")
    names = [p["name_en"] for p in found["products"]]
    # Munax declares itself free from milk; Kieku's data only lists egg, so a person checks it.
    assert any(n.startswith("Munax whole egg") for n in names)
    assert any(n.startswith("Kieku Barn egg") for n in names)
    assert max(i for i, n in enumerate(names) if n.startswith("Munax")) < min(
        i for i, n in enumerate(names) if n.startswith("Kieku"))
    assert not any("Dumle" in n for n in names)  # chocolate eggs contain milk
