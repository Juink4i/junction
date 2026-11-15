"""request_quote: ranked options, each its own signed quote, with what the mandate would decide."""

import pytest

from server import signing
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.service import Service
from server.tests.test_service import Catalog, Clock, count

MILKS = ["464201", "465039", "463038", "464179"]
ROLLS = "460500"  # 30 bread rolls per bag
MONDAY = "2026-11-16"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def catalog():
    return Catalog()


@pytest.fixture
def svc(clock, catalog):
    return Service(connect(":memory:"), catalog, clock)


@pytest.fixture
def tokens(svc):
    return issue_demo_mandates(svc.conn)


@pytest.fixture
def hotel(svc, tokens):
    return svc.authenticate(tokens["hotel"])


@pytest.fixture
def school(svc, tokens):
    return svc.authenticate(tokens["school"])


def quoted(svc, buyer, ids=MILKS, amount=1000, unit="L", need_by=MONDAY, **kw):
    return svc.request_quote(buyer, ids, amount, unit, need_by, **kw)


def first_products(result):
    return [o["quote"]["lines"][0]["product_id"] for o in result["options"]]


def test_options_come_back_ranked_with_one_signed_quote_each(svc, hotel, clock):
    result = quoted(svc, hotel)
    assert result["status"] == "ok"
    assert result["asked"] == {"amount": 1000, "unit": "L", "need_by": MONDAY}
    assert result["set_id"].startswith("qs_")
    assert [(o["rank"], o["label"]) for o in result["options"]] == [
        (1, "best"), (2, "better"), (3, "good"), (4, "other")]
    assert first_products(result) == ["464201", "464179", "465039", "463038"]
    assert [o["quote"]["total_eur"] for o in result["options"]] == [1560.0, 1620.0, 1620.0, 1370.0]
    assert result["options"][0]["trade_off"].startswith("1,000 × 1 L of Lactose-free skimmed milk")
    public_key = signing.server_key(svc.conn).public_key()
    for option in result["options"]:
        assert signing.check_quote(option["quote"], public_key, clock()).isoformat() == MONDAY
    assert len({o["quote"]["quote_id"] for o in result["options"]}) == 4
    assert result["not_offered"] == []


def test_each_line_carries_its_cut_off_time(svc, hotel):
    line = quoted(svc, hotel)["options"][0]["quote"]["lines"][0]
    assert line["closing_time"] and "T" in line["closing_time"]
    assert line["cutoff_passed"] is False


def test_each_option_says_what_the_mandate_would_decide(svc, hotel):
    big = quoted(svc, hotel)["options"][0]
    assert big["expected"]["status"] == "pending_approval"
    assert any("€1,560.00" in r for r in big["expected"]["reasons"])
    late = quoted(svc, hotel)["options"][-1]
    assert any("cut-off" in r for r in late["expected"]["reasons"])
    small = quoted(svc, hotel, amount=100)["options"][0]
    assert small["expected"]["status"] == "confirmed"
    assert count(svc, "orders") == 0 and count(svc, "approvals") == 0  # a forecast saves nothing


def test_the_forecast_is_what_place_order_then_decides(svc, hotel, tokens):
    for amount in (100, 1000):
        best = quoted(svc, hotel, amount=amount)["options"][0]
        placed = svc.place_order(best["quote"]["quote_id"], tokens["hotel"], "Best option")
        assert placed["status"] == best["expected"]["status"]
        assert placed["reasons"] == best["expected"]["reasons"]


def test_a_quote_request_is_one_price_call_however_many_products(svc, hotel, catalog):
    quoted(svc, hotel)
    assert catalog.price_calls == 1


def test_products_the_mandate_rejects_are_never_offered(svc, school):
    result = quoted(svc, school, ids=["460000", "460004"], amount=10, unit="KG")
    assert first_products(result) == ["460004"]  # no allergen information: a person decides
    assert result["options"][0]["expected"]["status"] == "pending_approval"
    (left_out,) = result["not_offered"]
    assert left_out["product_id"] == "460000" and "eggs" in left_out["reason"]


def test_what_cannot_be_priced_or_measured_is_left_out_with_a_reason(svc, school, catalog):
    catalog.offer_changes["464179"] = {"orderable": False}
    result = quoted(svc, school, ids=["464201", "464179", "460004", "nope"], amount=100)
    assert first_products(result) == ["464201"]
    reasons = {n["product_id"]: n["reason"] for n in result["not_offered"]}
    assert set(reasons) == {"464179", "460004", "nope"}
    assert "kilograms" in reasons["460004"] and "catalog" in reasons["nope"]
    assert "ordered" in reasons["464179"]


def test_a_product_short_on_stock_is_left_out_with_what_is_in_stock(svc, hotel, catalog):
    catalog.offer_changes["464179"] = {"available_units": 30}
    result = quoted(svc, hotel)
    assert "464179" not in first_products(result)
    assert any(n["product_id"] == "464179" and "300 L" in n["reason"] for n in result["not_offered"])


def test_the_buyers_preferences_change_the_order(svc, hotel):
    assert first_products(quoted(svc, hotel))[1:3] == ["464179", "465039"]
    small_packs = quoted(svc, hotel, preferences={"pack_size": "small"})
    assert first_products(small_packs)[1:3] == ["465039", "464179"]


@pytest.mark.parametrize("ids, amount, unit, need_by, missing", [
    (None, 1000, "L", MONDAY, ["product_ids"]),
    ([], 1000, "L", MONDAY, ["product_ids"]),
    (MILKS, None, None, None, ["amount", "unit", "need_by"]),
])
def test_missing_parameters_get_a_question(svc, hotel, ids, amount, unit, need_by, missing):
    asked = svc.request_quote(hotel, ids, amount, unit, need_by)
    assert (asked["status"], asked["missing"]) == ("needs_clarification", missing)
    assert asked["question"]
    assert count(svc, "quotes") == 0


@pytest.mark.parametrize("amount, unit, need_by, code", [
    (1000, "L", "next Monday", "bad_date"),
    (1000, "L", "2026-11-13", "need_by_in_past"),
    (-5, "L", MONDAY, "bad_amount"),
    (float("inf"), "L", MONDAY, "bad_amount"),
])
def test_bad_parameters_are_structured_errors(svc, hotel, amount, unit, need_by, code):
    error = svc.request_quote(hotel, MILKS, amount, unit, need_by)
    assert set(error) == {"code", "message", "retryable"}
    assert error["code"] == code


def test_a_unit_the_server_cannot_count_in_gets_a_question(svc, hotel):
    asked = quoted(svc, hotel, amount=3, unit="crates")
    assert (asked["status"], asked["missing"]) == ("needs_clarification", ["unit"])
    assert "crates" in asked["question"]
    assert count(svc, "quotes") == 0


@pytest.mark.parametrize("unit", ["l", "litres", "Liters"])
def test_unit_words_are_understood(svc, hotel, unit):
    assert quoted(svc, hotel, unit=unit)["asked"]["unit"] == "L"


def test_pieces_are_counted(svc, school):
    result = quoted(svc, school, ids=[ROLLS], amount=200, unit="PCS")
    line = result["options"][0]["quote"]["lines"][0]
    assert (line["units"], line["covers"], line["content_unit"]) == (7, 210, "PCS")


def test_products_that_cannot_be_counted_get_a_question_not_a_guess(svc, hotel):
    asked = quoted(svc, hotel, amount=200, unit="PCS")
    assert (asked["status"], asked["missing"]) == ("needs_clarification", ["unit"])
    assert "litres" in asked["question"]
    assert count(svc, "quotes") == 0


def test_the_same_number_in_another_unit_is_questioned_once(svc, hotel):
    quoted(svc, hotel, amount=200, unit="PCS")
    swapped = quoted(svc, hotel, amount=200, unit="L")
    assert swapped["status"] == "needs_clarification"
    assert "200 PCS" in swapped["question"]
    assert count(svc, "quotes") == 0
    # Asked again after the question, the buyer has confirmed it.
    assert quoted(svc, hotel, amount=200, unit="L")["status"] == "ok"


def test_a_new_amount_in_the_suggested_unit_goes_through(svc, hotel):
    quoted(svc, hotel, amount=200, unit="PCS")
    assert quoted(svc, hotel, amount=150, unit="L")["status"] == "ok"


def test_api_failure_is_a_retryable_error(svc, hotel, catalog):
    catalog.fail_times = 2
    error = quoted(svc, hotel)
    assert (error["code"], error["retryable"]) == ("valio_api_unavailable", True)


def test_nothing_to_offer_is_an_empty_list_not_an_error(svc, school):
    result = quoted(svc, school, ids=["460000"], amount=10, unit="KG")
    assert (result["status"], result["options"]) == ("ok", [])
    assert len(result["not_offered"]) == 1


def test_a_quote_issued_to_one_buyer_is_refused_for_another(svc, hotel, tokens):
    quote_id = quoted(svc, hotel, amount=100)["options"][0]["quote"]["quote_id"]
    stolen = svc.place_order(quote_id, tokens["cafe"], "Mine now")
    assert stolen["status"] == "rejected" and "another buyer" in stolen["reasons"][0]
    assert count(svc, "orders") == 0
    assert svc.place_order(quote_id, tokens["hotel"], "Ours")["status"] == "confirmed"


def test_each_option_is_logged_against_its_own_quote(svc, hotel):
    for option in quoted(svc, hotel)["options"]:
        (entry,) = svc.get_audit_log(quote_id=option["quote"]["quote_id"])
        assert (entry["actor"], entry["action"]) == ("buyer-agent-01", "request_quote")
        assert f"Option {option['rank']} of 4" in entry["reason"]


def test_an_existing_database_gets_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE quotes (quote_id TEXT PRIMARY KEY, body_json TEXT NOT NULL, "
                "signature TEXT NOT NULL, created_at TEXT NOT NULL)")
    old.commit()
    old.close()
    columns = {row["name"] for row in connect(path).execute("PRAGMA table_info(quotes)")}
    assert {"buyer_id", "set_id", "rank", "label"} <= columns


def test_a_short_first_choice_is_offered_as_a_split(svc, hotel, catalog, tokens):
    catalog.offer_changes["464201"] = {"available_units": 700}
    result = quoted(svc, hotel)
    split = result["options"][0]
    assert split["label"] == "split"
    assert [(l["product_id"], l["units"], l["covers"], l["stock"]) for l in split["quote"]["lines"]] == [
        ("464201", 700, 700.0, "confirmed"), ("464179", 30, 300.0, "unconfirmed")]
    assert split["quote"]["total_eur"] == 1578.0
    assert [o["label"] for o in result["options"][1:]] == ["better", "good", "other"]
    assert result["not_offered"] == []  # 464201 is part of the split, so it was not left out
    placed = svc.place_order(split["quote"]["quote_id"], tokens["hotel"], "Split")
    assert placed["status"] == "pending_approval"  # 1,578 is over the hotel's 1,500 limit


def test_a_substitute_option_goes_to_a_person_when_the_mandate_allows_none(svc, school, tokens):
    result = quoted(svc, school, amount=100)
    first, second = result["options"][0], result["options"][1]
    assert second["quote"]["lines"][0]["product_id"] != first["quote"]["lines"][0]["product_id"]
    assert not any("replaces the first choice" in r for r in first["expected"]["reasons"])
    assert second["expected"]["status"] == "pending_approval"
    assert any("replaces the first choice" in r for r in second["expected"]["reasons"])
    placed = svc.place_order(second["quote"]["quote_id"], tokens["school"], "Cheaper option")
    assert placed["status"] == "pending_approval"
    assert any("allows no substitutes" in r for r in placed["reasons"])
