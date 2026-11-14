"""One test per row of the "who decides" table."""

import copy
from dataclasses import replace

from server import fake_catalog
from server.make_mandate import DEMO_MANDATES
from server.policy import decide

PRODUCTS = {pid: fake_catalog.get_product(pid) for pid in ("464201", "463038", "460004", "460000")}
HISTORY = [{"category": "10400", "amount": litres, "content_unit": "L"} for litres in (20, 20, 25, 15)]


def line(product_id="464201", units=100, covers=100.0, unit_price=1.56, content_unit="L", **changes):
    return {
        "product_id": product_id, "name": PRODUCTS[product_id].name_en, "units": units,
        "sales_unit": "1 L", "covers": covers, "content_unit": content_unit,
        "unit_price_eur": unit_price, "line_total_eur": round(units * unit_price, 2),
        "available_date": "2026-11-16", "cutoff_passed": False, "stock": "unconfirmed",
        **changes,
    }


def quote(*lines, need_by="2026-11-16"):
    lines = lines or (line(),)
    return {"quote_id": "q_1", "lines": list(lines), "need_by": need_by,
            "total_eur": round(sum(l["line_total_eur"] for l in lines), 2)}


def mandate(buyer="hotel", **hard_rules):
    m = copy.deepcopy(DEMO_MANDATES[buyer])
    m["hard_rules"].update(hard_rules)
    return m


def test_within_every_limit_is_confirmed():
    decision = decide(quote(), mandate(), PRODUCTS, [])
    assert decision.status == "confirmed"
    assert decision.reasons


def test_over_max_order_eur_needs_a_human():
    # The demo order: 1,000 x 464201 at 1.56 = 1,560, over the hotel's 1,500.
    decision = decide(quote(line(units=1000, covers=1000.0)), mandate(), PRODUCTS, [])
    assert decision.status == "pending_approval"
    assert any("€1,560.00" in r and "€1,500.00" in r for r in decision.reasons)


def test_exactly_at_max_order_eur_is_confirmed():
    m = mandate()
    m["auto_approve"]["max_line_eur"] = 1500
    decision = decide(quote(line(units=1000, covers=1000.0, unit_price=1.5)), m, PRODUCTS, [])
    assert decision.status == "confirmed"


def test_over_max_line_eur_needs_a_human():
    decision = decide(quote(line(units=600, covers=600.0)), mandate(), PRODUCTS, [])
    assert decision.status == "pending_approval"
    assert any("€800.00" in r for r in decision.reasons)


def test_passed_cut_off_needs_a_human():
    decision = decide(quote(line(cutoff_passed=True)), mandate(), PRODUCTS, [])
    assert decision.status == "pending_approval"
    assert any("cut-off" in r for r in decision.reasons)


def test_delivery_after_need_by_date_needs_a_human():
    decision = decide(quote(line(available_date="2026-11-17")), mandate(), PRODUCTS, [])
    assert decision.status == "pending_approval"
    assert any("2026-11-17" in r and "2026-11-16" in r for r in decision.reasons)


def test_unknown_delivery_date_needs_a_human():
    decision = decide(quote(line(available_date=None)), mandate(), PRODUCTS, [])
    assert decision.status == "pending_approval"


def test_missing_allergen_info_needs_a_human_when_mandate_says_human():
    tomato = line("460004", units=5, covers=5.0, unit_price=6.5, content_unit="KG")
    decision = decide(quote(tomato), mandate("school"), PRODUCTS, [])
    assert decision.status == "pending_approval"
    assert any("allergen" in r.lower() for r in decision.reasons)


def test_missing_allergen_info_is_fine_when_mandate_allows_it():
    tomato = line("460004", units=5, covers=5.0, unit_price=6.5, content_unit="KG")
    decision = decide(quote(tomato), mandate("school", unknown_allergens="allow"), PRODUCTS, [])
    assert decision.status == "confirmed"


def test_blocked_allergen_is_rejected():
    pancake = line("460000", units=5, covers=10.0, unit_price=9.8, content_unit="KG")
    decision = decide(quote(pancake), mandate("school"), PRODUCTS, [])
    assert decision.status == "rejected"
    assert any("AE" in r for r in decision.reasons)


def test_blocked_allergen_wins_over_reasons_for_approval():
    pancake = line("460000", units=500, covers=1000.0, unit_price=9.8, content_unit="KG",
                   cutoff_passed=True)
    decision = decide(quote(pancake), mandate("school"), PRODUCTS, [], confirm_unusual=True)
    assert decision.status == "rejected"


def test_category_the_mandate_does_not_allow_is_rejected():
    tomato = line("460004", units=5, covers=5.0, unit_price=6.5, content_unit="KG")
    decision = decide(quote(tomato), mandate("hotel"), PRODUCTS, [])
    assert decision.status == "rejected"
    assert any("20100" in r for r in decision.reasons)


def test_product_missing_from_the_catalog_is_rejected():
    decision = decide(quote(line()), mandate(), {}, [])
    assert decision.status == "rejected"


def test_more_than_5_times_the_usual_amount_asks_the_agent():
    # Café usually orders 20 L. 200 L costs 312, inside its 500 limit.
    decision = decide(quote(line(units=200, covers=200.0)), mandate("cafe"), PRODUCTS, HISTORY)
    assert decision.status == "needs_clarification"
    assert decision.question
    assert any("200" in r and "20" in r for r in decision.reasons)


def test_exactly_5_times_the_usual_amount_is_not_unusual():
    decision = decide(quote(line(units=100, covers=100.0)), mandate("cafe"), PRODUCTS, HISTORY)
    assert decision.status == "confirmed"


def test_confirmed_unusual_amount_goes_to_a_human():
    decision = decide(quote(line(units=200, covers=200.0)), mandate("cafe"), PRODUCTS, HISTORY,
                      confirm_unusual=True)
    assert decision.status == "pending_approval"
    assert decision.question is None


def test_confirm_unusual_does_not_skip_other_checks_or_auto_approve():
    decision = decide(quote(), mandate("cafe"), PRODUCTS, HISTORY, confirm_unusual=True)
    assert decision.status == "confirmed"


def test_line_without_a_must_keep_tag_needs_a_human():
    products = {"464201": replace(PRODUCTS["464201"], tags=[])}
    decision = decide(quote(), mandate("hotel"), products, [])
    assert decision.status == "pending_approval"
    assert any("FREE_FROM_LACTOSE" in r for r in decision.reasons)


# Splitting an order into lines must not get around a limit.

def test_unusual_amount_split_over_several_lines_still_asks_the_agent():
    three_lines = [line(units=100, covers=100.0) for _ in range(3)]
    decision = decide(quote(*three_lines), mandate("cafe"), PRODUCTS, HISTORY)
    assert decision.status == "needs_clarification"
    assert any("300" in r for r in decision.reasons)


def test_line_limit_applies_to_a_product_split_over_several_lines():
    m = mandate("hotel")
    m["auto_approve"]["max_order_eur"] = 5000
    two_lines = [line(units=400, covers=400.0) for _ in range(2)]
    decision = decide(quote(*two_lines), m, PRODUCTS, [])
    assert decision.status == "pending_approval"
    assert any("€1,248.00" in r and "€800.00" in r for r in decision.reasons)


def test_blocked_allergen_codes_match_whatever_their_case():
    pancake = line("460000", units=5, covers=10.0, unit_price=9.8, content_unit="KG")
    m = mandate("school", blocked_allergens=["ae"])
    assert decide(quote(pancake), m, PRODUCTS, []).status == "rejected"


def test_missing_unknown_allergens_rule_is_treated_as_human():
    tomato = line("460004", units=5, covers=5.0, unit_price=6.5, content_unit="KG")
    m = mandate("school")
    del m["hard_rules"]["unknown_allergens"]
    assert decide(quote(tomato), m, PRODUCTS, []).status == "pending_approval"
