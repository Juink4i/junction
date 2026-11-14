import asyncio
import inspect
import threading
import time
from datetime import date, timedelta

import httpx
from google.adk.tools import FunctionTool

from agent.config import Settings
from agent.events import EventSink
from agent.mcp_link import TradeLink
from agent.tools import QuoteLine, Toolbox

MONDAY = (date.today() + timedelta(days=3)).isoformat()


def _box(link, answers=None, **kw):
    kw.setdefault("mandate_token", "demo-hotel")
    settings = Settings(server_url="unused", web_url=None, poll_every_s=0.1, **kw)
    sink = EventSink(None, console=False)

    async def ask(question):
        return (answers or {}).get("next")

    return Toolbox(link, settings, sink, ask), sink


def _tools(box):
    return {f.__name__: f for f in box.functions()}


def test_the_model_cannot_see_or_set_the_mandate():
    tools = _tools(_box(link=None)[0])
    assert "mandate_token" not in inspect.signature(tools["place_order"]).parameters
    decl = FunctionTool(tools["place_order"])._get_declaration()
    assert set(decl.parameters_json_schema["properties"]) == {"quote_id", "rationale", "confirm_unusual"}


async def _order_1000_litres(tools):
    quote = await tools["request_quote"](
        [QuoteLine(product_id="464201", amount=1000, unit="L")], MONDAY)
    return quote, await tools["place_order"](quote["quote_id"], "Cheapest on-time option.")


async def test_place_order_attaches_the_mandate_but_never_shows_it(fake):
    async with TradeLink(fake.mcp_url) as link:
        box, sink = _box(link)
        quote, result = await _order_1000_litres(_tools(box))
    assert quote["total_eur"] == 1560.0
    assert result["status"] == "pending_approval"
    calls = [e for e in sink.history if e["kind"] == "tool_call" and e["tool"] == "place_order"]
    assert calls[0]["args"]["mandate_token"] == "[signed mandate attached]"
    assert "demo-hotel" not in str(sink.history)


async def test_waits_for_a_person_to_approve(fake):
    async with TradeLink(fake.mcp_url) as link:
        box, sink = _box(link, approval_wait_s=10)
        tools = _tools(box)
        _, result = await _order_1000_litres(tools)

        def approve_soon():
            time.sleep(0.4)
            httpx.post(f"{fake.base_url}/approvals/{result['approval_id']}/approve")

        threading.Thread(target=approve_soon).start()
        status = await tools["get_approval_status"](result["approval_id"])
    assert status["status"] == "approved"
    assert status["decided_by"] == "procurement.manager@hotel.example"
    assert box.outcome == "approved"


async def test_stops_waiting_after_the_time_limit(fake):
    async with TradeLink(fake.mcp_url) as link:
        box, _ = _box(link, approval_wait_s=0.3)
        tools = _tools(box)
        _, result = await _order_1000_litres(tools)
        status = await tools["get_approval_status"](result["approval_id"])
    assert status["status"] == "pending"
    assert status["still_waiting"] is True
    assert box.outcome == "pending_approval"


async def test_unanswered_question_tells_the_agent_to_stop(fake):
    box, sink = _box(link=None)
    reply = await _tools(box)["ask_buyer"]("Is 200 L right?")
    assert reply["answered"] is False
    assert [e["kind"] for e in sink.history] == ["ask", "answer"]


async def test_bad_need_by_date_is_explained_not_raised(fake):
    async with TradeLink(fake.mcp_url) as link:
        box, _ = _box(link)
        out = await _tools(box)["request_quote"](
            [QuoteLine(product_id="464201", amount=10, unit="L")], "next Monday")
    assert out["error"]["code"] == "bad_date"


async def test_search_reports_count_and_products(fake):
    async with TradeLink(fake.mcp_url) as link:
        box, _ = _box(link)
        out = await _tools(box)["search_products"]("milk", "10400", ["FREE_FROM_LACTOSE"])
    assert out["count"] == len(out["products"]) >= 4


class RecordingLink:
    def __init__(self):
        self.calls = []

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return {"status": "confirmed", "order_id": "ord_1", "reasons": ["ok"]}


async def test_place_order_is_signed_by_the_agents_key_and_the_signature_is_hidden(tmp_path):
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agent.identity import ensure_agent_key, key_path

    public_pem = ensure_agent_key("k-0000", tmp_path)
    token = jwt.encode({"mandate_id": "mnd_k-0000_001", "agent_id": "agent-k-0000"},
                       Ed25519PrivateKey.generate(), algorithm="EdDSA", headers={"kid": "k-0000"})
    link = RecordingLink()
    box, sink = _box(link, mandate_token=token, agent_key_file=key_path("k-0000", tmp_path))
    await _tools(box)["place_order"]("q_1", "Cheapest on-time option.")

    sent = link.calls[0][1]
    payload = jwt.decode(sent["agent_signature"], serialization.load_pem_public_key(public_pem.encode()),
                         algorithms=["EdDSA"])
    assert payload == {"quote_id": "q_1", "mandate_id": "mnd_k-0000_001", "confirm_unusual": False}
    shown = next(e for e in sink.history if e["kind"] == "tool_call")["args"]
    assert shown["agent_signature"] == "[signed by the agent's key]"
    assert sent["agent_signature"] not in str(sink.history)


async def test_place_order_sends_no_signature_when_the_agent_has_no_key():
    link = RecordingLink()
    box, _ = _box(link)
    await _tools(box)["place_order"]("q_1", "Cheapest on-time option.")
    assert "agent_signature" not in link.calls[0][1]
