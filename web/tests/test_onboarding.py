"""The onboarding page and its routes, against the fake trade server."""

import jwt
import pytest
from starlette.testclient import TestClient

from onboarding.options import template
from web.app import create_app


@pytest.fixture
def client(fake, tmp_path):
    with TestClient(create_app(trade_http=fake.base_url, buyers_dir=tmp_path)) as c:
        yield c


def test_the_page_loads(client):
    res = client.get("/onboarding")
    assert res.status_code == 200
    assert "Set up your kitchen" in res.text


def test_options_give_the_page_its_lists_and_templates(client):
    opts = client.get("/api/onboarding/options").json()
    assert set(opts["templates"]) == {"daycare", "school", "hotel", "cafe"}
    assert {"code": "AP", "name": "Peanuts"} in opts["allergens"]
    assert opts["delivery_days_side"] in ("preference", "rule")


def test_preview_returns_labelled_sentences(client):
    body = client.post("/api/onboarding/preview", json=template("daycare")).json()
    assert body["problems"] == []
    assert {s["kind"] for s in body["sentences"]} == {"rule", "preference"}


def test_preview_reports_problems_and_no_sentences(client):
    answers = template("daycare")
    answers["kitchen"]["name"] = ""
    body = client.post("/api/onboarding/preview", json=answers).json()
    assert body["sentences"] == []
    assert any("name" in problem for problem in body["problems"])


def test_sign_up_registers_saves_the_files_and_tells_the_chat(client, fake, tmp_path):
    res = client.post("/api/onboarding", json=template("daycare"))
    assert res.status_code == 201
    out = res.json()
    assert out["name"] == "Päiväkoti Aurinko"
    folder = tmp_path / out["buyer_id"]
    assert (folder / "profile.json").exists() and (folder / "buyer_key.pem").exists()
    token = (folder / "mandate.jwt").read_text()
    assert jwt.get_unverified_header(token)["kid"] == out["buyer_id"]
    assert out["buyer_id"] in fake.state.buyers
    event = client.get("/api/events").json()[-1]
    assert (event["kind"], event["buyer"]) == ("onboarded", out["buyer_id"])
    assert event["sentences"] == out["sentences"]


def test_sign_up_with_problems_is_refused(client, tmp_path):
    answers = template("daycare")
    answers["money"]["max_order_eur"] = None
    res = client.post("/api/onboarding", json=answers)
    assert res.status_code == 400
    assert res.json()["code"] == "bad_answers"
    assert list(tmp_path.iterdir()) == []


def test_sign_up_with_the_trade_server_down_saves_nothing(tmp_path):
    with TestClient(create_app(trade_http="http://127.0.0.1:9", buyers_dir=tmp_path)) as c:
        res = c.post("/api/onboarding", json=template("daycare"))
    assert res.status_code == 502
    assert res.json()["code"] == "server_unreachable"
    assert list(tmp_path.iterdir()) == []


def test_a_body_that_is_not_an_object_is_a_bad_request(client):
    assert client.post("/api/onboarding/preview", json=["x"]).status_code == 400
    assert client.post("/api/onboarding", content=b"not json").status_code == 400


def test_the_stage_phone_frame_can_follow_the_scene(client):
    page = client.get("/").text
    assert 'id="phoneframe"' in page and 'id="phonelabel"' in page
    assert "/onboarding?preset=" in page
