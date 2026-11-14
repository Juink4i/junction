"""The tools the buyer agent can use.

Six of them are the trade server's MCP tools (Contract B), with two changes made in code
rather than left to the AI:
- place_order attaches the buyer's signed mandate. The AI never sees or chooses it.
- get_approval_status keeps checking until a person decides, or the wait runs out.

Three are local and only make the agent's work visible: record_request, present_options
and ask_buyer. None of them can change what the server allows.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import date
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from agent.config import Settings
from agent.events import EventSink
from agent.mcp_link import TradeLink

AskFn = Callable[[str], Awaitable[str | None]]
MANDATE_SHOWN_AS = "[signed mandate attached]"


class QuoteLine(BaseModel):
    product_id: str = Field(description="Product id from search_products.")
    amount: float = Field(description="How much is needed, in litres or kilograms (not sales units).")
    unit: Literal["L", "KG"] = Field(description='"L" for litres or "KG" for kilograms.')


class OptionCard(BaseModel):
    label: str = Field(description='"best", "better" or "good" (or "split" for a split order).')
    product_id: str
    name: str
    units: int | None = Field(default=None, description="Sales units to order.")
    sales_unit: str | None = None
    covers: float | None = Field(default=None, description="Litres or kilograms the units cover.")
    content_unit: str | None = Field(default=None, description='"L" or "KG", the unit of covers.')
    total_eur: float | None = None
    available_date: str | None = None
    trade_off: str = Field(description="One short line: what you gain and what you give up.")
    delivery_reliability: float | None = None
    carbon_kg_per_kg: float | None = None


def _err(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": False}}


class Toolbox:
    def __init__(self, link: TradeLink | None, settings: Settings, sink: EventSink, ask: AskFn):
        self.link = link
        self.settings = settings
        self.sink = sink
        self.ask = ask
        self.request: dict[str, Any] | None = None
        self.quotes: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.outcome: str | None = None  # last order: confirmed, pending_approval, approved, ...

    async def _call(self, tool: str, args: dict[str, Any], shown: dict[str, Any] | None = None) -> Any:
        call_id = uuid.uuid4().hex[:8]
        self.sink.publish("tool_call", tool=tool, args=shown if shown is not None else args, call_id=call_id)
        result = await self.link.call(tool, args)
        self.sink.publish("tool_result", tool=tool, call_id=call_id, result=result,
                          ok=not (isinstance(result, dict) and "error" in result))
        return result

    def functions(self) -> list[Callable[..., Awaitable[dict[str, Any]]]]:
        box = self

        async def record_request(product: str, amount: float, unit: Literal["L", "KG"], need_by: str,
                                 must_have: list[str] | None = None,
                                 avoid: list[str] | None = None, notes: str | None = None) -> dict:
            """Write down the buyer's request in structured form. Call this first, once.

            Args:
              product: What the buyer wants, in plain words, e.g. "lactose-free milk".
              amount: How much, in litres or kilograms.
              unit: "L" or "KG".
              need_by: The date it must arrive by, as YYYY-MM-DD.
              must_have: Properties the product must have, as catalog tags when you know them,
                e.g. ["FREE_FROM_LACTOSE"].
              avoid: Kinds of product the buyer would not accept, e.g. ["coffee milk", "flavoured"].
              notes: Anything else the buyer said that matters.
            """
            box.request = dict(product=product, amount=amount, unit=unit, need_by=need_by,
                               must_have=must_have or [], avoid=avoid or [], notes=notes)
            box.sink.publish("request", request=box.request)
            return {"recorded": True, **box.request}

        async def search_products(text: str, category: str | None = None,
                                  must_have_tags: list[str] | None = None) -> dict:
            """Search Valio Aimo's product file. No prices here; use request_quote for those.

            Args:
              text: Words to look for in the English or Finnish product name. Use few words.
                An empty string matches everything in the category and tags.
              category: Optional category code, e.g. "10400". Take codes from earlier results.
              must_have_tags: Optional tags every result must have, e.g. ["FREE_FROM_LACTOSE"].
            """
            args: dict[str, Any] = {"text": text}
            if category:
                args["category"] = category
            if must_have_tags:
                args["must_have_tags"] = must_have_tags
            found = await box._call("search_products", args)
            if isinstance(found, dict) and "error" in found:
                return found
            return {"count": len(found), "products": found}

        async def get_product(product_id: str) -> dict:
            """Full details of one product: allergens, origin, labels, description, delivery
            reliability (0 to 1) and carbon footprint (kg CO2e per kg) when known.

            Args:
              product_id: The id from search_products.
            """
            return await box._call("get_product", {"product_id": product_id})

        async def request_quote(lines: list[QuoteLine], need_by: str) -> dict:
            """Get real prices and delivery dates as a signed quote that expires in 15 minutes.

            Each line gives a product and the amount needed in litres or kilograms. The server
            works out how many sales units that is. To compare options, put every candidate in
            one quote as its own line; then ask for a fresh quote with only what you will buy.

            Args:
              lines: The products and amounts to price.
              need_by: Date the goods must arrive by, YYYY-MM-DD.
            """
            try:
                date.fromisoformat(need_by)
            except ValueError:
                return _err("bad_date", f'need_by must be a date like 2026-11-16, not "{need_by}".')
            payload = {"lines": [ln.model_dump() if isinstance(ln, BaseModel) else dict(ln) for ln in lines],
                       "need_by": need_by}
            quote = await box._call("request_quote", payload)
            if isinstance(quote, dict) and "quote_id" in quote:
                box.quotes.append(quote)
            return quote

        async def present_options(title: str, options: list[OptionCard]) -> dict:
            """Show the buyer the options you compared, best first, before ordering.

            Use labels "best", "better", "good". For substitutes, the trade-off line says what
            changes compared with the product that was asked for.

            Args:
              title: A short heading, e.g. "Options for 1,000 L lactose-free milk".
              options: Up to three options, best first.
            """
            cards = [o.model_dump() if isinstance(o, BaseModel) else dict(o) for o in options]
            box.sink.publish("options", title=title, options=cards)
            return {"shown": len(cards)}

        async def place_order(quote_id: str, rationale: str, confirm_unusual: bool = False) -> dict:
            """Order a quote. The buyer's signed mandate is attached automatically.

            The server decides the result, not you: "confirmed", "needs_clarification" (answer
            its question), "pending_approval" (a person must approve; then call
            get_approval_status) or "rejected" (explain why; do not try again).

            Args:
              quote_id: The id from request_quote.
              rationale: One or two sentences on why this is the right order. It is logged.
              confirm_unusual: Set true only after the buyer confirmed an amount the server
                asked about.
            """
            args = {"quote_id": quote_id, "mandate_token": box.settings.mandate_token,
                    "rationale": rationale, "confirm_unusual": confirm_unusual}
            shown = args | {"mandate_token": MANDATE_SHOWN_AS}
            result = await box._call("place_order", args, shown)
            if isinstance(result, dict) and "status" in result:
                box.orders.append(result)
                box.outcome = result["status"]
                box.sink.publish("decision", status=result["status"], reasons=result.get("reasons", []),
                                 question=result.get("question"), approval_id=result.get("approval_id"),
                                 order_id=result.get("order_id"), quote_id=quote_id)
            return result

        async def get_approval_status(approval_id: str) -> dict:
            """Wait for a person to approve or reject an order that needed approval.

            This keeps checking for a few minutes. If nobody has decided by then, the status is
            still "pending": tell the buyer the order is waiting for approval.

            Args:
              approval_id: The id from place_order.
            """
            s = box.settings
            box.sink.publish("waiting", approval_id=approval_id, wait_s=s.approval_wait_s)
            deadline = time.monotonic() + s.approval_wait_s
            while True:
                status = await box.link.call("get_approval_status", {"approval_id": approval_id})
                decided = not (isinstance(status, dict) and status.get("status") == "pending")
                if decided or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(s.poll_every_s)
            if isinstance(status, dict) and status.get("status") == "pending":
                status = status | {"still_waiting": True}
            call_id = uuid.uuid4().hex[:8]
            box.sink.publish("tool_call", tool="get_approval_status", args={"approval_id": approval_id},
                             call_id=call_id)
            box.sink.publish("tool_result", tool="get_approval_status", call_id=call_id, result=status,
                             ok="error" not in status)
            if isinstance(status, dict) and status.get("status") in ("approved", "rejected", "pending"):
                box.outcome = {"pending": "pending_approval"}.get(status["status"], status["status"])
                box.sink.publish("decision", status=status["status"], approval_id=approval_id,
                                 decided_by=status.get("decided_by"))
            return status

        async def ask_buyer(question: str) -> dict:
            """Ask the buyer a question and wait for the answer. Use it when the server asks you
            to confirm something only the buyer can confirm, or when the request is unclear.

            Args:
              question: One short, specific question.
            """
            box.sink.publish("ask", question=question)
            answer = await box.ask(question)
            if not answer:
                box.sink.publish("answer", text="(no answer)")
                return {"answered": False,
                        "answer": "The buyer did not answer. Do not go ahead; summarise and stop."}
            box.sink.publish("answer", text=answer)
            return {"answered": True, "answer": answer}

        async def get_audit_log(order_id: str | None = None, quote_id: str | None = None) -> dict:
            """Read the server's plain-language decision trail for an order or quote.

            Args:
              order_id: Optional order id.
              quote_id: Optional quote id.
            """
            args = {k: v for k, v in (("order_id", order_id), ("quote_id", quote_id)) if v}
            entries = await box._call("get_audit_log", args)
            if isinstance(entries, dict) and "error" in entries:
                return entries
            return {"entries": entries}

        return [record_request, search_products, get_product, request_quote, present_options,
                place_order, get_approval_status, ask_buyer, get_audit_log]
