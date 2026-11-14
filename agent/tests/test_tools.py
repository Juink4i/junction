import inspect
import threading
import time
from datetime import date, timedelta

import httpx
import pytest
from google.adk.tools import FunctionTool

from agent.config import Settings
from agent.events import EventSink
from agent.mcp_link import MandateRefused, TradeLink
from agent.tools import Toolbox, option_cards

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


def test_the_model_cannot_see_or_set_the_mandate_or_the_preferences():
    tools = _tools(_box(link=None)[0])
    for name in ("search_products", "request_quote", "place_order"):
        parameters = inspect.signature(tools[name]).parameters
        assert "mandate_token" not in parameters and "preferences" not in parameters
    decl = FunctionTool(tools["place_order"])._get_declaration()
    assert set(decl.parameters_json_schema["properties"]) == {"quote_id", "rationale"}
    assert "present_options" not in tools


async def _order_1000_litres(tools):
    found = await tools["search_products"]("lactose-free milk", None, 1000, "L")
    priced = await tools["request_quote"]([p["id"] for p in found["products"]], 1000, "L", MONDAY)
    best = priced["options"][0]
    return best, await tools["place_order"](best["quote"]["quote_id"], "Best option that arrives on time.")


async def test_the_mandate_travels_with_the_connection_and_is_never_shown(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        box, sink = _box(link)
        best, result = await _order_1000_litres(_tools(box))
    assert best["quote"]["total_eur"] == 1560.0
    assert result["status"] == "pending_approval"
    call = next(e for e in sink.history if e["kind"] == "tool_call" and e["tool"] == "place_order")
    assert set(call["args"]) == {"quote_id", "rationale"}
    assert "demo-hotel" not in str(sink.history)
    assert box.quotes == [best["quote"]]


async def test_a_mandate_the_server_does_not_know_is_refused_before_connecting(fake):
    with pytest.raises(MandateRefused) as refused:
        async with TradeLink(fake.mcp_url, "not-a-mandate"):
            pass
    assert refused.value.code == "mandate_invalid"
    assert refused.value.onboarding_url.endswith("/onboarding")


async def test_search_returns_what_fits_and_what_was_dropped(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        box, _ = _box(link)
        out = await _tools(box)["search_products"]("lactose-free milk")
    assert [p["id"] for p in out["products"]] == ["464201", "465039", "463038", "464179"]
    assert {d["id"] for d in out["dropped"]} == {"460101", "460104", "460105"}


async def test_the_servers_question_reaches_the_agent(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        box, _ = _box(link)
        out = await _tools(box)["search_products"]("milk", ["organic"])
    assert (out["status"], out["unknown"]) == ("needs_clarification", ["organic"])
    assert "lactose-free" in out["known_properties"]


async def test_the_options_card_comes_from_the_servers_ranking(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        box, sink = _box(link)
        tools = _tools(box)
        found = await tools["search_products"]("lactose-free milk")
        await tools["request_quote"]([p["id"] for p in found["products"]], 1000, "L", MONDAY)
    card = next(e for e in sink.history if e["kind"] == "options")
    assert [o["label"] for o in card["options"]] == ["best", "better", "good"]
    assert card["options"][0]["product_id"] == "464201"
    assert card["options"][0]["trade_off"].endswith("Needs a person's approval.")
    assert len(box.options) == 4


def test_a_split_option_becomes_one_card():
    option = {"label": "split", "trade_off": "700 from A + 300 from B.",
              "expected": {"status": "confirmed", "reasons": []},
              "quote": {"total_eur": 1578.0, "lines": [
                  {"product_id": "A", "name": "Milk A", "units": 700, "sales_unit": "1 L", "covers": 700.0,
                   "content_unit": "L", "available_date": "2026-11-16"},
                  {"product_id": "B", "name": "Milk B", "units": 60, "sales_unit": "5 L", "covers": 300.0,
                   "content_unit": "L", "available_date": "2026-11-17"}]}}
    (card,) = option_cards([option])
    assert (card["label"], card["name"], card["covers"], card["total_eur"]) == (
        "split", "Milk A + Milk B", 1000.0, 1578.0)
    assert (card["units"], card["available_date"]) == (None, "2026-11-17")
    assert card["trade_off"] == "700 from A + 300 from B."


async def test_waits_for_a_person_to_approve(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
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
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        box, _ = _box(link, approval_wait_s=0.3)
        tools = _tools(box)
        _, result = await _order_1000_litres(tools)
        status = await tools["get_approval_status"](result["approval_id"])
    assert status["status"] == "pending"
    assert status["still_waiting"] is True
    assert box.outcome == "pending_approval"


async def test_unanswered_question_tells_the_agent_to_stop(fake):
    box, sink = _box(link=None)
    reply = await _tools(box)["ask_buyer"]("By which date do you need it?")
    assert reply["answered"] is False
    assert [e["kind"] for e in sink.history] == ["ask", "answer"]


async def test_bad_need_by_date_is_explained_not_raised(fake):
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        box, _ = _box(link)
        out = await _tools(box)["request_quote"](["464201"], 10, "L", "next Monday")
    assert out["error"]["code"] == "bad_date"


class RecordingLink:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"status": "confirmed", "order_id": "ord_1", "reasons": ["ok"]}

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return self.result


async def test_the_kitchens_preferences_are_attached_by_code():
    link = RecordingLink({"status": "ok", "options": [], "not_offered": []})
    box, _ = _box(link, profile={"priorities": ["finnish", "price"], "pack_size": "small"})
    await _tools(box)["request_quote"](["464201"], 40, "L", MONDAY)
    assert link.calls == [("request_quote", {
        "product_ids": ["464201"], "amount": 40, "unit": "L", "need_by": MONDAY,
        "preferences": {"priorities": ["finnish", "price"], "pack_size": "small"}})]


async def test_a_kitchen_without_a_profile_sends_no_preferences():
    link = RecordingLink({"status": "ok", "options": [], "not_offered": []})
    box, _ = _box(link)
    await _tools(box)["request_quote"](["464201"], 40, "L", MONDAY)
    assert "preferences" not in link.calls[0][1]


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
    await _tools(box)["place_order"]("q_1", "Best option that arrives on time.")

    sent = link.calls[0][1]
    assert "mandate_token" not in sent
    payload = jwt.decode(sent["agent_signature"], serialization.load_pem_public_key(public_pem.encode()),
                         algorithms=["EdDSA"])
    assert payload == {"quote_id": "q_1", "mandate_id": "mnd_k-0000_001"}
    shown = next(e for e in sink.history if e["kind"] == "tool_call")["args"]
    assert shown["agent_signature"] == "[signed by the agent's key]"
    assert sent["agent_signature"] not in str(sink.history)


async def test_place_order_sends_no_signature_when_the_agent_has_no_key():
    link = RecordingLink()
    box, _ = _box(link)
    await _tools(box)["place_order"]("q_1", "Best option that arrives on time.")
    assert link.calls[0][1] == {"quote_id": "q_1", "rationale": "Best option that arrives on time."}
