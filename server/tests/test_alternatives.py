"""When an order needs a person, the reply lists what would go through alone.

Ordering one of those must not lead to buying twice.
"""

from dataclasses import replace

import pytest

from server import fake_catalog
from server.db import connect
from server.service import Service
from server.tests.test_register import Clock, signed
from server.tests.test_service import Catalog, count

MILKS = ["464201", "465039", "463038", "464179"]


class PatchedCatalog(Catalog):
    """The fake catalog, with per-test changes to products as well as offers."""

    def __init__(self):
        super().__init__()
        self.product_changes = {}

    def get_product(self, product_id):
        product = fake_catalog.get_product(product_id)
        changes = self.product_changes.get(product_id)
        return replace(product, **changes) if product and changes else product


@pytest.fixture
def svc():
    catalog = PatchedCatalog()
    # The cheapest milk has lost its lactose-free claim, which this kitchen's mandate requires.
    catalog.product_changes["464201"] = {"tags": []}
    return Service(connect(":memory:"), catalog, Clock())


@pytest.fixture
def token(svc):  # Päiväkoti Aurinko: €100 per order, €150 per week, must be lactose-free
    public_pem, token = signed()
    assert svc.register_buyer(public_pem, token)[0] == 201
    return token


@pytest.fixture
def options(svc, token):
    return svc.request_quote(svc.authenticate(token), MILKS, 60, "L", "2026-11-16")["options"]


def place(svc, token, option, why="Test"):
    return svc.place_order(option["quote"]["quote_id"], token, why)


def test_the_options_in_this_scenario(options):
    assert [o["quote"]["lines"][0]["product_id"] for o in options] == ["464201", "464179", "465039", "463038"]
    assert [o["quote"]["total_eur"] for o in options] == [93.6, 97.2, 97.2, 82.2]
    assert [o["expected"]["status"] for o in options] == [
        "pending_approval", "confirmed", "confirmed", "pending_approval"]


def test_an_order_that_needs_a_person_lists_what_would_go_through_alone(svc, token, options):
    placed = place(svc, token, options[0])
    assert placed["status"] == "pending_approval"
    assert [(a["quote_id"], a["rank"], a["label"], a["total_eur"]) for a in placed["alternatives"]] == [
        (options[1]["quote"]["quote_id"], 2, "better", 97.2),
        (options[2]["quote"]["quote_id"], 3, "good", 97.2)]
    assert placed["alternatives"][0]["summary"] == "6 × 10 L Lactose-free semi-skimmed milk drink 10 L (60 L)"
    offered = next(e for e in svc.get_audit_log(order_id=placed["order_id"]) if e["action"] == "alternatives")
    assert "6 × 10 L" in offered["reason"]


def test_the_same_call_again_returns_the_same_order_with_its_alternatives(svc, token, options):
    first = place(svc, token, options[0])
    assert place(svc, token, options[0], "Retry") == first
    assert count(svc, "orders") == 1


def test_ordering_an_alternative_withdraws_the_order_that_was_waiting(svc, token, options):
    first = place(svc, token, options[0], "Cheapest")
    second = place(svc, token, options[1], "The alternative")
    # €93.60 waiting plus €97.20 would pass the €150 weekly budget, but the waiting order is gone.
    assert second["status"] == "confirmed" and "alternatives" not in second

    withdrawn = place(svc, token, options[0], "Checking")
    assert (withdrawn["status"], withdrawn["order_id"]) == ("rejected", first["order_id"])
    assert withdrawn["reasons"][-1].startswith("Withdrawn")
    assert "alternatives" not in withdrawn
    assert svc.list_approvals() == []
    status = svc.get_approval_status(first["approval_id"])
    assert (status["status"], status["decided_by"]) == ("rejected", "agent-aurinko-3f2a")
    assert any(e["action"] == "order:withdrawn" for e in svc.get_audit_log(order_id=first["order_id"]))
    assert count(svc, "orders") == 2


def test_a_request_that_is_already_confirmed_cannot_be_ordered_again(svc, token, options):
    confirmed = place(svc, token, options[1])
    again = place(svc, token, options[2])
    assert confirmed["status"] == "confirmed"
    assert again["status"] == "rejected" and confirmed["order_id"] in again["reasons"][0]
    assert count(svc, "orders") == 1


def test_an_approved_order_no_longer_lists_alternatives(svc, token, options):
    placed = place(svc, token, options[0])
    svc.decide_approval(placed["approval_id"], approve=True)
    again = place(svc, token, options[0], "Checking")
    assert again["status"] == "confirmed" and "alternatives" not in again


def test_a_quote_outside_a_request_has_no_alternatives(svc, token):
    quote = svc.quote_lines([{"product_id": "464201", "amount": 60, "unit": "L"}], "2026-11-16")
    placed = svc.place_order(quote["quote_id"], token, "One line")
    assert placed["status"] == "pending_approval" and "alternatives" not in placed


def test_an_existing_database_gets_the_alternatives_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE orders (order_id TEXT PRIMARY KEY, quote_id TEXT NOT NULL UNIQUE, "
                "buyer_id TEXT NOT NULL, mandate_id TEXT NOT NULL, status TEXT NOT NULL, "
                "approval_id TEXT, question TEXT, reasons_json TEXT NOT NULL, rationale TEXT NOT NULL, "
                "created_at TEXT NOT NULL)")
    old.commit()
    old.close()
    assert "alternatives_json" in {r["name"] for r in connect(path).execute("PRAGMA table_info(orders)")}
