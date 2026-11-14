import pytest

from agent.mcp_link import TradeLink, TradeServerUnreachable

SIX_TOOLS = {"search_products", "get_product", "request_quote", "place_order",
             "get_approval_status", "get_audit_log"}


async def test_server_offers_the_six_contract_tools(fake):
    async with TradeLink(fake.mcp_url) as link:
        assert SIX_TOOLS <= set(await link.tool_names())


async def test_list_results_come_back_as_lists(fake):
    async with TradeLink(fake.mcp_url) as link:
        found = await link.call("search_products", {"text": "milk", "category": "10400",
                                                    "must_have_tags": ["FREE_FROM_LACTOSE"]})
    assert isinstance(found, list)
    assert "464201" in {p["id"] for p in found}


async def test_tool_errors_become_structured_errors(fake):
    async with TradeLink(fake.mcp_url) as link:
        res = await link.call("get_product", {"product_id": "nope"})
    assert res == {"error": {"code": "not_found", "message": "No product nope.", "retryable": False}}


async def test_unreachable_server_gives_a_clear_error():
    with pytest.raises(TradeServerUnreachable, match="127.0.0.1:9"):
        async with TradeLink("http://127.0.0.1:9/mcp"):
            pass


async def test_a_refused_mandate_raises_with_the_servers_reason():
    import pytest
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from agent.mcp_link import MandateRefused
    from demo.servers import run_in_thread

    async def mandate(request):
        assert request.headers["authorization"] == "Bearer old-token"
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
