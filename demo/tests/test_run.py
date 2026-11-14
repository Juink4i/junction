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


async def test_all_five_scenes(fake):
    cfg = DemoConfig(trade_http=fake.base_url, scripted=True, pause_s=0, wait_scale=0.05,
                     overrides_file=fake.overrides)
    sink = EventSink(None, console=False)
    phone = PhoneUser(fake.base_url)
    try:
        outcomes = await play(build_scenes(), cfg, sink)
    finally:
        phone.stop.set()

    assert outcomes == {"a": "approved", "b": "approved", "c": "confirmed", "d": "rejected", "e": "intact"}

    # Scene c split the order: the 700 L that was left plus a lactose-free substitute.
    final_quotes = [e["result"] for e in sink.history
                    if e["kind"] == "tool_result" and e["tool"] == "request_quote"]
    shortage_quote = final_quotes[5]  # a: compare+final, b: compare+final, c: compare+final
    assert sorted(ln["covers"] for ln in shortage_quote["lines"]) == [300, 700]

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


def test_next_weekday_never_today():
    saturday, monday = date(2026, 11, 14), date(2026, 11, 16)
    assert next_weekday(saturday, 0) == monday
    assert next_weekday(monday, 0) == date(2026, 11, 23)
