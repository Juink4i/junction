import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from server import audit, fake_catalog, signing
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.service import Service


class Clock:
    def __init__(self):
        self.time = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.time

    def forward(self, **delta):
        self.time += timedelta(**delta)


class Catalog:
    """The fake catalog, with per-test changes to offers."""

    def __init__(self):
        self.offer_changes = {}
        self.fail_times = 0
        self.price_calls = 0

    def __getattr__(self, name):
        return getattr(fake_catalog, name)

    def price_and_availability(self, product_ids, delivery_date):
        self.price_calls += 1
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("503 from upstream, key=SECRET")
        offers = fake_catalog.price_and_availability(product_ids, delivery_date)
        return {pid: replace(o, **self.offer_changes.get(pid, {})) for pid, o in offers.items()}


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


def milk(svc, litres, product_id="464201", need_by="2026-11-16"):
    return svc.request_quote([{"product_id": product_id, "amount": litres, "unit": "L"}], need_by)


def count(svc, table):
    return svc.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# Quotes

def test_quote_converts_litres_to_sales_units_and_totals(svc):
    quote = milk(svc, 1000, "463038")
    line = quote["lines"][0]
    assert (line["units"], line["sales_unit"], line["covers"]) == (50, "2 x 10 L", 1000.0)
    assert line["line_total_eur"] == 1370.0
    assert quote["total_eur"] == 1370.0
    assert quote["total_with_tax_eur"] == 1555.0
    assert line["cutoff_passed"] is True


def test_quote_is_signed_and_expires_after_15_minutes(svc, clock):
    quote = milk(svc, 1000)
    assert quote["expires_at"] == (clock() + timedelta(minutes=15)).isoformat()
    public_key = signing.server_key(svc.conn).public_key()
    assert signing.check_quote(quote, public_key, clock()).isoformat() == "2026-11-16"


def test_quote_never_shows_stock_numbers(svc, catalog):
    catalog.offer_changes["464201"] = {"available_units": 5000}
    quote = milk(svc, 1000)
    assert quote["lines"][0]["stock"] == "confirmed"
    assert "5000" not in json.dumps(quote["lines"])
    catalog.offer_changes["464201"] = {"available_units": None}
    assert milk(svc, 1000)["lines"][0]["stock"] == "unconfirmed"


def test_quote_for_more_than_the_stock_is_an_error_with_what_is_available(svc, catalog):
    catalog.offer_changes["464201"] = {"available_units": 700}
    error = milk(svc, 1000)
    assert error["code"] == "insufficient_stock"
    assert "700" in error["message"]
    assert "464179" in error["message"]  # a substitute that can arrive on time


@pytest.mark.parametrize("lines, need_by, code", [
    ([{"product_id": "nope", "amount": 1, "unit": "L"}], "2026-11-16", "product_not_found"),
    ([{"product_id": "464201", "amount": 1, "unit": "KG"}], "2026-11-16", "bad_unit"),
    ([{"product_id": "464201", "amount": 0, "unit": "L"}], "2026-11-16", "bad_amount"),
    ([{"product_id": "464201", "amount": 1, "unit": "L"}], "2026-11-13", "need_by_in_past"),
    ([], "2026-11-16", "no_lines"),
])
def test_bad_quote_requests_are_structured_errors(svc, lines, need_by, code):
    error = svc.request_quote(lines, need_by)
    assert set(error) == {"code", "message", "retryable"}
    assert error["code"] == code


def test_api_failure_is_retried_once(svc, catalog):
    catalog.fail_times = 1
    assert "quote_id" in milk(svc, 10)
    assert catalog.price_calls == 2


def test_repeated_api_failure_is_a_retryable_error_without_details(svc, catalog):
    catalog.fail_times = 2
    error = milk(svc, 10)
    assert (error["code"], error["retryable"]) == ("valio_api_unavailable", True)
    assert "SECRET" not in error["message"]


def test_product_that_cannot_be_ordered_is_an_error(svc, catalog):
    catalog.offer_changes["464201"] = {"orderable": False}
    assert milk(svc, 10)["code"] == "not_orderable"


# Orders

def test_small_order_within_limits_is_confirmed(svc, tokens):
    result = svc.place_order(milk(svc, 100)["quote_id"], tokens["hotel"], "Weekly milk")
    assert result["status"] == "confirmed"
    assert result["order_id"]
    assert "approval_id" not in result and "question" not in result


def test_demo_hotel_order_goes_to_a_human(svc, tokens):
    result = svc.place_order(milk(svc, 1000)["quote_id"], tokens["hotel"], "Best on-time option")
    assert result["status"] == "pending_approval"
    assert result["order_id"] and result["approval_id"]
    assert any("€1,560.00" in r for r in result["reasons"])


def test_expired_quote_is_refused(svc, tokens, clock):
    quote_id = milk(svc, 100)["quote_id"]
    clock.forward(minutes=16)
    result = svc.place_order(quote_id, tokens["hotel"], "Late")
    assert result["status"] == "rejected"
    assert "expired" in result["reasons"][0]
    assert count(svc, "orders") == 0


def test_quote_changed_in_the_database_is_refused(svc, tokens):
    quote_id = milk(svc, 1000)["quote_id"]
    body = json.loads(svc.conn.execute("SELECT body_json FROM quotes").fetchone()[0])
    body["total_eur"] = 15.6
    body["lines"][0]["unit_price_eur"] = 0.0156
    svc.conn.execute("UPDATE quotes SET body_json = ?", (json.dumps(body),))
    result = svc.place_order(quote_id, tokens["hotel"], "Cheap!")
    assert result["status"] == "rejected"
    assert "changed" in result["reasons"][0]


def test_unknown_quote_is_refused(svc, tokens):
    result = svc.place_order("q_missing", tokens["hotel"], "?")
    assert result["status"] == "rejected"


def test_bad_mandate_signature_is_rejected(svc, tokens):
    quote_id = milk(svc, 100)["quote_id"]
    result = svc.place_order(quote_id, tokens["hotel"][:-4] + "AAAA", "Weekly milk")
    assert result["status"] == "rejected"
    assert "signature" in result["reasons"][0]
    assert count(svc, "orders") == 0


def test_bad_mandate_does_not_burn_the_quote(svc, tokens):
    quote_id = milk(svc, 100)["quote_id"]
    svc.place_order(quote_id, "not-a-token", "Weekly milk")
    assert svc.place_order(quote_id, tokens["hotel"], "Weekly milk")["status"] == "confirmed"


def test_expired_mandate_is_rejected(svc, tokens, clock):
    clock.time = datetime(2027, 1, 2, 10, 0, tzinfo=timezone.utc)
    quote_id = milk(svc, 100, need_by="2027-01-05")["quote_id"]
    result = svc.place_order(quote_id, tokens["hotel"], "Weekly milk")
    assert result["status"] == "rejected"
    assert "expired" in result["reasons"][0]


def test_policy_rejection_creates_no_approval(svc, tokens):
    quote = svc.request_quote([{"product_id": "460000", "amount": 10, "unit": "KG"}], "2026-11-16")
    result = svc.place_order(quote["quote_id"], tokens["school"], "Pancake day")
    assert result["status"] == "rejected"
    assert "approval_id" not in result
    assert count(svc, "approvals") == 0


def test_same_quote_twice_returns_the_same_order(svc, tokens):
    quote_id = milk(svc, 1000)["quote_id"]
    first = svc.place_order(quote_id, tokens["hotel"], "Best on-time option")
    second = svc.place_order(quote_id, tokens["hotel"], "Retry after timeout")
    assert second == first
    assert count(svc, "orders") == 1
    assert count(svc, "approvals") == 1


def test_same_quote_still_returns_its_order_after_the_quote_expires(svc, tokens, clock):
    quote_id = milk(svc, 100)["quote_id"]
    first = svc.place_order(quote_id, tokens["hotel"], "Weekly milk")
    clock.forward(minutes=20)
    assert svc.place_order(quote_id, tokens["hotel"], "Retry") == first


def test_another_buyer_cannot_take_over_or_read_an_order(svc, tokens):
    quote_id = milk(svc, 1000)["quote_id"]
    svc.place_order(quote_id, tokens["hotel"], "Best on-time option")
    result = svc.place_order(quote_id, tokens["cafe"], "Mine now")
    assert result["status"] == "rejected"
    assert "order_id" not in result
    assert count(svc, "orders") == 1


def test_unusual_amount_asks_the_agent_then_goes_to_a_human(svc, tokens):
    quote_id = milk(svc, 200)["quote_id"]
    asked = svc.place_order(quote_id, tokens["cafe"], "Big event")
    assert asked["status"] == "needs_clarification"
    assert asked["question"]
    assert count(svc, "approvals") == 0

    assert svc.place_order(quote_id, tokens["cafe"], "Big event") == asked

    confirmed = svc.place_order(quote_id, tokens["cafe"], "Yes, 200 L", confirm_unusual=True)
    assert confirmed["status"] == "pending_approval"
    assert confirmed["order_id"] == asked["order_id"]
    assert confirmed["approval_id"]
    assert count(svc, "orders") == 1


# Approvals

@pytest.fixture
def pending(svc, tokens):
    quote_id = milk(svc, 1000)["quote_id"]
    return quote_id, svc.place_order(quote_id, tokens["hotel"], "Best on-time option")


def test_pending_approval_is_listed_with_its_reasons(svc, pending):
    _, order = pending
    (approval,) = svc.list_approvals()
    assert approval["approval_id"] == order["approval_id"]
    assert approval["buyer"] == "Hotel Chain Oy / Helsinki Central"
    assert approval["reasons"] == order["reasons"]
    assert approval["total_eur"] == 1560.0
    assert svc.get_approval_status(order["approval_id"]) == {"status": "pending"}


def test_approve_confirms_the_order(svc, pending, tokens, clock):
    quote_id, order = pending
    decided = svc.decide_approval(order["approval_id"], approve=True)
    assert decided["status"] == "approved"
    status = svc.get_approval_status(order["approval_id"])
    assert status == {"status": "approved", "decided_by": "procurement.manager@hotel.example",
                      "decided_at": clock().isoformat()}
    assert svc.list_approvals() == []
    again = svc.place_order(quote_id, tokens["hotel"], "Checking")
    assert (again["status"], again["order_id"]) == ("confirmed", order["order_id"])


def test_reject_rejects_the_order(svc, pending, tokens):
    quote_id, order = pending
    svc.decide_approval(order["approval_id"], approve=False, decided_by="cfo@hotel.example")
    status = svc.get_approval_status(order["approval_id"])
    assert (status["status"], status["decided_by"]) == ("rejected", "cfo@hotel.example")
    assert svc.place_order(quote_id, tokens["hotel"], "Checking")["status"] == "rejected"


def test_an_approval_can_only_be_decided_once(svc, pending):
    _, order = pending
    svc.decide_approval(order["approval_id"], approve=True)
    assert svc.decide_approval(order["approval_id"], approve=False)["code"] == "already_decided"
    assert svc.get_approval_status(order["approval_id"])["status"] == "approved"


def test_unknown_approval_is_an_error(svc):
    assert svc.get_approval_status("apr_missing")["code"] == "approval_not_found"
    assert svc.decide_approval("apr_missing", approve=True)["code"] == "approval_not_found"


# Log

def test_every_tool_call_and_decision_is_logged(svc, pending):
    quote_id, order = pending
    svc.search_products("milk", "10400", ["FREE_FROM_LACTOSE"])
    svc.get_product("464201")
    svc.get_approval_status(order["approval_id"])
    svc.get_audit_log(order_id=order["order_id"])
    actions = [e["action"] for e in audit.entries(svc.conn)]
    assert actions == ["request_quote", "place_order", "decision:pending_approval",
                       "search_products", "get_product", "get_approval_status", "get_audit_log"]
    assert audit.verify(svc.conn) == {"ok": True}


def test_log_names_who_acted_and_why(svc, pending):
    _, order = pending
    by_action = {e["action"]: e for e in svc.get_audit_log(order_id=order["order_id"])}
    assert by_action["place_order"]["actor"] == "buyer-agent-01"
    assert "Best on-time option" in by_action["place_order"]["reason"]
    assert by_action["decision:pending_approval"]["actor"] == "policy"
    assert "€1,560.00" in by_action["decision:pending_approval"]["reason"]


def test_order_log_includes_the_quote_and_the_approval(svc, pending):
    _, order = pending
    svc.decide_approval(order["approval_id"], approve=True)
    entries = svc.get_audit_log(order_id=order["order_id"])
    assert [e["action"] for e in entries] == [
        "request_quote", "place_order", "decision:pending_approval", "approval:approved"]
    assert entries[-1]["actor"] == "procurement.manager@hotel.example"


def test_refusals_are_logged_too(svc, tokens):
    quote_id = milk(svc, 100)["quote_id"]
    svc.place_order(quote_id, "not-a-token", "Weekly milk")
    last = svc.get_audit_log(quote_id=quote_id)[-1]
    assert last["action"] == "decision:rejected"
    assert "mandate" in last["reason"]


def test_audit_log_needs_an_order_or_a_quote(svc):
    assert svc.get_audit_log()["code"] == "missing_filter"


def test_product_details_never_include_stock_or_price_fields(svc):
    assert "available_units" not in svc.get_product("464201")
    assert svc.get_product("nope")["code"] == "product_not_found"


# Robustness

def test_parallel_tool_calls_keep_orders_and_the_log_intact(svc, tokens):
    import threading
    errors, results = [], []

    def run(work):
        try:
            for _ in range(40):
                work()
        except Exception as e:
            errors.append(e)

    def order():
        results.append(svc.place_order(milk(svc, 10)["quote_id"], tokens["hotel"], "Weekly milk"))

    threads = [threading.Thread(target=run, args=(lambda: svc.search_products("milk"),)) for _ in range(4)]
    threads += [threading.Thread(target=run, args=(order,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(results) == count(svc, "orders") == 80
    assert svc.verify_log() == {"ok": True}


def test_failed_write_does_not_leave_a_transaction_open(svc):
    from server.db import transaction
    with pytest.raises(Exception):
        with transaction(svc.conn):
            svc.conn.execute("INSERT INTO approvals (approval_id) VALUES ('apr_x')")
    assert not svc.conn.in_transaction
    assert svc.search_products("milk")


def test_decided_by_must_be_text(svc, pending):
    _, order = pending
    assert svc.decide_approval(order["approval_id"], True, decided_by={"a": 1})["code"] == "bad_request"
    assert svc.get_approval_status(order["approval_id"]) == {"status": "pending"}


def test_infinite_amount_is_a_bad_amount(svc):
    assert milk(svc, float("inf"))["code"] == "bad_amount"


def test_calls_that_fail_early_are_logged_too(svc):
    svc.get_audit_log()
    svc.decide_approval("apr_missing", approve=True)
    assert [e["action"] for e in svc.full_log()] == ["get_audit_log", "approval:not_found"]


def test_shortage_hint_copes_with_a_substitute_without_a_price_per_litre(svc, catalog):
    catalog.offer_changes["464201"] = {"available_units": 700}
    catalog.offer_changes["464179"] = {"comparison_price_eur": None, "comparison_unit": None}
    catalog.substitute_candidates = lambda pid, tags, pct, d: [
        replace(fake_catalog._offer("464179", d), comparison_price_eur=None, comparison_unit=None)]
    error = milk(svc, 1000)
    assert error["code"] == "insufficient_stock"
    assert "464179" in error["message"]
