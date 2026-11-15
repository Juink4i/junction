"""Demo buyers get agent keys: hotel, cafe and school can connect like an onboarded kitchen.

Temp paths only: nothing here touches data/state.db, server/mandates or data/buyers."""

from datetime import date, datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from agent.identity import ensure_agent_key
from agent.mcp_link import TradeLink
from demo.servers import run_in_thread
from server import app as server_app
from server import fake_catalog, signing
from server.app import build_http_app
from server.db import connect
from server.make_mandate import DEMO_MANDATES, refresh_demo_buyers
from server.mandate import MandateError, verify_mandate
from server.service import Service


def paths(tmp_path):
    return {"mandate_dir": tmp_path / "mandates", "buyers_dir": tmp_path / "buyers",
            "buyer_keys_dir": tmp_path / "buyer_keys"}


def payload(path) -> dict:
    return jwt.decode(path.read_text(), options={"verify_signature": False})


def registered_pem(conn, buyer_id) -> str:
    return conn.execute("SELECT public_pem FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()[0]


def test_fresh_demo_buyers_get_agent_keys(tmp_path):
    conn = connect(tmp_path / "state.db")
    p = paths(tmp_path)
    tokens = refresh_demo_buyers(conn, **p)
    assert set(tokens) == {"hotel", "cafe", "school"}
    for buyer_id, token in tokens.items():
        assert (p["mandate_dir"] / f"{buyer_id}.jwt").read_text() == token
        found, mandate = verify_mandate(token, conn, date.today())
        assert found == buyer_id
        assert mandate["agent_key"] == ensure_agent_key(buyer_id, p["buyers_dir"])
        assert mandate["mandate_id"] == DEMO_MANDATES[buyer_id]["mandate_id"]
        assert {k: v for k, v in mandate.items() if k != "agent_key"} == DEMO_MANDATES[buyer_id]
        # The agent key sits where the agent looks; no mandate.jwt there, so the agent keeps
        # reading server/mandates/<id>.jwt.
        assert (p["buyers_dir"] / buyer_id / "agent_key.pem").exists()
        assert not (p["buyers_dir"] / buyer_id / "mandate.jwt").exists()
        # The kitchen's own key is kept where the web mandate editor looks, so it never rotates.
        key = serialization.load_pem_private_key(
            (p["buyer_keys_dir"] / f"{buyer_id}.pem").read_bytes(), password=None)
        assert signing.public_pem(key.public_key()) == registered_pem(conn, buyer_id)
    assert conn.execute("SELECT count(*) FROM order_history").fetchone()[0] > 0


def test_existing_rules_are_kept_and_the_version_bumped(tmp_path):
    conn = connect(tmp_path / "state.db")
    p = paths(tmp_path)
    p["mandate_dir"].mkdir()
    edited = {**DEMO_MANDATES["cafe"], "mandate_id": "mnd_cafe_kallio_002",
              "auto_approve": {"max_order_eur": 600, "max_line_eur": 400, "allowed_categories": ["10400"]},
              "budget": {"period": "week", "max_eur": 900}, "issued_at": "2026-11-14T10:00:00+00:00"}
    old_key = signing.generate_key()  # the web editor's key for the café, kept in buyer_keys
    p["buyer_keys_dir"].mkdir()
    (p["buyer_keys_dir"] / "cafe.pem").write_text(signing.private_pem(old_key))
    (p["mandate_dir"] / "cafe.jwt").write_text(signing.sign(edited, old_key, kid="cafe"))

    tokens = refresh_demo_buyers(conn, **p)
    _, cafe = verify_mandate(tokens["cafe"], conn, date.today())
    assert cafe["mandate_id"] == "mnd_cafe_kallio_003"
    assert cafe["auto_approve"]["max_order_eur"] == 600
    assert cafe["budget"] == {"period": "week", "max_eur": 900}
    assert cafe["issued_at"] == "2026-11-14T10:00:00+00:00"
    assert cafe["agent_key"] == ensure_agent_key("cafe", p["buyers_dir"])
    assert registered_pem(conn, "cafe") == signing.public_pem(old_key.public_key())  # key reused

    again = refresh_demo_buyers(conn, **p)
    assert payload(p["mandate_dir"] / "cafe.jwt")["mandate_id"] == "mnd_cafe_kallio_004"
    assert payload(p["mandate_dir"] / "hotel.jwt")["mandate_id"] == "mnd_hotel_helsinki_002"
    assert jwt.decode(again["hotel"], options={"verify_signature": False})["agent_key"] == \
        ensure_agent_key("hotel", p["buyers_dir"])


async def test_a_demo_buyer_can_connect_after_the_refresh(tmp_path):
    p = paths(tmp_path)
    svc = Service(connect(tmp_path / "state.db"), fake_catalog, lambda: datetime.now(timezone.utc))
    tokens = refresh_demo_buyers(svc.conn, **p)
    server_app.use_service(svc)
    running = run_in_thread(build_http_app())
    try:
        async with TradeLink(f"{running.base_url}/mcp", mandate_token=tokens["hotel"],
                             agent_key_file=p["buyers_dir"] / "hotel" / "agent_key.pem") as link:
            found = await link.call("search_products", {"text": "milk"})
    finally:
        running.stop()
        server_app.use_service(None)
    assert found
    row = svc.conn.execute("SELECT actor FROM log WHERE action = 'search_products'").fetchone()
    assert row["actor"] == "buyer-agent-01"


def test_refreshing_the_demo_mandates_retires_the_old_ones(tmp_path):
    conn = connect(tmp_path / "state.db")
    p = paths(tmp_path)
    first = refresh_demo_buyers(conn, **p)
    second = refresh_demo_buyers(conn, **p)
    with pytest.raises(MandateError) as refused:
        verify_mandate(first["hotel"], conn, date.today())
    assert refused.value.code == "mandate_replaced"
    verify_mandate(second["hotel"], conn, date.today())
