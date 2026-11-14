"""Per-account views: each buyer sees only its own orders, approvals, log rows and events."""

import json

from starlette.testclient import TestClient

from server import fake_catalog
from web.app import create_app
from web.tests.world import KID, NEED_BY, SOINTU


def test_accounts_list_mandates_without_tokens(client, world):
    res = client.get("/api/accounts")
    assert res.status_code == 200
    accounts = res.json()
    # Demo buyers first, then onboarded kitchens by name (Café Sointu before Päiväkoti Aurinko).
    assert [a["buyer_id"] for a in accounts] == ["hotel", "cafe", "school", SOINTU, KID]
    hotel = accounts[0]
    assert hotel["name"] == "Hotel Chain Oy / Helsinki Central"
    assert hotel["mandate"]["auto_approve"]["max_line_eur"] == 800
    assert all(a["mandate_verified"] is True and a["mandate_problem"] is None for a in accounts)
    for token in world.tokens.values():
        assert token not in res.text
        assert token.split(".")[2] not in res.text  # not even the signature


def test_account_with_missing_or_bad_mandate(client, world):
    (world.mandates / "school.jwt").unlink()
    (world.mandates / "cafe.jwt").write_text(world.tokens["hotel"][:-4] + "AAAA")
    accounts = {a["buyer_id"]: a for a in client.get("/api/accounts").json()}
    assert accounts["school"]["mandate"] is None
    assert accounts["school"]["mandate_verified"] is False
    assert accounts["cafe"]["mandate_verified"] is False
    assert "signature" in accounts["cafe"]["mandate_problem"]


def test_unknown_account_is_404(client):
    for path in ("/api/accounts/nobody/orders", "/api/accounts/nobody/approvals",
                 "/api/accounts/nobody/log", "/api/accounts/nobody/orders/ord_x"):
        res = client.get(path)
        assert res.status_code == 404
        assert res.json()["code"] == "account_not_found"


def test_orders_are_per_account(client, world):
    hotel = client.get("/api/accounts/hotel/orders").json()
    assert [o["order_id"] for o in hotel] == [world.hotel["order_id"]]
    order = hotel[0]
    assert order["status"] == "pending_approval"
    assert order["quote_id"] == world.hotel["quote_id"]
    assert order["rationale"] == "test hotel"
    assert order["reasons"] and isinstance(order["reasons"], list)
    assert order["total_eur"] == 1560.0
    assert order["total_with_tax_eur"] > order["total_eur"]
    assert order["lines"][0]["product_id"] == "464201"
    assert order["delivery_date"] == NEED_BY
    assert order["expires_at"]
    assert order["approval"]["approval_id"] == world.hotel["approval_id"]
    assert order["approval"]["status"] == "pending"
    assert order["approval"]["approvers"] == ["procurement.manager@hotel.example"]
    assert order["approval"]["decided_by"] is None

    cafe = client.get("/api/accounts/cafe/orders").json()
    assert [o["order_id"] for o in cafe] == [world.cafe_wait["order_id"], world.cafe_ok["order_id"]]
    assert cafe[1]["approval"] is None
    assert client.get("/api/accounts/school/orders").json() == []


def test_one_order_with_log_and_product_details(client, world):
    res = client.get(f"/api/accounts/hotel/orders/{world.hotel['order_id']}")
    assert res.status_code == 200
    order = res.json()
    assert order["order_id"] == world.hotel["order_id"]
    product = order["lines"][0]["product"]
    assert product["category"] == "10400"
    assert product["tags"] == ["FREE_FROM_LACTOSE"]
    assert product["allergens_contains"] == ["BM"]
    assert product["allergen_info_missing"] is False
    assert "delivery_reliability" in product and "carbon_kg_per_kg" in product
    actions = [row["action"] for row in order["log"]]
    assert "request_quote" in actions and "decision:pending_approval" in actions
    seqs = [row["seq"] for row in order["log"]]
    assert seqs == sorted(seqs)
    assert set(order["log"][0]) == {"seq", "time", "actor", "action", "reason", "prev_hash", "hash"}


def test_missing_product_gives_null_details(world):
    class Broken:
        def get_product(self, product_id):
            raise RuntimeError("catalog down")

    app = create_app(trade_http="http://trade.test", state_db=world.state_db,
                     mandate_dir=world.mandates, catalog=Broken(), frontend_dist=world.dist)
    with TestClient(app) as c:
        order = c.get(f"/api/accounts/hotel/orders/{world.hotel['order_id']}").json()
    assert order["lines"][0]["product"] is None


def test_another_accounts_order_looks_like_it_does_not_exist(client, world):
    res = client.get(f"/api/accounts/hotel/orders/{world.cafe_ok['order_id']}")
    assert res.status_code == 404
    assert res.json()["code"] == "order_not_found"
    missing = client.get("/api/accounts/hotel/orders/ord_nope")
    assert missing.status_code == 404
    assert missing.json()["code"] == "order_not_found"
    assert set(res.json()) == {"code", "message", "retryable"}
    assert res.json() == missing.json()  # indistinguishable from an order that does not exist


def test_approvals_are_per_account(client, world):
    hotel = client.get("/api/accounts/hotel/approvals").json()
    assert [a["approval_id"] for a in hotel] == [world.hotel["approval_id"]]
    assert set(hotel[0]) == {"approval_id", "order_id", "quote_id", "status", "buyer", "approvers",
                             "reasons", "agent_rationale", "lines", "total_eur", "total_with_tax_eur",
                             "created_at"}
    assert hotel[0]["buyer"] == "Hotel Chain Oy / Helsinki Central"
    cafe = client.get("/api/accounts/cafe/approvals").json()
    assert [a["approval_id"] for a in cafe] == [world.cafe_wait["approval_id"]]


def test_cannot_decide_another_accounts_approval(client, world):
    for action in ("approve", "reject"):
        res = client.post(f"/api/accounts/hotel/approvals/{world.cafe_wait['approval_id']}/{action}")
        assert res.status_code == 404
        assert res.json()["code"] == "approval_not_found"
    missing = client.post("/api/accounts/hotel/approvals/apr_nope/approve")
    assert missing.status_code == 404 and missing.json() == res.json()
    res = client.post("/api/accounts/nobody/approvals/apr_x/approve")
    assert res.json()["code"] == "account_not_found"
    assert world.trade.calls == []
    assert [a["approval_id"] for a in client.get("/api/accounts/cafe/approvals").json()] == \
        [world.cafe_wait["approval_id"]]


def test_bad_action_is_404(client, world):
    res = client.post(f"/api/accounts/hotel/approvals/{world.hotel['approval_id']}/delete")
    assert res.status_code == 404
    assert res.json()["code"] == "bad_action"
    assert world.trade.calls == []


def test_own_approval_is_forwarded(client, world):
    approval_id = world.hotel["approval_id"]
    res = client.post(f"/api/accounts/hotel/approvals/{approval_id}/approve",
                      json={"decided_by": "chef@hotel.example"})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert res.json()["decided_by"] == "chef@hotel.example"
    method, path, body = world.trade.calls[0]
    assert (method, path) == ("POST", f"/approvals/{approval_id}/approve")
    assert json.loads(body) == {"decided_by": "chef@hotel.example"}

    assert client.get("/api/accounts/hotel/approvals").json() == []
    order = client.get("/api/accounts/hotel/orders").json()[0]
    assert order["status"] == "confirmed"
    assert order["approval"]["status"] == "approved"
    assert order["approval"]["decided_by"] == "chef@hotel.example"
    assert order["approval"]["decided_at"]


def test_log_is_per_account(client, world):
    hotel = client.get("/api/accounts/hotel/log").json()
    assert hotel
    assert {r["order_id"] for r in hotel if r["order_id"]} == {world.hotel["order_id"]}
    assert {r["quote_id"] for r in hotel} == {world.hotel["quote_id"]}
    assert set(hotel[0]) == {"seq", "time", "actor", "action", "reason", "prev_hash", "hash",
                             "order_id", "quote_id"}
    assert [r["seq"] for r in hotel] == sorted(r["seq"] for r in hotel)

    cafe = client.get("/api/accounts/cafe/log").json()
    cafe_quotes = {world.cafe_ok["quote_id"], world.cafe_wait["quote_id"]}
    assert {r["quote_id"] for r in cafe} == cafe_quotes
    assert not {r["seq"] for r in cafe} & {r["seq"] for r in hotel}
    assert client.get("/api/accounts/school/log").json() == []


def _options(world, buyer, litres):
    svc = world.svc
    return svc.request_quote(svc.authenticate(world.tokens[buyer]), ["464201", "463038"], litres,
                             "L", NEED_BY)["options"]


def test_log_shows_every_option_quoted_not_only_the_ordered_one(client, world):
    options = _options(world, "school", 20)
    assert len(options) >= 2
    logged = {r["quote_id"] for r in client.get("/api/accounts/school/log").json()}
    assert {o["quote"]["quote_id"] for o in options} <= logged
    assert not logged & {r["quote_id"] for r in client.get("/api/accounts/cafe/log").json()}


def test_an_order_replaced_by_another_option_is_withdrawn_not_rejected(client, world):
    token = world.tokens["hotel"]
    first, second = (o["quote"]["quote_id"] for o in _options(world, "hotel", 1000)[:2])
    waiting = world.svc.place_order(first, token, "first choice")
    assert waiting["status"] == "pending_approval"
    assert world.svc.place_order(second, token, "the other option")["status"] != "rejected"

    order = client.get(f"/api/accounts/hotel/orders/{waiting['order_id']}").json()
    assert order["status"] == "withdrawn"
    assert order["approval"]["status"] == "withdrawn"
    listed = {o["order_id"]: o["status"] for o in client.get("/api/accounts/hotel/orders").json()}
    assert listed[waiting["order_id"]] == "withdrawn"
    assert world.hotel["order_id"] in listed and listed[world.hotel["order_id"]] == "pending_approval"


def test_new_writes_show_up(client, world):
    q = world.quote(world.tokens["school"], "464201", 200)
    r = world.svc.place_order(q["quote_id"], world.tokens["school"], "school milk")
    orders = client.get("/api/accounts/school/orders").json()
    assert [o["order_id"] for o in orders] == [r["order_id"]]


def test_events_filter_by_buyer(client):
    client.post("/api/events", json={"kind": "agent", "text": "hotel says", "buyer": "hotel"})
    client.post("/api/events", json={"kind": "agent", "text": "cafe says", "buyer": "cafe"})
    client.post("/api/events", json={"kind": "note", "text": "no buyer"})
    assert [e["text"] for e in client.get("/api/events?buyer=hotel").json()] == ["hotel says"]
    assert len(client.get("/api/events").json()) == 3

    with client.stream("GET", "/api/events/stream?replay_only=1&buyer=cafe") as stream:
        body = "".join(stream.iter_text())
    frames = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert [f["text"] for f in frames] == ["cafe says"]


def test_live_stream_filter_lets_clear_through():
    from web.app import buyer_filter
    keep = buyer_filter("hotel")
    assert keep({"kind": "clear"})
    assert keep({"kind": "agent", "buyer": "hotel"})
    assert not keep({"kind": "agent", "buyer": "cafe"})
    assert not keep({"kind": "agent"})
    assert buyer_filter(None)({"kind": "agent", "buyer": "cafe"})


def test_info_reports_active_buyer(client):
    assert client.get("/api/info").json()["active_buyer"] is None
    client.post("/api/events", json={"kind": "run_start", "buyer": "hotel"})
    assert client.get("/api/info").json()["active_buyer"] == "hotel"
    client.post("/api/events", json={"kind": "agent", "buyer": "cafe", "text": "x"})
    assert client.get("/api/info").json()["active_buyer"] == "hotel"
    client.post("/api/events", json={"kind": "scene", "buyer": "cafe", "title": "Cafe"})
    assert client.get("/api/info").json()["active_buyer"] == "cafe"
    info = client.get("/api/info").json()
    assert info["trade_http"] == "http://trade.test"
    client.post("/api/events/clear")
    assert client.get("/api/info").json()["active_buyer"] is None


def test_frontend_is_served_with_spa_fallback(client):
    res = client.get("/app", follow_redirects=False)
    assert res.status_code in (301, 302, 307, 308)
    assert res.headers["location"].endswith("/app/")
    assert "SPA shell" in client.get("/app/").text
    assert "SPA shell" in client.get("/app/accounts/hotel/orders").text
    js = client.get("/app/assets/app.js")
    assert js.status_code == 200 and "console.log" in js.text
    assert "Trusted Trade" in client.get("/").text  # the old stage page is unchanged


def test_frontend_not_built(world, tmp_path):
    app = create_app(trade_http="http://trade.test", state_db=world.state_db,
                     mandate_dir=world.mandates, catalog=fake_catalog,
                     frontend_dist=tmp_path / "no-dist")
    with TestClient(app) as c:
        res = c.get("/app/")
        assert res.status_code == 404
        assert "Frontend not built" in res.text
        assert c.get("/app/anything").status_code == 404


def test_missing_state_db_is_a_clear_error(world, tmp_path):
    app = create_app(trade_http="http://trade.test", state_db=tmp_path / "missing.db",
                     mandate_dir=world.mandates, catalog=fake_catalog, frontend_dist=world.dist)
    with TestClient(app) as c:
        res = c.get("/api/accounts")
    assert res.status_code == 503
    assert res.json()["code"] == "state_db_unavailable"
    assert not (tmp_path / "missing.db").exists()


def test_onboarded_kitchen_is_an_account(client, world):
    res = client.get("/api/accounts")
    accounts = {a["buyer_id"]: a for a in res.json()}
    kid = accounts[KID]
    assert kid["name"] == "Päiväkoti Aurinko"
    assert kid["mandate_verified"] is True and kid["mandate_problem"] is None
    assert kid["mandate"]["mandate_id"] == f"mnd_{KID}_001"
    assert "PUBLIC KEY" in kid["mandate"]["agent_key"]  # the agent's public half, not a secret
    assert kid["mandate"]["budget"] == {"period": "week", "max_eur": 150}
    assert kid["mandate"]["usual_orders"][0]["amount"] == 40
    assert accounts[SOINTU]["mandate_verified"] is True
    for buyer_id in (KID, SOINTU):
        token = (world.buyers / buyer_id / "mandate.jwt").read_text()
        assert token.split(".")[2] not in res.text
    assert "PRIVATE" not in res.text


def test_onboarded_kitchen_sees_only_its_own(client, world):
    order_id = world.kid["order_id"]
    assert [o["order_id"] for o in client.get(f"/api/accounts/{KID}/orders").json()] == [order_id]
    assert order_id not in [o["order_id"] for o in client.get("/api/accounts/hotel/orders").json()]
    assert client.get(f"/api/accounts/hotel/orders/{order_id}").status_code == 404
    assert client.get(f"/api/accounts/{KID}/orders/{world.hotel['order_id']}").status_code == 404
    assert client.get(f"/api/accounts/{KID}/orders/{order_id}").json()["status"] == "confirmed"
    log = client.get(f"/api/accounts/{KID}/log").json()
    assert log and {r["quote_id"] for r in log} == {world.kid["quote_id"]}
    assert client.get(f"/api/accounts/{SOINTU}/orders").json() == []
    assert client.get(f"/api/accounts/{SOINTU}/log").json() == []
    res = client.post(f"/api/accounts/{KID}/approvals/{world.hotel['approval_id']}/approve")
    assert res.status_code == 404 and world.trade.calls == []
