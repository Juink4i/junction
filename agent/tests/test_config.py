"""A kitchen signed up on the onboarding page is a buyer the agent can run for."""

import json

from agent import config
from agent import __main__ as main_module
from agent.__main__ import main


def onboarded(tmp_path, monkeypatch, buyer="aurinko-3f2a"):
    monkeypatch.setattr(config, "BUYERS_DIR", tmp_path)
    monkeypatch.delenv("MANDATE_TOKEN", raising=False)
    folder = tmp_path / buyer
    folder.mkdir()
    (folder / "mandate.jwt").write_text("signed.token.here\n")
    (folder / "profile.json").write_text(json.dumps({"name": "Päiväkoti Aurinko",
                                                     "priorities": ["price"]}))
    return buyer


def test_an_onboarded_kitchens_mandate_and_profile_load(tmp_path, monkeypatch):
    buyer = onboarded(tmp_path, monkeypatch)
    token, source = config.load_mandate(buyer)
    assert token == "signed.token.here"
    assert source == "data/buyers/aurinko-3f2a/mandate.jwt"
    profile = config.load_profile(buyer)
    assert profile["priorities"] == ["price"]
    assert config.Settings(buyer=buyer, profile=profile).buyer_name == "Päiväkoti Aurinko"


def test_seeded_buyers_have_no_profile_and_keep_their_names(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BUYERS_DIR", tmp_path)
    assert config.load_profile("hotel") is None
    assert config.Settings(buyer="hotel").buyer_name == "Hotel Chain Oy / Helsinki Central"


def test_known_buyers_are_the_seeded_ones_and_the_onboarded_ones(tmp_path, monkeypatch):
    buyer = onboarded(tmp_path, monkeypatch)
    assert config.known_buyer("hotel") and config.known_buyer(buyer)
    assert not config.known_buyer("nobody")


def test_an_unknown_buyer_stops_with_a_plain_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "BUYERS_DIR", tmp_path)
    assert main(["--buyer", "nobody", "milk please"]) == 2
    assert "No buyer called 'nobody'" in capsys.readouterr().err


def test_a_buyer_without_an_agent_key_stops_before_connecting(tmp_path, monkeypatch, capsys):
    buyer = onboarded(tmp_path, monkeypatch)
    monkeypatch.setattr(main_module, "load_gemini_key", lambda: True)
    assert main(["--buyer", buyer, "milk please"]) == 2
    err = capsys.readouterr().err
    assert "no agent key" in err and "/onboarding" in err and "server.make_mandate" in err
