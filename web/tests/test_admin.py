"""The Valio Aimo operations view: every account, every order, the whole log."""

from datetime import datetime, timedelta, timezone


def _ts(minutes_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="milliseconds")


def test_admin_orders_across_buyers(client, world):
    orders = client.get("/api/admin/orders").json()
    assert [o["order_id"] for o in orders] == [world.cafe_wait["order_id"], world.cafe_ok["order_id"],
                                               world.hotel["order_id"]]
    assert [o["buyer_id"] for o in orders] == ["cafe", "cafe", "hotel"]
    assert orders[2]["buyer_name"] == "Hotel Chain Oy / Helsinki Central"
    per_account = client.get("/api/accounts/hotel/orders").json()[0]
    assert {k: v for k, v in orders[2].items() if k not in ("buyer_id", "buyer_name")} == per_account


def test_admin_orders_since_and_until(client, world):
    orders = client.get("/api/admin/orders").json()
    newest = orders[0]["created_at"]
    since = client.get("/api/admin/orders", params={"since": newest}).json()
    assert [o["order_id"] for o in since] == [world.cafe_wait["order_id"]]
    until = client.get("/api/admin/orders", params={"until": orders[2]["created_at"]}).json()
    assert [o["order_id"] for o in until] == [world.hotel["order_id"]]
    future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert client.get("/api/admin/orders", params={"since": future}).json() == []
    res = client.get("/api/admin/orders", params={"since": "yesterday"})
    assert res.status_code == 400 and res.json()["code"] == "bad_date"


def test_admin_order_detail(client, world):
    res = client.get(f"/api/admin/orders/{world.cafe_wait['order_id']}")
    assert res.status_code == 200
    order = res.json()
    assert order["buyer_id"] == "cafe" and order["buyer_name"] == "Café Kallio"
    assert order["lines"][0]["product"]["category"] == "10400"
    assert "decision:pending_approval" in [r["action"] for r in order["log"]]
    missing = client.get("/api/admin/orders/ord_nope")
    assert missing.status_code == 404 and missing.json()["code"] == "order_not_found"


def test_admin_log_attributes_rows_to_buyers(client, world):
    world.svc.search_products("milk", actor="buyer-agent-02")          # no ids, cafe's agent
    world.svc.decide_approval("apr_nope", True, "kitchen.lead@school.example")  # school's approver
    world.svc.search_products("milk", actor="valio-buyer-agent")       # shared client name

    log = client.get("/api/admin/log").json()
    assert [r["seq"] for r in log] == sorted(r["seq"] for r in log)
    assert set(log[0]) == {"seq", "time", "actor", "action", "reason", "prev_hash", "hash",
                           "order_id", "quote_id", "buyer_id"}
    by_quote = {r["quote_id"]: r["buyer_id"] for r in log if r["quote_id"]}
    assert by_quote[world.hotel["quote_id"]] == "hotel"
    assert by_quote[world.cafe_ok["quote_id"]] == "cafe"
    assert [r["buyer_id"] for r in log if r["action"] == "decision:pending_approval"] == \
        ["hotel", "cafe"]
    last3 = log[-3:]
    assert [r["buyer_id"] for r in last3] == ["cafe", "school", None]

    since = client.get("/api/admin/log", params={"since": last3[1]["time"]}).json()
    assert [r["seq"] for r in since] == [last3[1]["seq"], last3[2]["seq"]]


def test_admin_clients(client, world):
    clients = client.get("/api/admin/clients").json()
    assert [c["buyer_id"] for c in clients] == ["hotel", "cafe", "school"]
    hotel = clients[0]
    assert set(hotel) == {"buyer_id", "name", "agent_id", "mandate_id", "valid_until",
                          "mandate_verified", "mandate_problem", "last_seen", "agent_running",
                          "orders_total"}
    assert hotel["agent_id"] == "buyer-agent-01"
    assert hotel["mandate_id"] == "mnd_hotel_helsinki_001"
    assert hotel["valid_until"] == "2026-12-31"
    assert hotel["mandate_verified"] is True
    assert [c["orders_total"] for c in clients] == [1, 2, 0]
    assert hotel["last_seen"]  # from its log rows
    assert clients[2]["last_seen"] is None
    assert not any(c["agent_running"] for c in clients)


def test_agent_running_and_last_seen_from_events(client, world):
    now = _ts()
    client.post("/api/events", json={"kind": "run_start", "buyer": "hotel", "run_id": "r1", "ts": _ts(1)})
    client.post("/api/events", json={"kind": "tool_call", "buyer": "hotel", "run_id": "r1", "ts": now})
    client.post("/api/events", json={"kind": "run_start", "buyer": "cafe", "run_id": "r2", "ts": _ts(30)})
    client.post("/api/events", json={"kind": "agent", "buyer": "cafe", "run_id": "r2", "ts": _ts(20)})
    client.post("/api/events", json={"kind": "run_start", "buyer": "school", "run_id": "r3", "ts": _ts(2)})
    clients = {c["buyer_id"]: c for c in client.get("/api/admin/clients").json()}
    assert clients["hotel"]["agent_running"] is True
    assert clients["hotel"]["last_seen"] == now
    assert clients["cafe"]["agent_running"] is False  # silent for 20 minutes
    assert clients["school"]["agent_running"] is True
    assert clients["school"]["last_seen"] is not None

    client.post("/api/events", json={"kind": "run_end", "buyer": "hotel", "run_id": "r1", "ts": _ts()})
    client.post("/api/events", json={"kind": "run_start", "buyer": "school", "run_id": "r4", "ts": _ts()})
    client.post("/api/events", json={"kind": "run_end", "buyer": "school", "run_id": "r3", "ts": _ts()})
    clients = {c["buyer_id"]: c for c in client.get("/api/admin/clients").json()}
    assert clients["hotel"]["agent_running"] is False
    assert clients["school"]["agent_running"] is True  # r4 is the latest run and has not ended
