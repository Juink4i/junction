"""Each onboarding answer lands in the mandate (a rule) or in the profile (a preference)."""

import re
from datetime import date

import pytest

from onboarding.build import build, new_buyer_id, problems
from catalog.names import CATEGORY_NAMES
from onboarding.options import TEMPLATES, options, template
from server.mandate import _shape_problems

TODAY = date(2026, 11, 14)


def built(answers=None, **kw):
    return build(answers or template("daycare"), "aurinko-3f2a", TODAY, **kw)


def texts(result, kind):
    return [s["text"] for s in result.sentences if s["kind"] == kind]


def test_kitchen_name_approver_and_ids_go_into_the_mandate():
    mandate = built().mandate
    assert mandate["buyer"] == "Päiväkoti Aurinko"
    assert mandate["approvers"] == ["kitchen.lead@aurinko.example"]
    assert mandate["mandate_id"] == "mnd_aurinko-3f2a_001"
    assert mandate["agent_id"] == "agent-aurinko-3f2a"
    assert mandate["valid_until"] == "2027-11-14"


def test_allergen_answers_become_hard_rules():
    assert built().mandate["hard_rules"] == {
        "blocked_allergens": ["AP", "AN"], "unknown_allergens": "human",
        "no_delivery_after": "need_by_date"}


def test_every_product_must_be_becomes_must_keep():
    assert built().mandate["substitution"] == {
        "allowed": True, "max_price_increase_pct": 10, "must_keep": ["FREE_FROM_LACTOSE"]}


def test_categories_are_limited_only_when_some_are_chosen():
    for kind in ("daycare", "school", "hotel", "cafe"):
        assert "allowed_categories" not in built(template(kind)).mandate["auto_approve"]
    answers = template("hotel")
    answers["money"]["allowed_categories"] = ["10400"]
    assert built(answers).mandate["auto_approve"]["allowed_categories"] == ["10400"]


def test_per_order_amount_becomes_max_order_eur():
    assert built().mandate["auto_approve"]["max_order_eur"] == 100


def test_budget_becomes_a_mandate_part_or_is_left_out():
    assert built().mandate["budget"] == {"period": "week", "max_eur": 150}
    answers = template("daycare")
    answers["money"]["budget"] = None
    assert "budget" not in built(answers).mandate


def test_usual_orders_go_to_the_mandate_and_the_profile():
    result = built()
    assert result.mandate["usual_orders"] == [
        {"category": "10400", "amount": 40, "content_unit": "L", "every": "week"}]
    assert result.profile["usual_orders"] == [
        {"what": "lactose-free milk", "amount": 40, "unit": "L", "every": "week"}]


def test_a_usual_order_can_name_its_day():
    answers = template("daycare")
    answers["usual_orders"] = [
        {"what": "milk", "category": "10400", "amount": 40, "unit": "L", "every": "week", "on": "THU"},
        {"what": "cream", "category": "10400", "amount": 5, "unit": "L", "every": "month", "on": 15},
    ]
    result = built(answers)
    assert [o["on"] for o in result.mandate["usual_orders"]] == ["THU", 15]
    assert [o["on"] for o in result.profile["usual_orders"]] == ["THU", 15]
    rules = " ".join(texts(result, "rule"))
    assert "each week on Thursday" in rules
    assert "each month on day 15" in rules
    assert _shape_problems(result.mandate) == []


def test_a_usual_order_without_a_day_has_no_on_key():
    result = built()
    assert "on" not in result.mandate["usual_orders"][0]
    assert "on" not in result.profile["usual_orders"][0]


@pytest.mark.parametrize("every, on", [("week", "XYZ"), ("week", 3), ("month", 0), ("month", 32),
                                       ("month", "MON"), ("month", 2.5), ("month", True)])
def test_a_usual_order_day_must_fit_its_rhythm(every, on):
    answers = template("daycare")
    answers["usual_orders"][0].update(every=every, on=on)
    assert any("Usual order 1" in p and "day" in p for p in problems(answers))


@pytest.mark.parametrize("every, on", [("week", "MON"), ("week", None), ("month", 1), ("month", 31),
                                       ("month", None)])
def test_a_usual_order_day_that_fits_is_fine(every, on):
    answers = template("daycare")
    answers["usual_orders"][0].update(every=every, on=on)
    assert problems(answers) == []


def test_options_offer_the_days_of_the_month():
    assert options()["month_days"] == list(range(1, 32))


def test_preferences_stay_out_of_the_mandate():
    result = built()
    assert "priorities" not in result.mandate and "pack_size" not in result.mandate
    assert result.profile["priorities"] == ["price", "reliability", "finnish", "sustainability"]
    assert result.profile["pack_size"] == "small"


def test_the_profile_holds_no_rule():
    assert set(built().profile) == {"buyer_id", "name", "kitchen_type", "priorities", "pack_size",
                                    "prefer", "usual_orders"}


def test_delivery_days_are_a_rule_in_the_mandate():
    result = built()
    assert result.mandate["delivery"] == {"days": ["MON", "THU"]}
    assert "delivery_days" not in result.profile
    assert ("Goods can arrive on Monday and Thursday. Any other day needs a person's approval."
            in texts(result, "rule"))
    assert options()["delivery_days_side"] == "rule"
    answers = template("daycare")
    answers["delivery"]["days"] = []
    assert "delivery" not in built(answers).mandate


def test_agent_key_is_in_the_mandate_only_when_given():
    assert "agent_key" not in built().mandate
    result = built(agent_public_pem="PEM")
    assert result.mandate["agent_key"] == "PEM"
    assert any("signed by this kitchen's agent" in t for t in texts(result, "rule"))


def test_review_sentences_are_labelled_rule_or_preference():
    result = built()
    rules, preferences = texts(result, "rule"), texts(result, "preference")
    assert "Never deliver products that contain or may contain: Peanuts, Tree nuts." in rules
    assert "If a product does not say whether it has those allergens, a person must check it." in rules
    assert ("The agent may spend up to €100 on one order by itself. Above that, a person approves."
            in rules)
    assert ("Spending is capped at €150 per week. An order that would pass it goes to a person."
            in rules)
    assert any("5 times the usual (40 L of lactose-free milk each week)" in r for r in rules)
    assert ("When several products fit, prefer the lowest price, then reliable delivery, then "
            "Finnish origin, then sustainability.") in preferences
    assert ("If two products are equally good, prefer smaller packs. Every pack size can still "
            "be ordered.") in preferences
    assert {s["kind"] for s in result.sentences} == {"rule", "preference"}


@pytest.mark.parametrize("kind", sorted(TEMPLATES))
def test_every_template_can_be_signed_and_passes_the_servers_shape_check(kind):
    assert problems(template(kind)) == []
    assert _shape_problems(build(template(kind), "k-0000", TODAY).mandate) == []


def test_template_returns_a_fresh_copy():
    template("daycare")["kitchen"]["name"] = "changed"
    assert template("daycare")["kitchen"]["name"] == "Päiväkoti Aurinko"


@pytest.mark.parametrize("change, fragment", [
    (lambda a: a["kitchen"].update(name=" "), "name"),
    (lambda a: a["kitchen"].update(approver=""), "approves"),
    (lambda a: a["money"].update(max_order_eur="lots"), "one order"),
    (lambda a: a["money"]["budget"].update(max_eur=0), "above zero"),
    (lambda a: a["money"]["budget"].update(max_eur=50), "smaller"),
    (lambda a: a["money"]["budget"].update(period="year"), "per week or per month"),
    (lambda a: a["money"].update(priorities=["price", "price", "finnish", "sustainability"]), "priorities"),
    (lambda a: a["safety"].update(blocked_allergens=["ZZ"]), "ZZ"),
    (lambda a: a["safety"].update(unknown_allergens="allow"), "allergen information"),
    (lambda a: a["safety"].update(must_be=["KETO"]), "KETO"),
    (lambda a: a["money"].update(allowed_categories=["99999"]), "99999"),
    (lambda a: a["delivery"].update(days=["FUNDAY"]), "FUNDAY"),
    (lambda a: a["usual_orders"][0].update(amount=0), "amount above zero"),
    (lambda a: (a["money"].update(allowed_categories=["10400"]),
                a["usual_orders"][0].update(category="10401")), "may not buy"),
])
def test_each_problem_is_reported_in_plain_language(change, fragment):
    answers = template("daycare")
    change(answers)
    assert any(fragment in problem for problem in problems(answers))
    with pytest.raises(ValueError):
        build(answers, "k-0000", TODAY)


def test_buyer_id_is_a_slug_plus_four_hex_characters():
    assert re.fullmatch(r"paivakoti-aurinko-[0-9a-f]{4}", new_buyer_id("Päiväkoti Aurinko"))
    assert re.fullmatch(r"kitchen-[0-9a-f]{4}", new_buyer_id("!!!"))


def test_the_enrolment_code_is_never_written_into_the_mandate_or_the_profile():
    answers = template("daycare")
    answers["kitchen"]["enrolment_code"] = "AIMO-7Q4K-2M9X"
    result = built(answers)
    assert "AIMO-7Q4K-2M9X" not in str(result.mandate) + str(result.profile)
    assert any("customer account" in text for text in texts(result, "rule"))
    answers["kitchen"]["enrolment_code"] = ""
    assert not any("customer account" in text for text in texts(built(answers), "rule"))


def test_only_properties_allergen_data_can_prove_are_offered_as_rules():
    # A rule like "every product must be vegan" would rule out every egg and steak. Such
    # properties belong on a single request, which still accepts all 21.
    from datetime import date

    from onboarding.build import build
    from onboarding.options import options, template

    assert [t["code"] for t in options()["tags"]] == [
        "FREE_FROM_LACTOSE", "FREE_FROM_GLUTEN", "VEGAN", "VEGETARIAN", "FREE_FROM_EGGS",
        "FREE_FROM_SOY", "FREE_FROM_WHEAT"]
    assert options()["tags"][0] == {"code": "FREE_FROM_LACTOSE", "name": "lactose-free"}

    answers = template("daycare")
    answers["safety"]["must_be"] = ["FREE_FROM_GLUTEN", "FREE_FROM_LACTOSE"]
    built = build(answers, "aurinko-3f2a", date(2026, 11, 14))
    assert built.mandate["substitution"]["must_keep"] == ["FREE_FROM_GLUTEN", "FREE_FROM_LACTOSE"]
    [rule] = [s["text"] for s in built.sentences if s["text"].startswith("Every product must be")]
    assert rule == ("Every product must be gluten-free and lactose-free: the supplier says so, or "
                    "its allergen data shows it. If the data does not say, a person must check it. "
                    "Anything else needs a person's approval.")


def test_any_other_property_is_a_preference_not_a_rule():
    from onboarding.build import problems
    from onboarding.options import template

    answers = template("daycare")
    answers["safety"]["must_be"] = ["LOW_SODIUM_SALT"]
    assert any(p.startswith("Low-salt cannot be a rule") and "preference" in p for p in problems(answers))


def test_the_other_14_properties_are_offered_as_preferences():
    from datetime import date

    from onboarding.build import build, problems
    from onboarding.options import options, template

    offered = [t["code"] for t in options()["prefer_tags"]]
    assert len(offered) == 14 and "FREE_FROM_COLOURING_AGENTS" in offered and "VEGAN" not in offered

    answers = template("daycare")
    answers["prefer"] = ["LOW_SODIUM_SALT", "FREE_FROM_COLOURING_AGENTS"]
    built = build(answers, "aurinko-3f2a", date(2026, 11, 14))
    assert built.profile["prefer"] == ["LOW_SODIUM_SALT", "FREE_FROM_COLOURING_AGENTS"]
    assert "LOW_SODIUM_SALT" not in str(built.mandate)  # a preference is never signed as a rule
    assert {"kind": "preference", "text": "If two products are equally good, prefer ones that are "
            "low-salt and no colouring agents."} in built.sentences

    answers["prefer"] = ["VEGAN"]
    assert any("Vegan" in p and "rule" in p for p in problems(answers))


def test_every_category_is_offered_with_example_products(tmp_path):
    import sqlite3

    from onboarding.options import category_examples

    db = tmp_path / "catalog.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (id TEXT, category TEXT, name_en TEXT, name_fi TEXT)")
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", [
        ("1", "10402", "Oatly Oat Drink Semi 1L", ""), ("2", "10402", "Alpro soya drink 1 L", ""),
        ("3", "10402", "Oddlygood® Barista oat drink 1 l UHT gluten free", ""),
        ("4", "10402", "Elovena 1l oat drink barista", ""), ("5", "10500", "", "Voi 500 g")])
    con.commit()
    examples = category_examples(db)
    assert len(examples["10402"]) == 3 and "Oatly Oat Drink Semi 1L" in examples["10402"]
    assert examples["10500"] == ["Voi 500 g"]  # no English name: the Finnish one
    assert category_examples(tmp_path / "missing.db") == {}

    offered = options()["categories"]
    assert len(offered) == len(CATEGORY_NAMES) > 300
    assert offered[0]["code"] == "10400"
    assert all({"code", "name", "examples"} <= set(c) for c in offered)
