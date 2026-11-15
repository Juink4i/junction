"""The order box: POST /api/accounts/{id}/ask starts the buyer agent for that one account."""

import asyncio
import threading
import time

import httpx
import pytest
from starlette.testclient import TestClient

from server import fake_catalog
from web.app import create_app


class FakeAgent:
    """Stands in for `python -m agent`: records each run and finishes when the test says so."""

    def __init__(self, exit_code: int = 0, last_line: str = ""):
        self.runs: list[tuple[str, str]] = []
        self.done = threading.Event()
        self.exit_code, self.last_line = exit_code, last_line

    async def __call__(self, buyer: str, text: str) -> tuple[int, str]:
        self.runs.append((buyer, text))
        while not self.done.is_set():
            await asyncio.sleep(0.01)
        return self.exit_code, self.last_line


def make_client(world, agent, **kw):
    app = create_app(trade_http="http://trade.test", state_db=world.state_db,
                     mandate_dir=world.mandates, catalog=fake_catalog, frontend_dist=world.dist,
                     buyer_keys_dir=world.keys, buyers_dir=world.buyers, agent_launcher=agent, **kw)
    return TestClient(app)


def wait_idle(c, buyer: str) -> None:
    for _ in range(200):
        if not c.get(f"/api/accounts/{buyer}/ask").json()["running"]:
            return
        time.sleep(0.01)
    pytest.fail("the run never finished")


def test_ask_starts_the_agent_for_that_account(world):
    agent = FakeAgent()
    with make_client(world, agent) as c:
        res = c.post("/api/accounts/hotel/ask", json={"text": "  1,000 L lactose-free milk by Monday "})
        assert res.status_code == 202
        assert c.get("/api/accounts/hotel/ask").json() == {"running": True}
        assert c.get("/api/accounts/cafe/ask").json() == {"running": False}
        agent.done.set()
        wait_idle(c, "hotel")
    assert agent.runs == [("hotel", "1,000 L lactose-free milk by Monday")]


def test_one_run_per_account_and_a_cap_on_all_runs(world):
    agent = FakeAgent()
    with make_client(world, agent, max_agent_runs=2) as c:
        assert c.post("/api/accounts/hotel/ask", json={"text": "milk"}).status_code == 202
        busy = c.post("/api/accounts/hotel/ask", json={"text": "more milk"})
        assert busy.status_code == 409 and busy.json()["code"] == "agent_busy"
        assert c.post("/api/accounts/cafe/ask", json={"text": "milk"}).status_code == 202
        full = c.post("/api/accounts/school/ask", json={"text": "milk"})
        assert full.status_code == 429 and full.json()["code"] == "too_many_runs"
        agent.done.set()
        wait_idle(c, "hotel")
        wait_idle(c, "cafe")
        assert c.post("/api/accounts/school/ask", json={"text": "milk"}).status_code == 202


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}, {"text": "x" * 301}, {}, {"text": 5}])
def test_bad_requests_start_nothing(world, body):
    agent = FakeAgent()
    with make_client(world, agent) as c:
        res = c.post("/api/accounts/hotel/ask", json=body)
        assert res.status_code == 400 and res.json()["code"] == "bad_request"
    assert agent.runs == []


def test_unknown_account_starts_nothing(world):
    agent = FakeAgent()
    with make_client(world, agent) as c:
        assert c.post("/api/accounts/nobody/ask", json={"text": "milk"}).status_code == 404
        assert c.get("/api/accounts/nobody/ask").status_code == 404
    assert agent.runs == []


def test_a_failed_run_says_so_in_that_accounts_chat(world):
    agent = FakeAgent(exit_code=3, last_line="The trade server refused the agent: mandate expired")
    agent.done.set()
    with make_client(world, agent) as c:
        assert c.post("/api/accounts/cafe/ask", json={"text": "milk"}).status_code == 202
        wait_idle(c, "cafe")
        cafe = c.get("/api/events", params={"buyer": "cafe"}).json()
        hotel = c.get("/api/events", params={"buyer": "hotel"}).json()
    said = [e["text"] for e in cafe if e["kind"] == "agent"]
    assert said == ["The agent stopped: The trade server refused the agent: mandate expired"]
    assert not any(e["kind"] == "agent" for e in hotel)


def test_ask_can_be_switched_off(world, monkeypatch):
    monkeypatch.setenv("ASK_AGENT", "off")
    agent = FakeAgent()
    with make_client(world, agent) as c:
        res = c.post("/api/accounts/hotel/ask", json={"text": "milk"})
        assert res.status_code == 403 and res.json()["code"] == "ask_off"
    assert agent.runs == []


def test_the_real_launcher_never_hands_the_agent_the_valio_key(monkeypatch):
    from web import ask

    seen = {}

    async def fake_exec(*args, env=None, **kw):
        seen["args"], seen["env"] = args, env

        class Proc:
            returncode = 0
            stderr = None

            async def wait(self):
                return 0

            async def communicate(self):
                return b"", b""

        return Proc()

    monkeypatch.setenv("VALIO_API_KEY", "valio-secret-123")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-456")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    code, _ = asyncio.run(ask.launch_agent("hotel", "--gullible milk", mcp_url="http://t/mcp",
                                           web_url="http://w"))
    assert code == 0
    assert "VALIO_API_KEY" not in seen["env"]
    assert seen["env"]["GEMINI_API_KEY"] == "gemini-key-456"
    args = list(seen["args"])
    # The request goes after "--", so text that looks like a flag stays text.
    assert args[-2:] == ["--", "--gullible milk"]
    assert args[args.index("--buyer") + 1] == "hotel"
    assert "--gullible" not in args[:-1]
