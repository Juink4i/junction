"""Only a registered kitchen's agent may call /mcp. Tested over real HTTP, with a real MCP client."""

import time
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from agent.identity import ensure_agent_key, key_path, sign_order, session_token
from agent.mcp_link import MandateRefused, TradeLink, TradeServerRefused
from demo.servers import run_in_thread
from server import app as server_app
from server import audit, fake_catalog
from server.app import build_http_app
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.service import Service
from server.tests.kitchens import mcp_headers, register_kitchen

NEED_BY = (date.today() + timedelta(days=2)).isoformat()
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}


@pytest.fixture
def world(tmp_path):
    svc = Service(connect(tmp_path / "state.db"), fake_catalog, lambda: datetime.now(timezone.utc))
    demo_tokens = issue_demo_mandates(svc.conn)  # demo mandates without an agent key
    buyers = tmp_path / "buyers"
    aurinko = register_kitchen(svc, "aurinko-3f2a", "Päiväkoti Aurinko", buyers)
    sointu = register_kitchen(svc, "sointu-0001", "Café Sointu", buyers)
    server_app.use_service(svc)
    running = run_in_thread(build_http_app())

    class World:
        pass

    w = World()
    w.svc, w.demo_tokens, w.aurinko, w.sointu, w.buyers = svc, demo_tokens, aurinko, sointu, buyers
    w.base, w.mcp = running.base_url, f"{running.base_url}/mcp"
    yield w
    running.stop()
    server_app.use_service(None)


def post(world, headers=None):
    return httpx.post(world.mcp, json=INIT, timeout=10,
                      headers={"Accept": "application/json, text/event-stream", **(headers or {})})


def refusals(world):
    return world.svc.conn.execute(
        "SELECT * FROM log WHERE action = 'connect:refused' ORDER BY seq").fetchall()


def assert_refused(res, code):
    assert res.status_code == 401, res.text
    assert res.json()["code"] == code
    assert res.json()["retryable"] is False
    assert res.headers["www-authenticate"].startswith("Bearer")


def test_no_headers_is_refused(world):
    assert_refused(post(world), "agent_not_authenticated")
    assert_refused(post(world, {"X-Mandate": world.aurinko.mandate_token}), "agent_not_authenticated")
    [row] = refusals(world)[:1]
    assert row["actor"] == "unknown agent"


def test_a_mandate_without_an_agent_key_is_refused(world):
    key_file = key_path("hotel", world.buyers)
    ensure_agent_key("hotel", world.buyers)
    res = post(world, mcp_headers(world.demo_tokens["hotel"], key_file))
    assert_refused(res, "agent_key_missing")
    assert "Hotel Chain Oy" in refusals(world)[-1]["reason"]


def test_an_unregistered_kitchen_is_refused(world, tmp_path):
    other = register_kitchen(Service(connect(":memory:"), fake_catalog,
                                     lambda: datetime.now(timezone.utc)),
                             "stranger-0001", "Stranger", tmp_path / "elsewhere")
    res = post(world, other.headers())
    assert_refused(res, "mandate_not_accepted")
    assert "not registered" in res.json()["message"]


def test_a_token_signed_by_another_key_is_refused(world):
    # Sointu's agent key signs a token for Aurinko's mandate.
    token = session_token(world.sointu.agent_key_file, world.aurinko.mandate_token)
    res = post(world, {"X-Mandate": world.aurinko.mandate_token, "Authorization": f"Bearer {token}"})
    assert_refused(res, "agent_token_invalid")
    assert "not signed by the agent key" in res.json()["message"]


def test_an_expired_token_is_refused(world):
    res = post(world, world.aurinko.headers(now=time.time() - 20 * 60, ttl_s=600))
    assert_refused(res, "agent_token_invalid")
    assert "expired" in res.json()["message"]


def _crafted(world, **claims):
    key = serialization.load_pem_private_key(world.aurinko.agent_key_file.read_bytes(), password=None)
    now = int(time.time())
    payload = {"aud": "valio-aimo-trade", "mandate_id": world.aurinko.mandate["mandate_id"],
               "iat": now, "exp": now + 600, **claims}
    payload = {k: v for k, v in payload.items() if v is not None}
    token = jwt.encode(payload, key, algorithm="EdDSA",
                       headers={"kid": world.aurinko.mandate["agent_id"]})
    return post(world, {"X-Mandate": world.aurinko.mandate_token, "Authorization": f"Bearer {token}"})


@pytest.mark.parametrize("claims,words", [
    ({"aud": "someone-else"}, "not meant for valio-aimo-trade"),
    ({"aud": None}, "audience"),
    ({"mandate_id": "mnd_aurinko-3f2a_000"}, "different mandate"),
    ({"exp": int(time.time()) + 3600}, "more than 15 minutes"),
    ({"iat": int(time.time()) + 600, "exp": int(time.time()) + 900}, "future"),
])
def test_bad_token_claims_are_refused(world, claims, words):
    res = _crafted(world, **claims)
    assert_refused(res, "agent_token_invalid")
    assert words in res.json()["message"]


def test_a_minute_of_clock_difference_is_allowed(world):
    now = int(time.time())
    assert _crafted(world, iat=now + 30, exp=now + 600).status_code == 200


async def test_a_registered_agent_can_use_the_tools_under_its_own_name(world):
    async with TradeLink(world.mcp, mandate_token=world.aurinko.mandate_token,
                         agent_key_file=world.aurinko.agent_key_file) as link:
        found = await link.call("search_products", {"product": "milk"})
        assert "464201" in {p["id"] for p in found["products"]}
        await link.call("get_product", {"product_id": "464201"})
        quote = await _quote(link, 40)
        signature = sign_order(world.aurinko.agent_key_file, world.aurinko.mandate_token,
                               quote["quote_id"])
        result = await link.call("place_order", {
            "quote_id": quote["quote_id"], "rationale": "weekly milk", "agent_signature": signature})
        assert result["status"] == "confirmed", result
    rows = world.svc.conn.execute(
        "SELECT actor, action FROM log WHERE action IN "
        "('search_products', 'get_product', 'request_quote', 'place_order')").fetchall()
    assert {r["actor"] for r in rows} == {"agent-aurinko-3f2a"}
    assert {r["action"] for r in rows} == {"search_products", "get_product", "request_quote",
                                           "place_order"}


async def test_another_kitchens_agent_cannot_sign_this_kitchens_order(world):
    async with TradeLink(world.mcp, mandate_token=world.aurinko.mandate_token,
                         agent_key_file=world.aurinko.agent_key_file) as link:
        quote = await _quote(link, 20)
        # A valid signature, but from Sointu's agent: not the key Aurinko's mandate names.
        signature = sign_order(world.sointu.agent_key_file, world.aurinko.mandate_token,
                               quote["quote_id"])
        result = await link.call("place_order", {
            "quote_id": quote["quote_id"], "rationale": "sneaky", "agent_signature": signature})
    assert result["status"] == "rejected"
    assert world.svc.conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0


async def _quote(link, litres):
    """The first option request_quote offers for product 464201."""
    options = await link.call("request_quote", {"product_ids": ["464201"], "amount": litres,
                                                "unit": "L", "need_by": NEED_BY})
    return options["options"][0]["quote"]


async def _order(world, kitchen, litres):
    """kitchen's agent quotes and orders; returns (quote, result)."""
    async with TradeLink(world.mcp, mandate_token=kitchen.mandate_token,
                         agent_key_file=kitchen.agent_key_file) as link:
        quote = await _quote(link, litres)
        signature = sign_order(kitchen.agent_key_file, kitchen.mandate_token, quote["quote_id"])
        result = await link.call("place_order", {
            "quote_id": quote["quote_id"], "rationale": "test", "agent_signature": signature})
    return quote, result


async def _as(world, kitchen, tool, args):
    async with TradeLink(world.mcp, mandate_token=kitchen.mandate_token,
                         agent_key_file=kitchen.agent_key_file) as link:
        return await link.call(tool, args)


async def test_an_agent_reads_only_its_own_kitchens_audit_log(world):
    quote, result = await _order(world, world.aurinko, 40)
    own = await _as(world, world.aurinko, "get_audit_log", {"order_id": result["order_id"]})
    assert len(own) >= 2
    # Another kitchen's agent gets exactly what an unknown id gets: nothing.
    unknown = await _as(world, world.sointu, "get_audit_log", {"order_id": "ord_does_not_exist"})
    for args in ({"order_id": result["order_id"]}, {"quote_id": quote["quote_id"]},
                 {"order_id": "ord_does_not_exist", "quote_id": quote["quote_id"]}):
        assert await _as(world, world.sointu, "get_audit_log", args) == unknown == []


async def test_an_agent_reads_its_own_quote_before_ordering_but_not_anothers(world):
    async with TradeLink(world.mcp, mandate_token=world.aurinko.mandate_token,
                         agent_key_file=world.aurinko.agent_key_file) as link:
        quote = await _quote(link, 40)
        assert await link.call("get_audit_log", {"quote_id": quote["quote_id"]})
    assert await _as(world, world.sointu, "get_audit_log", {"quote_id": quote["quote_id"]}) == []


async def test_an_agent_sees_only_its_own_kitchens_approvals(world):
    _, result = await _order(world, world.aurinko, 2000)  # over €500 per order: needs a person
    assert result["status"] == "pending_approval", result
    own = await _as(world, world.aurinko, "get_approval_status", {"approval_id": result["approval_id"]})
    assert own["status"] == "pending"
    # The agent's link hands tool errors back as {"error": {code, message, retryable}}.
    other = (await _as(world, world.sointu, "get_approval_status",
                       {"approval_id": result["approval_id"]}))["error"]
    missing = (await _as(world, world.sointu, "get_approval_status",
                         {"approval_id": "apr_does_not_exist"}))["error"]
    assert other["code"] == missing["code"] == "approval_not_found"
    assert other["message"] == missing["message"].replace("apr_does_not_exist", result["approval_id"])


async def test_a_refused_agent_gets_a_clear_error(world):
    ensure_agent_key("hotel", world.buyers)
    with pytest.raises(TradeServerRefused, match="agent_key_missing"):
        async with TradeLink(world.mcp, mandate_token=world.demo_tokens["hotel"],
                             agent_key_file=key_path("hotel", world.buyers)):
            pass
    # No mandate at all: the agent's own check of /mandate stops it first, with the reason.
    with pytest.raises(MandateRefused) as refused:
        async with TradeLink(world.mcp):
            pass
    assert refused.value.code == "mandate_missing"


def test_refusals_are_logged_without_tokens_and_the_chain_holds(world):
    post(world)
    token = session_token(world.sointu.agent_key_file, world.aurinko.mandate_token)
    post(world, {"X-Mandate": world.aurinko.mandate_token, "Authorization": f"Bearer {token}"})
    post(world, {"X-Mandate": "not-a-token", "Authorization": "Bearer nope"})
    rows = refusals(world)
    assert len(rows) == 3
    for row in rows:
        assert row["actor"] == "unknown agent"
        assert token not in row["reason"] and world.aurinko.mandate_token not in row["reason"]
        assert "eyJ" not in row["reason"]
    assert audit.verify(world.svc.conn) == {"ok": True}


def test_screens_and_registration_stay_open(world):
    assert httpx.get(f"{world.base}/approvals").status_code == 200
    assert httpx.get(f"{world.base}/log").status_code == 200
    assert httpx.get(f"{world.base}/log/verify").json() == {"ok": True}
    res = httpx.post(f"{world.base}/buyers", json={})
    assert res.status_code == 400 and res.json()["code"] == "bad_request"
