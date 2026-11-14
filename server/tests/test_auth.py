"""The mandate is shown to connect: /mcp refuses without one, and every tool call checks again.

The agent's own session token is tested in test_agent_auth.py."""

from datetime import datetime, timezone

import pytest
from mcp import Client
from starlette.testclient import TestClient

from server import app as server_app
from server import auth, fake_catalog
from server.app import build_http_app, mcp
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.mandate import MandateError
from server.service import Service
from server.tests.kitchens import register_kitchen
from server.tests.test_register import Clock

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(clock):
    svc = Service(connect(":memory:"), fake_catalog, clock)
    server_app.use_service(svc)
    yield svc
    server_app.use_service(None)


@pytest.fixture
def tokens(svc):
    return issue_demo_mandates(svc.conn)


def test_bearer_token_is_read_from_the_authorization_header():
    assert auth.bearer_token({"authorization": "Bearer abc.def"}) == "abc.def"
    assert auth.bearer_token({"authorization": "bearer  abc "}) == "abc"
    assert auth.bearer_token({"authorization": "Basic abc"}) is None
    assert auth.bearer_token({}) is None
    assert auth.bearer_token(None) is None


def test_a_valid_mandate_identifies_the_buyer(svc, tokens):
    buyer = svc.authenticate(tokens["hotel"])
    assert (buyer.buyer_id, buyer.actor, buyer.name) == (
        "hotel", "buyer-agent-01", "Hotel Chain Oy / Helsinki Central")


@pytest.mark.parametrize("token, code", [
    (None, "mandate_missing"),
    ("", "mandate_missing"),
    ("not-a-token", "mandate_invalid"),
])
def test_a_missing_or_unreadable_mandate_is_refused_and_logged(svc, token, code):
    with pytest.raises(MandateError) as refused:
        svc.authenticate(token)
    assert refused.value.code == code
    assert svc.full_log()[-1]["action"] == "connect:refused"


def test_an_expired_mandate_has_its_own_code(svc, tokens, clock):
    clock.time = datetime(2027, 1, 2, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(MandateError) as refused:
        svc.authenticate(tokens["hotel"])
    assert refused.value.code == "mandate_expired"
    assert "2026-12-31" in str(refused.value)


def test_mcp_without_a_mandate_is_refused_with_the_onboarding_link(svc):
    response = TestClient(build_http_app()).post("/mcp", json={})
    assert response.status_code == 401
    body = response.json()
    assert (body["code"], body["retryable"]) == ("agent_not_authenticated", False)
    assert body["onboarding_url"].endswith("/onboarding")
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_mandate_endpoint_says_who_the_mandate_belongs_to(svc, tokens):
    http = TestClient(build_http_app())
    ok = http.get("/mandate", headers={"X-Mandate": tokens["cafe"]})
    assert ok.status_code == 200
    assert ok.json() == {"buyer_id": "cafe", "buyer": "Café Kallio", "agent_id": "buyer-agent-02",
                         "mandate_id": "mnd_cafe_kallio_001", "valid_until": "2026-12-31"}
    refused = http.get("/mandate", headers={"X-Mandate": "nope"})
    assert (refused.status_code, refused.json()["code"]) == (401, "mandate_invalid")


def test_the_screens_need_no_mandate(svc):
    http = TestClient(build_http_app())
    assert http.get("/approvals").status_code == 200
    assert http.get("/log/verify").json() == {"ok": True}


async def test_a_tool_call_without_a_mandate_gets_the_refusal(svc):
    async with Client(mcp) as client:  # in-process: no headers at all
        result = await client.call_tool("get_product", {"product_id": "464201"})
    assert result.structured_content["code"] == "mandate_missing"
    assert result.structured_content["onboarding_url"].endswith("/onboarding")


async def test_a_mandate_that_expires_mid_session_fails_the_next_call(svc, tokens, clock, monkeypatch):
    monkeypatch.setattr(server_app, "_token", lambda ctx: tokens["hotel"])
    async with Client(mcp) as client:
        first = await client.call_tool("get_product", {"product_id": "464201"})
        clock.time = datetime(2027, 1, 2, 10, 0, tzinfo=timezone.utc)
        second = await client.call_tool("get_product", {"product_id": "464201"})
    assert first.structured_content["id"] == "464201"
    assert second.structured_content["code"] == "mandate_expired"


async def test_the_log_names_the_mandates_agent(svc, tokens, monkeypatch):
    monkeypatch.setattr(server_app, "_token", lambda ctx: tokens["hotel"])
    async with Client(mcp) as client:
        await client.call_tool("get_product", {"product_id": "464201"})
    assert svc.full_log()[-1]["actor"] == "buyer-agent-01"


async def test_the_headers_reach_a_tool_over_real_http(svc, clock, tmp_path):
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    from demo.servers import run_in_thread

    running = run_in_thread(build_http_app())
    try:
        kitchen = register_kitchen(svc, "aurinko-3f2a", "Päiväkoti Aurinko", tmp_path)
        headers = kitchen.headers(now=clock.time.timestamp())
        async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
            async with Client(streamable_http_client(f"{running.base_url}/mcp", http_client=http)) as client:
                result = await client.call_tool("get_product", {"product_id": "464201"})
        assert not result.is_error
    finally:
        running.stop()
    assert svc.full_log()[-1]["actor"] == "agent-aurinko-3f2a"
