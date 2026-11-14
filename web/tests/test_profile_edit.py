"""The buyer changes its preferences: the profile only its own agent reads. No signing, no log."""

import json

import pytest

from agent.instructions import preference_lines
from web.tests.world import KID


def _profile(world) -> dict:
    return json.loads((world.buyers / KID / "profile.json").read_text())


def test_get_returns_the_onboarding_preferences(client, world):
    res = client.get(f"/api/accounts/{KID}/profile")
    assert res.status_code == 200, res.text
    assert res.json() == _profile(world)
    assert res.json()["priorities"] == ["price", "reliability", "finnish", "sustainability"]
    assert res.json()["pack_size"] == "small"


def test_demo_buyer_has_no_profile(client, world):
    res = client.get("/api/accounts/cafe/profile")
    assert res.status_code == 404
    assert res.json()["code"] == "profile_not_found"
    res = client.put("/api/accounts/cafe/profile", json={"pack_size": "large"})
    assert res.status_code == 404
    assert not (world.buyers / "cafe").exists()


def test_unknown_account_is_404(client, world):
    assert client.get("/api/accounts/nobody/profile").json()["code"] == "account_not_found"
    assert client.put("/api/accounts/nobody/profile", json={}).status_code == 404


def test_put_changes_priorities_and_pack_size(client, world):
    before = _profile(world)
    body = {"priorities": ["finnish", "price", "reliability", "sustainability"], "pack_size": "large"}
    res = client.put(f"/api/accounts/{KID}/profile", json=body)
    assert res.status_code == 200, res.text
    after = _profile(world)
    assert res.json() == after
    assert after == {**before, **body}
    # The agent reads the new preferences on its next run.
    lines = preference_lines(after)
    assert lines[0].startswith("When several products fit, prefer Finnish origin, then the lowest")
    assert "Prefer large packs." in lines
    assert world.conn.execute("SELECT COUNT(*) FROM log WHERE action LIKE 'profile%'").fetchone()[0] == 0


@pytest.mark.parametrize("body,code,words", [
    ({"priorities": ["price", "price", "finnish", "sustainability"]}, "bad_profile", "Rank each"),
    ({"priorities": ["price"]}, "bad_profile", "Rank each"),
    ({"pack_size": "huge"}, "bad_profile", "small or large"),
    ({"usual_orders": []}, "bad_field", "mandate"),
    ({"name": "Other kitchen"}, "bad_field", "name"),
    ([1], "bad_field", "JSON object"),
])
def test_rejects_bad_changes(client, world, body, code, words):
    before = _profile(world)
    res = client.put(f"/api/accounts/{KID}/profile", json=body)
    assert res.status_code == 400
    assert res.json()["code"] == code
    assert words in res.json()["message"]
    assert _profile(world) == before
