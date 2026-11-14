"""One test per row of the "who decides" table."""

import copy
from dataclasses import replace
from datetime import datetime, timezone

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
    decision = decide(quote(pancake), mandate("school"), PRODUCTS, [])
    assert decision.status == "rejected"


def test_category_the_mandate_does_not_allow_is_rejected():
    tomato = line("460004", units=5, covers=5.0, unit_price=6.5, content_unit="KG")
    decision = decide(quote(tomato), mandate("hotel"), PRODUCTS, [])
    assert decision.status == "rejected"
    assert any("20100" in r for r in decision.reasons)


def test_product_missing_from_the_catalog_is_rejected():
    decision = decide(quote(line()), mandate(), {}, [])
    assert decision.status == "rejected"


def test_more_than_5_times_the_usual_amount_needs_a_human():
    # Café usually orders 20 L. 200 L costs 312, inside its 500 limit.
    decision = decide(quote(line(units=200, covers=200.0)), mandate("cafe"), PRODUCTS, HISTORY)
    assert decision.status == "pending_approval"
    assert any("200" in r and "20" in r for r in decision.reasons)


def test_exactly_5_times_the_usual_amount_is_not_unusual():
    decision = decide(quote(line(units=100, covers=100.0)), mandate("cafe"), PRODUCTS, HISTORY)
    assert decision.status == "confirmed"


def test_line_without_a_must_keep_tag_needs_a_human():
    products = {"464201": replace(PRODUCTS["464201"], tags=[], allergens_contains=["AM"])}
    decision = decide(quote(), mandate("hotel"), products, [])
    assert decision.status == "pending_approval"
    assert any("is not lactose-free" in r and "FREE_FROM" not in r for r in decision.reasons)


# Splitting an order into lines must not get around a limit.

def test_unusual_amount_split_over_several_lines_still_needs_a_human():
    three_lines = [line(units=100, covers=100.0) for _ in range(3)]
    decision = decide(quote(*three_lines), mandate("cafe"), PRODUCTS, HISTORY)
    assert decision.status == "pending_approval"
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


# A product can list some allergens and say nothing about the rest.

def milk_listing_only(contains, free_from=()):
    return {"464201": replace(PRODUCTS["464201"], allergens_contains=list(contains),
                              allergens_free_from=list(free_from), allergen_info_missing=False)}


def test_blocked_allergen_the_product_says_nothing_about_needs_a_human():
    products = milk_listing_only(["BM"], free_from=["AP"])
    decision = decide(quote(), mandate("school"), products, [])
    assert decision.status == "pending_approval"
    assert any("AE, AN" in r and "unknown" in r.lower() for r in decision.reasons)


def test_blocked_allergens_all_listed_as_free_from_is_confirmed():
    products = milk_listing_only(["BM"], free_from=["AP", "AN", "AE"])
    assert decide(quote(), mandate("school"), products, []).status == "confirmed"


def test_blocked_allergen_the_product_says_nothing_about_is_rejected_when_mandate_says_reject():
    products = milk_listing_only(["BM"])
    decision = decide(quote(), mandate("school", unknown_allergens="reject"), products, [])
    assert decision.status == "rejected"


def test_unlisted_allergens_are_ignored_when_mandate_allows_unknown():
    products = milk_listing_only(["BM"])
    decision = decide(quote(), mandate("school", unknown_allergens="allow"), products, [])
    assert decision.status == "confirmed"


# The Decisions API score can only send an order to a person, never wave one through.

AI_FLAG = "Google's Decisions API rates this order 97% likely to be unusual for this buyer."


def test_ai_flag_alone_needs_a_human():
    decision = decide(quote(), mandate("cafe"), PRODUCTS, HISTORY, ai_unusual=AI_FLAG)
    assert decision.status == "pending_approval"
    assert AI_FLAG in decision.reasons


def test_ai_flag_does_not_soften_a_rejection():
    tomato = line("460004", units=5, covers=5.0, unit_price=6.5, content_unit="KG")
    decision = decide(quote(tomato), mandate("hotel"), PRODUCTS, [], ai_unusual=AI_FLAG)
    assert decision.status == "rejected"


# Budget per week or month

from datetime import datetime, timezone  # noqa: E402

from server.policy import period_start  # noqa: E402


def budget_mandate(period="week", max_eur=150):
    m = mandate("cafe")
    m["budget"] = {"period": period, "max_eur": max_eur}
    return m


def forty_litres():
    return quote(line(units=40, covers=40.0))  # 40 x 1.56 = 62.40


def test_under_the_budget_is_confirmed():
    decision = decide(forty_litres(), budget_mandate(), PRODUCTS, [], spent_in_period=60)
    assert decision.status == "confirmed"


def test_exactly_at_the_budget_is_confirmed():
    decision = decide(forty_litres(), budget_mandate(), PRODUCTS, [], spent_in_period=87.6)
    assert decision.status == "confirmed"


def test_over_the_weekly_budget_needs_a_human():
    decision = decide(forty_litres(), budget_mandate(), PRODUCTS, [], spent_in_period=108)
    assert decision.status == "pending_approval"
    assert any("€62.40" in r and "this week's spending to €170.40" in r
               and "weekly budget of €150.00" in r for r in decision.reasons)


def test_over_the_monthly_budget_says_month():
    decision = decide(forty_litres(), budget_mandate("month"), PRODUCTS, [], spent_in_period=108)
    assert decision.status == "pending_approval"
    assert any("this month's spending" in r and "monthly budget" in r for r in decision.reasons)


def test_a_mandate_without_a_budget_ignores_what_was_spent():
    decision = decide(forty_litres(), mandate("cafe"), PRODUCTS, [], spent_in_period=10_000)
    assert decision.status == "confirmed"


def test_a_budget_period_starts_on_monday_or_on_the_first():
    saturday = datetime(2026, 11, 14, 10, 30, tzinfo=timezone.utc)
    assert period_start("week", saturday) == datetime(2026, 11, 9, tzinfo=timezone.utc)
    assert period_start("month", saturday) == datetime(2026, 11, 1, tzinfo=timezone.utc)


# Delivery days


def test_delivery_on_a_day_the_kitchen_cannot_receive_needs_a_human():
    m = mandate("cafe")
    m["delivery"] = {"days": ["TUE", "THU"]}
    decision = decide(quote(), m, PRODUCTS, [])  # the default line arrives on Monday 2026-11-16
    assert decision.status == "pending_approval"
    assert any("would arrive on a Monday" in r and "Tuesday and Thursday only" in r
               for r in decision.reasons)


def test_delivery_on_an_allowed_day_is_confirmed():
    m = mandate("cafe")
    m["delivery"] = {"days": ["MON", "THU"]}
    assert decide(quote(), m, PRODUCTS, []).status == "confirmed"


def test_a_mandate_without_delivery_days_accepts_any_day():
    assert decide(quote(), mandate("cafe"), PRODUCTS, []).status == "confirmed"


# The cut-off is checked again when the order arrives, from the time stored in the quote.

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def test_cut_off_that_passed_since_the_quote_needs_a_human():
    closed = line(closing_time="2026-11-14T09:59:00+00:00")
    decision = decide(quote(closed), mandate("hotel"), PRODUCTS, [], now=NOW)
    assert decision.status == "pending_approval"
    assert any("cut-off" in r for r in decision.reasons)


def test_cut_off_still_ahead_is_confirmed():
    still_open = line(closing_time="2026-11-14T10:01:00+00:00")
    assert decide(quote(still_open), mandate("hotel"), PRODUCTS, [], now=NOW).status == "confirmed"


def test_a_line_without_a_closing_time_is_judged_by_its_flag_alone():
    assert decide(quote(line(closing_time=None)), mandate("hotel"), PRODUCTS, [], now=NOW).status == "confirmed"
    assert decide(quote(), mandate("hotel"), PRODUCTS, []).status == "confirmed"


def test_a_cut_off_time_without_an_offset_counts_as_passed():
    unclear = line(closing_time="2026-11-14T09:59:00")
    decision = decide(quote(unclear), mandate("hotel"), PRODUCTS, [], now=NOW)
    assert decision.status == "pending_approval"
    assert any("cut-off" in r for r in decision.reasons)


def test_a_cut_off_time_that_is_not_a_date_counts_as_passed():
    unreadable = line(closing_time="yesterday afternoon")
    decision = decide(quote(unreadable), mandate("hotel"), PRODUCTS, [], now=NOW)
    assert decision.status == "pending_approval"
    assert any("cut-off" in r for r in decision.reasons)


# A free-from must-have is proven by a claim or by the allergen data.

def _eggs(**allergens):
    egg = fake_catalog.Product(id="egg", name_en="Barn egg 30 pcs", name_fi="Kananmuna 30 kpl",
                               category="10590", sales_unit="30 PCS", allergens_contains=["AE"],
                               **allergens)
    return {"egg": egg}


def _lactose_free_school(**hard_rules):
    m = mandate("school", **{"blocked_allergens": [], **hard_rules})  # the school blocks eggs
    m["substitution"]["must_keep"] = ["FREE_FROM_LACTOSE"]
    return m


def _egg_line():
    return {**line(units=10, covers=300.0, unit_price=4.0, content_unit="PCS"),
            "product_id": "egg", "name": "Barn egg 30 pcs", "sales_unit": "30 PCS"}


def test_eggs_free_from_milk_meet_a_lactose_free_rule():
    decision = decide(quote(_egg_line()), _lactose_free_school(), _eggs(allergens_free_from=["AM"]), [])
    assert decision.status == "confirmed", decision.reasons


def test_eggs_that_do_not_mention_milk_go_to_a_person():
    decision = decide(quote(_egg_line()), _lactose_free_school(), _eggs(), [])
    assert decision.status == "pending_approval"
    assert ["The product data does not say whether Barn egg 30 pcs is lactose-free, which the "
            "mandate requires. Unknown is not treated as safe, so a person must check it."] == [
        r for r in decision.reasons if "lactose-free" in r]


def test_eggs_that_do_not_mention_milk_are_refused_when_the_mandate_refuses_unknowns():
    decision = decide(quote(_egg_line()), _lactose_free_school(unknown_allergens="reject"), _eggs(), [])
    assert decision.status == "rejected"
    assert any("lactose-free" in r and "rejects" in r for r in decision.reasons)
