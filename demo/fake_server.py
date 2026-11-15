"""A stand-in for Runner 2's MCP server, so the bot and screens can be built first.

It follows Contract B in docs/runner-tasks.md and reuses the real server's vocabulary,
keyword rules and ranking. Its Policy is a small copy, good enough for development and
tests. The real server (server/) replaces it: start that one on port 8000 instead.

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
from types import SimpleNamespace
from typing import Any

import jwt
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from server import ranking, vocabulary
from server.seller import KeywordSeller, Need
from server.vocabulary import unit_code

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
    "demo-cafe": dict(key="cafe", buyer="Café Kallio", agent_id="buyer-agent-02",
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
    # Same file format as Runner 1's catalog/overrides.py: {"offers": {id: {...}}, "products": {id: {...}}}
    data = _overrides()
    if "available_units" in data.get("offers", {}).get(pid, {}):
        merged["available_units"] = data["offers"][pid]["available_units"]
    if "description" in data.get("products", {}).get(pid, {}):
        merged["description"] = data["products"][pid]["description"]
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
    buyers: dict[str, dict[str, Any]] = field(default_factory=dict)  # signed up through POST /buyers
    log: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def reset(self) -> None:
        with self.lock:
            self.quotes.clear(), self.orders.clear(), self.approvals.clear(), self.log.clear()
            self.buyers.clear()


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


@mcp.tool()
def get_product(product_id: str) -> dict[str, Any]:
    """Full details for one product: allergens, origin, labels, description."""
    p = _product(product_id)
    if p is None:
        raise _error("not_found", f"No product {product_id}.")
    log("buyer agent", "get_product", f"Read details of {product_id} {p['name_en']}.")
    return _details(product_id, p)


ONBOARDING_URL = "http://localhost:8080/onboarding"


def _token_of(headers) -> str:
    """The mandate in X-Mandate. The fake does not check the agent's session token."""
    return ((headers.get("x-mandate") if headers else None) or "").strip()


def _refusal(token: str) -> dict[str, Any]:
    code = "mandate_invalid" if token else "mandate_missing"
    return {"code": code, "retryable": False, "onboarding_url": ONBOARDING_URL,
            "message": "No valid mandate was shown. Connect with the kitchen's mandate in X-Mandate."}


def _ask(question: str, missing=(), unknown=()) -> dict[str, Any]:
    return dict(status="needs_clarification", missing=list(missing), unknown=list(unknown),
                known_properties=vocabulary.known_names(), question=question)


@mcp.tool()
def search_products(ctx: Context, product: str | None = None, must_have: list[str] | None = None,
                    amount: float | None = None, unit: str | None = None) -> dict[str, Any]:
    """Find the products that fit a request, in plain words. Dropped products come back with a reason."""
    token = _token_of(ctx.headers)
    m = _mandate_for(token)
    if m is None:
        return _refusal(token)
    understood = vocabulary.understand(product or "", must_have)
    if understood.unknown:
        return _ask(f"I don't know the product property {', '.join(understood.unknown)}.",
                    unknown=understood.unknown)
    if not understood.text:
        return _ask("What product do you need?", missing=["product"])
    if unit is not None and unit_code(unit) is None:
        return _ask(f'The server cannot measure in "{unit}". Ask the buyer for L, KG or PCS.',
                    missing=["unit"])
    unit = unit_code(unit)
    words, tags = understood.text.split(), set(understood.tags)
    candidates = []
    for pid in PRODUCTS:
        p = _product(pid)
        hay = f"{p['name_en']} {p['name_fi']}".lower()
        if (all(w in hay for w in words) and tags <= set(p["tags"])
                and p["category"] in m["allowed_categories"]):
            candidates.append(SimpleNamespace(**_summary(pid, p)))
    need = Need(" ".join(str(product).split()), tuple(vocabulary.names(understood.tags)), amount, unit)
    verdicts = KeywordSeller().screen(need, candidates).verdicts
    kept = [vars(c) | {"properties": vocabulary.names(c.tags)} for c in candidates if verdicts[c.id].keep]
    dropped = [dict(id=c.id, name=c.name_en, reason=verdicts[c.id].reason)
               for c in candidates if not verdicts[c.id].keep]
    log(f"{m['agent_id']} ({m['key']})", "search_products",
        f'Searched for "{understood.text}": kept {len(kept)} and dropped {len(dropped)}.')
    return dict(status="ok",
                understood=dict(product=understood.text, must_have=vocabulary.names(understood.tags),
                                from_mandate=[]),
                products=kept, dropped=dropped, screened_by="keyword rules",
                total_matches=len(candidates), truncated=False)


def _quote(lines, need_by: date) -> dict[str, Any]:
    out_lines = []
    for line in lines:
        c = line.candidate
        out_lines.append(dict(
            product_id=c.product_id, name=c.name, units=line.units, sales_unit=c.sales_unit,
            covers=line.covers, content_unit=c.content_unit, unit_price_eur=c.unit_price_eur,
            line_total_eur=line.total_eur, available_date=c.available_date.isoformat(),
            cutoff_passed=c.cutoff_passed, closing_time=None,
            stock="confirmed" if c.available_units is not None else "unconfirmed"))
    total = round(sum(ln["line_total_eur"] for ln in out_lines), 2)
    quote = dict(quote_id=f"q_{uuid.uuid4().hex[:10]}", lines=out_lines, total_eur=total,
                 total_with_tax_eur=round(total * (1 + TAX_RATE), 2),
                 expires_at=(_now() + QUOTE_TTL).isoformat(timespec="seconds"))
    quote["signature"] = _sign(quote)
    return quote


@mcp.tool()
def request_quote(ctx: Context, product_ids: list[str] | None = None, amount: float | None = None,
                  unit: str | None = None, need_by: str | None = None,
                  preferences: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ranked options for one need. Each option is its own signed quote, valid for 15 minutes."""
    token = _token_of(ctx.headers)
    m = _mandate_for(token)
    if m is None:
        return _refusal(token)
    missing = [name for name, value in (("product_ids", product_ids), ("amount", amount),
                                        ("unit", unit), ("need_by", need_by)) if not value]
    if missing:
        return _ask("To price this I need: " + ", ".join(missing) + ".", missing=missing)
    try:
        need = date.fromisoformat(need_by)
    except ValueError:
        return {"code": "bad_date", "message": "need_by must be a date like 2026-11-16.",
                "retryable": False}
    if unit_code(unit) is None:
        return _ask(f'The server cannot measure in "{unit}". Ask the buyer for L, KG or PCS.',
                    missing=["unit"])
    unit = unit_code(unit)
    candidates, not_offered = [], []
    for pid in dict.fromkeys(product_ids):
        p = _product(pid)
        if p is None:
            not_offered.append(dict(product_id=pid, name=None, reason="Not in the catalog."))
            continue
        if unit != _content_unit(p):
            not_offered.append(dict(product_id=pid, name=p["name_en"],
                                    reason=f"It is sold by {_content_unit(p)}, not {unit}."))
            continue
        available = p.get("available_units")
        candidates.append(ranking.Candidate(
            product_id=pid, name=p["name_en"], sales_unit=p["sales_unit"],
            content_per_unit=p["content"], content_unit=_content_unit(p),
            units=math.ceil(round(amount / p["content"], 6)), unit_price_eur=p["unit_price"],
            unit_price_with_tax_eur=round(p["unit_price"] * (1 + TAX_RATE), 4),
            available_date=date.today() + timedelta(days=p["lead_days"]), closing_time=None,
            cutoff_passed=p["cutoff_passed"],
            available_units=None if available is None else int(available),
            reliability=p.get("reliability"), country="FI", labels=tuple(p["labels"]),
            carbon=p.get("carbon"), tags=tuple(p.get("tags", ()))))
    prefs = preferences or {}
    ranked = ranking.rank(candidates, need, prefs.get("priorities"), prefs.get("pack_size"),
                          prefs.get("prefer"))
    plans = ranking.options(ranked, amount, need)
    offered = {line.candidate.product_id for plan in plans for line in plan.lines}
    for c in ranked:
        if c.short and c.product_id not in offered:
            not_offered.append(dict(
                product_id=c.product_id, name=c.name,
                reason=f"Only {c.available_units * c.content_per_unit:g} {c.content_unit} is in "
                       f"stock, less than the {amount:g} {unit} asked for."))
    set_id = f"qs_{uuid.uuid4().hex[:10]}"
    options = []
    for rank_no, plan in enumerate(plans, 1):
        quote = _quote(plan.lines, need)
        stored = quote | {"need_by": need.isoformat(), "set_id": set_id, "buyer": m["key"],
                          "rank": rank_no, "label": plan.label}
        with STATE.lock:
            STATE.quotes[quote["quote_id"]] = stored
        status, reasons = _decide(stored, m)
        options.append(dict(rank=rank_no, label=plan.label, trade_off=plan.trade_off,
                            expected=dict(status=status, reasons=reasons), quote=quote))
        log(f"{m['agent_id']} ({m['key']})", "request_quote",
            f"Option {rank_no} of {len(plans)} ({plan.label}): {plan.trade_off} "
            f"{_eur(quote['total_eur'])} before tax.", refs=(quote["quote_id"],))
    return dict(status="ok", set_id=set_id,
                asked=dict(amount=amount, unit=unit, need_by=need.isoformat()),
                options=options, not_offered=not_offered, earliest=None)


def _mandate_for(token: str) -> dict[str, Any] | None:
    """Demo tokens, a kitchen signed up through POST /buyers, or a real mandate from
    server/make_mandate.py mapped by its "kid" (buyer id).

    The fake does NOT verify signatures. The real server does.
    """
    if token in MANDATES:
        return MANDATES[token]
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except Exception:
        return None
    return STATE.buyers.get(kid) or MANDATES.get(f"demo-{kid}")



STORED_ONLY = ("signature", "need_by", "set_id", "buyer", "rank", "label")


def _decide(quote: dict[str, Any], m: dict[str, Any]) -> tuple[str, list[str]]:
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
        reasons_human.append(f"{amount:,.0f} L is {ratio:.0f}× this buyer's usual "
                             f"{m['usual_amount']:,} L, so a person must approve.")
    if quote["total_eur"] > m["max_order_eur"]:
        reasons_human.append(f"Total {_eur(quote['total_eur'])} is over this buyer's "
                             f"{_eur(m['max_order_eur'])} limit for orders without approval.")
    if reasons_human:
        return "pending_approval", reasons_human
    return "confirmed", ["Within every limit in the buyer's mandate."]


@mcp.tool()
def place_order(ctx: Context, quote_id: str, rationale: str,
                agent_signature: str | None = None) -> dict[str, Any]:
    """Order a quote. Plain code checks the quote and the connection's mandate and decides.

    The fake accepts agent_signature and ignores it. The real server checks it.
    """
    m = _mandate_for(_token_of(ctx.headers))
    if m is None:
        log("policy", "place_order rejected", "The mandate is missing or its signature is not valid.",
            refs=(quote_id,))
        return dict(status="rejected", reasons=["The mandate is missing or its signature is not valid."])
    actor = f"{m['agent_id']} ({m['key']})"
    with STATE.lock:
        existing = STATE.orders.get(quote_id)
        if existing:
            return existing["result"]
        quote = STATE.quotes.get(quote_id)
        if quote is None or _sign({k: v for k, v in quote.items() if k not in STORED_ONLY}) \
                != quote["signature"]:
            return dict(status="rejected", reasons=["The quote is unknown or has been changed."])
        if quote["buyer"] != m["key"]:
            return dict(status="rejected", reasons=["This quote was issued to another buyer."])
        if datetime.fromisoformat(quote["expires_at"]) < _now():
            return dict(status="rejected", reasons=["The quote has expired. Ask for a new one."])
        log(actor, "place_order", f"Asked to order quote {quote_id}. Agent's reason: {rationale}",
            refs=(quote_id,))
        status, reasons = _decide(quote, m)
        result: dict[str, Any] = dict(status=status, reasons=reasons)
        if status != "confirmed":
            others = sorted((q for q in STATE.quotes.values()
                             if q.get("set_id") == quote["set_id"] and q["quote_id"] != quote_id
                             and q["quote_id"] not in STATE.orders and _decide(q, m)[0] == "confirmed"),
                            key=lambda q: q["rank"])[:3]
            if others:
                result["alternatives"] = [
                    dict(quote_id=q["quote_id"], rank=q["rank"], label=q["label"],
                         summary=" + ".join(f"{ln['units']:,} × {ln['sales_unit']} {ln['name']}"
                                            for ln in q["lines"]),
                         total_eur=q["total_eur"]) for q in others]
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

@mcp.custom_route("/mandate", methods=["GET"])
async def http_mandate(request: Request) -> JSONResponse:
    """Is this mandate accepted? The agent asks before it connects."""
    token = _token_of(request.headers)
    m = _mandate_for(token)
    if m is None:
        return JSONResponse(_refusal(token), 401)
    return JSONResponse({"buyer_id": m["key"], "buyer": m["buyer"], "agent_id": m["agent_id"]})


@mcp.custom_route("/buyers", methods=["POST"])
async def http_register_buyer(request: Request) -> JSONResponse:
    """Fake registration. It does NOT check the signature; the real server does."""
    try:
        token = (await request.json())["mandate_token"]
        buyer_id = jwt.get_unverified_header(token)["kid"]
        m = jwt.decode(token, options={"verify_signature": False})
        usual = m.get("usual_orders") or []
        mine = dict(
            key=buyer_id, buyer=m["buyer"], agent_id=m["agent_id"],
            max_order_eur=m["auto_approve"]["max_order_eur"],
            allowed_categories=(m["auto_approve"].get("allowed_categories")
                                or sorted({p["category"] for p in PRODUCTS.values()})),
            blocked_allergens=[],  # this fake's products use their own allergen words
            unknown_allergens=m["hard_rules"].get("unknown_allergens", "human"),
            usual_amount=usual[0]["amount"] if usual else 10 ** 9,
            approver=(m.get("approvers") or ["approver"])[0])
    except Exception:
        return JSONResponse({"code": "mandate_invalid", "retryable": False,
                             "message": "Send public_pem and a signed mandate_token."}, 400)
    with STATE.lock:
        if buyer_id in STATE.buyers:
            return JSONResponse({"code": "buyer_exists", "retryable": False,
                                 "message": f"A buyer with id {buyer_id} is already registered."}, 409)
        STATE.buyers[buyer_id] = mine
    log(m["buyer"], "register_buyer",
        f"{m['buyer']} registered its signing key and mandate {m['mandate_id']} as buyer {buyer_id}.")
    return JSONResponse({"buyer_id": buyer_id, "mandate_id": m["mandate_id"], "status": "registered"}, 201)


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

