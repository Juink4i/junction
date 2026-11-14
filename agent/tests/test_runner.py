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
                                              "must_have": ["lactose-free"]}),
        lambda _: ("call", "search_products", {"product": "lactose-free milk", "amount": 1000,
                                               "unit": "L"}),
        lambda last: ("call", "request_quote", {"product_ids": [p["id"] for p in last["products"]],
                                                "amount": 1000, "unit": "L", "need_by": MONDAY}),
        lambda last: ("call", "place_order", {"quote_id": last["options"][0]["quote"]["quote_id"],
                                              "rationale": "Best option that arrives on time."}),
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
    for kind in ("run_start", "user", "request", "tool_call", "tool_result", "options", "decision", "waiting",
                 "agent", "run_end"):
        assert kind in kinds, kind


# The step budget: a run may make so many model calls since the buyer last said something.

def _search(_):
    return ("call", "search_products", {"product": "coffee"})


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


# The search cap: a few searches per buyer message, then the agent must report back.
# Calibrated on the audit log: every run that ended in an order found its product on the
# first search; runs that went on past five only found the wrong products.

def test_the_defaults_are_five_searches_and_fifteen_steps():
    settings = Settings(server_url="http://x", web_url=None, model="m", mandate_token="t")
    assert (settings.searches_per_input, settings.steps_per_input) == (5, 15)


async def test_the_sixth_search_is_answered_without_asking_the_server(fake):
    seen = []

    def stop_and_report(last):
        seen.append(last)
        return ("text", "Nothing fits; here is what I searched.")

    script = ScriptedLlm(steps=[_search] * 6 + [stop_and_report])
    settings = Settings(server_url=fake.mcp_url, web_url=None, model=script,
                        mandate_token="demo-cafe", steps_per_input=40)
    sink = EventSink(None, console=False)

    result = await run_buyer("Philippine coffee beans", settings, sink, make_ask([], interactive=False))

    assert _searches(sink.history) == 5
    assert seen[0]["status"] == "search_limit"
    assert "5 searches" in seen[0]["message"] and "tell the buyer" in seen[0]["message"]
    assert result.summary == "Nothing fits; here is what I searched."


async def test_each_buyer_answer_gives_fresh_searches(fake):
    script = ScriptedLlm(steps=[_search] * 5 + [lambda _: ("call", "ask_buyer", {"question": "Which origin?"})]
                         + [_search] * 5 + [lambda _: ("text", "Found Brazilian beans.")])
    settings = Settings(server_url=fake.mcp_url, web_url=None, model=script,
                        mandate_token="demo-cafe", steps_per_input=40)
    sink = EventSink(None, console=False)

    await run_buyer("coffee beans", settings, sink, make_ask(["brazil"], interactive=False))

    assert _searches(sink.history) == 10


async def test_a_refused_mandate_ends_the_run_with_the_onboarding_link(monkeypatch):
    from agent.mcp_link import MandateRefused

    class Refusing:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise MandateRefused("mandate_expired", "The mandate expired on 2026-01-01.",
                                 "http://localhost:8080/onboarding")

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr("agent.runner.TradeLink", Refusing)
    sink = EventSink(None, console=False)
    settings = Settings(server_url="unused", web_url=None, model=ScriptedLlm(steps=[]),
                        mandate_token="old-token")

    result = await run_buyer("Milk, please", settings, sink, make_ask([], interactive=False))

    assert result.outcome is None
    assert "expired on 2026-01-01" in result.mandate_problem
    note = next(e for e in sink.history if e["kind"] == "note")
    assert "http://localhost:8080/onboarding" in note["text"]
    assert sink.history[-1]["kind"] == "run_end"
