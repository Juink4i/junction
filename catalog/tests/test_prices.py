from datetime import date

import pytest

from catalog import api
from catalog.valio_client import ValioApiError

MONDAY = date(2026, 11, 16)


def test_one_call_to_each_endpoint(priced):
    offers = api.price_and_availability(["464201", "465039", "463038"], MONDAY)
    assert set(offers) == {"464201", "465039", "463038"}
    assert priced.fake.calls("price") == 1 and priced.fake.calls("availability") == 1


def test_sends_api_key_and_own_user_agent(priced):
    api.price_and_availability(["464201"], MONDAY)
    req = priced.fake.requests[0]
    assert req.headers["X-API-Key"] == "test-key"
    # The real API answers 403 to Python's default user agent.
    assert not req.headers["User-Agent"].lower().startswith("python")


def test_cached_for_five_minutes(priced):
    api.price_and_availability(["464201"], MONDAY)
    priced.clock.advance(299)
    api.price_and_availability(["464201"], MONDAY)
    assert priced.fake.calls("price") == 1
    priced.clock.advance(2)
    api.price_and_availability(["464201"], MONDAY)
    assert priced.fake.calls("price") == 2


def test_only_uncached_ids_are_requested(priced):
    api.price_and_availability(["464201"], MONDAY)
    api.price_and_availability(["464201", "465039"], MONDAY)
    assert priced.fake.requested_ids("price") == [["464201"], ["465039"]]


def test_prices(priced):
    o = api.price_and_availability(["464201"], MONDAY)["464201"]
    assert o.unit_price_eur == 1.56
    assert o.comparison_price_eur == 1.56 and o.comparison_unit == "L"
    assert o.tax_rate == 13.5
    assert o.unit_price_with_tax_eur > o.unit_price_eur


def test_cutoff_compares_closing_time_with_api_time_now(priced):
    offers = api.price_and_availability(["464201", "465039"], MONDAY)
    # timeNow is Sat 14 Nov 09:24. 465039 closed Thu 12 Nov, 464201 closes Sun 15 Nov 17:00.
    assert offers["465039"].cutoff_passed is True
    assert offers["464201"].cutoff_passed is False


def test_cutoff_moves_on_while_answer_is_cached(priced_long_cache):
    api.price_and_availability(["464201"], MONDAY)
    priced_long_cache.clock.advance(32 * 3600)  # past Sun 17:00
    assert api.price_and_availability(["464201"], MONDAY)["464201"].cutoff_passed is True
    assert priced_long_cache.fake.calls("price") == 1


def test_placeholder_stock_is_unknown(priced):
    offers = api.price_and_availability(["464201", "463779", "465039", "463380"], MONDAY)
    assert offers["464201"].available_units is None  # 9999999999
    assert offers["463779"].available_units is None  # 666666666
    assert offers["465039"].available_units is None  # 999999
    assert offers["463380"].available_units == 698  # real stock count


def test_undeliverable_product(priced):
    o = api.price_and_availability(["464440"], MONDAY)["464440"]
    assert o.orderable is False
    assert o.available_date is None
    assert o.logistic_model is None


def test_deliverable_product(priced):
    o = api.price_and_availability(["464201"], MONDAY)["464201"]
    assert o.orderable is True
    assert o.available_date == MONDAY
    assert o.logistic_model == "Stock"


def test_product_without_price_is_left_out(priced):
    assert api.price_and_availability(["999999"], MONDAY) == {}


def test_retries_once_after_server_error(priced):
    priced.fake.fail_next = [503]
    assert "464201" in api.price_and_availability(["464201"], MONDAY)


def test_reports_error_after_second_failure(priced):
    priced.fake.fail_next = [503, 503]
    with pytest.raises(ValioApiError) as e:
        api.price_and_availability(["464201"], MONDAY)
    assert e.value.retryable is True


def test_bad_request_is_not_retried(priced):
    priced.fake.fail_next = [422]
    with pytest.raises(ValioApiError) as e:
        api.price_and_availability(["464201"], MONDAY)
    assert e.value.retryable is False
    assert len(priced.fake.requests) == 1
