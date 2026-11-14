"""MCP server "valio-aimo-trade": six tools plus plain HTTP for the screens."""

import importlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.db import connect
from server.service import Service

mcp = MCPServer(
    "valio-aimo-trade",
    instructions=(
        "Buy from Valio Aimo. Search, then request a quote, then place the order with the "
        "buyer's signed mandate. The server decides whether an order goes through."
    ),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_service: Service | None = None


def load_catalog() -> Any:
    # Fall back only while Runner 1's file is absent. A broken real catalog must fail loudly.
    if (REPO_ROOT / "catalog" / "api.py").exists():
        return importlib.import_module("catalog.api")
    from server import fake_catalog
    return fake_catalog


def service() -> Service:
    global _service
    if _service is None:
        _service = Service(connect(), load_catalog(), lambda: datetime.now(timezone.utc))
    return _service


def use_service(replacement: Service | None) -> None:
    global _service
    _service = replacement


def _actor(ctx: Context) -> str:
    try:
        return ctx.session.client_params.client_info.name or "agent"
    except AttributeError:
        return "agent"


class QuoteLineRequest(BaseModel):
    product_id: str
    amount: float
    unit: Literal["L", "KG"]


@mcp.tool()
def search_products(ctx: Context, text: str, category: str | None = None,
                    must_have_tags: list[str] | None = None) -> list[dict[str, Any]]:
    """Search the Valio Aimo product file by text, category code and tags.

    Static data only: no prices or stock. Example: category "10400" (milk) with
    must_have_tags ["FREE_FROM_LACTOSE"].
    """
    return service().search_products(text, category, must_have_tags, actor=_actor(ctx))


@mcp.tool()
def get_product(ctx: Context, product_id: str) -> dict[str, Any]:
    """Full details of one product: allergens, origin, labels, official substitutes.

    allergen_info_missing = true means the allergens are unknown, not that there are none.
    """
    return service().get_product(product_id, actor=_actor(ctx))


@mcp.tool()
def request_quote(ctx: Context, lines: list[QuoteLineRequest], need_by: date) -> dict[str, Any]:
    """Price and delivery for the chosen products, as a signed quote valid for 15 minutes.

    amount is in litres ("L") or kilograms ("KG"); the server converts it to whole sales
    units. Prices are in euros without VAT unless the field says with_tax. stock
    "unconfirmed" means Valio Aimo gave no real stock figure. The stock hold is simulated.
    """
    return service().request_quote([line.model_dump() for line in lines], need_by, actor=_actor(ctx))


@mcp.tool()
def place_order(quote_id: str, mandate_token: str, rationale: str,
                confirm_unusual: bool = False) -> dict[str, Any]:
    """Place the order for a quote, using the buyer's signed mandate.

    Returns one status: confirmed, needs_clarification, pending_approval or rejected,
    always with plain-language reasons. Calling again with the same quote_id returns the
    same order.
    """
    return service().place_order(quote_id, mandate_token, rationale, confirm_unusual)


@mcp.tool()
def get_approval_status(ctx: Context, approval_id: str) -> dict[str, Any]:
    """Whether a human has decided on an order: pending, approved or rejected."""
    return service().get_approval_status(approval_id, actor=_actor(ctx))


@mcp.tool()
def get_audit_log(ctx: Context, order_id: str | None = None,
                  quote_id: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """The plain-language decision trail for one order or quote. Give one of the two ids."""
    return service().get_audit_log(order_id, quote_id, actor=_actor(ctx))


@mcp.custom_route("/approvals", methods=["GET"])
async def list_approvals(request: Request) -> JSONResponse:
    return JSONResponse(service().list_approvals())


async def _decide(request: Request, approve: bool) -> JSONResponse:
    try:
        decided_by = (await request.json()).get("decided_by")
    except Exception:
        decided_by = None
    result = service().decide_approval(request.path_params["approval_id"], approve, decided_by)
    status = {"approval_not_found": 404, "already_decided": 409}.get(result.get("code"), 200)
    return JSONResponse(result, status_code=status)


@mcp.custom_route("/approvals/{approval_id}/approve", methods=["POST"])
async def approve(request: Request) -> JSONResponse:
    return await _decide(request, approve=True)


@mcp.custom_route("/approvals/{approval_id}/reject", methods=["POST"])
async def reject(request: Request) -> JSONResponse:
    return await _decide(request, approve=False)


@mcp.custom_route("/log", methods=["GET"])
async def full_log(request: Request) -> JSONResponse:
    return JSONResponse(service().full_log())


@mcp.custom_route("/log/verify", methods=["GET"])
async def verify_log(request: Request) -> JSONResponse:
    return JSONResponse(service().verify_log())


def build_http_app() -> Starlette:
    app = mcp.streamable_http_app()
    # The approval and log pages are served from another port.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    return app
