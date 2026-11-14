"""MCP server "valio-aimo-trade": six tools plus plain HTTP for the screens."""

import importlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from server import auth, vocabulary
from server.db import connect
from server.mandate import MandateError
from server.seller import GeminiSeller, KeywordSeller
from server.service import Buyer, Service
from server.unusual import DecisionsScorer

mcp = MCPServer(
    "valio-aimo-trade",
    instructions=(
        "Buy from Valio Aimo. Search, then request a quote, then place the order. The server "
        "decides whether an order goes through. Only the agent of a registered kitchen may "
        "connect: every HTTP request carries the kitchen's signed mandate in X-Mandate and a "
        "short session token signed with the agent's own key in Authorization: Bearer."
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


def _seller() -> Any:
    """Gemini by default. SELLER=keyword forces the plain rules, for tests and rehearsals.

    Without a Gemini key the Gemini seller falls back to the keyword rules on every search.
    """
    if os.environ.get("SELLER") == "keyword":
        return KeywordSeller()
    return GeminiSeller(vocabulary.names)


def service() -> Service:
    global _service
    if _service is None:
        scorer = None if os.environ.get("DECISIONS_API") == "off" else DecisionsScorer()
        _service = Service(connect(), load_catalog(), lambda: datetime.now(timezone.utc), scorer,
                           require_enrolment_code=os.environ.get("ENROLMENT_CODES") == "on",
                           seller=_seller())
    return _service


def use_service(replacement: Service | None) -> None:
    global _service
    _service = replacement


def _token(ctx: Context) -> str | None:
    """The mandate this call was made with. Tests replace this: an in-process client has no headers."""
    return auth.mandate_token(ctx.headers)


def _connect(ctx: Context) -> tuple[Buyer | None, dict[str, Any] | None]:
    """(buyer, None), or (None, the refusal to return).

    AgentAuth already checked the agent's session token for this mandate. The mandate is
    checked again on every call, not only when connecting: a session can outlive a mandate.
    """
    try:
        return service().authenticate(_token(ctx)), None
    except MandateError as e:
        return None, auth.refusal(e.code, str(e))


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


class Preferences(BaseModel):
    """The buyer's own order of what matters. Preferences only order products that already fit."""
    priorities: list[str] | None = None  # any of: price, reliability, finnish, sustainability
    pack_size: Literal["small", "large"] | None = None


@mcp.tool()
def request_quote(ctx: Context, product_ids: list[str] | None = None, amount: float | None = None,
                  unit: Literal["L", "KG"] | None = None, need_by: str | None = None,
                  preferences: Preferences | None = None) -> dict[str, Any]:
    """Price the products from search_products and get ranked options to order.

    Give every product id the search returned, the amount needed in litres ("L") or kilograms
    ("KG"), and need_by as a date like 2026-11-16. The server converts the amount to whole
    sales units, prices each product and ranks them: on time first, then the buyer's
    preferences, or price, delivery date, reliability and sustainability.

    The reply lists up to five options, best first. Each option is its own signed quote, valid
    for 15 minutes, and says what the buyer's mandate would decide if it were ordered now.
    Order one with place_order and its quote_id. Products that cannot be offered are listed
    with the reason. Prices are in euros without VAT unless the field says with_tax. stock
    "unconfirmed" means Valio Aimo gave no real stock figure. The stock hold is simulated.
    """
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().request_quote(buyer, product_ids, amount, unit, need_by,
                                   preferences.model_dump() if preferences else None)


@mcp.tool()
def place_order(ctx: Context, quote_id: str, rationale: str,
                agent_signature: str | None = None) -> dict[str, Any]:
    """Place the order for one quote. The mandate shown when connecting is the one that counts.

    Returns one status: confirmed, pending_approval (a person must approve; check with
    get_approval_status) or rejected, always with plain-language reasons. Calling again with
    the same quote_id returns the same order.

    agent_signature is the agent's own signature over this order (quote_id and mandate_id).
    It is required when the mandate names an agent key, so a copy of the mandate alone
    cannot place orders.
    """
    return service().place_order(quote_id, _token(ctx) or "", rationale, agent_signature)


@mcp.tool()
def get_approval_status(ctx: Context, approval_id: str) -> dict[str, Any]:
    """Whether a human has decided on an order: pending, approved or rejected."""
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().get_approval_status(approval_id, actor=buyer.actor, caller=buyer.caller)


@mcp.tool()
def get_audit_log(ctx: Context, order_id: str | None = None,
                  quote_id: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """The plain-language decision trail for one order or quote. Give one of the two ids."""
    buyer, refused = _connect(ctx)
    if refused:
        return refused
    return service().get_audit_log(order_id, quote_id, actor=buyer.actor, caller=buyer.caller)


@mcp.custom_route("/mandate", methods=["GET"])
async def check_mandate(request: Request) -> JSONResponse:
    """Is this mandate accepted? The same check that guards /mcp, readable by any HTTP client.

    An MCP client only learns that its connection failed. This says why.
    """
    token = auth.mandate_token(request.headers)
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


MCP_PATH = "/mcp"


class AgentAuth:
    """Lets only a registered kitchen's agent reach /mcp. The other routes (/approvals, /log,
    POST /buyers) serve the screens and registration, and stay open.

    On failure: 401 with {code, message, retryable, onboarding_url} and WWW-Authenticate:
    Bearer. Service.authenticate_agent logs every refusal."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (scope["type"] != "http" or scope.get("method") == "OPTIONS"
                or not (path == MCP_PATH or path.startswith(MCP_PATH + "/"))):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        # In a thread: the check takes the service's lock, which a slow quote may hold.
        result = await anyio.to_thread.run_sync(service().authenticate_agent,
                                                auth.mandate_token(headers), auth.bearer_token(headers))
        if "code" in result:
            response = JSONResponse(auth.refusal(result["code"], result["message"]), status_code=401,
                                    headers={"WWW-Authenticate": 'Bearer realm="valio-aimo-trade"'})
            await response(scope, receive, send)
            return
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
