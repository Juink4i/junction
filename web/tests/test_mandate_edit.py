"""The buyer edits its own mandate; web/ signs it with the buyer's key and registers it."""

from datetime import date

import pytest

from server import audit
from server.mandate import verify_mandate


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
    assert account["mandate"]["auto_approve"] == {"max_order_eur": 600, "max_line_eur": 400,
                                                  "allowed_categories": ["10400"]}
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
