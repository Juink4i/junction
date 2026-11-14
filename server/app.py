"""MCP server "valio-aimo-trade": six tools plus plain HTTP for the screens."""

import importlib
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from server import auth
from server.db import connect
from server.mandate import MandateError
from server.service import Buyer, Service
from server.unusual import DecisionsScorer

mcp = MCPServer(
    "valio-aimo-trade",
    instructions=(
        "Buy from Valio Aimo. Connect with the buyer's signed mandate as a bearer token. Search, "
        "then request a quote, then place the order. The server decides whether an order goes through."
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
        scorer = None if os.environ.get("DECISIONS_API") == "off" else DecisionsScorer()
        _service = Service(connect(), load_catalog(), lambda: datetime.now(timezone.utc), scorer,
                           require_enrolment_code=os.environ.get("ENROLMENT_CODES") == "on")
    return _service


def use_service(replacement: Service | None) -> None:
    global _service
    _service = replacement


def _token(ctx: Context) -> str | None:
    """The mandate this call was made with. Tests replace this: an in-process client has no headers."""
    return auth.bearer_token(ctx.headers)


def _connect(ctx: Context) -> tuple[Buyer | None, dict[str, Any] | None]:
    """(buyer, None), or (None, the refusal to return).

    Checked on every call, not only when connecting: a session can outlive a mandate.
    """
    try:
        return service().authenticate(_token(ctx)), None
    except MandateError as e:
        return None, auth.refusal(e.code, str(e))


def _mandate_problem(token: str | None) -> dict[str, Any] | None:
    try:
        service().authenticate(token)
    except MandateError as e:
        return auth.refusal(e.code, str(e))
    return None


class QuoteLineRequest(BaseModel):
    product_id: str
    amount: float
    unit: Literal["L", "KG"]


@mcp.tool()
def search_products(ctx: Context, product: str | None = None, must_have: list[str] | None = None,
                    amount: float | None = None,
                    unit: Literal["L", "KG"] | None = None) -> dict[str, Any]:
    """Find the products that fit a request. No prices here; use request_quote for those.

    Say what is needed in plain words. product is the kind of product, for example "milk" or
    "lactose-free milk". must_have lists properties every product must have, in plain words,
    for example ["lactose-free"]. You never need a catalog code. amount and unit ("L" or
    "KG") are optional and help leave out packs of the wrong size.

    The reply lists the products that fit, and the ones that were dropped with the reason for
    each. The buyer's mandate is applied: its own must-haves and allowed categories always
    count. If something is missing or not understood, the reply has status
    "needs_clarification" with a question and the list of known properties.
    """
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().search_products(buyer, product, must_have, amount, unit)


@mcp.tool()
def get_product(ctx: Context, product_id: str) -> dict[str, Any]:
    """Full details of one product: allergens, origin, labels, official substitutes.

    allergen_info_missing = true means the allergens are unknown, not that there are none.
    """
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().get_product(product_id, actor=buyer.actor)


@mcp.tool()
def request_quote(ctx: Context, lines: list[QuoteLineRequest], need_by: date) -> dict[str, Any]:
    """Price and delivery for the chosen products, as a signed quote valid for 15 minutes.

    amount is in litres ("L") or kilograms ("KG"); the server converts it to whole sales
    units. Prices are in euros without VAT unless the field says with_tax. stock
    "unconfirmed" means Valio Aimo gave no real stock figure. The stock hold is simulated.
    """
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().request_quote([line.model_dump() for line in lines], need_by, actor=buyer.actor)


@mcp.tool()
def place_order(ctx: Context, quote_id: str, mandate_token: str, rationale: str,
                confirm_unusual: bool = False, agent_signature: str | None = None) -> dict[str, Any]:
    """Place the order for a quote, using the buyer's signed mandate.

    Returns one status: confirmed, needs_clarification, pending_approval or rejected,
    always with plain-language reasons. Calling again with the same quote_id returns the
    same order.

    agent_signature is the agent's own signature over this order (quote_id, mandate_id,
    confirm_unusual). It is required when the mandate names an agent key, so a copy of the
    mandate alone cannot place orders.
    """
    _, refused = _connect(ctx)
    if refused:
        return refused
    return service().place_order(quote_id, mandate_token, rationale, confirm_unusual, agent_signature)


@mcp.tool()
def get_approval_status(ctx: Context, approval_id: str) -> dict[str, Any]:
    """Whether a human has decided on an order: pending, approved or rejected."""
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().get_approval_status(approval_id, actor=buyer.actor)


@mcp.tool()
def get_audit_log(ctx: Context, order_id: str | None = None,
                  quote_id: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """The plain-language decision trail for one order or quote. Give one of the two ids."""
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().get_audit_log(order_id, quote_id, actor=buyer.actor)


@mcp.custom_route("/mandate", methods=["GET"])
async def check_mandate(request: Request) -> JSONResponse:
    """Is this mandate accepted? The same check that guards /mcp, readable by any HTTP client.

    An MCP client only learns that its connection failed. This says why.
    """
    token = auth.bearer_token(request.headers)
    try:
        buyer = await run_in_threadpool(service().authenticate, token)
    except MandateError as e:
        return JSONResponse(auth.refusal(e.code, str(e)), status_code=401)
    return JSONResponse({"buyer_id": buyer.buyer_id, "buyer": buyer.name, "agent_id": buyer.actor,
                         "mandate_id": buyer.mandate["mandate_id"],
                         "valid_until": buyer.mandate["valid_until"]})


@mcp.custom_route("/buyers", methods=["POST"])
async def register_buyer(request: Request) -> JSONResponse:
    """A kitchen registers its public key and signed mandate. Not an MCP tool, on purpose."""
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        body = {}
    status, result = service().register_buyer(body.get("public_pem"), body.get("mandate_token"),
                                              body.get("enrolment_code"))
    return JSONResponse(result, status_code=status)


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
    app.add_middleware(auth.RequireMandate, check=_mandate_problem)
    # Added last, so it wraps the mandate check and a refusal still carries CORS headers.
    # The approval and log pages are served from another port.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    return app
