"""End to end without Gemini: ADK runs a scripted model against the fake trade server."""

import threading
import time
from datetime import date, timedelta

import httpx

from agent.config import Settings
from agent.events import EventSink
from agent.runner import make_ask, run_buyer
from agent.tests.scripted_llm import ScriptedLlm

MONDAY = (date.today() + timedelta(days=3)).isoformat()


def approve_when_pending(base_url: str) -> None:
    def loop():
        for _ in range(100):
            pending = httpx.get(f"{base_url}/approvals").json()
            if pending:
                httpx.post(f"{base_url}/approvals/{pending[0]['approval_id']}/approve")
                return
            time.sleep(0.1)

    threading.Thread(target=loop, daemon=True).start()


async def test_hotel_order_goes_to_a_person_and_is_approved(fake):
    script = ScriptedLlm(steps=[
        lambda _: ("call", "record_request", {"product": "lactose-free milk", "amount": 1000,
                                              "unit": "L", "need_by": MONDAY,
                                              "must_have": ["FREE_FROM_LACTOSE"]}),
        lambda _: ("call", "search_products", {"text": "", "category": "10400",
                                               "must_have_tags": ["FREE_FROM_LACTOSE"]}),
        lambda _: ("call", "request_quote", {"lines": [{"product_id": "464201", "amount": 1000,
                                                        "unit": "L"}], "need_by": MONDAY}),
        lambda last: ("call", "place_order", {"quote_id": last["quote_id"],
                                              "rationale": "Cheapest option that arrives on time."}),
        lambda last: ("call", "get_approval_status", {"approval_id": last["approval_id"]}),
        lambda _: ("text", "Ordered 1,000 × 1 L. Approved by the procurement manager."),
    ])
    settings = Settings(server_url=fake.mcp_url, web_url=None, model=script,
                        mandate_token="demo-hotel", approval_wait_s=10, poll_every_s=0.1)
    sink = EventSink(None, console=False)
    approve_when_pending(fake.base_url)

    result = await run_buyer("I need 1,000 litres of lactose-free milk by Monday", settings, sink,
                             make_ask([], interactive=False))

    assert result.error is None
    assert result.outcome == "approved"
    assert result.request["amount"] == 1000
    assert result.orders[0]["status"] == "pending_approval"
    assert result.summary.startswith("Ordered 1,000")
    kinds = [e["kind"] for e in sink.history]
    for kind in ("run_start", "user", "request", "tool_call", "tool_result", "decision", "waiting",
                 "agent", "run_end"):
        assert kind in kinds, kind


# The step budget: a run may make so many model calls since the buyer last said something.

def _search(_):
    return ("call", "search_products", {"text": "coffee"})


def _searches(events):
    return sum(1 for e in events if e["kind"] == "tool_call" and e["tool"] == "search_products")


async def test_a_run_stops_gently_when_the_step_budget_is_used(fake):
    script = ScriptedLlm(steps=[_search] * 10 + [lambda _: ("text", "never reached")])
    settings = Settings(server_url=fake.mcp_url, web_url=None, model=script,
                        mandate_token="demo-cafe", steps_per_input=5)
    sink = EventSink(None, console=False)

    result = await run_buyer("Philippine coffee beans", settings, sink, make_ask([], interactive=False))

    assert result.error is None  # a plain stop, not an ADK error
    assert _searches(sink.history) == 5
    assert "5 steps" in result.summary and "No order was placed" in result.summary
    assert sink.history[-1]["kind"] == "run_end"


async def test_each_buyer_answer_gives_the_agent_a_fresh_step_budget(fake):
    script = ScriptedLlm(steps=[_search, _search, _search,
                                lambda _: ("call", "ask_buyer", {"question": "Which origin?"}),
                                _search, _search, _search,
                                lambda _: ("text", "Found Brazilian beans.")])
    settings = Settings(server_url=fake.mcp_url, web_url=None, model=script,
                        mandate_token="demo-cafe", steps_per_input=4)
    sink = EventSink(None, console=False)

    result = await run_buyer("coffee beans", settings, sink, make_ask(["brazil"], interactive=False))

    # Without the reset the 5th model call would be over budget.
    assert result.error is None
    assert _searches(sink.history) == 6
    assert result.summary == "Found Brazilian beans."


async def test_no_answer_does_not_reset_the_step_budget(fake):
    script = ScriptedLlm(steps=[_search, _search,
                                lambda _: ("call", "ask_buyer", {"question": "Which origin?"}),
                                _search, _search, _search, lambda _: ("text", "never reached")])
    settings = Settings(server_url=fake.mcp_url, web_url=None, model=script,
                        mandate_token="demo-cafe", steps_per_input=4)
    sink = EventSink(None, console=False)

    result = await run_buyer("coffee beans", settings, sink, make_ask([], interactive=False))

    assert _searches(sink.history) == 3
    assert "4 steps" in result.summary
