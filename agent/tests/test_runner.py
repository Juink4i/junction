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
