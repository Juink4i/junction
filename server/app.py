"""MCP server "valio-aimo-trade": six tools plus plain HTTP for the screens."""

import importlib
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from server.db import connect
from server.service import Service
from server.unusual import DecisionsScorer

mcp = MCPServer(
    "valio-aimo-trade",
    instructions=(
        "Buy from Valio Aimo. Search, then request a quote, then place the order with the "
        "buyer's signed mandate. The server decides whether an order goes through. "
        "Only the agent of a registered kitchen may connect: every HTTP request carries the "
        "kitchen's signed mandate in X-Mandate and a short session token signed with the "
        "agent's own key in Authorization: Bearer. An agent may only order for its own kitchen."
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


def _caller(ctx: Context) -> dict | None:
    """The agent AgentAuth let in for this HTTP request: {buyer_id, agent_id, mandate_id}.

    The SDK hands each tool the Starlette request that carried the call, and AgentAuth put
    the identity in that request's scope. None for in-process calls (tests), which have no
    HTTP request and never pass through AgentAuth."""
    try:
        request = ctx.request_context.request
    except (ValueError, AttributeError):
        return None
    caller = getattr(getattr(request, "state", None), "agent", None)
    return caller if isinstance(caller, dict) else None


def _actor(ctx: Context) -> str:
    caller = _caller(ctx)
    if caller:
        return caller["agent_id"]
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
def place_order(ctx: Context, quote_id: str, mandate_token: str, rationale: str,
                confirm_unusual: bool = False, agent_signature: str | None = None) -> dict[str, Any]:
    """Place the order for a quote, using the buyer's signed mandate.

    Returns one status: confirmed, needs_clarification, pending_approval or rejected,
    always with plain-language reasons. Calling again with the same quote_id returns the
    same order.

    agent_signature is the agent's own signature over this order (quote_id, mandate_id,
    confirm_unusual). It is required when the mandate names an agent key, so a copy of the
    mandate alone cannot place orders. An agent may only order for its own kitchen.
    """
    return service().place_order(quote_id, mandate_token, rationale, confirm_unusual, agent_signature,
                                 caller=_caller(ctx))


@mcp.tool()
def get_approval_status(ctx: Context, approval_id: str) -> dict[str, Any]:
    """Whether a human has decided on an order: pending, approved or rejected."""
    return service().get_approval_status(approval_id, actor=_actor(ctx), caller=_caller(ctx))


@mcp.tool()
def get_audit_log(ctx: Context, order_id: str | None = None,
                  quote_id: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """The plain-language decision trail for one order or quote. Give one of the two ids."""
    return service().get_audit_log(order_id, quote_id, actor=_actor(ctx), caller=_caller(ctx))


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


MCP_PATH = "/mcp"


class AgentAuth:
    """Lets only a registered kitchen's agent reach /mcp. The other routes (/approvals, /log,
    POST /buyers) serve the screens and registration, and stay open.

    On success the caller {buyer_id, agent_id, mandate_id} goes into the request scope's
    state, where the tools read it (see _caller). On failure: 401 with {code, message,
    retryable} and WWW-Authenticate: Bearer. Service.authenticate_agent logs every refusal."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (scope["type"] != "http" or scope.get("method") == "OPTIONS"
                or not (path == MCP_PATH or path.startswith(MCP_PATH + "/"))):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        authorization = headers.get("authorization", "")
        bearer = authorization[7:].strip() if authorization[:7].lower() == "bearer " else None
        result = await anyio.to_thread.run_sync(service().authenticate_agent,
                                                headers.get("x-mandate"), bearer)
        if "code" in result:
            response = JSONResponse(result, status_code=401,
                                    headers={"WWW-Authenticate": 'Bearer realm="valio-aimo-trade"'})
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["agent"] = result
        await self.app(scope, receive, send)


def build_http_app() -> Starlette:
    app = mcp.streamable_http_app()
    app.add_middleware(AgentAuth)
    # The approval and log pages are served from another port. CORS is added last, so it is
    # outermost and a refused request still carries CORS headers.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    return app
