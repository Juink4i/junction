import json
import re
from datetime import date, timedelta

import httpx
import pytest
from starlette.testclient import TestClient

from agent.mcp_link import TradeLink
from web.app import create_app

MONDAY = (date.today() + timedelta(days=3)).isoformat()


@pytest.fixture
def client(fake):
    with TestClient(create_app(trade_http=fake.base_url)) as c:
        yield c


async def _pending_order(fake) -> str:
    async with TradeLink(fake.mcp_url, "demo-hotel") as link:
        priced = await link.call("request_quote", {"product_ids": ["464201"], "amount": 1000,
                                                   "unit": "L", "need_by": MONDAY})
        r = await link.call("place_order", {"quote_id": priced["options"][0]["quote"]["quote_id"],
                                            "rationale": "test"})
    return r["approval_id"]


@pytest.mark.parametrize("path,title", [("/", "Trusted Trade"), ("/approvals", "Approvals"),
                                        ("/log", "Decision log"), ("/chat", "Agent")])
def test_pages_load(client, path, title):
    res = client.get(path)
    assert res.status_code == 200
    assert title in res.text


@pytest.mark.parametrize("path", ["/", "/approvals", "/log", "/chat", "/onboarding"])
def test_every_page_finds_its_built_scripts_and_styles(client, path):
    # The pages are built from web/ui (npm run build). A missing or stale build shows here.
    page = client.get(path).text
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', page)
    assert any(a.endswith(".js") for a in assets) and any(a.endswith(".css") for a in assets)
    for asset in assets:
        assert client.get(asset).status_code == 200, asset


async def test_approve_from_the_phone_page(client, fake):
    approval_id = await _pending_order(fake)
    pending = client.get("/api/approvals").json()
    assert [a["approval_id"] for a in pending] == [approval_id]
    assert pending[0]["reasons"]

    res = client.post(f"/api/approvals/{approval_id}/approve")
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert client.get("/api/approvals").json() == []


async def test_reject_from_the_phone_page(client, fake):
    approval_id = await _pending_order(fake)
    assert client.post(f"/api/approvals/{approval_id}/reject").json()["status"] == "rejected"


async def test_log_and_verify_turn_red_after_tampering(client, fake):
    await _pending_order(fake)
    assert len(client.get("/api/log").json()) >= 3
    assert client.get("/api/log/verify").json() == {"ok": True}
    httpx.post(f"{fake.base_url}/_fake/tamper/2")  # someone edits row 2 by hand
    assert client.get("/api/log/verify").json() == {"ok": False, "broken_at_seq": 2}


def test_server_down_gives_a_clear_error():
    with TestClient(create_app(trade_http="http://127.0.0.1:9")) as c:
        res = c.get("/api/approvals")
    assert res.status_code == 502
    assert res.json()["code"] == "server_unreachable"


def test_events_are_kept_and_replayed(client):
    client.post("/api/events", json={"kind": "agent", "text": "hello"})
    client.post("/api/events", json={"kind": "note", "text": "second"})
    history = client.get("/api/events").json()
    assert [e["text"] for e in history] == ["hello", "second"]
    assert [e["id"] for e in history] == [1, 2]

    with client.stream("GET", "/api/events/stream?replay_only=1") as stream:
        body = "".join(stream.iter_text())
    frames = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert [f["text"] for f in frames] == ["hello", "second"]

    client.post("/api/events/clear")
    assert client.get("/api/events").json() == []
