"""Contract B, through a real MCP client and the HTTP endpoints."""

from datetime import datetime, timedelta, timezone

import pytest
from mcp import Client
from starlette.testclient import TestClient

from server import app as server_app
from server import fake_catalog
from server.app import build_http_app, mcp
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.service import Service

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
NEED_BY = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def tokens():
    svc = Service(connect(":memory:"), fake_catalog, lambda: datetime.now(timezone.utc))
    server_app.use_service(svc)
    yield issue_demo_mandates(svc.conn)
    server_app.use_service(None)


async def call(client, name, **args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content
    data = result.structured_content
    return data["result"] if set(data) == {"result"} else data


async def quote_milk(client, litres):
    return await call(client, "request_quote", need_by=NEED_BY,
                      lines=[{"product_id": "464201", "amount": litres, "unit": "L"}])


async def test_server_name_and_exactly_six_tools():
    assert mcp.name == "valio-aimo-trade"
    async with Client(mcp) as client:
        listed = await client.list_tools()
    assert {t.name for t in listed.tools} == TOOLS


async def test_tool_inputs_match_the_contract():
    async with Client(mcp) as client:
        tools = {t.name: t.input_schema for t in (await client.list_tools()).tools}
    inputs = {name: (set(s["properties"]), set(s.get("required", []))) for name, s in tools.items()}
    assert inputs == {
        "search_products": ({"text", "category", "must_have_tags"}, {"text"}),
        "get_product": ({"product_id"}, {"product_id"}),
        "request_quote": ({"lines", "need_by"}, {"lines", "need_by"}),
        "place_order": ({"quote_id", "mandate_token", "rationale", "confirm_unusual"},
                        {"quote_id", "mandate_token", "rationale"}),
        "get_approval_status": ({"approval_id"}, {"approval_id"}),
        "get_audit_log": ({"order_id", "quote_id"}, set()),
    }


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
        quote = await quote_milk(client, 1000)
    assert set(quote) == QUOTE_KEYS
    assert all(set(line) == LINE_KEYS for line in quote["lines"])
    assert quote["lines"][0]["stock"] in {"confirmed", "unconfirmed"}
    assert quote["total_eur"] == 1560.0


async def test_order_approval_and_log_flow(tokens):
    async with Client(mcp) as client:
        quote = await quote_milk(client, 1000)
        order = await call(client, "place_order", quote_id=quote["quote_id"],
                           mandate_token=tokens["hotel"], rationale="Best on-time option")
        assert set(order) == {"status", "order_id", "approval_id", "reasons"}
        assert order["status"] == "pending_approval"

        status = await call(client, "get_approval_status", approval_id=order["approval_id"])
        assert status == {"status": "pending"}

        http = TestClient(build_http_app())
        (listed,) = http.get("/approvals").json()
        assert listed["approval_id"] == order["approval_id"]
        approved = http.post(f"/approvals/{order['approval_id']}/approve")
        assert approved.status_code == 200
        assert http.post(f"/approvals/{order['approval_id']}/reject").status_code == 409
        assert http.post("/approvals/apr_missing/approve").status_code == 404
        assert http.get("/approvals").json() == []

        status = await call(client, "get_approval_status", approval_id=order["approval_id"])
        assert set(status) == {"status", "decided_by", "decided_at"}
        assert status["status"] == "approved"

        entries = await call(client, "get_audit_log", order_id=order["order_id"])
        assert all(set(e) == LOG_KEYS for e in entries)
        assert [e["action"] for e in entries] == [
            "request_quote", "place_order", "decision:pending_approval", "approval:approved"]


async def test_log_verify_endpoint_finds_a_row_edited_by_hand():
    async with Client(mcp) as client:
        await quote_milk(client, 10)
        await quote_milk(client, 20)
    http = TestClient(build_http_app())
    assert all(set(e) == LOG_KEYS for e in http.get("/log").json())
    assert http.get("/log/verify").json() == {"ok": True}
    server_app.service().conn.execute("UPDATE log SET reason = 'edited' WHERE seq = 1")
    assert http.get("/log/verify").json() == {"ok": False, "broken_at_seq": 1}


def test_a_broken_real_catalog_is_an_error_not_a_silent_fallback(tmp_path, monkeypatch):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "api.py").write_text("import a_dependency_that_is_missing\n")
    monkeypatch.setattr(server_app, "REPO_ROOT", tmp_path)
    with pytest.raises(ImportError):
        server_app.load_catalog()


def test_fake_catalog_is_used_while_the_real_one_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(server_app, "REPO_ROOT", tmp_path)
    assert server_app.load_catalog() is fake_catalog
