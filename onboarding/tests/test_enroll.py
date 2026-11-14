"""Enrolment end to end against the real trade server code (in process, no network)."""

import json
from datetime import date, datetime, timezone

import httpx
import pytest
from starlette.testclient import TestClient

from onboarding.enroll import EnrollError, enroll
from onboarding.options import template
from server import app as server_app
from server import fake_catalog
from server.app import build_http_app
from server.db import connect
from server.service import Service

TODAY = date(2026, 11, 14)
TRADE = "http://testserver"


@pytest.fixture
def svc():
    return Service(connect(":memory:"), fake_catalog,
                   lambda: datetime(2026, 11, 14, 10, tzinfo=timezone.utc))


@pytest.fixture
def trade(svc):
    server_app.use_service(svc)
    yield TestClient(build_http_app())
    server_app.use_service(None)


def answers():
    a = template("daycare")
    a["safety"]["blocked_allergens"] = []  # the fake catalog's milk says nothing about nuts
    return a


def test_enroll_registers_the_kitchen_and_saves_its_files(trade, svc, tmp_path):
    built = enroll(answers(), "aurinko-3f2a", None, TRADE, today=TODAY, buyers_dir=tmp_path, client=trade)
    folder = tmp_path / "aurinko-3f2a"
    assert sorted(p.name for p in folder.iterdir()) == ["buyer_key.pem", "mandate.jwt", "profile.json"]
    assert json.loads((folder / "profile.json").read_text()) == built.profile
    # The saved mandate is accepted by the server for a real order.
    token = (folder / "mandate.jwt").read_text()
    quote = svc.request_quote([{"product_id": "464201", "amount": 40, "unit": "L"}], "2026-11-16")
    assert svc.place_order(quote["quote_id"], token, "Weekly milk")["status"] == "confirmed"


def test_the_private_key_is_never_sent(tmp_path):
    seen = {}

    class Recorder:
        def post(self, url, json):
            seen.update(url=url, body=json)
            return httpx.Response(201, json={"buyer_id": "k-0000", "mandate_id": "m",
                                             "status": "registered"})

    enroll(answers(), "k-0000", None, "http://trade/", today=TODAY, buyers_dir=tmp_path,
           client=Recorder())
    assert seen["url"] == "http://trade/buyers"
    assert set(seen["body"]) == {"public_pem", "mandate_token"}
    assert "PRIVATE" not in json.dumps(seen["body"])
    assert "PRIVATE KEY" in (tmp_path / "k-0000" / "buyer_key.pem").read_text()


def test_a_refused_registration_leaves_no_folder(trade, tmp_path):
    enroll(answers(), "aurinko-3f2a", None, TRADE, today=TODAY, buyers_dir=tmp_path / "first",
           client=trade)
    with pytest.raises(EnrollError) as refused:
        enroll(answers(), "aurinko-3f2a", None, TRADE, today=TODAY, buyers_dir=tmp_path / "second",
               client=trade)
    assert refused.value.code == "buyer_exists"
    assert not (tmp_path / "second" / "aurinko-3f2a").exists()


def test_an_unreachable_server_leaves_no_folder(tmp_path):
    with pytest.raises(EnrollError) as refused:
        enroll(answers(), "aurinko-3f2a", None, "http://127.0.0.1:9", today=TODAY, buyers_dir=tmp_path)
    assert refused.value.code == "server_unreachable" and refused.value.retryable
    assert not (tmp_path / "aurinko-3f2a").exists()


def test_bad_answers_never_reach_the_server(tmp_path):
    bad = answers()
    bad["kitchen"]["name"] = ""
    with pytest.raises(ValueError):
        enroll(bad, "aurinko-3f2a", None, "http://127.0.0.1:9", today=TODAY, buyers_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []
