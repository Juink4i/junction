"""Registration: a kitchen sends its public key and its signed mandate (POST /buyers)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from starlette.testclient import TestClient

from server import app as server_app
from server import audit, fake_catalog, signing
from server.app import build_http_app
from server.db import connect
from server.service import Service

MANDATE = {
    "mandate_id": "mnd_aurinko-3f2a_001",
    "buyer": "Päiväkoti Aurinko",
    "agent_id": "agent-aurinko-3f2a",
    "valid_until": "2027-11-14",
    "auto_approve": {"max_order_eur": 100, "allowed_categories": ["10400"]},
    "substitution": {"allowed": True, "must_keep": ["FREE_FROM_LACTOSE"], "max_price_increase_pct": 10},
    "hard_rules": {"blocked_allergens": [], "unknown_allergens": "human",
                   "no_delivery_after": "need_by_date"},
    "budget": {"period": "week", "max_eur": 150},
    "usual_orders": [{"category": "10400", "amount": 40, "content_unit": "L", "every": "week"}],
    "approvers": ["kitchen.lead@aurinko.example"],
}


class Clock:
    def __init__(self):
        self.time = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)  # a Saturday

    def __call__(self):
        return self.time

    def forward(self, **delta):
        self.time += timedelta(**delta)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(clock):
    return Service(connect(":memory:"), fake_catalog, clock)


def signed(mandate=MANDATE, kid="aurinko-3f2a", key=None):
    """(public_pem, mandate_token), signed by a fresh key unless one is given."""
    key = key or signing.generate_key()
    if kid is None:  # a token with no buyer id at all; PyJWT will not sign kid=None
        token = jwt.encode(mandate, key, algorithm=signing.ALGORITHM)
    else:
        token = signing.sign(mandate, key, kid=kid)
    return signing.public_pem(key.public_key()), token


def milk(svc, litres, need_by="2026-11-16"):
    return svc.request_quote([{"product_id": "464201", "amount": litres, "unit": "L"}], need_by)


def buyers(svc):
    return [row["buyer_id"] for row in svc.conn.execute("SELECT buyer_id FROM buyers")]


def test_registration_is_accepted_and_logged(svc):
    status, body = svc.register_buyer(*signed())
    assert status == 201
    assert body == {"buyer_id": "aurinko-3f2a", "mandate_id": "mnd_aurinko-3f2a_001",
                    "status": "registered"}
    assert buyers(svc) == ["aurinko-3f2a"]
    entry = audit.entries(svc.conn)[-1]
    assert entry["action"] == "register_buyer"
    assert "Päiväkoti Aurinko" in entry["reason"] and "40 L" in entry["reason"]
    assert audit.verify(svc.conn) == {"ok": True}


def test_a_registered_kitchen_can_order_straight_away(svc):
    public_pem, token = signed()
    svc.register_buyer(public_pem, token)
    result = svc.place_order(milk(svc, 40)["quote_id"], token, "Weekly milk")
    assert result["status"] == "confirmed"


def test_a_buyer_id_cannot_be_registered_twice(svc):
    first_pem, first_token = signed()
    svc.register_buyer(first_pem, first_token)
    status, body = svc.register_buyer(*signed())  # same id, another key
    assert (status, body["code"]) == (409, "buyer_exists")
    assert set(body) == {"code", "message", "retryable"}
    # The first key still works, so nobody took the buyer over.
    assert svc.place_order(milk(svc, 40)["quote_id"], first_token, "Weekly milk")["status"] == "confirmed"


def test_a_mandate_signed_by_another_key_is_refused(svc):
    public_pem, _ = signed()
    _, token = signed()
    status, body = svc.register_buyer(public_pem, token)
    assert (status, body["code"]) == (400, "mandate_invalid")
    assert "signature" in body["message"]
    assert buyers(svc) == []


@pytest.mark.parametrize("kid", ["Bad Id!", "ab", "UPPER-case", None])
def test_a_bad_buyer_id_is_refused(svc, kid):
    status, body = svc.register_buyer(*signed(kid=kid))
    assert (status, body["code"]) == (400, "mandate_invalid")


def test_an_expired_mandate_is_refused(svc):
    status, body = svc.register_buyer(*signed({**MANDATE, "valid_until": "2026-11-13"}))
    assert (status, body["code"]) == (400, "mandate_invalid")
    assert "expired" in body["message"]


def test_a_key_that_is_not_ed25519_is_refused(svc):
    _, token = signed()
    status, body = svc.register_buyer("not a key", token)
    assert (status, body["code"]) == (400, "bad_key")


@pytest.mark.parametrize("public_pem, token", [(None, "x"), ("x", None), ("", ""), (5, "x")])
def test_missing_fields_are_a_bad_request(svc, public_pem, token):
    status, body = svc.register_buyer(public_pem, token)
    assert (status, body["code"]) == (400, "bad_request")


@pytest.mark.parametrize("part, value", [
    ("budget", {"period": "year", "max_eur": 150}),
    ("budget", {"period": "week", "max_eur": 0}),
    ("budget", "150 a week"),
    ("usual_orders", [{"category": "10400", "amount": -1, "content_unit": "L", "every": "week"}]),
    ("usual_orders", [{"category": "10400", "amount": 40, "content_unit": "pints", "every": "week"}]),
    ("usual_orders", {"category": "10400"}),
    ("delivery", {"days": ["FUNDAY"]}),
    ("delivery", {"days": []}),
    ("delivery", "MON"),
])
def test_a_typo_in_a_new_mandate_part_is_refused(svc, part, value):
    status, body = svc.register_buyer(*signed({**MANDATE, part: value}))
    assert (status, body["code"]) == (400, "mandate_invalid")
    assert part in body["message"]


def test_declared_usual_orders_make_a_big_first_order_go_to_a_person(svc):
    public_pem, token = signed()
    svc.register_buyer(public_pem, token)
    result = svc.place_order(milk(svc, 240)["quote_id"], token, "Party")  # more than 5 x 40 L
    assert result["status"] == "pending_approval"
    assert "40 L" in " ".join(result["reasons"])


def test_a_kitchen_without_usual_orders_registers_too(svc):
    mandate = {k: v for k, v in MANDATE.items() if k != "usual_orders"}
    status, _ = svc.register_buyer(*signed(mandate))
    assert status == 201
    assert "No usual orders" in audit.entries(svc.conn)[-1]["reason"]


@pytest.fixture
def http(svc):
    server_app.use_service(svc)
    yield TestClient(build_http_app())
    server_app.use_service(None)


def test_post_buyers_over_http(http):
    public_pem, token = signed()
    body = {"public_pem": public_pem, "mandate_token": token}
    created = http.post("/buyers", json=body)
    assert created.status_code == 201
    assert created.json()["buyer_id"] == "aurinko-3f2a"
    assert http.post("/buyers", json=body).status_code == 409
    garbage = http.post("/buyers", content=b"not json")
    assert garbage.status_code == 400
    assert garbage.json()["code"] == "bad_request"


# Budget per week or month


def registered(svc):
    public_pem, token = signed()
    svc.register_buyer(public_pem, token)
    return token


def test_a_second_order_in_the_same_week_goes_over_the_weekly_budget(svc):
    token = registered(svc)  # €100 per order, €150 per week
    first = svc.place_order(milk(svc, 60)["quote_id"], token, "Weekly milk")  # €93.60
    assert first["status"] == "confirmed"
    second = svc.place_order(milk(svc, 60)["quote_id"], token, "More milk")  # €187.20 this week
    assert second["status"] == "pending_approval"
    assert any("weekly budget of €150.00" in r for r in second["reasons"])


def test_the_budget_starts_again_the_next_week(svc, clock):
    token = registered(svc)
    svc.place_order(milk(svc, 60)["quote_id"], token, "Weekly milk")
    clock.forward(days=7)
    again = svc.place_order(milk(svc, 60, need_by="2026-11-23")["quote_id"], token, "Weekly milk")
    assert again["status"] == "confirmed"


def test_an_order_waiting_for_approval_counts_and_a_rejected_one_does_not(svc):
    token = registered(svc)
    big = svc.place_order(milk(svc, 100)["quote_id"], token, "Big order")  # €156, over both limits
    assert big["status"] == "pending_approval"
    waiting = svc.place_order(milk(svc, 60)["quote_id"], token, "Weekly milk")
    assert waiting["status"] == "pending_approval"
    for approval in svc.list_approvals():
        svc.decide_approval(approval["approval_id"], approve=False)
    after = svc.place_order(milk(svc, 60)["quote_id"], token, "Weekly milk")
    assert after["status"] == "confirmed"


# Enrolment code: tie a registration to a customer Valio Aimo already knows

from server.make_mandate import DEMO_CUSTOMERS, seed_demo_customers  # noqa: E402

CUSTOMER_NO, CUSTOMER_NAME, CODE = DEMO_CUSTOMERS[0]


@pytest.fixture
def strict(clock):
    svc = Service(connect(":memory:"), fake_catalog, clock, require_enrolment_code=True)
    seed_demo_customers(svc.conn)
    return svc


@pytest.mark.parametrize("code", [None, "", "WRONG-CODE", 12345])
def test_registration_without_a_known_enrolment_code_is_refused(strict, code):
    status, body = strict.register_buyer(*signed(), enrolment_code=code)
    assert (status, body["code"]) == (403, "enrolment_code_invalid")
    assert buyers(strict) == []


def test_a_known_enrolment_code_ties_the_buyer_to_the_customer(strict):
    status, body = strict.register_buyer(*signed(), enrolment_code=CODE)
    assert status == 201 and body["customer_no"] == CUSTOMER_NO
    assert f"customer {CUSTOMER_NO}" in audit.entries(strict.conn)[-1]["reason"]


def test_the_name_on_valio_aimos_record_wins_over_the_name_in_the_mandate(strict):
    strict.register_buyer(*signed({**MANDATE, "buyer": "Hotel Chain Oy"}), enrolment_code=CODE)
    assert strict.conn.execute("SELECT name FROM buyers").fetchone()["name"] == CUSTOMER_NAME


def test_without_the_requirement_no_code_is_needed(svc):
    assert svc.register_buyer(*signed())[0] == 201


def test_post_buyers_passes_the_enrolment_code_on(strict):
    server_app.use_service(strict)
    try:
        public_pem, token = signed()
        body = {"public_pem": public_pem, "mandate_token": token}
        client = TestClient(build_http_app())
        assert client.post("/buyers", json=body).status_code == 403
        assert client.post("/buyers", json={**body, "enrolment_code": CODE}).status_code == 201
    finally:
        server_app.use_service(None)


def test_an_order_arriving_on_the_wrong_weekday_goes_to_a_person(svc):
    public_pem, token = signed({**MANDATE, "delivery": {"days": ["TUE", "THU"]}})
    svc.register_buyer(public_pem, token)
    result = svc.place_order(milk(svc, 40)["quote_id"], token, "Weekly milk")  # arrives Monday
    assert result["status"] == "pending_approval"
    assert any("Tuesday and Thursday only" in r for r in result["reasons"])
