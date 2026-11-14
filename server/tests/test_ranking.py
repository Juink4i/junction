"""Ranking is plain code: on time first, then the buyer's preferences, then a stable order."""

from datetime import date

from server.ranking import Candidate, options, rank

MONDAY = date(2026, 11, 16)


def milk(product_id, price, content=1.0, amount=1000, **changes):
    fields = dict(
        product_id=product_id, name=f"Milk {product_id}", sales_unit=f"{content:g} L",
        content_per_unit=content, content_unit="L", units=round(amount / content),
        unit_price_eur=price, unit_price_with_tax_eur=round(price * 1.135, 2),
        available_date=MONDAY, closing_time=None, cutoff_passed=False, available_units=None)
    fields.update(changes)
    return Candidate(**fields)


def order(candidates, **kw):
    return [c.product_id for c in rank(candidates, MONDAY, **kw)]


def test_cheapest_on_time_comes_first_and_late_comes_last():
    cheap_but_late = milk("C", 27.40, 20.0, cutoff_passed=True)  # 1,370 in total
    assert order([milk("B", 8.10, 5.0), cheap_but_late, milk("A", 1.56)]) == ["A", "B", "C"]


def test_arriving_after_the_need_by_date_counts_as_late():
    tuesday = milk("A", 1.00, available_date=date(2026, 11, 17))
    assert order([tuesday, milk("B", 2.00)]) == ["B", "A"]
    assert order([milk("A", 1.00, available_date=None), milk("B", 2.00)]) == ["B", "A"]


def test_equal_prices_fall_back_to_the_product_id():
    assert order([milk("B", 1.62), milk("A", 1.62)]) == ["A", "B"]


def test_earlier_delivery_breaks_a_price_tie():
    sunday = milk("B", 1.62, available_date=date(2026, 11, 15))
    assert order([milk("A", 1.62), sunday]) == ["B", "A"]


def test_prices_within_two_percent_tie_so_the_next_preference_decides():
    organic = milk("B", 1.57, labels=("EU_ORGANIC_FARMING",))
    assert order([milk("A", 1.56), organic], priorities=["price", "sustainability"]) == ["B", "A"]
    far_dearer = milk("B", 1.70, labels=("EU_ORGANIC_FARMING",))
    assert order([milk("A", 1.56), far_dearer], priorities=["price", "sustainability"]) == ["A", "B"]


def test_the_buyers_first_preference_wins_over_price():
    reliable = milk("B", 2.00, reliability=0.99)
    assert order([milk("A", 1.56, reliability=0.90), reliable], priorities=["reliability", "price"]) == ["B", "A"]
    finnish = milk("B", 2.00, country="fi")
    assert order([milk("A", 1.56, country="dk"), finnish], priorities=["finnish"]) == ["B", "A"]


def test_unknown_reliability_counts_as_lowest():
    assert order([milk("A", 1.56), milk("B", 1.56, reliability=0.5)], priorities=["reliability"]) == ["B", "A"]


def test_unknown_preference_words_are_ignored():
    assert order([milk("B", 2.00), milk("A", 1.56)], priorities=["vibes"]) == ["A", "B"]


def test_pack_size_breaks_remaining_ties():
    small, large = milk("A", 1.00), milk("B", 10.00, 10.0)
    assert order([small, large], pack_size="large") == ["B", "A"]
    assert order([large, small], pack_size="small") == ["A", "B"]


def test_options_are_labelled_and_describe_the_trade_off():
    ranked = rank([milk("A", 1.56), milk("B", 8.10, 5.0), milk("D", 16.20, 10.0),
                   milk("C", 27.40, 20.0, cutoff_passed=True)], MONDAY)
    found = options(ranked, 1000, MONDAY)
    assert [(o.label, o.lines[0].candidate.product_id, o.total_eur) for o in found] == [
        ("best", "A", 1560.0), ("better", "B", 1620.0), ("good", "D", 1620.0), ("other", "C", 1370.0)]
    assert found[0].trade_off == "1,000 × 1 L of Milk A (1000 L), arrives 2026-11-16."
    assert "€60.00 more than the best option" in found[1].trade_off
    assert "€190.00 less than the best option" in found[3].trade_off
    assert "Not certain to arrive on time: Milk C" in found[3].trade_off


def test_at_most_five_options():
    ranked = rank([milk(str(i), 1.0 + i) for i in range(8)], MONDAY)
    assert len(options(ranked, 1000, MONDAY)) == 5


def test_a_product_short_on_stock_is_not_offered_alone():
    ranked = rank([milk("A", 1.56), milk("B", 8.10, 5.0, available_units=10)], MONDAY)
    assert [o.lines[0].candidate.product_id for o in options(ranked, 1000, MONDAY)] == ["A"]
    assert milk("A", 1.56, available_units=1000).short is False
    assert milk("A", 1.56, available_units=999).short is True


def test_a_short_first_choice_becomes_a_split_with_the_next_product():
    ranked = rank([milk("A", 1.56, available_units=700), milk("B", 8.10, 5.0),
                   milk("D", 16.20, 10.0)], MONDAY)
    found = options(ranked, 1000, MONDAY)
    assert [o.label for o in found] == ["split", "better", "good"]
    assert [(l.candidate.product_id, l.units, l.covers) for l in found[0].lines] == [
        ("A", 700, 700.0), ("B", 60, 300.0)]
    assert found[0].total_eur == 1578.0
    assert found[0].trade_off.startswith("700 × 1 L of Milk A (700 L) + 60 × 5 L of Milk B (300 L)")
    assert "€42.00 more than the best option" in found[1].trade_off


def test_the_split_walks_down_the_list_until_the_amount_is_covered():
    ranked = rank([milk("A", 1.00, available_units=500), milk("B", 1.10, available_units=300),
                   milk("C", 1.20)], MONDAY)
    split, single = options(ranked, 1000, MONDAY)
    assert [(l.candidate.product_id, l.units) for l in split.lines] == [("A", 500), ("B", 300), ("C", 200)]
    assert single.lines[0].candidate.product_id == "C"


def test_no_split_when_the_rest_cannot_be_covered():
    ranked = rank([milk("A", 1.00, available_units=500), milk("B", 1.10, available_units=100)], MONDAY)
    assert options(ranked, 1000, MONDAY) == []


def test_only_a_short_first_choice_causes_a_split():
    ranked = rank([milk("A", 1.00), milk("B", 1.10, available_units=100)], MONDAY)
    assert [o.label for o in options(ranked, 1000, MONDAY)] == ["best"]
