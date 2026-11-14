"""The tools the buyer agent can use.

Six of them are the trade server's MCP tools (Contract B). The agent passes the buyer's words
on and follows the server's answer. Three things are done in code rather than left to the AI:
- The buyer's signed mandate travels with the connection, and each order is signed with the
  agent's own key when it has one. The AI never sees or chooses either.
- The kitchen's preferences are attached to every quote request.
- get_approval_status keeps checking until a person decides, or the wait runs out.

Two are local and only make the agent's work visible: record_request and ask_buyer. Neither
can change what the server allows.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

from agent.config import Settings
from agent.events import EventSink
from agent.identity import sign_order
from agent.mcp_link import TradeLink

AskFn = Callable[[str], Awaitable[str | None]]
SIGNATURE_SHOWN_AS = "[signed by the agent's key]"


def option_cards(options: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """The options card for the chat page, built from the server's ranked options."""
    cards = []
    for option in options[:limit]:
        quote, expected = option["quote"], option.get("expected") or {}
        lines = quote["lines"]
        one = lines[0] if len(lines) == 1 else None
        trade_off = option.get("trade_off", "")
        if expected.get("status") == "pending_approval":
            trade_off += " Needs a person's approval."
        dates = [ln["available_date"] for ln in lines if ln.get("available_date")]
        cards.append({
            "label": option["label"],
            "product_id": lines[0]["product_id"],
            "name": one["name"] if one else " + ".join(ln["name"] for ln in lines),
            "units": one["units"] if one else None,
            "sales_unit": one["sales_unit"] if one else None,
            "covers": round(sum(ln["covers"] for ln in lines), 3),
            "content_unit": lines[0]["content_unit"],
            "total_eur": quote["total_eur"],
            "available_date": max(dates) if dates else None,
            "trade_off": trade_off.strip(),
        })
    return cards


class StepBudget:
    """How many model calls the agent may still make before the buyer says something again.

    Each buyer answer starts it over, so a conversation can go on as long as the buyer is in
    it, while an agent searching on its own cannot loop forever."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        """Use one step. False when none are left."""
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    def reset(self) -> None:
        self.used = 0


class Toolbox:
    def __init__(self, link: TradeLink | None, settings: Settings, sink: EventSink, ask: AskFn):
        self.link = link
        self.settings = settings
        self.sink = sink
        self.ask = ask
        self.request: dict[str, Any] | None = None
        self.options: dict[str, dict[str, Any]] = {}  # every option offered, by quote id
        self.quotes: list[dict[str, Any]] = []  # the quotes that were ordered
        self.orders: list[dict[str, Any]] = []
        self.outcome: str | None = None  # last order: confirmed, pending_approval, approved, ...
        self.budget = StepBudget(settings.steps_per_input)
        self.searches = StepBudget(settings.searches_per_input)

    async def _call(self, tool: str, args: dict[str, Any], shown: dict[str, Any] | None = None) -> Any:
        call_id = uuid.uuid4().hex[:8]
        self.sink.publish("tool_call", tool=tool, args=shown if shown is not None else args, call_id=call_id)
        result = await self.link.call(tool, args)
        self.sink.publish("tool_result", tool=tool, call_id=call_id, result=result,
                          ok=not (isinstance(result, dict) and "error" in result))
        return result

    async def before_model(self, _ctx: Any, _request: Any) -> Any:
        """ADK calls this before each model call. Over budget, it answers instead of the model
        with a plain stop, which ends the run cleanly."""
        if self.budget.take():
            return None
        from google.adk.models import LlmResponse
        from google.genai import types

        done = ("No order was placed." if not self.orders else
                f"The last order is {self.orders[-1].get('status', 'unknown')}; nothing more was done.")
        text = (f"I have used {self.budget.limit} steps since your last message without finishing, "
                f"so I am stopping here instead of searching on. {done} Tell me more precisely "
                "what you need (for example a product name), and I will try again.")
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]),
                           turn_complete=True)

    def _preferences(self) -> dict[str, Any]:
        """The kitchen's own preferences, attached by code so the AI cannot change them."""
        profile = self.settings.profile or {}
        preferences: dict[str, Any] = {}
        if profile.get("priorities"):
            preferences["priorities"] = list(profile["priorities"])
        if profile.get("pack_size") in ("small", "large"):
            preferences["pack_size"] = profile["pack_size"]
        if profile.get("prefer"):
            preferences["prefer"] = list(profile["prefer"])
        return preferences

    def functions(self) -> list[Callable[..., Awaitable[dict[str, Any]]]]:
        box = self

        async def record_request(product: str, amount: float, unit: str, need_by: str,
                                 must_have: list[str] | None = None,
                                 avoid: list[str] | None = None, notes: str | None = None) -> dict:
            """Write down the buyer's request in structured form. Call this first, once.

            Args:
              product: What the buyer wants, in the buyer's own words, e.g. "lactose-free milk".
              amount: How much, exactly as the buyer said it. Never convert it to another unit.
              unit: "L" for litres, "KG" for kilograms, "PCS" for pieces (e.g. 200 eggs). If
                none fits, the buyer's own word, e.g. "crates".
              need_by: The date it must arrive by, as YYYY-MM-DD.
              must_have: Properties the product must have, in plain words, e.g. ["lactose-free"].
              avoid: Kinds of product the buyer would not accept, if they said so.
              notes: Anything else the buyer said that matters.
            """
            box.request = dict(product=product, amount=amount, unit=unit, need_by=need_by,
                               must_have=must_have or [], avoid=avoid or [], notes=notes)
            box.sink.publish("request", request=box.request)
            return {"recorded": True, **box.request}

        async def search_products(product: str, must_have: list[str] | None = None,
                                  amount: float | None = None, unit: str | None = None) -> dict:
            """Ask Valio Aimo which products fit. No prices here; use request_quote for those.

            Use the buyer's own words. Valio Aimo's side maps them to its catalog, applies the
            buyer's mandate and removes products that do a different job. The reply lists the
            products that fit, and the ones that were dropped with a reason for each.

            If the reply has status "needs_clarification", it asks for something that is missing
            or was not understood. Answer from what the buyer said, or ask the buyer.

            Args:
              product: What is needed, in plain words, e.g. "lactose-free milk".
              must_have: Properties every product must have, in plain words, e.g. ["lactose-free"].
              amount: How much is needed, if known. It helps leave out packs of the wrong size.
              unit: "L", "KG" or "PCS" (pieces), the unit of amount, or the buyer's own word.
            """
            if not box.searches.take():
                # Without this a model that finds nothing guesses unrelated words on and on.
                return {"status": "search_limit",
                        "message": f"You have used {box.searches.limit} searches since the buyer's "
                                   "last message. Do not search again: tell the buyer what you "
                                   "searched and what the server said, and ask what they need."}
            args: dict[str, Any] = {"product": product}
            if must_have:
                args["must_have"] = must_have
            if amount:
                args["amount"] = amount
            if unit:
                args["unit"] = unit
            return await box._call("search_products", args)

        async def get_product(product_id: str) -> dict:
            """Full details of one product: allergens, origin, labels, description, delivery
            reliability (0 to 1) and carbon footprint (kg CO2e per kg) when known.

            Args:
              product_id: The id from search_products.
            """
            return await box._call("get_product", {"product_id": product_id})

        async def request_quote(product_ids: list[str], amount: float, unit: str,
                                need_by: str) -> dict:
            """Get real prices and delivery dates as ranked options, best first.

            Pass every product id the search returned. The server works out the sales units,
            prices each product and ranks them. Each option is a signed quote that expires in
            15 minutes, and says what the buyer's mandate would decide if it were ordered.
            The buyer's preferences are attached automatically.

            Args:
              product_ids: Every product id from search_products.
              amount: How much is needed, as the buyer said it (not sales units).
              unit: "L" for litres, "KG" for kilograms or "PCS" for pieces. If the reply is
                "needs_clarification" about the unit, ask the buyer; never convert it yourself.
              need_by: Date the goods must arrive by, YYYY-MM-DD.
            """
            args: dict[str, Any] = {"product_ids": list(product_ids), "amount": amount, "unit": unit,
                                    "need_by": need_by}
            preferences = box._preferences()
            if preferences:
                args["preferences"] = preferences
            result = await box._call("request_quote", args)
            if isinstance(result, dict) and result.get("options"):
                for option in result["options"]:
                    box.options[option["quote"]["quote_id"]] = option
                box.sink.publish("options", title=f"Options for {amount:g} {unit}",
                                 options=option_cards(result["options"]))
            return result

        async def place_order(quote_id: str, rationale: str) -> dict:
            """Order one option. The buyer's signed mandate travels with the connection.

            The server decides the result, not you: "confirmed", "pending_approval" (a person
            must approve; then call get_approval_status) or "rejected" (explain why; do not try
            to get around it). When it is not confirmed, the reply may list alternatives from the
            same request that would go through without a person.

            Args:
              quote_id: The quote_id of the option to order, from request_quote.
              rationale: One or two sentences on why this is the right order. It is logged.
            """
            args: dict[str, Any] = {"quote_id": quote_id, "rationale": rationale}
            shown = dict(args)
            if box.settings.agent_key_file:
                args["agent_signature"] = sign_order(box.settings.agent_key_file,
                                                     box.settings.mandate_token, quote_id)
                shown["agent_signature"] = SIGNATURE_SHOWN_AS
            result = await box._call("place_order", args, shown)
            if isinstance(result, dict) and "status" in result:
                if quote_id in box.options:
                    box.quotes.append(box.options[quote_id]["quote"])
                box.orders.append(result)
                box.outcome = result["status"]
                box.sink.publish("decision", status=result["status"], reasons=result.get("reasons", []),
                                 approval_id=result.get("approval_id"), order_id=result.get("order_id"),
                                 quote_id=quote_id, alternatives=result.get("alternatives", []))
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
            """Ask the buyer a question and wait for the answer. Use it when the server asks for
            something only the buyer knows, or when the request is unclear.

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
            box.budget.reset()  # the buyer is still here: a fresh step budget
            box.searches.reset()
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

        return [record_request, search_products, get_product, request_quote, place_order,
                get_approval_status, ask_buyer, get_audit_log]
