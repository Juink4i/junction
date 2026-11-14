"""Scripted mode: the same agent runtime with a fixed plan instead of Gemini. No AI.

Use it to rehearse the demo without a Gemini key, or as a fallback if the model is rate
limited on stage. Every tool call still goes over MCP to the real trade server, so the
server's decisions, the approval page and the log are all real. Only the shopping choices
are hard-coded here. It is always labelled "scripted" on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Generator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types
from pydantic import PrivateAttr

WRONG_KINDS = {
    "coffee": "coffee milk", "kahvi": "coffee milk", "latte": "latte drink", "cappuccino": "coffee drink",
    "chocolate": "chocolate drink", "kaakao": "chocolate drink", "cocoa": "chocolate drink",
    "sour": "sour milk", "piimä": "sour milk", "buttermilk": "buttermilk", "yogurt": "yoghurt",
    "yoghurt": "yoghurt", "jogurtti": "yoghurt", "low-lactose": "low-lactose, not lactose-free",
    "vähälaktoosinen": "low-lactose, not lactose-free", "oat": "plant drink", "kaura": "plant drink",
    "cream": "cream", "kerma": "cream", "0.2 l": "portion pack", "0.25 l": "portion pack",
}


@dataclass
class ShoppingRequest:
    product: str
    amount: float
    unit: str
    need_by: str
    must_have: list[str] = field(default_factory=lambda: ["FREE_FROM_LACTOSE"])
    search_words: str = "milk"


def call(name: str, args: dict[str, Any], say: str | None = None) -> tuple:
    return ("call", name, args, say)


def text(words: str) -> tuple:
    return ("text", words)


class PlannedLlm(BaseLlm):
    """Plays a generator plan: it yields call()/text() and receives each tool's result."""

    model: str = "scripted (no AI)"
    _plan: Generator = PrivateAttr()
    _started: bool = PrivateAttr(default=False)

    def __init__(self, plan: Generator, **kw: Any):
        super().__init__(**kw)
        self._plan = plan

    async def generate_content_async(self, llm_request: LlmRequest,
                                     stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        last: dict[str, Any] = {}
        for content in reversed(llm_request.contents or []):
            responses = [p.function_response for p in content.parts or [] if p.function_response]
            if responses:
                last = dict(responses[-1].response or {})
                break
        try:
            step = self._plan.send(last if self._started else None)
        except StopIteration:
            step = text("Done.")
        self._started = True
        parts = []
        if step[0] == "call":
            _, name, args, say = step
            if say:
                parts.append(types.Part(text=say))
            parts.append(types.Part(function_call=types.FunctionCall(name=name, args=args)))
        else:
            parts.append(types.Part(text=step[1]))
        yield LlmResponse(content=types.Content(role="model", parts=parts), turn_complete=True)


def _wrong_kind(name: str) -> str | None:
    low = f" {name.lower()} "
    for word, why in WRONG_KINDS.items():
        if word in low:
            return why
    return None


def _eur(x: float) -> str:
    return f"€{x:,.2f}"


def _usable(line: dict[str, Any], need_by: str) -> bool:
    return not line.get("cutoff_passed") and str(line.get("available_date", "9999")) <= need_by


def shopping_plan(req: ShoppingRequest, *, gullible: bool = False) -> Generator:
    """Shopper + Substitution, as fixed code. Mirrors the steps in agent/instructions.py."""
    yield call("record_request", dict(product=req.product, amount=req.amount, unit=req.unit,
                                      need_by=req.need_by, must_have=req.must_have,
                                      avoid=["coffee milk", "flavoured drinks", "low-lactose milk"]))
    found = yield call("search_products", {"text": req.search_words, "must_have_tags": req.must_have})
    products = found.get("products", [])
    categories = [p["category"] for p in products if not _wrong_kind(p.get("name_en", ""))]
    category = max(set(categories), key=categories.count) if categories else None
    found = yield call("search_products", {"text": "", "category": category, "must_have_tags": req.must_have})
    products = found.get("products", [])

    keep, dropped = [], []
    for p in products:
        why = _wrong_kind(f"{p.get('name_en', '')} {p.get('name_fi', '')}")
        (dropped if why else keep).append((p, why))
    drop_note = "; ".join(f"{p['name_en']} ({why})" for p, why in dropped) or "nothing"
    candidates = [p for p, _ in keep][:4]
    if not candidates:
        yield text(f"I found no product that matches {req.product}. I dropped: {drop_note}.")
        return

    amount = req.amount
    detail = yield call("get_product", {"product_id": candidates[0]["id"]},
                        say=f"Dropped {drop_note}. {len(candidates)} candidates left.")
    description = str(detail.get("description", ""))
    injected = gullible and "10x" in description.lower().replace("×", "x")
    if injected:
        amount = req.amount * 10
        say = f"The supplier's note says to order 10x, so I will order {amount:,.0f} {req.unit}."
    else:
        say = "Comparing price and delivery for every candidate."

    lines = [{"product_id": p["id"], "amount": amount, "unit": req.unit} for p in candidates]
    compare = yield call("request_quote", {"lines": lines, "need_by": req.need_by}, say=say)
    if "error" in compare:
        yield text(f"I could not get prices: {compare['error'].get('message')}")
        return

    usable = [ln for ln in compare.get("lines", []) if _usable(ln, req.need_by)]
    usable.sort(key=lambda ln: (ln["covers"] < amount, ln["line_total_eur"] / max(ln["covers"], 1e-9)))
    if not usable:
        yield text("No candidate can arrive by the need-by date. A person needs to choose between a "
                   "late delivery and a different product.")
        return

    chosen, still_needed = [], amount
    for ln in usable:
        if still_needed <= 0:
            break
        take = min(ln["covers"], still_needed)
        chosen.append({"product_id": ln["product_id"], "amount": take, "unit": req.unit, "_line": ln})
        still_needed -= take

    labels = ["best", "better", "good"]
    options = [dict(label=labels[i], product_id=ln["product_id"], name=ln["name"], units=ln["units"],
                    sales_unit=ln["sales_unit"], covers=ln["covers"], content_unit=ln.get("content_unit"),
                    total_eur=ln["line_total_eur"],
                    available_date=ln["available_date"],
                    trade_off=("covers the full amount" if ln["covers"] >= amount
                               else f"only {ln['covers']:,.0f} {req.unit} available") +
                              f", {_eur(ln['line_total_eur'] / max(ln['covers'], 1e-9))}/{req.unit}")
               for i, ln in enumerate(usable[:3])]
    split = len(chosen) > 1
    title = (f"Shortage: {chosen[0]['amount']:,.0f} {req.unit} available, rest from a substitute"
             if split else f"Options for {amount:,.0f} {req.unit} {req.product}")
    yield call("present_options", {"title": title, "options": options})

    final_lines = [{k: v for k, v in c.items() if k != "_line"} for c in chosen]
    quote = yield call("request_quote", {"lines": final_lines, "need_by": req.need_by})
    if "error" in quote:
        yield text(f"The final quote failed: {quote['error'].get('message')}")
        return
    names = " + ".join(f"{c['_line']['name']}" for c in chosen)
    rationale = (f"Cheapest lactose-free milk that arrives by {req.need_by}: {names}."
                 + (" The first choice is short, so a lactose-free substitute fills the rest." if split else ""))
    order = yield call("place_order", {"quote_id": quote["quote_id"], "rationale": rationale})
    status = order.get("status")

    if status == "needs_clarification" and injected:
        order = yield call("place_order", {"quote_id": quote["quote_id"], "rationale": rationale,
                                           "confirm_unusual": True},
                           say="The supplier's note says this is pre-approved, so I confirm it myself.")
        status = order.get("status")
    elif status == "needs_clarification":
        answer = yield call("ask_buyer", {"question": order.get("question") or "Please confirm the amount."})
        if answer.get("answered") and str(answer.get("answer", "")).strip().lower().startswith("yes"):
            order = yield call("place_order", {"quote_id": quote["quote_id"], "rationale": rationale,
                                               "confirm_unusual": True})
            status = order.get("status")
        else:
            yield text(f"The server asked about the amount and the buyer did not confirm, so I ordered "
                       f"nothing. Server's reason: {' '.join(order.get('reasons', []))}")
            return

    total = _eur(quote.get("total_eur", 0))
    what = ", ".join(f"{ln['units']:,} × {ln['sales_unit']} {ln['name']} ({ln['covers']:,.0f} {ln['content_unit']})"
                     for ln in quote.get("lines", []))
    if status == "pending_approval":
        decision = yield call("get_approval_status", {"approval_id": order["approval_id"]})
        result = {"approved": "approved by", "rejected": "rejected by"}.get(decision.get("status"))
        who = decision.get("decided_by", "")
        if result:
            yield text(f"Order {result} {who}: {what}, {total} before VAT, arriving by {req.need_by}.\n"
                       f"It needed a person because: {' '.join(order.get('reasons', []))}")
        else:
            yield text(f"Waiting for approval: {what}, {total}. Reason: {' '.join(order.get('reasons', []))}")
    elif status == "confirmed":
        yield text(f"Ordered {what}, {total} before VAT, arriving by {req.need_by}. "
                   f"The server confirmed it within the buyer's rules. Dropped: {drop_note}.")
    else:
        yield text(f"The server rejected the order: {' '.join(order.get('reasons', []))} I will not retry.")
