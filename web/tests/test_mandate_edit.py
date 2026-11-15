"""The buyer edits its own mandate; web/ signs it with the buyer's key and registers it."""

import json
from datetime import date

import jwt
import pytest

from agent.identity import key_path, sign_order
from server import audit, signing
from server.mandate import MandateError, verify_mandate
from web.tests.world import KID


def decode(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _updates(conn) -> list:
    return conn.execute("SELECT * FROM log WHERE action = 'mandate:updated' ORDER BY seq").fetchall()


def _pem(conn, buyer_id: str) -> str:
    return conn.execute("SELECT public_pem FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()[0]


def test_put_changes_the_limit_and_signs_a_new_version(client, world):
    old_token = (world.mandates / "cafe.jwt").read_text()
    old_pem = _pem(world.conn, "cafe")

    res = client.put("/api/accounts/cafe/mandate", json={"auto_approve": {"max_order_eur": 600}})
    assert res.status_code == 200, res.text
    account = res.json()
    assert set(account) == {"buyer_id", "name", "mandate", "mandate_verified", "mandate_problem"}
    assert account["mandate_verified"] is True
    assert account["mandate"]["auto_approve"] == {"max_order_eur": 600, "max_line_eur": 400}
    assert account["mandate"]["mandate_id"] == "mnd_cafe_kallio_002"
    assert account["mandate"]["issued_at"]

    token = (world.mandates / "cafe.jwt").read_text()
    assert token != old_token
    assert token not in res.text and token.split(".")[2] not in res.text
    buyer_id, mandate = verify_mandate(token, world.conn, date.today())
    assert buyer_id == "cafe" and mandate["auto_approve"]["max_order_eur"] == 600

    assert (world.keys / "cafe.pem").exists()
    assert _pem(world.conn, "cafe") != old_pem  # first rotation registers the new key

    [row] = _updates(world.conn)
    assert row["actor"] == "owner@cafe.example"
    assert row["reason"].startswith("Café Kallio changed its mandate to mnd_cafe_kallio_002: ")
    assert "limit per order €500.00 → €600.00" in row["reason"]
    assert row["reason"].endswith("The agent uses the new rules from its next order.")
    assert audit.verify(world.conn) == {"ok": True}  # what GET /api/log/verify reports


def test_second_put_reuses_the_key(client, world):
    assert client.put("/api/accounts/hotel/mandate",
                      json={"auto_approve": {"max_line_eur": 900}}).status_code == 200
    key = (world.keys / "hotel.pem").read_text()
    pem = _pem(world.conn, "hotel")

    res = client.put("/api/accounts/hotel/mandate", json={"substitution": {"must_keep": []}})
    assert res.status_code == 200, res.text
    assert res.json()["mandate"]["mandate_id"] == "mnd_hotel_helsinki_003"
    assert res.json()["mandate"]["auto_approve"]["max_line_eur"] == 900  # first change kept
    assert (world.keys / "hotel.pem").read_text() == key
    assert _pem(world.conn, "hotel") == pem
    rows = _updates(world.conn)
    assert len(rows) == 2
    assert "substitutes must stay Lactose-free → (none)" in rows[1]["reason"]
    assert audit.verify(world.conn) == {"ok": True}
    verify_mandate((world.mandates / "hotel.jwt").read_text(), world.conn, date.today())


def test_empty_categories_means_any_category(client, world):
    res = client.put("/api/accounts/cafe/mandate", json={"auto_approve": {"allowed_categories": []}})
    assert res.status_code == 200
    assert "allowed_categories" not in res.json()["mandate"]["auto_approve"]
    res = client.put("/api/accounts/hotel/mandate", json={"auto_approve": {"allowed_categories": None}})
    assert "allowed_categories" not in res.json()["mandate"]["auto_approve"]


def test_other_editable_fields(client, world):
    body = {"substitution": {"allowed": False, "max_price_increase_pct": 5},
            "hard_rules": {"blocked_allergens": ["AE"], "unknown_allergens": "reject"},
            "approvers": ["boss@cafe.example", "owner@cafe.example"], "valid_until": "2027-01-31"}
    res = client.put("/api/accounts/cafe/mandate", json=body)
    assert res.status_code == 200, res.text
    m = res.json()["mandate"]
    assert m["substitution"] == {"allowed": False, "must_keep": [], "max_price_increase_pct": 5}
    assert m["hard_rules"]["blocked_allergens"] == ["AE"]
    assert m["hard_rules"]["no_delivery_after"] == "need_by_date"  # not editable, kept
    assert m["approvers"][0] == "boss@cafe.example" and m["valid_until"] == "2027-01-31"
    [row] = _updates(world.conn)
    assert row["actor"] == "boss@cafe.example"


def test_no_change_writes_nothing(client, world):
    token = (world.mandates / "cafe.jwt").read_text()
    res = client.put("/api/accounts/cafe/mandate", json={"auto_approve": {"max_order_eur": 500}})
    assert res.status_code == 200
    assert res.json()["mandate"]["mandate_id"] == "mnd_cafe_kallio_001"
    assert (world.mandates / "cafe.jwt").read_text() == token
    assert _updates(world.conn) == []


@pytest.mark.parametrize("body", [
    {"agent_id": "evil-agent"},
    {"mandate_id": "mnd_x_999"},
    {"auto_approve": {"max_order": 1}},
    {"hard_rules": {"no_delivery_after": "never"}},
    {"substitution": "yes"},
    [1, 2],
])
def test_rejects_fields_that_are_not_editable(client, world, body):
    res = client.put("/api/accounts/cafe/mandate", json=body)
    assert res.status_code == 400
    assert res.json()["code"] == "bad_field"
    assert _updates(world.conn) == []


@pytest.mark.parametrize("body,words", [
    ({"auto_approve": {"max_order_eur": 0}}, "above zero"),
    ({"auto_approve": {"max_line_eur": -5}}, "above zero"),
    ({"auto_approve": {"max_order_eur": "lots"}}, "number of euros"),
    ({"auto_approve": {"max_line_eur": 900}}, "per line"),
    ({"substitution": {"max_price_increase_pct": 150}}, "between 0 and 100"),
    ({"substitution": {"allowed": "maybe"}}, "true or false"),
    ({"valid_until": "2020-01-01"}, "past"),
    ({"valid_until": "soon"}, "date"),
    ({"approvers": []}, "approver"),
    ({"hard_rules": {"unknown_allergens": "maybe"}}, "unknown_allergens"),
    ({"hard_rules": {"blocked_allergens": "AE"}}, "blocked_allergens"),
])
def test_rejects_bad_values(client, world, body, words):
    token = (world.mandates / "cafe.jwt").read_text()
    res = client.put("/api/accounts/cafe/mandate", json=body)
    assert res.status_code == 400
    assert res.json()["code"] == "bad_mandate"
    assert words in res.json()["message"]
    assert (world.mandates / "cafe.jwt").read_text() == token
    assert not (world.keys / "cafe.pem").exists()
    assert _updates(world.conn) == []


def test_unknown_account_is_404(client, world):
    res = client.put("/api/accounts/nobody/mandate", json={"auto_approve": {"max_order_eur": 600}})
    assert res.status_code == 404
    assert res.json()["code"] == "account_not_found"


# Kitchens signed up through onboarding, and main's new mandate fields


def test_onboarded_kitchen_edits_in_place_with_its_own_key(client, world):
    path = world.buyers / KID / "mandate.jwt"
    before = decode(path.read_text())
    pem = _pem(world.conn, KID)

    res = client.put(f"/api/accounts/{KID}/mandate",
                     json={"budget": {"max_eur": 1000}, "auto_approve": {"max_order_eur": 120}})
    assert res.status_code == 200, res.text
    assert res.json()["mandate_verified"] is True
    after = decode(path.read_text())
    assert after["mandate_id"] == f"mnd_{KID}_002"
    assert after["budget"] == {"period": "week", "max_eur": 1000}
    for kept in ("agent_key", "usual_orders", "delivery", "agent_id", "buyer"):
        assert after[kept] == before[kept]
    assert after["hard_rules"]["no_delivery_after"] == before["hard_rules"]["no_delivery_after"]
    assert not (world.mandates / f"{KID}.jwt").exists()
    assert not (world.keys / f"{KID}.pem").exists()
    assert _pem(world.conn, KID) == pem  # never rotated
    [row] = _updates(world.conn)
    assert row["actor"] == "kitchen.lead@aurinko.example"
    assert "budget €150.00 per week → €1,000.00 per week" in row["reason"]
    assert "limit per order €100.00 → €120.00" in row["reason"]
    assert audit.verify(world.conn) == {"ok": True}

    # The agent still orders with the new mandate, signing the new mandate id.
    token = path.read_text()
    q = world.quote(token, "464201", 40)
    signature = sign_order(key_path(KID, world.buyers), token, q["quote_id"])
    result = world.svc.place_order(q["quote_id"], token, "more milk", agent_signature=signature)
    assert result["status"] == "confirmed", result


def test_budget_and_delivery_days(client, world):
    res = client.put("/api/accounts/cafe/mandate",
                     json={"budget": {"period": "week", "max_eur": 600},
                           "delivery": {"days": ["FRI", "MON", "MON"]}})
    assert res.status_code == 200, res.text
    m = res.json()["mandate"]
    assert m["budget"] == {"period": "week", "max_eur": 600}
    assert m["delivery"] == {"days": ["MON", "FRI"]}
    [row] = _updates(world.conn)
    assert "budget none → €600.00 per week" in row["reason"]
    assert "delivery days any day → Monday, Friday" in row["reason"]

    res = client.put("/api/accounts/cafe/mandate", json={"budget": None, "delivery": {"days": []}})
    assert res.status_code == 200, res.text
    m = res.json()["mandate"]
    assert "budget" not in m and "delivery" not in m
    res = client.put(f"/api/accounts/{KID}/mandate", json={"delivery": None})
    assert "delivery" not in res.json()["mandate"]


@pytest.mark.parametrize("body,words", [
    ({"budget": {"period": "day", "max_eur": 600}}, "period of week or month"),
    ({"budget": {"period": "week", "max_eur": 0}}, "above zero"),
    ({"budget": {"max_eur": 600}}, "period of week or month"),
    ({"budget": {"period": "week", "max_eur": 100}}, "cannot be less than the limit per order"),
    ({"delivery": {"days": ["XYZ"]}}, "delivery.days"),
])
def test_rejects_bad_budget_and_days(client, world, body, words):
    res = client.put("/api/accounts/cafe/mandate", json=body)
    assert res.status_code == 400
    assert res.json()["code"] == "bad_mandate"
    assert words in res.json()["message"]
    assert _updates(world.conn) == []


@pytest.mark.parametrize("body", [{"budget": {"limit": 1}}, {"delivery": {"note": "back door"}},
                                  {"agent_key": "x"}, {"budget": 5},
                                  {"usual_orders": "40 L milk"},
                                  {"usual_orders": [{"category": "10400", "amount": 40, "content_unit": "L",
                                                     "every": "week", "price": 1}]}])
def test_new_fields_that_are_not_editable(client, world, body):
    res = client.put(f"/api/accounts/{KID}/mandate", json=body)
    assert res.status_code == 400 and res.json()["code"] == "bad_field"


def test_onboarded_key_that_does_not_match_is_refused(client, world):
    path = world.buyers / KID / "mandate.jwt"
    token = path.read_text()
    (world.buyers / KID / "buyer_key.pem").write_text(signing.private_pem(signing.generate_key()))
    res = client.put(f"/api/accounts/{KID}/mandate", json={"budget": {"max_eur": 1000}})
    assert res.status_code == 409 and res.json()["code"] == "key_mismatch"
    assert path.read_text() == token
    assert _updates(world.conn) == []


# Usual orders: the mandate holds the amounts, the profile the plain names. One PUT changes both.


def _profile(world, buyer_id: str) -> dict:
    return json.loads((world.buyers / buyer_id / "profile.json").read_text())


def test_usual_orders_change_in_the_mandate_and_the_profile(client, world):
    order = {"what": "lactose-free milk, 1 L", "category": "10400", "amount": 60,
             "content_unit": "L", "every": "week", "on": "THU"}
    res = client.put(f"/api/accounts/{KID}/mandate", json={"usual_orders": [order]})
    assert res.status_code == 200, res.text
    assert res.json()["mandate_verified"] is True
    m = res.json()["mandate"]
    assert m["mandate_id"] == f"mnd_{KID}_002"
    assert m["usual_orders"] == [{"category": "10400", "amount": 60, "content_unit": "L",
                                  "every": "week", "on": "THU"}]
    assert _profile(world, KID)["usual_orders"] == [{"what": "lactose-free milk, 1 L", "amount": 60,
                                                     "unit": "L", "every": "week", "on": "THU"}]
    [row] = _updates(world.conn)
    assert ("usual orders 40 L of Milk and sour milk every week → "
            "60 L of Milk and sour milk every week on Thursday") in row["reason"]


def test_renaming_a_usual_order_changes_only_the_profile(client, world):
    token = (world.buyers / KID / "mandate.jwt").read_text()
    order = {"what": "oat-free milk", "category": "10400", "amount": 40, "content_unit": "L", "every": "week"}
    res = client.put(f"/api/accounts/{KID}/mandate", json={"usual_orders": [order]})
    assert res.status_code == 200, res.text
    assert res.json()["mandate"]["mandate_id"] == f"mnd_{KID}_001"
    assert (world.buyers / KID / "mandate.jwt").read_text() == token
    assert _profile(world, KID)["usual_orders"][0]["what"] == "oat-free milk"
    assert _updates(world.conn) == []


def test_no_usual_orders_removes_them_from_both(client, world):
    res = client.put(f"/api/accounts/{KID}/mandate", json={"usual_orders": []})
    assert res.status_code == 200, res.text
    assert "usual_orders" not in res.json()["mandate"]
    assert _profile(world, KID)["usual_orders"] == []
    [row] = _updates(world.conn)
    assert "→ none" in row["reason"]


def test_usual_order_without_a_name_is_named_after_its_category(client, world):
    order = {"category": "10400", "amount": 50, "content_unit": "L", "every": "month", "on": 15}
    assert client.put(f"/api/accounts/{KID}/mandate", json={"usual_orders": [order]}).status_code == 200
    assert _profile(world, KID)["usual_orders"] == [{"what": "Milk and sour milk", "amount": 50,
                                                     "unit": "L", "every": "month", "on": 15}]


def test_demo_buyer_gets_usual_orders_but_no_profile(client, world):
    order = {"what": "milk", "category": "10400", "amount": 20, "content_unit": "L", "every": "week"}
    res = client.put("/api/accounts/cafe/mandate", json={"usual_orders": [order]})
    assert res.status_code == 200, res.text
    assert res.json()["mandate"]["usual_orders"] == [{"category": "10400", "amount": 20,
                                                      "content_unit": "L", "every": "week"}]
    assert not (world.buyers / "cafe").exists()


def _usual(**change) -> dict:
    return {"usual_orders": [{"what": "milk", "category": "10400", "amount": 40, "content_unit": "L",
                              "every": "week", **change}]}


@pytest.mark.parametrize("body,words", [
    (_usual(amount=0), "amount above zero"),
    (_usual(content_unit="box"), "L or KG"),
    (_usual(every="day"), "every week or every month"),
    (_usual(on="XYZ"), "pick a day of the week"),
    (_usual(every="month", on=40), "1 to 31"),
    (_usual(category="99999"), "unknown category"),
    ({**_usual(category="10401"), "auto_approve": {"allowed_categories": ["10400"]}}, "may not buy"),
    ({"auto_approve": {"allowed_categories": ["10401"]}}, "may not buy"),
])
def test_rejects_bad_usual_orders(client, world, body, words):
    token = (world.buyers / KID / "mandate.jwt").read_text()
    profile = _profile(world, KID)
    res = client.put(f"/api/accounts/{KID}/mandate", json=body)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "bad_mandate"
    assert words in res.json()["message"]
    assert (world.buyers / KID / "mandate.jwt").read_text() == token
    assert _profile(world, KID) == profile
    assert _updates(world.conn) == []


# A kitchen that tightens its rules must not be bound only by agents that restart: once a new
# version is signed, an agent still holding the old one is refused.

def test_the_old_mandate_stops_working_once_a_new_version_is_signed(client, world):
    # The first edit rotates a demo buyer's key; the second reuses it, so only the id tells.
    assert client.put("/api/accounts/cafe/mandate",
                      json={"auto_approve": {"max_order_eur": 600}}).status_code == 200
    old_token = (world.mandates / "cafe.jwt").read_text()
    assert client.put("/api/accounts/cafe/mandate",
                      json={"auto_approve": {"max_order_eur": 450}}).status_code == 200
    with pytest.raises(MandateError) as refused:
        verify_mandate(old_token, world.conn, date.today())
    assert refused.value.code == "mandate_replaced"
    assert "mnd_cafe_kallio_003" in str(refused.value)
    verify_mandate((world.mandates / "cafe.jwt").read_text(), world.conn, date.today())


def test_an_onboarded_kitchens_old_mandate_stops_working_after_an_edit(client, world):
    path = world.buyers / KID / "mandate.jwt"
    old_token = path.read_text()
    assert client.put(f"/api/accounts/{KID}/mandate",
                      json={"auto_approve": {"max_order_eur": 120}}).status_code == 200
    with pytest.raises(MandateError) as refused:
        verify_mandate(old_token, world.conn, date.today())
    assert refused.value.code == "mandate_replaced"
    verify_mandate(path.read_text(), world.conn, date.today())
