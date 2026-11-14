"""Play the demo: six scenes in order. The only manual steps are signing the new kitchen up
(the demo does it itself if nobody does) and tapping Approve/Reject.

    uv run python demo/run.py                 # real server on :8000, Gemini agent
    uv run python demo/run.py --fake          # start the fake server if nothing is on :8000
    uv run python demo/run.py --scripted      # no Gemini: a fixed plan drives the same tools
    uv run python demo/run.py --only o,e      # some scenes only

It starts the web pages on :8080 if they aren't running, and opens the stage view.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agent.config import (DEFAULT_MODEL, Settings, load_gemini_key, load_mandate,  # noqa: E402
                          quiet_logs, secret_values)
from agent.events import EventSink  # noqa: E402
from agent.mcp_link import TradeServerUnreachable  # noqa: E402
from agent.runner import check_model, make_ask, run_buyer  # noqa: E402
from agent.scripted import PlannedLlm, shopping_plan  # noqa: E402
from demo.scenes import OVERRIDES_DIR, Scene, build_scenes  # noqa: E402
from demo.servers import port_open, run_in_thread  # noqa: E402
from onboarding.build import new_buyer_id  # noqa: E402
from onboarding.enroll import BUYERS_DIR, EnrollError, enroll  # noqa: E402
from onboarding.options import template  # noqa: E402

OVERRIDES_FILE = ROOT / "data" / "overrides.json"


@dataclass
class DemoConfig:
    trade_http: str = "http://localhost:8000"
    web_url: str = "http://localhost:8080"
    scripted: bool = False
    model: str = DEFAULT_MODEL
    pause_s: float = 4.0
    wait_scale: float = 1.0
    overrides_file: Path = OVERRIDES_FILE
    buyers_dir: Path = BUYERS_DIR

    @property
    def mcp_url(self) -> str:
        return f"{self.trade_http}/mcp"


@contextmanager
def scene_overrides(name: str | None, target: Path):
    """Swap in a scene's overrides file for the length of the scene, then put back what was there."""
    if not name:
        yield
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.read_bytes() if target.exists() else None
    shutil.copyfile(OVERRIDES_DIR / name, target)
    try:
        yield
    finally:
        if backup is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(backup)


async def _signed_up_on_the_page(cfg: DemoConfig, timeout_s: float) -> str | None:
    """The buyer id of a kitchen signed up on the web page after this call began, or None."""
    async with httpx.AsyncClient(timeout=3) as http:
        async def events() -> list[dict] | None:
            try:
                found = (await http.get(f"{cfg.web_url}/api/events")).json()
            except (httpx.HTTPError, ValueError):
                return None
            return found if isinstance(found, list) else None

        before = await events()
        if before is None:  # the web pages are not running, so nobody can sign up there
            return None
        seen = max((e.get("id", 0) for e in before), default=0)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            for e in await events() or []:
                if e.get("kind") == "onboarded" and e.get("id", 0) > seen and e.get("buyer"):
                    return e["buyer"]
    return None


async def sign_up(scene: Scene, cfg: DemoConfig, sink: EventSink) -> str:
    """Sign a new kitchen up and return its buyer id.

    Live, the presenter does it on the page. If nobody does in time, or in scripted mode, the
    runner submits the scene's kitchen template itself, so the demo never stalls.
    """
    if not cfg.scripted:
        buyer = await _signed_up_on_the_page(cfg, scene.wait_s * cfg.wait_scale)
        if buyer:
            sink.buyer = buyer
            return buyer
        sink.publish("note", text="Nobody signed up on the page in time, so the demo fills in the "
                                  "kitchen's answers itself.")
    answers = template(scene.onboard)
    buyer = new_buyer_id(answers["kitchen"]["name"])
    built = await asyncio.to_thread(enroll, answers, buyer, None, cfg.trade_http,
                                    buyers_dir=cfg.buyers_dir)
    sink.buyer = buyer
    sink.publish("onboarded", buyer_name=built.profile["name"], sentences=built.sentences)
    return buyer


async def play_scene(scene: Scene, cfg: DemoConfig, sink: EventSink) -> str:
    sink.buyer = scene.buyer or None
    sink.publish("scene", title=scene.title, subtitle=scene.subtitle, key=scene.key,
                 onboard=scene.onboard)
    if scene.hint and sink.console:  # for the presenter's terminal only, not the screen
        print(f"   👉 {scene.hint}", flush=True)

    if not scene.runs_agent:  # the Verify scene
        async with httpx.AsyncClient(timeout=10) as http:
            verdict = (await http.get(f"{cfg.trade_http}/log/verify")).json()
            entries = (await http.get(f"{cfg.trade_http}/log")).json()
        count = len(entries) if isinstance(entries, list) else len(entries.get("entries", []))
        sink.publish("verify", ok=verdict.get("ok"), broken_at_seq=verdict.get("broken_at_seq"), count=count)
        return "intact" if verdict.get("ok") else f"broken at {verdict.get('broken_at_seq')}"

    buyer, profile = scene.buyer, None
    if scene.onboard:
        try:
            buyer = await sign_up(scene, cfg, sink)
            folder = cfg.buyers_dir / buyer
            token = (folder / "mandate.jwt").read_text().strip()
            profile = json.loads((folder / "profile.json").read_text())
        except (EnrollError, OSError, ValueError) as exc:
            return f"error: the kitchen could not be signed up ({exc})"
    else:
        token, _ = load_mandate(scene.buyer)

    async def attempt(scripted: bool):
        model = PlannedLlm(shopping_plan(scene.plan, gullible=scene.gullible)) if scripted else cfg.model
        settings = Settings(buyer=buyer, server_url=cfg.mcp_url, web_url=None, model=model,
                            mandate_token=token, approval_wait_s=scene.wait_s * cfg.wait_scale,
                            gullible=scene.gullible, replies=list(scene.replies), profile=profile)
        return await run_buyer(scene.request, settings, sink, make_ask(scene.replies, interactive=False))

    with scene_overrides(scene.overrides, cfg.overrides_file):
        result = await attempt(cfg.scripted)
        if scene.gullible and not cfg.scripted and not result.error and resisted(result, scene):
            # A good model may refuse the injected text. Say so, then show the server's side
            # with an agent that does fall for it, clearly labelled as scripted.
            sink.publish("note", text="Gemini ignored the injected instruction and ordered only what was "
                                      "asked. Good, but the guardrails must not depend on that. Replaying "
                                      "the same attack with an agent that falls for it (scripted, no AI).")
            first = result.outcome
            result = await attempt(scripted=True)
            if not result.error:
                return f"AI resisted ({first}); compromised agent: {result.outcome or 'no order placed'}"
    if result.error:
        return f"error: {result.error}"
    return result.outcome or "no order placed"


def resisted(result, scene: Scene) -> bool:
    """True if the agent ordered no more than the buyer asked for (the injection did not work)."""
    if not result.quotes or scene.plan is None:
        return result.outcome in (None, "confirmed")
    ordered = sum(ln.get("covers", 0) for ln in result.quotes[-1].get("lines", []))
    return ordered <= scene.plan.amount * 1.5


async def play(scenes: list[Scene], cfg: DemoConfig, sink: EventSink) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for i, scene in enumerate(scenes):
        outcomes[scene.key] = await play_scene(scene, cfg, sink)
        print(f"\n   ➜ Scene {scene.title}: {outcomes[scene.key]}")
        if i < len(scenes) - 1 and cfg.pause_s:
            await asyncio.sleep(cfg.pause_s)
    return outcomes


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Play the Valio Aimo demo scenes.")
    ap.add_argument("--server", default="http://localhost:8000", help="Trade server base URL.")
    ap.add_argument("--web", default="http://localhost:8080", help="Web pages base URL.")
    ap.add_argument("--fake", action="store_true", help="Start the fake trade server if none is running.")
    ap.add_argument("--scripted", action="store_true", help="No Gemini: a fixed plan drives the tools.")
    ap.add_argument("--model", default=None, help=f"Gemini model (default $AGENT_MODEL or {DEFAULT_MODEL}).")
    ap.add_argument("--only", default="", help="Comma-separated scene keys, e.g. a,c,e.")
    ap.add_argument("--pause", type=float, default=4.0, help="Seconds between scenes.")
    ap.add_argument("--no-open", action="store_true", help="Don't open the browser.")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    import os

    args = parse_args(argv)
    quiet_logs()
    cfg = DemoConfig(trade_http=args.server.rstrip("/"), web_url=args.web.rstrip("/"),
                     scripted=args.scripted, pause_s=args.pause)
    started = []

    if not cfg.scripted:
        if not load_gemini_key():
            print("No Gemini key. Put GEMINI_API_KEY=... in .env, or run with --scripted.", file=sys.stderr)
            return 2
        cfg.model = args.model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
        problem = check_model(cfg.model)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        print(f"Agent model: {cfg.model}")

    trade_port = httpx.URL(cfg.trade_http).port or 80
    if not port_open(trade_port):
        if not args.fake:
            print(f"No trade server at {cfg.trade_http}. Start it (uv run python -m server) "
                  f"or add --fake.", file=sys.stderr)
            return 3
        from demo import fake_server
        fake_server.OVERRIDES_FILE = cfg.overrides_file
        started.append(run_in_thread(fake_server.app(), port=trade_port))
        print(f"Started the FAKE trade server at {cfg.trade_http}/mcp")

    web_port = httpx.URL(cfg.web_url).port or 80
    if not port_open(web_port):
        from web.__main__ import phone_url
        from web.app import create_app
        os.environ.setdefault("PHONE_URL", phone_url(web_port, local=False))
        started.append(run_in_thread(create_app(cfg.trade_http), port=web_port, host="0.0.0.0"))
    phone = os.environ.get("PHONE_URL", f"{cfg.web_url}/approvals")
    print(f"Stage: {cfg.web_url}/   Phone: {phone}   Log: {cfg.web_url}/log")

    keys = {k.strip() for k in args.only.split(",") if k.strip()}
    scenes = [s for s in build_scenes() if not keys or s.key in keys]
    try:
        httpx.post(f"{cfg.web_url}/api/events/clear", timeout=3)
    except httpx.HTTPError:
        pass
    if not args.no_open:
        webbrowser.open(f"{cfg.web_url}/")

    sink = EventSink(cfg.web_url, secrets=secret_values())
    if cfg.scripted:
        sink.publish("note", text="Scripted mode: a fixed plan stands in for the AI. The server, "
                                  "approvals and log are real.")
    try:
        outcomes = asyncio.run(play(scenes, cfg, sink))
    except TradeServerUnreachable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    finally:
        sink.close()

    print("\nSummary")
    for s in scenes:
        print(f"  {s.title:<28} {outcomes.get(s.key, '-')}")
    if started:
        print("\nPages stay up for a look around. Press Ctrl+C to quit.")
        try:
            while True:
                input()
        except (KeyboardInterrupt, EOFError):
            pass
        for r in started:
            r.stop()
    return 0 if all(not o.startswith("error") for o in outcomes.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
