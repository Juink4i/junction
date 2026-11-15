"""request_quote tells the buyer the earliest delivery date when nothing arrives by need_by."""

from dataclasses import replace
from datetime import date

import pytest

from server import fake_catalog
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.service import Service
from server.tests.test_service import Clock

MILKS = ["464201", "465039"]
NEED_BY = date(2026, 11, 16)


class ScriptedCatalog:
    """The fake catalog, where `rule(delivery_date, product_id)` returns changes to an offer."""

    def __init__(self, rule):
        self.rule = rule
        self.calls = []

    def __getattr__(self, name):
        return getattr(fake_catalog, name)

    def price_and_availability(self, product_ids, delivery_date):
        self.calls.append((list(product_ids), delivery_date))
        offers = fake_catalog.price_and_availability(product_ids, delivery_date)
        return {pid: replace(o, **self.rule(delivery_date, pid)) for pid, o in offers.items()}


def quote(rule):
    catalog = ScriptedCatalog(rule)
    svc = Service(connect(":memory:"), catalog, Clock())
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    result = svc.request_quote(hotel, MILKS, 10, "L", NEED_BY)
    return result, catalog, svc


def late_on(day_by_pid):
    return lambda d, pid: {"available_date": day_by_pid[pid], "cutoff_passed": False}


def test_on_time_option_means_no_earliest():
    result, catalog, _ = quote(lambda d, pid: {"available_date": NEED_BY, "cutoff_passed": False})
    assert result["status"] == "ok"
    assert result["earliest"] is None
    assert len(catalog.calls) == 1


def test_only_late_options_give_the_smallest_available_date():
    result, catalog, svc = quote(late_on({"464201": date(2026, 11, 19), "465039": date(2026, 11, 18)}))
    assert result["earliest"] == {"date": "2026-11-18", "product_ids": ["465039"]}
    assert len(catalog.calls) == 1
    line = svc.conn.execute("SELECT reason FROM log WHERE reason LIKE 'Nothing arrives%'"
                            ).fetchone()
    assert line["reason"] == ("Nothing arrives by 2026-11-16. The earliest delivery is 2026-11-18 "
                              "(1 product).")


def test_products_sharing_the_earliest_date_are_all_listed_sorted():
    result, _, _ = quote(late_on({"464201": date(2026, 11, 18), "465039": date(2026, 11, 18)}))
    assert result["earliest"] == {"date": "2026-11-18", "product_ids": ["464201", "465039"]}


def test_nothing_orderable_probes_later_dates_and_stops_at_the_first_hit():
    def rule(d, pid):
        if d == NEED_BY or d.day == 17:
            return {"orderable": False}
        return {"available_date": d, "cutoff_passed": False}

    result, catalog, _ = quote(rule)
    assert result["options"] == []
    assert result["earliest"] == {"date": "2026-11-18", "product_ids": ["464201", "465039"]}
    assert [d for _, d in catalog.calls] == [NEED_BY, date(2026, 11, 17), date(2026, 11, 18)]


def test_nothing_orderable_on_any_probe_gives_no_earliest_after_three_probes():
    result, catalog, _ = quote(lambda d, pid: {"orderable": False})
    assert result["earliest"] is None
    assert len(catalog.calls) == 4


def test_a_failing_probe_is_skipped():
    def rule(d, pid):
        if d == date(2026, 11, 17):
            raise RuntimeError("503 from upstream")
        if d == NEED_BY:
            return {"orderable": False}
        return {"available_date": d, "cutoff_passed": False}

    result, catalog, _ = quote(rule)
    assert result["status"] == "ok"
    assert result["earliest"]["date"] == "2026-11-18"


def test_cutoff_passed_candidates_never_give_an_earliest_date():
    result, _, _ = quote(lambda d, pid: {"available_date": NEED_BY, "cutoff_passed": True})
    assert result["earliest"] is None


def test_a_cutoff_passed_candidate_does_not_hide_or_beat_a_genuinely_later_one():
    def rule(d, pid):
        if pid == "464201":
            return {"available_date": NEED_BY, "cutoff_passed": True}
        return {"available_date": date(2026, 11, 18), "cutoff_passed": False}

    result, _, _ = quote(rule)
    assert result["earliest"] == {"date": "2026-11-18", "product_ids": ["465039"]}
