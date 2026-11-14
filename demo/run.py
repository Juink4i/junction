"""Play the demo: five scenes in order. The only manual step is tapping Approve/Reject.

    uv run python demo/run.py                 # real server on :8000, Gemini agent
    uv run python demo/run.py --fake          # start the fake server if nothing is on :8000
    uv run python demo/run.py --scripted      # no Gemini: a fixed plan drives the same tools
    uv run python demo/run.py --only a,e      # some scenes only

It starts the web pages on :8080 if they aren't running, and opens the stage view.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agent.config import DEFAULT_MODEL, Settings, load_gemini_key, load_mandate, secret_values  # noqa: E402
from agent.events import EventSink  # noqa: E402
from agent.mcp_link import TradeServerUnreachable  # noqa: E402
from agent.runner import make_ask, run_buyer  # noqa: E402
from agent.scripted import PlannedLlm, shopping_plan  # noqa: E402
from demo.scenes import OVERRIDES_DIR, Scene, build_scenes  # noqa: E402
from demo.servers import port_open, run_in_thread  # noqa: E402

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


async def play_scene(scene: Scene, cfg: DemoConfig, sink: EventSink) -> str:
    sink.buyer = scene.buyer
    sink.publish("scene", title=scene.title, subtitle=scene.subtitle, key=scene.key)
    if scene.hint and sink.console:  # for the presenter's terminal only, not the screen
        print(f"   👉 {scene.hint}", flush=True)

    if not scene.runs_agent:  # the Verify scene
        async with httpx.AsyncClient(timeout=10) as http:
            verdict = (await http.get(f"{cfg.trade_http}/log/verify")).json()
            entries = (await http.get(f"{cfg.trade_http}/log")).json()
        count = len(entries) if isinstance(entries, list) else len(entries.get("entries", []))
        sink.publish("verify", ok=verdict.get("ok"), broken_at_seq=verdict.get("broken_at_seq"), count=count)
        return "intact" if verdict.get("ok") else f"broken at {verdict.get('broken_at_seq')}"

    token, _ = load_mandate(scene.buyer)
    model = (PlannedLlm(shopping_plan(scene.plan, gullible=scene.gullible)) if cfg.scripted else cfg.model)
    settings = Settings(buyer=scene.buyer, server_url=cfg.mcp_url, web_url=None, model=model,
                        mandate_token=token, approval_wait_s=scene.wait_s * cfg.wait_scale,
                        gullible=scene.gullible, replies=list(scene.replies))
    with scene_overrides(scene.overrides, cfg.overrides_file):
        result = await run_buyer(scene.request, settings, sink, make_ask(scene.replies, interactive=False))
    if result.error:
        return f"error: {result.error}"
    return result.outcome or "no order placed"


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
    cfg = DemoConfig(trade_http=args.server.rstrip("/"), web_url=args.web.rstrip("/"),
                     scripted=args.scripted, pause_s=args.pause)
    started = []

    if not cfg.scripted:
        if not load_gemini_key():
            print("No Gemini key. Put GEMINI_API_KEY=... in .env, or run with --scripted.", file=sys.stderr)
            return 2
        cfg.model = args.model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL)

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
