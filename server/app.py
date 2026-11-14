"""MCP server "valio-aimo-trade": six tools plus plain HTTP for the screens.

SKELETON: quotes, orders, approvals and the log return fixed fake data.
"""

from dataclasses import asdict
from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from server import fake_catalog as catalog

mcp = MCPServer(
    "valio-aimo-trade",
    instructions=(
        "Buy from Valio Aimo. Search, then request a quote, then place the order with the "
        "buyer's signed mandate. The server decides whether an order goes through."
    ),
)


class QuoteLineRequest(BaseModel):
    product_id: str
    amount: float
    unit: Literal["L", "KG"]


def error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


FAKE_QUOTE = {
    "quote_id": "q_demo",
    "lines": [
        {
            "product_id": "464201",
            "name": "Lactose-free skimmed milk drink 1 L",
            "units": 1000,
            "sales_unit": "1 L",
            "covers": 1000.0,
            "content_unit": "L",
            "unit_price_eur": 1.56,
            "line_total_eur": 1560.0,
            "available_date": "2026-11-16",
            "cutoff_passed": False,
            "stock": "unconfirmed",
        }
    ],
    "total_eur": 1560.0,
    "total_with_tax_eur": 1770.6,
    "expires_at": "2026-11-14T10:15:00+00:00",
    "signature": "fake.skeleton.signature",
}
FAKE_ORDER_RESULT = {
    "status": "pending_approval",
    "order_id": "ord_demo",
    "approval_id": "apr_demo",
    "reasons": ["The order total of €1,560.00 is over the mandate's limit of €1,500.00."],
}
FAKE_APPROVAL = {
    "approval_id": "apr_demo",
    "order_id": "ord_demo",
    "status": "pending",
    "buyer": "Hotel Chain Oy / Helsinki Central",
    "total_eur": 1560.0,
    "reasons": FAKE_ORDER_RESULT["reasons"],
    "lines": FAKE_QUOTE["lines"],
}
FAKE_LOG = [
    {
        "seq": 1,
        "time": "2026-11-14T10:00:00+00:00",
        "actor": "buyer-agent-01",
        "action": "request_quote",
        "reason": "Quoted 1,000 × Lactose-free skimmed milk drink 1 L for €1,560.00.",
        "prev_hash": "0" * 64,
        "hash": "a" * 64,
    },
    {
        "seq": 2,
        "time": "2026-11-14T10:00:05+00:00",
        "actor": "policy",
        "action": "decision:pending_approval",
        "reason": FAKE_ORDER_RESULT["reasons"][0],
        "prev_hash": "a" * 64,
        "hash": "b" * 64,
    },
]


@mcp.tool()
def search_products(text: str, category: str | None = None,
                    must_have_tags: list[str] | None = None) -> list[dict[str, Any]]:
    """Search the Valio Aimo product file by text, category code and tags.

    Static data only: no prices or stock. Example: category "10400" (milk) with
    must_have_tags ["FREE_FROM_LACTOSE"].
    """
    return [asdict(p) for p in catalog.search_products(text, category, must_have_tags or [])]


@mcp.tool()
def get_product(product_id: str) -> dict[str, Any]:
    """Full details of one product: allergens, origin, labels, official substitutes.

    allergen_info_missing = true means the allergens are unknown, not that there are none.
    """
    product = catalog.get_product(product_id)
    if product is None:
        return error("product_not_found", f"No product with id {product_id}.")
    return asdict(product)


@mcp.tool()
def request_quote(lines: list[QuoteLineRequest], need_by: date) -> dict[str, Any]:
    """Price and delivery for the chosen products, as a signed quote valid for 15 minutes.

    amount is in litres ("L") or kilograms ("KG"); the server converts it to whole sales
    units. All prices are in euros without VAT unless the field says with_tax.
    """
    return FAKE_QUOTE


@mcp.tool()
def place_order(quote_id: str, mandate_token: str, rationale: str,
                confirm_unusual: bool = False) -> dict[str, Any]:
    """Place the order for a quote, using the buyer's signed mandate.

    Returns one status: confirmed, needs_clarification, pending_approval or rejected,
    always with plain-language reasons. Calling again with the same quote_id returns the
    same order.
    """
    return FAKE_ORDER_RESULT


@mcp.tool()
def get_approval_status(approval_id: str) -> dict[str, Any]:
    """Whether a human has decided on an order: pending, approved or rejected."""
    return {"status": "pending"}


@mcp.tool()
def get_audit_log(order_id: str | None = None, quote_id: str | None = None) -> list[dict[str, Any]]:
    """The plain-language decision trail for one order or quote."""
    return FAKE_LOG


@mcp.custom_route("/approvals", methods=["GET"])
async def list_approvals(request: Request) -> JSONResponse:
    return JSONResponse([FAKE_APPROVAL])


@mcp.custom_route("/approvals/{approval_id}/approve", methods=["POST"])
async def approve(request: Request) -> JSONResponse:
    return JSONResponse({"status": "approved", "decided_by": "human", "decided_at": FAKE_LOG[1]["time"]})


@mcp.custom_route("/approvals/{approval_id}/reject", methods=["POST"])
async def reject(request: Request) -> JSONResponse:
    return JSONResponse({"status": "rejected", "decided_by": "human", "decided_at": FAKE_LOG[1]["time"]})


@mcp.custom_route("/log", methods=["GET"])
async def full_log(request: Request) -> JSONResponse:
    return JSONResponse(FAKE_LOG)


@mcp.custom_route("/log/verify", methods=["GET"])
async def verify_log(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def build_http_app() -> Starlette:
    app = mcp.streamable_http_app()
    # The approval and log pages are served from another port.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    return app
