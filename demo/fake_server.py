"""A stand-in for Runner 2's MCP server, so the bot and screens can be built first.

It follows Contract B in docs/runner-tasks.md: the same six tools, the same shapes,
and the same HTTP endpoints for the approval and log pages. Its rules are a small
copy of the ones in the plan, good enough for development and tests. The real
server (server/) replaces it: start that one on port 8000 instead.

Run:  uv run python -m demo.fake_server            (http://localhost:8000/mcp)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_FILE = ROOT / "data" / "overrides.json"
QUOTE_TTL = timedelta(minutes=15)
TAX_RATE = 0.135
_SIGNING_KEY = b"fake-server-demo-key"  # The real server signs with Ed25519.

# --- Catalog --------------------------------------------------------------------------
# Product ids match the real file where the plan names them (464201, 465039, 463038,
# 464179). The rest are made up to reproduce the traps: coffee milk, latte, low-lactose
# milk, sour milk, chocolate milk, oat drink and a bread mix all look like a match.

PRODUCTS: dict[str, dict[str, Any]] = {
    "464201": dict(name_en="Valio lactose-free semi-skimmed milk drink 1 L",
                   name_fi="Valio laktoositon kevytmaitojuoma 1 l", category="10400",
                   sales_unit="PCE", content=1.0, unit_price=1.56, lead_days=1, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=["Finnish product"], carbon=1.3, reliability=0.98,
                   official_substitutes=["464179"], allergens=["MILK"]),
    "465039": dict(name_en="Lactose-free milk drink 1.5% 5 L bag-in-box",
                   name_fi="Laktoositon maitojuoma 1,5 % 5 l", category="10400",
                   sales_unit="PCE", content=5.0, unit_price=6.85, lead_days=1, cutoff_passed=True,
                   tags=["FREE_FROM_LACTOSE"], labels=[], carbon=1.3, reliability=0.91,
                   official_substitutes=[], allergens=["MILK"]),
    "463038": dict(name_en="Lactose-free milk drink 1% 20 L",
                   name_fi="Laktoositon maitojuoma 1 % 20 l", category="10400",
                   sales_unit="PCE", content=20.0, unit_price=32.40, lead_days=4, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=[], carbon=1.3, reliability=0.87,
                   official_substitutes=[], allergens=["MILK"]),
    "464179": dict(name_en="Lactose-free milk drink 1% 10 L",
                   name_fi="Laktoositon maitojuoma 1 % 10 l", category="10400",
                   sales_unit="PCE", content=10.0, unit_price=15.80, lead_days=1, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=["Finnish product"], carbon=1.3, reliability=0.95,
                   official_substitutes=[], allergens=["MILK"]),
    "460101": dict(name_en="Valio lactose-free coffee milk 1 L",
                   name_fi="Valio laktoositon kahvimaito 1 l", category="10400",
                   sales_unit="PCE", content=1.0, unit_price=1.29, lead_days=2, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=[], carbon=1.5, reliability=0.97,
                   official_substitutes=[], allergens=["MILK"]),
    "460102": dict(name_en="Lactose-free caffe latte drink 0.25 L",
                   name_fi="Laktoositon caffe latte 0,25 l", category="10400",
                   sales_unit="PCE", content=0.25, unit_price=1.10, lead_days=2, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=[], carbon=1.6, reliability=0.96,
                   official_substitutes=[], allergens=["MILK"]),
    "460103": dict(name_en="Low-lactose milk 1 L",
                   name_fi="Vähälaktoosinen maito 1 l", category="10400",
                   sales_unit="PCE", content=1.0, unit_price=1.19, lead_days=1, cutoff_passed=False,
                   tags=["LOW_LACTOSE"], labels=[], carbon=1.3, reliability=0.99,
                   official_substitutes=[], allergens=["MILK"]),
    "460104": dict(name_en="Lactose-free chocolate milk drink 1 L",
                   name_fi="Laktoositon kaakaojuoma 1 l", category="10400",
                   sales_unit="PCE", content=1.0, unit_price=1.79, lead_days=2, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=[], carbon=1.7, reliability=0.94,
                   official_substitutes=[], allergens=["MILK"]),
    "460105": dict(name_en="Lactose-free sour milk 1 L",
                   name_fi="Laktoositon piimä 1 l", category="10400",
                   sales_unit="PCE", content=1.0, unit_price=1.35, lead_days=2, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE"], labels=[], carbon=1.3, reliability=0.93,
                   official_substitutes=[], allergens=["MILK"]),
    "460106": dict(name_en="Oat drink 1 L",
                   name_fi="Kaurajuoma 1 l", category="10500",
                   sales_unit="PCE", content=1.0, unit_price=1.49, lead_days=2, cutoff_passed=False,
                   tags=["FREE_FROM_LACTOSE", "FREE_FROM_MILK", "VEGAN"], labels=[], carbon=0.4,
                   reliability=0.97, official_substitutes=[], allergens=["OATS"]),
    "470001": dict(name_en="Gluten-free bread mix, lactose-free",
                   name_fi="Gluteeniton leipäjauhoseos, laktoositon", category="20100",
                   sales_unit="PCE", content=1.0, content_unit="KG", unit_price=4.90, lead_days=3,
                   cutoff_passed=False, tags=["FREE_FROM_LACTOSE", "FREE_FROM_GLUTEN"], labels=[],
                   carbon=None, reliability=None, official_substitutes=[], allergens=None),
}

# --- Buyers ---------------------------------------------------------------------------
# Demo tokens only. The real server verifies an Ed25519-signed mandate instead.

MANDATES: dict[str, dict[str, Any]] = {
    "demo-hotel": dict(key="hotel", buyer="Hotel Chain Oy / Helsinki Central", agent_id="buyer-agent-01",
                       max_order_eur=1500, allowed_categories=["10400"], blocked_allergens=[],
                       unknown_allergens="human", usual_amount=400,
                       approver="procurement.manager@hotel.example"),
    "demo-cafe": dict(key="cafe", buyer="Café Aalto", agent_id="buyer-agent-02",
                      max_order_eur=300, allowed_categories=["10400"], blocked_allergens=[],
                      unknown_allergens="agent", usual_amount=20, approver="owner@cafe.example"),
    "demo-school": dict(key="school", buyer="Espoo School Kitchens", agent_id="buyer-agent-03",
                        max_order_eur=2500, allowed_categories=["10400"], blocked_allergens=["PEANUT"],
                        unknown_allergens="human", usual_amount=800,
                        approver="kitchen.lead@school.example"),
}


def _content_unit(p: dict[str, Any]) -> str:
    return p.get("content_unit", "L")


def _overrides() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(OVERRIDES_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _product(pid: str) -> dict[str, Any] | None:
    base = PRODUCTS.get(pid)
    if base is None:
        return None
    merged = dict(base)
    merged.update({k: v for k, v in _overrides().get(pid, {}).items() if k in ("description", "available_units")})
    return merged


def _summary(pid: str, p: dict[str, Any]) -> dict[str, Any]:
    return dict(id=pid, name_en=p["name_en"], name_fi=p["name_fi"], category=p["category"],
                sales_unit=p["sales_unit"], tags=p["tags"], labels=p["labels"])


def _details(pid: str, p: dict[str, Any]) -> dict[str, Any]:
    allergens = p.get("allergens")
    return _summary(pid, p) | dict(
        allergens_contains=allergens or [], allergens_may_contain=[], allergens_free_from=[],
        allergen_info_missing=allergens is None, vendor="Valio Oy" if "Valio" in p["name_en"] else "Supplier Oy",
        country="FI", description=p.get("description", f"{p['name_en']}."),
        carbon_kg_per_kg=p.get("carbon"), delivery_reliability=p.get("reliability"),
        official_substitutes=p.get("official_substitutes", []))


# --- State ----------------------------------------------------------------------------

@dataclass
class State:
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)  # by quote_id
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def reset(self) -> None:
        with self.lock:
            self.quotes.clear(), self.orders.clear(), self.approvals.clear(), self.log.clear()


STATE = State()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry_hash(e: dict[str, Any]) -> str:
    body = json.dumps({k: e[k] for k in ("seq", "time", "actor", "action", "reason", "prev_hash")},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()


def log(actor: str, action: str, reason: str, *, refs: tuple[str, ...] = ()) -> dict[str, Any]:
    with STATE.lock:
        prev = STATE.log[-1]["hash"] if STATE.log else "0" * 64
        e = dict(seq=len(STATE.log) + 1, time=_now().isoformat(timespec="seconds"), actor=actor,
                 action=action, reason=reason, prev_hash=prev)
        e["hash"] = _entry_hash(e)
        e["_refs"] = list(refs)
        STATE.log.append(e)
        return e


def verify_log() -> dict[str, Any]:
    prev = "0" * 64
    for e in STATE.log:
        if e["prev_hash"] != prev or _entry_hash(e) != e["hash"]:
            return {"ok": False, "broken_at_seq": e["seq"]}
        prev = e["hash"]
    return {"ok": True}


def _public(e: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _sign(payload: dict[str, Any]) -> str:
    return hmac.new(_SIGNING_KEY, json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def _error(code: str, message: str, retryable: bool = False) -> ToolError:
    return ToolError(json.dumps({"code": code, "message": message, "retryable": retryable}))


def _eur(x: float) -> str:
    return f"€{x:,.2f}"


# --- Tools ----------------------------------------------------------------------------

mcp = MCPServer("valio-aimo-trade", instructions="FAKE development server for Valio Aimo trade tools.")


class QuoteLineIn(BaseModel):
    product_id: str
    amount: float = Field(gt=0)
    unit: str = Field(description='"L" or "KG"')


@mcp.tool()
def search_products(text: str, category: str | None = None,
                    must_have_tags: list[str] | None = None) -> list[dict[str, Any]]:
    """Search the product file by words in the English or Finnish name, with optional filters."""
    words = [w for w in text.lower().split() if w]
    tags = set(must_have_tags or [])
    out = []
    for pid in PRODUCTS:
        p = _product(pid)
        hay = f"{p['name_en']} {p['name_fi']}".lower()
        if words and not all(w in hay for w in words):
            continue
        if category and p["category"] != category:
            continue
        if not tags <= set(p["tags"]):
            continue
        out.append(_summary(pid, p))
    log("buyer agent", "search_products", f'Searched for "{text}" (category {category or "any"}, '
        f'tags {", ".join(sorted(tags)) or "none"}): {len(out)} products.')
    return out[:20]


@mcp.tool()
def get_product(product_id: str) -> dict[str, Any]:
    """Full details for one product: allergens, origin, labels, description."""
    p = _product(product_id)
    if p is None:
        raise _error("not_found", f"No product {product_id}.")
    log("buyer agent", "get_product", f"Read details of {product_id} {p['name_en']}.")
    return _details(product_id, p)


@mcp.tool()
def request_quote(lines: list[QuoteLineIn], need_by: date) -> dict[str, Any]:
    """Price and availability for the chosen lines, as a signed quote that expires in 15 minutes."""
    out_lines = []
    for ln in lines:
        p = _product(ln.product_id)
        if p is None:
            raise _error("not_found", f"No product {ln.product_id}.")
        if ln.unit.upper() != _content_unit(p):
            raise _error("bad_unit", f"{ln.product_id} is sold by {_content_unit(p)}, not {ln.unit}.")
        units = math.ceil(round(ln.amount / p["content"], 6))
        stock = "unconfirmed"
        avail = p.get("available_units")
        if avail is not None:
            stock = "confirmed"
            units = min(units, int(avail))
        available = date.today() + timedelta(days=p["lead_days"])
        out_lines.append(dict(
            product_id=ln.product_id, name=p["name_en"], units=units, sales_unit=p["sales_unit"],
            covers=round(units * p["content"], 3), content_unit=_content_unit(p),
            unit_price_eur=p["unit_price"], line_total_eur=round(units * p["unit_price"], 2),
            available_date=available.isoformat(), cutoff_passed=p["cutoff_passed"], stock=stock))
    total = round(sum(ln["line_total_eur"] for ln in out_lines), 2)
    quote = dict(quote_id=f"q_{uuid.uuid4().hex[:10]}", lines=out_lines, total_eur=total,
                 total_with_tax_eur=round(total * (1 + TAX_RATE), 2),
                 expires_at=(_now() + QUOTE_TTL).isoformat(timespec="seconds"))
    quote["signature"] = _sign(quote)
    with STATE.lock:
        STATE.quotes[quote["quote_id"]] = quote | {"need_by": need_by.isoformat()}
    log("buyer agent", "request_quote", f"Quote {quote['quote_id']}: {len(out_lines)} line(s), "
        f"{_eur(total)} before tax, need by {need_by.isoformat()}.", refs=(quote["quote_id"],))
    return quote


def _decide(quote: dict[str, Any], m: dict[str, Any], confirm_unusual: bool) -> tuple[str, list[str]]:
    reasons_reject, reasons_human = [], []
    for ln in quote["lines"]:
        p = PRODUCTS[ln["product_id"]]
        if p["category"] not in m["allowed_categories"]:
            reasons_reject.append(f"{ln['name']} is in category {p['category']}, which this buyer's "
                                  f"mandate does not allow.")
        if set(p.get("allergens") or []) & set(m["blocked_allergens"]):
            reasons_reject.append(f"{ln['name']} contains an allergen this buyer has blocked.")
        if p.get("allergens") is None and m["unknown_allergens"] == "human":
            reasons_human.append(f"{ln['name']} has no allergen information, and this buyer wants a "
                                 f"person to check those.")
        if ln["cutoff_passed"]:
            reasons_human.append(f"The order cut-off for {ln['name']} has passed.")
        if ln["available_date"] > quote["need_by"]:
            reasons_human.append(f"{ln['name']} arrives {ln['available_date']}, after the need-by date "
                                 f"{quote['need_by']}.")
    if reasons_reject:
        return "rejected", reasons_reject
    amount = sum(ln["covers"] for ln in quote["lines"])
    if amount > 5 * m["usual_amount"]:
        ratio = amount / m["usual_amount"]
        if not confirm_unusual:
            return "needs_clarification", [f"{amount:,.0f} L is {ratio:.0f}× this buyer's usual "
                                           f"{m['usual_amount']:,} L."]
        reasons_human.append(f"{amount:,.0f} L is {ratio:.0f}× this buyer's usual {m['usual_amount']:,} L. "
                             f"The agent confirmed it, so a person must approve.")
    if quote["total_eur"] > m["max_order_eur"]:
        reasons_human.append(f"Total {_eur(quote['total_eur'])} is over this buyer's "
                             f"{_eur(m['max_order_eur'])} limit for orders without approval.")
    if reasons_human:
        return "pending_approval", reasons_human
    return "confirmed", ["Within every limit in the buyer's mandate."]


@mcp.tool()
def place_order(quote_id: str, mandate_token: str, rationale: str,
                confirm_unusual: bool = False) -> dict[str, Any]:
    """Order a quote. Plain code checks the quote and the buyer's mandate and decides the result."""
    m = MANDATES.get(mandate_token)
    if m is None:
        log("policy", "place_order rejected", "The mandate is missing or its signature is not valid.",
            refs=(quote_id,))
        return dict(status="rejected", reasons=["The mandate is missing or its signature is not valid."])
    actor = f"{m['agent_id']} ({m['key']})"
    with STATE.lock:
        existing = STATE.orders.get(quote_id)
        if existing and not (existing["status"] == "needs_clarification" and confirm_unusual):
            return existing["result"]
        quote = STATE.quotes.get(quote_id)
        if quote is None or _sign({k: v for k, v in quote.items() if k not in ("signature", "need_by")}) \
                != quote["signature"]:
            return dict(status="rejected", reasons=["The quote is unknown or has been changed."])
        if datetime.fromisoformat(quote["expires_at"]) < _now():
            return dict(status="rejected", reasons=["The quote has expired. Ask for a new one."])
        log(actor, "place_order", f"Asked to order quote {quote_id}. Agent's reason: {rationale}",
            refs=(quote_id,))
        status, reasons = _decide(quote, m, confirm_unusual)
        result: dict[str, Any] = dict(status=status, reasons=reasons)
        order_id = f"o_{quote_id[2:]}"
        if status in ("confirmed", "pending_approval"):
            result["order_id"] = order_id
        if status == "pending_approval":
            approval_id = f"a_{quote_id[2:]}"
            result["approval_id"] = approval_id
            STATE.approvals[approval_id] = dict(
                approval_id=approval_id, status="pending", quote_id=quote_id, order_id=order_id,
                buyer=m["buyer"], agent_id=m["agent_id"], approver=m["approver"],
                total_eur=quote["total_eur"], need_by=quote["need_by"], reasons=reasons,
                rationale=rationale, lines=quote["lines"],
                created_at=_now().isoformat(timespec="seconds"), decided_by=None, decided_at=None)
        if status == "needs_clarification":
            result["question"] = (f"{reasons[0]} Please confirm this amount is intended. If it is, "
                                  f"place the order again with confirm_unusual set to true.")
        STATE.orders[quote_id] = dict(status=status, result=result)
        log("policy", f"decision: {status}", " ".join(reasons), refs=(quote_id, order_id))
        return result


@mcp.tool()
def get_approval_status(approval_id: str) -> dict[str, Any]:
    """Whether a person has approved or rejected an order that needed approval."""
    a = STATE.approvals.get(approval_id)
    if a is None:
        raise _error("not_found", f"No approval {approval_id}.")
    out = dict(status=a["status"])
    if a["decided_by"]:
        out |= dict(decided_by=a["decided_by"], decided_at=a["decided_at"])
    return out


@mcp.tool()
def get_audit_log(order_id: str | None = None, quote_id: str | None = None) -> list[dict[str, Any]]:
    """The plain-language decision trail, optionally only for one order or quote."""
    wanted = {x for x in (order_id, quote_id) if x}
    return [_public(e) for e in STATE.log if not wanted or wanted & set(e["_refs"])]


# --- HTTP for the screens -------------------------------------------------------------

@mcp.custom_route("/approvals", methods=["GET"])
async def http_approvals(_: Request) -> JSONResponse:
    return JSONResponse([a for a in STATE.approvals.values() if a["status"] == "pending"])


async def _decide_approval(request: Request, status: str) -> JSONResponse:
    a = STATE.approvals.get(request.path_params["approval_id"])
    if a is None:
        return JSONResponse({"code": "not_found", "message": "No such approval.", "retryable": False}, 404)
    if a["status"] != "pending":
        return JSONResponse({"code": "already_decided", "message": f"Already {a['status']}.",
                             "retryable": False}, 409)
    a.update(status=status, decided_by=a["approver"], decided_at=_now().isoformat(timespec="seconds"))
    STATE.orders[a["quote_id"]]["result"]["status"] = "confirmed" if status == "approved" else "rejected"
    log(f"approver {a['approver']}", f"approval: {status}",
        f"{a['approver']} {status} order {a['order_id']} ({_eur(a['total_eur'])}).",
        refs=(a["quote_id"], a["order_id"]))
    return JSONResponse(a)


@mcp.custom_route("/approvals/{approval_id}/approve", methods=["POST"])
async def http_approve(request: Request) -> JSONResponse:
    return await _decide_approval(request, "approved")


@mcp.custom_route("/approvals/{approval_id}/reject", methods=["POST"])
async def http_reject(request: Request) -> JSONResponse:
    return await _decide_approval(request, "rejected")


@mcp.custom_route("/log", methods=["GET"])
async def http_log(_: Request) -> JSONResponse:
    return JSONResponse([_public(e) for e in STATE.log])


@mcp.custom_route("/log/verify", methods=["GET"])
async def http_verify(_: Request) -> JSONResponse:
    return JSONResponse(verify_log())


@mcp.custom_route("/_fake/tamper/{seq}", methods=["POST"])
async def http_tamper(request: Request) -> JSONResponse:
    """Fake-only: edit one log row by hand, to show Verify turning red."""
    seq = int(request.path_params["seq"])
    for e in STATE.log:
        if e["seq"] == seq:
            e["reason"] += " (edited)"
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": False}, 404)


def app():
    return mcp.streamable_http_app(host="0.0.0.0")


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"FAKE valio-aimo-trade server at http://{args.host}:{args.port}/mcp")
    uvicorn.run(app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
