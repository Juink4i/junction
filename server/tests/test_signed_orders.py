"""Orders signed by the agent: a copy of the mandate alone cannot place an order."""

import pytest

from server import audit, fake_catalog, signing
from server.db import connect
from server.service import Service
from server.tests.test_register import MANDATE, Clock, milk, signed

AGENT_ID = MANDATE["agent_id"]


@pytest.fixture
def svc():
    return Service(connect(":memory:"), fake_catalog, Clock())


def register(svc, agent_key=None):
    """Register the kitchen, naming the agent's key in the mandate if one is given."""
    mandate = dict(MANDATE)
    if agent_key is not None:
        mandate["agent_key"] = signing.public_pem(agent_key.public_key())
    public_pem, token = signed(mandate)
    assert svc.register_buyer(public_pem, token)[0] == 201
    return token


def order_signature(agent_key, quote_id, confirm_unusual=False, mandate_id=MANDATE["mandate_id"]):
    payload = {"quote_id": quote_id, "mandate_id": mandate_id, "confirm_unusual": confirm_unusual}
    return signing.sign(payload, agent_key, kid=AGENT_ID)


def orders(svc):
    return svc.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


def test_an_order_signed_by_the_agent_is_accepted_and_the_log_says_so(svc):
    agent_key = signing.generate_key()
    token = register(svc, agent_key)
    quote_id = milk(svc, 40)["quote_id"]
    result = svc.place_order(quote_id, token, "Weekly milk",
                             agent_signature=order_signature(agent_key, quote_id))
    assert result["status"] == "confirmed"
    placed = [e for e in audit.entries(svc.conn) if e["action"] == "place_order"][-1]
    assert "signed by the agent key named in the mandate" in placed["reason"]


def test_a_copied_mandate_without_the_agents_signature_is_rejected(svc):
    agent_key = signing.generate_key()
    token = register(svc, agent_key)
    quote_id = milk(svc, 40)["quote_id"]
    stolen = svc.place_order(quote_id, token, "Weekly milk")
    assert stolen["status"] == "rejected"
    assert "agent key" in stolen["reasons"][0]
    assert orders(svc) == 0  # the quote was not used up
    genuine = svc.place_order(quote_id, token, "Weekly milk",
                              agent_signature=order_signature(agent_key, quote_id))
    assert genuine["status"] == "confirmed"


@pytest.mark.parametrize("forge", [
    lambda key, quote_id: order_signature(signing.generate_key(), quote_id),           # another key
    lambda key, quote_id: order_signature(key, "q_someone_elses"),                     # another quote
    lambda key, quote_id: order_signature(key, quote_id, mandate_id="mnd_other_001"),  # another mandate
    lambda key, quote_id: order_signature(key, quote_id, confirm_unusual=True),        # flipped flag
    lambda key, quote_id: "garbage",
    lambda key, quote_id: 12345,
])
def test_a_signature_that_does_not_match_this_order_is_rejected(svc, forge):
    agent_key = signing.generate_key()
    token = register(svc, agent_key)
    quote_id = milk(svc, 40)["quote_id"]
    result = svc.place_order(quote_id, token, "Weekly milk", agent_signature=forge(agent_key, quote_id))
    assert result["status"] == "rejected"
    assert orders(svc) == 0


def test_confirming_an_unusual_amount_needs_a_signature_over_the_confirmation(svc):
    agent_key = signing.generate_key()
    token = register(svc, agent_key)
    quote_id = milk(svc, 240)["quote_id"]  # more than 5 x the usual 40 L
    asked = svc.place_order(quote_id, token, "Party",
                            agent_signature=order_signature(agent_key, quote_id))
    assert asked["status"] == "needs_clarification"
    replayed = svc.place_order(quote_id, token, "Party", confirm_unusual=True,
                               agent_signature=order_signature(agent_key, quote_id))
    assert replayed["status"] == "rejected"
    confirmed = svc.place_order(quote_id, token, "Party", confirm_unusual=True,
                                agent_signature=order_signature(agent_key, quote_id, confirm_unusual=True))
    assert confirmed["status"] == "pending_approval"


def test_a_mandate_without_an_agent_key_ignores_the_signature_input(svc):
    token = register(svc)
    result = svc.place_order(milk(svc, 40)["quote_id"], token, "Weekly milk", agent_signature="garbage")
    assert result["status"] == "confirmed"


def test_a_mandate_with_an_unreadable_agent_key_is_refused_at_registration(svc):
    status, body = svc.register_buyer(*signed({**MANDATE, "agent_key": "not a key"}))
    assert (status, body["code"]) == (400, "mandate_invalid")
    assert "agent_key" in body["message"]
