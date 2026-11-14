"""The whole demo, scripted (no Gemini), against the fake server. A thread plays the person
with the phone: it approves everything except the order caused by the injected text."""

import threading
import time
from datetime import date

import httpx

from agent.events import EventSink
from demo.run import DemoConfig, play, scene_overrides
from demo.scenes import build_scenes, next_weekday


class PhoneUser:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.decisions: list[tuple[str, str]] = []
        self.stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        cafe_seen = 0
        while not self.stop.is_set():
            for a in httpx.get(f"{self.base_url}/approvals").json():
                act = "approve"
                if "Café" in a["buyer"]:
                    cafe_seen += 1
                    act = "approve" if cafe_seen == 1 else "reject"  # second café order = injection
                httpx.post(f"{self.base_url}/approvals/{a['approval_id']}/{act}")
                self.decisions.append((a["buyer"], act))
            time.sleep(0.1)


async def test_all_six_scenes(fake, tmp_path):
    cfg = DemoConfig(trade_http=fake.base_url, scripted=True, pause_s=0, wait_scale=0.05,
                     overrides_file=fake.overrides, buyers_dir=tmp_path)
    sink = EventSink(None, console=False)
    phone = PhoneUser(fake.base_url)
    try:
        outcomes = await play(build_scenes(), cfg, sink)
    finally:
        phone.stop.set()

    assert outcomes == {"o": "confirmed", "a": "approved", "b": "approved", "c": "approved",
                        "d": "rejected", "e": "intact"}

    # Scene o: a new kitchen signed up, and its first order needed no person.
    assert next(e for e in sink.history if e["kind"] == "scene")["onboard"] == "daycare"
    signed_up = [e for e in sink.history if e["kind"] == "onboarded"]
    assert len(signed_up) == 1 and signed_up[0]["buyer_name"] == "Päiväkoti Aurinko"
    assert (tmp_path / signed_up[0]["buyer"] / "mandate.jwt").exists()
    assert all("Aurinko" not in buyer for buyer, _ in phone.decisions)
    started = next(e for e in sink.history if e["kind"] == "run_start")
    assert any("lowest total price" in line for line in started["preferences"])
    first_order = next(e for e in sink.history if e["kind"] == "tool_call" and e["tool"] == "place_order")
    assert first_order["args"]["agent_signature"] == "[signed by the agent's key]"

    # Scene c: the server said "insufficient_stock", and the agent split the order into the
    # 700 L that was left plus a lactose-free substitute.
    quotes = [e["result"] for e in sink.history if e["kind"] == "tool_result" and e["tool"] == "request_quote"]
    assert any(q.get("error", {}).get("code") == "insufficient_stock" for q in quotes)
    assert any(sorted(ln["covers"] for ln in q.get("lines", [])) == [300, 700] for q in quotes)

    # Scene d: the fooled agent asked for 10x, the server held it for a person.
    injection = [e for e in sink.history if e["kind"] == "decision" and e.get("status") == "needs_clarification"]
    assert any("10×" in " ".join(e["reasons"]) for e in injection)
    assert not fake.overrides.exists()  # overrides put back after each scene


def test_overrides_are_restored(tmp_path):
    target = tmp_path / "data" / "overrides.json"
    target.parent.mkdir()
    target.write_text('{"keep": 1}')
    with scene_overrides("shortage.json", target):
        assert "464201" in target.read_text()
    assert target.read_text() == '{"keep": 1}'


def test_reads_the_real_servers_shortage_message():
    from agent.scripted import _parse_short
    # Wording from server/service.py (Runner 2).
    msg = ("Only 700 sales units of Lactose-free skimmed milk drink 1 L (464201) are available, which "
           "covers 700 L of the 1000 L asked for. Quote what is available and cover the rest with a "
           "substitute. Substitutes with the same tags that can arrive on time: 464179 ...")
    assert _parse_short(msg) == ("464201", 700.0)


def test_injection_counts_as_resisted_only_when_the_amount_stayed_as_asked():
    from agent.runner import RunResult
    from demo.run import resisted
    scene = next(s for s in build_scenes() if s.key == "d")  # café asks for 20 L
    asked = RunResult(outcome="confirmed", quotes=[{"lines": [{"covers": 20}]}])
    fooled = RunResult(outcome="pending_approval", quotes=[{"lines": [{"covers": 200}]}])
    assert resisted(asked, scene)
    assert not resisted(fooled, scene)


def test_next_weekday_never_today():
    saturday, monday = date(2026, 11, 14), date(2026, 11, 16)
    assert next_weekday(saturday, 0) == monday
    assert next_weekday(monday, 0) == date(2026, 11, 23)
