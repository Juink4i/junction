import httpx2
import jwt
import pytest

from agent.identity import ensure_agent_key, key_path
from agent.mcp_link import AgentCredentials, TradeLink, TradeServerUnreachable
from agent.tests.test_identity import mandate_token
from demo import fake_server
from demo.servers import run_in_thread

SIX_TOOLS = {"search_products", "get_product", "request_quote", "place_order",
             "get_approval_status", "get_audit_log"}


async def test_server_offers_the_six_contract_tools(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        assert SIX_TOOLS <= set(await link.tool_names())


async def test_results_come_back_as_plain_data(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        found = await link.call("search_products", {"product": "lactose-free milk"})
        entries = await link.call("get_audit_log", {})
    assert "464201" in {p["id"] for p in found["products"]}
    assert isinstance(entries, list)


async def test_tool_errors_become_structured_errors(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        res = await link.call("get_product", {"product_id": "nope"})
    assert res == {"error": {"code": "not_found", "message": "No product nope.", "retryable": False}}


async def test_unreachable_server_gives_a_clear_error():
    with pytest.raises(TradeServerUnreachable, match="127.0.0.1:9"):
        async with TradeLink("http://127.0.0.1:9/mcp"):
            pass


class HeaderRecorder:
    """Sits in front of the fake trade server and keeps the headers of every /mcp request."""

    def __init__(self, app):
        self.app, self.seen = app, []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            self.seen.append({k.decode().lower(): v.decode() for k, v in scope["headers"]})
        await self.app(scope, receive, send)


async def test_every_request_carries_the_mandate_and_a_session_token(tmp_path):
    ensure_agent_key("hotel", tmp_path)
    token = mandate_token("hotel")  # the fake maps kid "hotel" to its demo hotel
    tokens_seen = []
    recorder = HeaderRecorder(fake_server.app())
    running = run_in_thread(recorder)
    try:
        async with TradeLink(f"{running.base_url}/mcp", mandate_token=token,
                             agent_key_file=key_path("hotel", tmp_path),
                             on_token=tokens_seen.append) as link:
            await link.call("search_products", {"product": "milk"})
    finally:
        running.stop()
    assert len(recorder.seen) >= 2
    for headers in recorder.seen:
        assert headers["x-mandate"] == token
        bearer = headers["authorization"].removeprefix("Bearer ")
        assert jwt.decode(bearer, options={"verify_signature": False})["aud"] == "valio-aimo-trade"
    assert tokens_seen and all(t in [h["authorization"][7:] for h in recorder.seen] for t in tokens_seen)


def test_the_session_token_is_renewed_before_it_runs_out(tmp_path):
    ensure_agent_key("k-0000", tmp_path)
    clock = [1_800_000_000.0]
    made = []
    creds = AgentCredentials(mandate_token(), key_path("k-0000", tmp_path), ttl_s=600,
                             clock=lambda: clock[0], on_token=made.append)

    def bearer():
        request = httpx2.Request("POST", "http://trade/mcp")
        next(creds.auth_flow(request))
        return request.headers["authorization"]

    first = bearer()
    clock[0] += 500  # 100 s left: still fine
    assert bearer() == first
    clock[0] += 50   # 50 s left: renew
    second = bearer()
    assert second != first and len(made) == 2
    assert jwt.decode(second[7:], options={"verify_signature": False})["iat"] == 1_800_000_550


async def test_a_refused_mandate_raises_with_the_servers_reason():
    import pytest
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from agent.mcp_link import MandateRefused
    from demo.servers import run_in_thread

    async def mandate(request):
        assert request.headers["x-mandate"] == "old-token"
        return JSONResponse({"code": "mandate_expired", "message": "The mandate expired on 2026-01-01.",
                             "retryable": False, "onboarding_url": "http://localhost:8080/onboarding"},
                            status_code=401)

    running = run_in_thread(Starlette(routes=[Route("/mandate", mandate)]))
    try:
        with pytest.raises(MandateRefused) as refused:
            async with TradeLink(f"{running.base_url}/mcp", "old-token"):
                pass
    finally:
        running.stop()
    assert refused.value.code == "mandate_expired"
    assert "2026-01-01" in refused.value.message
    assert refused.value.onboarding_url == "http://localhost:8080/onboarding"
