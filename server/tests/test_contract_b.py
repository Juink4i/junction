"""Contract B: tool names and the shape of every tool's output."""

import pytest
from mcp import Client
from starlette.testclient import TestClient

from server.app import build_http_app, mcp

pytestmark = pytest.mark.anyio

TOOLS = {
    "search_products",
    "get_product",
    "request_quote",
    "place_order",
    "get_approval_status",
    "get_audit_log",
}
SUMMARY_KEYS = {"id", "name_en", "name_fi", "category", "sales_unit", "tags", "labels"}
PRODUCT_KEYS = SUMMARY_KEYS | {
    "allergens_contains",
    "allergens_may_contain",
    "allergens_free_from",
    "allergen_info_missing",
    "vendor",
    "country",
    "description",
    "carbon_kg_per_kg",
    "delivery_reliability",
    "official_substitutes",
}
QUOTE_KEYS = {"quote_id", "lines", "total_eur", "total_with_tax_eur", "expires_at", "signature"}
LINE_KEYS = {
    "product_id",
    "name",
    "units",
    "sales_unit",
    "covers",
    "content_unit",
    "unit_price_eur",
    "line_total_eur",
    "available_date",
    "cutoff_passed",
    "stock",
}
LOG_KEYS = {"seq", "time", "actor", "action", "reason", "prev_hash", "hash"}
STATUSES = {"confirmed", "needs_clarification", "pending_approval", "rejected"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(client, name, **args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content
    data = result.structured_content
    return data["result"] if set(data) == {"result"} else data


async def test_server_name_and_exactly_six_tools():
    assert mcp.name == "valio-aimo-trade"
    async with Client(mcp) as client:
        listed = await client.list_tools()
    assert {t.name for t in listed.tools} == TOOLS


async def test_search_products_returns_product_summaries():
    async with Client(mcp) as client:
        found = await call(
            client, "search_products", text="milk", category="10400",
            must_have_tags=["FREE_FROM_LACTOSE"],
        )
    assert found
    assert all(set(p) == SUMMARY_KEYS for p in found)


async def test_get_product_returns_product():
    async with Client(mcp) as client:
        product = await call(client, "get_product", product_id="464201")
    assert set(product) == PRODUCT_KEYS


async def test_get_product_unknown_id_returns_structured_error():
    async with Client(mcp) as client:
        error = await call(client, "get_product", product_id="nope")
    assert set(error) == {"code", "message", "retryable"}


async def test_request_quote_returns_quote():
    async with Client(mcp) as client:
        quote = await call(
            client, "request_quote",
            lines=[{"product_id": "464201", "amount": 1000, "unit": "L"}],
            need_by="2026-11-16",
        )
    assert set(quote) == QUOTE_KEYS
    assert quote["lines"]
    assert all(set(line) == LINE_KEYS for line in quote["lines"])
    assert all(line["stock"] in {"confirmed", "unconfirmed"} for line in quote["lines"])


async def test_place_order_returns_order_result():
    async with Client(mcp) as client:
        result = await call(
            client, "place_order", quote_id="q_demo", mandate_token="x.y.z",
            rationale="Cheapest on-time lactose-free milk",
        )
    assert result["status"] in STATUSES
    assert isinstance(result["reasons"], list) and result["reasons"]
    assert set(result) <= {"status", "order_id", "approval_id", "question", "reasons"}


async def test_get_approval_status_returns_status():
    async with Client(mcp) as client:
        status = await call(client, "get_approval_status", approval_id="apr_demo")
    assert status["status"] in {"pending", "approved", "rejected"}
    assert set(status) <= {"status", "decided_by", "decided_at"}


async def test_get_audit_log_returns_log_entries():
    async with Client(mcp) as client:
        entries = await call(client, "get_audit_log", quote_id="q_demo")
    assert entries
    assert all(set(e) == LOG_KEYS for e in entries)


def test_http_endpoints_for_the_screens():
    http = TestClient(build_http_app())
    approvals = http.get("/approvals")
    assert approvals.status_code == 200
    assert isinstance(approvals.json(), list)
    assert http.post("/approvals/apr_demo/approve").status_code == 200
    assert http.post("/approvals/apr_demo/reject").status_code == 200
    log = http.get("/log")
    assert all(set(e) == LOG_KEYS for e in log.json())
    assert http.get("/log/verify").json()["ok"] is True
