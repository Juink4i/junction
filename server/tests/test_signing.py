import copy
from datetime import date, datetime, timedelta, timezone

import pytest

from server import signing
from server.db import connect
from server.mandate import MandateError, verify_mandate
from server.make_mandate import DEMO_MANDATES, issue_demo_mandates

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
BODY = {
    "quote_id": "q_1",
    "lines": [{
        "product_id": "464201", "name": "Milk 1 L", "units": 10, "sales_unit": "1 L",
        "covers": 10.0, "content_unit": "L", "unit_price_eur": 1.56, "line_total_eur": 15.6,
        "available_date": "2026-11-16", "cutoff_passed": False, "stock": "unconfirmed",
    }],
    "total_eur": 15.6,
    "total_with_tax_eur": 17.71,
    "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
}


@pytest.fixture
def key():
    return signing.generate_key()


@pytest.fixture
def quote(key):
    return {**BODY, "signature": signing.sign_quote(BODY, date(2026, 11, 16), key)}


def test_signed_quote_verifies_and_gives_back_need_by(key, quote):
    assert signing.check_quote(quote, key.public_key(), NOW) == date(2026, 11, 16)


def test_signature_is_an_ed25519_jws(quote):
    import jwt
    assert jwt.get_unverified_header(quote["signature"])["alg"] == "EdDSA"


@pytest.mark.parametrize("change", [
    lambda q: q.update(total_eur=1.0),
    lambda q: q.update(total_with_tax_eur=1.0),
    lambda q: q.update(quote_id="q_2"),
    lambda q: q.update(expires_at=(NOW + timedelta(days=1)).isoformat()),
    lambda q: q["lines"][0].update(units=1000),
    lambda q: q["lines"][0].update(unit_price_eur=0.01),
    lambda q: q["lines"][0].update(product_id="463038"),
    lambda q: q["lines"][0].update(cutoff_passed=True),
    lambda q: q["lines"][0].update(available_date="2026-11-15"),
    lambda q: q["lines"].append(dict(q["lines"][0])),
])
def test_any_changed_field_breaks_the_quote(key, quote, change):
    tampered = copy.deepcopy(quote)
    change(tampered)
    with pytest.raises(signing.QuoteError, match="changed"):
        signing.check_quote(tampered, key.public_key(), NOW)


def test_quote_signed_by_another_key_is_refused(quote):
    with pytest.raises(signing.QuoteError):
        signing.check_quote(quote, signing.generate_key().public_key(), NOW)


def test_quote_is_refused_after_15_minutes(key, quote):
    signing.check_quote(quote, key.public_key(), NOW + timedelta(minutes=14, seconds=59))
    with pytest.raises(signing.QuoteError, match="expired"):
        signing.check_quote(quote, key.public_key(), NOW + timedelta(minutes=15, seconds=1))


def test_server_key_is_created_once_and_reused():
    conn = connect(":memory:")
    first = signing.public_pem(signing.server_key(conn).public_key())
    assert signing.public_pem(signing.server_key(conn).public_key()) == first


# Mandates

TODAY = date(2026, 11, 14)


@pytest.fixture
def conn():
    return connect(":memory:")


def test_demo_mandates_for_hotel_cafe_and_school_verify(conn):
    tokens = issue_demo_mandates(conn)
    assert set(tokens) == {"hotel", "cafe", "school"}
    buyer_id, mandate = verify_mandate(tokens["hotel"], conn, TODAY)
    assert buyer_id == "hotel"
    assert mandate["auto_approve"]["max_order_eur"] == 1500
    assert mandate == DEMO_MANDATES["hotel"]


def test_expired_mandate_is_rejected(conn):
    tokens = issue_demo_mandates(conn)
    verify_mandate(tokens["hotel"], conn, date(2026, 12, 31))
    with pytest.raises(MandateError, match="expired"):
        verify_mandate(tokens["hotel"], conn, date(2027, 1, 1))


def test_mandate_with_a_changed_payload_is_rejected(conn):
    import base64, json
    token = issue_demo_mandates(conn)["hotel"]
    header, payload, sig = token.split(".")
    mandate = json.loads(base64.urlsafe_b64decode(payload + "=="))
    mandate["auto_approve"]["max_order_eur"] = 1_000_000
    forged = base64.urlsafe_b64encode(json.dumps(mandate).encode()).rstrip(b"=").decode()
    with pytest.raises(MandateError, match="signature"):
        verify_mandate(f"{header}.{forged}.{sig}", conn, TODAY)


def test_mandate_signed_by_an_unregistered_key_is_rejected(conn):
    issue_demo_mandates(conn)
    token = signing.sign(DEMO_MANDATES["hotel"], signing.generate_key(), kid="hotel")
    with pytest.raises(MandateError, match="signature"):
        verify_mandate(token, conn, TODAY)


def test_mandate_from_an_unknown_buyer_is_rejected(conn):
    token = signing.sign(DEMO_MANDATES["hotel"], signing.generate_key(), kid="stranger")
    with pytest.raises(MandateError, match="not registered"):
        verify_mandate(token, conn, TODAY)


def test_garbage_token_is_rejected(conn):
    with pytest.raises(MandateError):
        verify_mandate("x.y.z", conn, TODAY)


def test_unsigned_alg_none_token_is_rejected(conn):
    import jwt
    issue_demo_mandates(conn)
    token = jwt.encode(DEMO_MANDATES["hotel"], None, algorithm="none", headers={"kid": "hotel"})
    with pytest.raises(MandateError):
        verify_mandate(token, conn, TODAY)


def signed(conn, **changes):
    """A hotel mandate with some fields changed, properly signed by a registered buyer."""
    import copy
    key = signing.generate_key()
    conn.execute("INSERT INTO buyers (buyer_id, name, public_pem) VALUES ('odd', 'Odd', ?)",
                 (signing.public_pem(key.public_key()),))
    mandate = copy.deepcopy(DEMO_MANDATES["hotel"])
    for path, value in changes.items():
        target = mandate
        *parents, leaf = path.split("__")
        for parent in parents:
            target = target[parent]
        target[leaf] = value
    return signing.sign(mandate, key, kid="odd")


@pytest.mark.parametrize("changes", [
    {"mandate_id": None},
    {"buyer": ""},
    {"agent_id": 7},
    {"auto_approve": None},
    {"auto_approve__max_order_eur": "1500"},
    {"auto_approve__max_order_eur": float("nan")},
    {"auto_approve__max_order_eur": float("inf")},
    {"auto_approve__max_order_eur": -1},
    {"auto_approve__max_order_eur": True},
    {"auto_approve__max_line_eur": "800"},
    {"auto_approve__allowed_categories": "10400"},
    {"auto_approve__allowed_categories": [10400]},
    {"hard_rules": None},
    {"hard_rules__blocked_allergens": "AE"},
    {"hard_rules__blocked_allergens": None},
    {"hard_rules__unknown_allergens": "Human"},
    {"hard_rules__unknown_allergens": None},
    {"substitution": None},
    {"substitution__must_keep": "FREE_FROM_LACTOSE"},
    {"approvers": "boss@hotel.example"},
])
def test_signed_mandate_with_a_badly_shaped_field_is_rejected(conn, changes):
    with pytest.raises(MandateError):
        verify_mandate(signed(conn, **changes), conn, TODAY)


def test_signed_mandate_without_optional_parts_is_accepted(conn):
    import copy
    key = signing.generate_key()
    conn.execute("INSERT INTO buyers (buyer_id, name, public_pem) VALUES ('min', 'Min', ?)",
                 (signing.public_pem(key.public_key()),))
    mandate = copy.deepcopy(DEMO_MANDATES["hotel"])
    del mandate["substitution"], mandate["approvers"], mandate["auto_approve"]["allowed_categories"]
    assert verify_mandate(signing.sign(mandate, key, kid="min"), conn, TODAY)[1] == mandate
