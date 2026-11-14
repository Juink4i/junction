"""A temp state.db with the three demo buyers and a few real orders, shared by the web tests."""

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from starlette.testclient import TestClient

from server import fake_catalog
from server.db import connect
from server.make_mandate import issue_demo_mandates
from server.service import Service
from web.app import create_app

NEED_BY = (date.today() + timedelta(days=3)).isoformat()


class Trade:
    """Stands in for the trade server's HTTP endpoints, deciding approvals in the temp DB."""

    def __init__(self, svc: Service):
        self.svc = svc
        self.calls: list[tuple[str, str, bytes]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, request.content))
        parts = request.url.path.strip("/").split("/")
        if request.method == "POST" and len(parts) == 3 and parts[0] == "approvals":
            body = json.loads(request.content) if request.content else {}
            result = self.svc.decide_approval(parts[1], parts[2] == "approve", body.get("decided_by"))
            return httpx.Response(404 if "code" in result else 200, json=result)
        return httpx.Response(404, json={"code": "not_found"})


@pytest.fixture
def world(tmp_path):
    conn = connect(tmp_path / "state.db")
    tokens = issue_demo_mandates(conn)
    mandates = tmp_path / "mandates"
    mandates.mkdir()
    for buyer_id, token in tokens.items():
        (mandates / f"{buyer_id}.jwt").write_text(token)
    svc = Service(conn, fake_catalog, lambda: datetime.now(timezone.utc))

    def order(buyer: str, product_id: str, litres: float) -> dict:
        q = svc.request_quote([{"product_id": product_id, "amount": litres, "unit": "L"}], NEED_BY)
        return {**svc.place_order(q["quote_id"], tokens[buyer], f"test {buyer}"), "quote_id": q["quote_id"]}

    hotel = order("hotel", "464201", 1000)        # €1,560: over the hotel's €800 line limit
    cafe_ok = order("cafe", "464201", 20)         # small and usual: confirmed
    cafe_wait = order("cafe", "463038", 20)       # cut-off passed: a person must approve
    assert hotel["status"] == "pending_approval"
    assert cafe_ok["status"] == "confirmed"
    assert cafe_wait["status"] == "pending_approval"

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>SPA shell</html>")
    (dist / "assets" / "app.js").write_text("console.log('app')")

    class World:
        pass

    w = World()
    w.conn, w.svc, w.tokens = conn, svc, tokens
    w.hotel, w.cafe_ok, w.cafe_wait = hotel, cafe_ok, cafe_wait
    w.state_db, w.mandates, w.dist = tmp_path / "state.db", mandates, dist
    w.keys = tmp_path / "buyer_keys"
    w.trade = Trade(svc)
    yield w
    conn.close()


@pytest.fixture
def client(world):
    app = create_app(trade_http="http://trade.test", state_db=world.state_db,
                     mandate_dir=world.mandates, catalog=fake_catalog, frontend_dist=world.dist,
                     buyer_keys_dir=world.keys)
    with TestClient(app) as c:
        real = c.app.state.http
        c.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(world.trade))
        yield c
        c.app.state.http = real
