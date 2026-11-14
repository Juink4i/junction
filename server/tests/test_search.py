"""search_products: plain words in, the products that fit out, and what was dropped and why."""

import pytest

from server import fake_catalog
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.seller import KeywordSeller, Need, Screening, Verdict, keyword_verdict
from server.service import Service
from server.tests.test_register import Clock


class FixedSeller:
    """Stands in for the seller agent: fixed verdicts by product id."""

    def __init__(self, verdicts=None):
        self.verdicts = verdicts or {}
        self.seen = None

    def screen(self, need, candidates):
        self.seen = (need, [c.id for c in candidates])
        return Screening(dict(self.verdicts), "seller agent (test)")


@pytest.fixture
def svc():
    return Service(connect(":memory:"), fake_catalog, Clock())


@pytest.fixture
def tokens(svc):
    return issue_demo_mandates(svc.conn)


@pytest.fixture
def hotel(svc, tokens):  # milk only, every product must be lactose-free
    return svc.authenticate(tokens["hotel"])


@pytest.fixture
def school(svc, tokens):  # any category, no must-have
    return svc.authenticate(tokens["school"])


def ids(found):
    return [p["id"] for p in found["products"]]


def test_search_keeps_what_fits_and_says_what_was_dropped(svc, hotel):
    found = svc.search_products(hotel, "lactose-free milk", amount=1000, unit="L")
    assert found["status"] == "ok"
    assert ids(found) == ["464201", "465039", "463038", "464179"]
    assert found["dropped"] == [{"id": "464500", "name": "Lactose-free coffee milk 1 L",
                                 "reason": "coffee milk or coffee drink"}]
    assert found["understood"] == {"product": "milk", "must_have": ["lactose-free"],
                                   "from_mandate": ["lactose-free"]}
    assert (found["screened_by"], found["total_matches"], found["truncated"]) == ("keyword rules", 5, False)
    assert found["products"][0]["properties"] == ["lactose-free"]
    assert "hint" not in found


def test_the_mandates_must_haves_and_categories_always_apply(svc, hotel):
    found = svc.search_products(hotel, "milk")  # the buyer did not say lactose-free
    assert found["understood"] == {"product": "milk", "must_have": [], "from_mandate": ["lactose-free"]}
    assert ids(found) == ["464201", "465039", "463038", "464179"]
    assert ids(svc.search_products(hotel, "tomato")) == []  # category 20100 is not in the mandate


def test_a_buyer_without_category_rules_searches_everything(svc, school):
    assert ids(svc.search_products(school, "tomato")) == ["460004"]


def test_nothing_found_comes_with_a_hint(svc, school):
    found = svc.search_products(school, "unicorn")
    assert (found["status"], found["products"], found["dropped"]) == ("ok", [], [])
    assert "unicorn" in found["hint"]


def test_missing_product_words_get_a_question(svc, hotel):
    asked = svc.search_products(hotel, "", ["lactose-free"])
    assert (asked["status"], asked["missing"], asked["unknown"]) == ("needs_clarification", ["product"], [])
    assert asked["question"]
    assert svc.search_products(hotel, None)["missing"] == ["product"]


def test_an_unknown_must_have_gets_a_question_with_the_known_properties(svc, hotel):
    asked = svc.search_products(hotel, "milk", ["organic"])
    assert (asked["status"], asked["unknown"]) == ("needs_clarification", ["organic"])
    assert "organic" in asked["question"]
    assert len(asked["known_properties"]) == 21 and "lactose-free" in asked["known_properties"]


def test_more_candidates_than_the_limit_is_flagged(svc, hotel, monkeypatch):
    monkeypatch.setattr("server.service.CANDIDATE_LIMIT", 2)
    found = svc.search_products(hotel, "milk")
    assert (found["total_matches"], found["truncated"]) == (2, True)
    assert "hint" in found


def test_the_seller_sees_the_need_and_decides_what_is_kept():
    seller = FixedSeller({"464201": Verdict(True), "465039": Verdict(False, "wrong fat percentage"),
                          "463038": Verdict(True), "464179": Verdict(True),
                          "464500": Verdict(False, "coffee milk")})
    svc = Service(connect(":memory:"), fake_catalog, Clock(), seller=seller)
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    found = svc.search_products(hotel, "Lactose-free  milk", amount=1000, unit="L")
    assert ids(found) == ["464201", "463038", "464179"]
    assert {d["id"]: d["reason"] for d in found["dropped"]} == {
        "465039": "wrong fat percentage", "464500": "coffee milk"}
    assert found["screened_by"] == "seller agent (test)"
    need, candidate_ids = seller.seen
    assert need == Need("Lactose-free milk", ("lactose-free",), 1000, "L")
    assert candidate_ids == ["464201", "465039", "463038", "464179", "464500"]


def test_the_seller_cannot_add_a_product_and_a_missing_verdict_falls_back():
    # A verdict for a product that was not a candidate is ignored. A candidate without a
    # verdict is judged by the keyword rules.
    seller = FixedSeller({"460000": Verdict(True), "464201": Verdict(True)})
    svc = Service(connect(":memory:"), fake_catalog, Clock(), seller=seller)
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    found = svc.search_products(hotel, "milk")
    assert "460000" not in ids(found)
    assert ids(found) == ["464201", "465039", "463038", "464179"]
    assert [d["id"] for d in found["dropped"]] == ["464500"]


def test_a_search_is_logged_with_who_asked_and_what_was_dropped(svc, hotel):
    svc.search_products(hotel, "lactose-free milk")
    entry = svc.full_log()[-1]
    assert (entry["actor"], entry["action"]) == ("buyer-agent-01", "search_products")
    assert "kept 4 and dropped 1" in entry["reason"]
    assert "coffee milk or coffee drink (1)" in entry["reason"]
    assert "lactose-free" in entry["reason"] and "FREE_FROM_LACTOSE" not in entry["reason"]


def test_a_question_is_logged_too(svc, hotel):
    svc.search_products(hotel, "milk", ["organic"])
    assert svc.full_log()[-1]["reason"].startswith("Asked the agent:")


class Named:
    def __init__(self, name_en, name_fi=""):
        self.id, self.name_en, self.name_fi, self.sales_unit, self.tags = "1", name_en, name_fi, "1 L", []


@pytest.mark.parametrize("asked, name, kept", [
    ("milk", "Valio whole milk 1 l lactose free UHT", True),
    ("milk", "Valio coffee milk 1 l lactose free UHT", False),
    ("milk", "Arla Cafè milk 1 L UHT lactose free", False),
    ("milk", "Valio Eila® skimmed sour milk 1 l lactose free", False),
    ("milk", "Arla Portion milk 100x2 cl lactose free 1,5% UHT", False),
    ("coffee milk", "Valio coffee milk 1 l lactose free UHT", True),   # asked for by name
    ("ice cream", "Dairy ice cream 5 L", True),                         # cream asked for by name
    ("milk", "Goat milk 1 l", True),                  # "oat" inside "goat" is not oat
    ("bread", "Sourdough bread 500 g", True),         # "sour" inside "sourdough"
    ("soup", "Cafeteria soup base", True),            # "cafe" inside "cafeteria"
    ("milk", "Oat drink 1 l", False),
    ("milk", "Oats drink 1 l", False),                # plural
])
def test_keyword_rules_drop_other_kinds_unless_asked_for_by_name(asked, name, kept):
    assert keyword_verdict(Need(asked), Named(name)).keep is kept


def test_keyword_rules_read_the_finnish_name_too():
    verdict = keyword_verdict(Need("milk"), Named("Laktoositon 1 l", "Laktoositon kahvimaito 1 l"))
    assert (verdict.keep, verdict.reason) == (False, "coffee milk or coffee drink")


@pytest.mark.parametrize("name_en, name_fi, reason", [
    ("Cooking cream 2 dl", "Ruokakerma 2 dl", "cream"),
    ("Yoghurt drink", "Valiojogurtti 1 kg", "yoghurt"),
])
def test_finnish_stems_match_inside_compound_words(name_en, name_fi, reason):
    verdict = keyword_verdict(Need("milk"), Named(name_en, name_fi))
    assert (verdict.keep, verdict.reason) == (False, reason)


def test_a_seller_that_raises_does_not_fail_the_search():
    class Broken:
        def screen(self, need, candidates):
            raise RuntimeError("model unavailable")

    svc = Service(connect(":memory:"), fake_catalog, Clock(), seller=Broken())
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    found = svc.search_products(hotel, "milk")
    assert found["status"] == "ok"
    assert ids(found) == ["464201", "465039", "463038", "464179"]
    assert [d["id"] for d in found["dropped"]] == ["464500"]
    assert found["screened_by"] == "keyword rules"


def test_the_keyword_seller_answers_for_every_candidate():
    screening = KeywordSeller().screen(Need("milk"), [Named("Whole milk")])
    assert screening == Screening({"1": Verdict(True)}, "keyword rules")


def test_the_seller_runs_outside_the_services_lock():
    # The approval and log pages must stay usable while the seller agent thinks.
    import threading

    class SlowSeller:
        other_call_finished = False

        def screen(self, need, candidates):
            done = threading.Event()
            threading.Thread(target=lambda: (svc.list_approvals(), done.set())).start()
            self.other_call_finished = done.wait(timeout=2)
            return KeywordSeller().screen(need, candidates)

    seller = SlowSeller()
    svc = Service(connect(":memory:"), fake_catalog, Clock(), seller=seller)
    hotel = svc.authenticate(issue_demo_mandates(svc.conn)["hotel"])
    svc.search_products(hotel, "milk")
    assert seller.other_call_finished
