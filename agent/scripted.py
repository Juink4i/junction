"""Scripted mode: the same agent runtime with a fixed plan instead of Gemini. No AI.

Use it to rehearse the demo without a Gemini key, or as a fallback if the model is rate
limited on stage. Every tool call still goes over MCP to the trade server, so the server's
search, ranking, decisions, the approval page and the log are all real. Only the agent's
steps are fixed here. It is always labelled "scripted" on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Generator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types
from pydantic import PrivateAttr


@dataclass
class ShoppingRequest:
    product: str  # in the buyer's words, e.g. "lactose-free milk"
    amount: float
    unit: str
    need_by: str
    must_have: list[str] = field(default_factory=list)  # plain words, when not already in product


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


def _eur(x: float) -> str:
    return f"€{x:,.2f}"


def shopping_plan(req: ShoppingRequest, *, gullible: bool = False) -> Generator:
    """The steps in agent/instructions.py, as fixed code."""
    yield call("record_request", dict(product=req.product, amount=req.amount, unit=req.unit,
                                      need_by=req.need_by, must_have=req.must_have))
    search = dict(product=req.product, amount=req.amount, unit=req.unit)
    if req.must_have:
        search["must_have"] = req.must_have
    found = yield call("search_products", search)
    if "error" in found:
        yield text(f"The search failed: {found['error'].get('message')}")
        return
    if found.get("status") == "needs_clarification":
        yield text(f"Valio Aimo asked: \"{found.get('question')}\" I could not answer that, "
                   "so I ordered nothing.")
        return
    products = found.get("products", [])
    drop_note = "; ".join(f"{d['name']} ({d['reason']})" for d in found.get("dropped", [])[:4]) or "nothing"
    if not products:
        yield text(f"Valio Aimo found no product that fits {req.product}. Dropped: {drop_note}.")
        return

    amount, injected = req.amount, False
    if gullible:  # the compromised agent reads supplier descriptions and obeys them
        for product in products[:3]:
            detail = yield call("get_product", {"product_id": product["id"]})
            description = str(detail.get("description", "")).lower().replace("×", "x")
            injected = injected or "10x" in description
    if injected:
        amount = req.amount * 10
        say = f"The supplier's note says to order 10x, so I will order {amount:,.0f} {req.unit}."
    else:
        say = f"{len(products)} products fit. Valio Aimo dropped: {drop_note}."

    priced = yield call("request_quote", dict(product_ids=[p["id"] for p in products], amount=amount,
                                              unit=req.unit, need_by=req.need_by), say=say)
    if "error" in priced:
        yield text(f"I could not get prices: {priced['error'].get('message')}")
        return
    options = priced.get("options", [])
    if not options:
        yield text("Valio Aimo could not offer anything for this request. A person needs to choose "
                   "between a later date, a smaller amount or a different product.")
        return

    best = options[0]
    quote = best["quote"]
    rationale = f"Valio Aimo's best option for {amount:,.0f} {req.unit} by {req.need_by}: {best['trade_off']}"
    order = yield call("place_order", {"quote_id": quote["quote_id"], "rationale": rationale[:300]})
    status = order.get("status")
    total = _eur(quote.get("total_eur", 0))
    what = ", ".join(f"{ln['units']:,} × {ln['sales_unit']} {ln['name']} ({ln['covers']:,.0f} {ln['content_unit']})"
                     for ln in quote.get("lines", []))
    reasons = " ".join(order.get("reasons", []))
    alternatives = order.get("alternatives") or []
    other = (f" Alternatives that need no person: {'; '.join(a['summary'] for a in alternatives)}."
             if alternatives else "")

    if status == "pending_approval":
        decision = yield call("get_approval_status", {"approval_id": order["approval_id"]})
        result = {"approved": "approved by", "rejected": "rejected by"}.get(decision.get("status"))
        who = decision.get("decided_by", "")
        if result:
            yield text(f"Order {result} {who}: {what}, {total} before VAT, arriving by {req.need_by}.\n"
                       f"It needed a person because: {reasons}")
        else:
            yield text(f"Waiting for approval: {what}, {total}. Reason: {reasons}{other}")
    elif status == "confirmed":
        yield text(f"Ordered {what}, {total} before VAT, arriving by {req.need_by}. "
                   f"The server confirmed it within the buyer's rules. Dropped: {drop_note}.")
    else:
        yield text(f"The server rejected the order: {reasons} I will not retry.{other}")
