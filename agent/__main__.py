"""Buyer agent command line.

    uv run python -m agent "I need 1,000 litres of lactose-free milk by Monday"
    uv run python -m agent --buyer cafe "200 litres of lactose-free milk for Tuesday"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from agent.config import (BUYERS, DEFAULT_MODEL, Settings, known_buyer, load_gemini_key, load_mandate,
                          load_profile, quiet_logs, secret_values)
from agent.events import EventSink
from agent.identity import key_path
from agent.mcp_link import TradeServerUnreachable
from agent.runner import check_model, run_buyer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m agent", description="Valio Aimo buyer agent.")
    ap.add_argument("request", help="What to buy, in plain words.")
    ap.add_argument("--buyer", default="hotel",
                    help="hotel, cafe, school, or the id of a kitchen signed up at /onboarding.")
    ap.add_argument("--server", default=os.environ.get("TRADE_MCP_URL", "http://localhost:8000/mcp"))
    ap.add_argument("--web", default=os.environ.get("WEB_URL", "http://localhost:8080"),
                    help="Chat page server to stream events to. Use --web '' to turn off.")
    ap.add_argument("--model", default=None, help=f"Gemini model (default $AGENT_MODEL or {DEFAULT_MODEL}).")
    ap.add_argument("--mandate", default=None, help="File holding the buyer's signed mandate token.")
    ap.add_argument("--wait", type=float, default=300, help="Seconds to wait for a person to approve.")
    ap.add_argument("--reply", action="append", default=[],
                    help="Scripted answer if the agent asks the buyer something (repeatable).")
    ap.add_argument("--gullible", action="store_true",
                    help="Demo only: let catalog text instruct the agent, to simulate prompt injection.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    quiet_logs()
    if not known_buyer(args.buyer):
        print(f"No buyer called {args.buyer!r}. Use one of {', '.join(sorted(BUYERS))}, or sign a "
              f"kitchen up at {args.web or 'http://localhost:8080'}/onboarding and use its buyer id.",
              file=sys.stderr)
        return 2
    if not load_gemini_key():
        print("No Gemini key. Put GEMINI_API_KEY=... in .env at the repo root.", file=sys.stderr)
        return 2
    token, source = load_mandate(args.buyer, args.mandate)
    key_file = key_path(args.buyer)
    if not key_file.exists():
        print(f"This buyer has no agent key ({key_file}), so the trade server will refuse it. "
              f"Sign the kitchen up at {args.web or 'http://localhost:8080'}/onboarding, or run "
              "`uv run python -m server.make_mandate` for the demo buyers.", file=sys.stderr)
        return 2
    settings = Settings(
        buyer=args.buyer, server_url=args.server, web_url=args.web or None,
        model=args.model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
        mandate_token=token, mandate_source=source, approval_wait_s=args.wait,
        gullible=args.gullible, replies=args.reply, profile=load_profile(args.buyer),
        agent_key_file=key_file)
    problem = check_model(settings.model)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    print(f"Mandate: {source}", file=sys.stderr)
    sink = EventSink(settings.web_url, secrets=secret_values(), buyer=settings.buyer)
    try:
        result = asyncio.run(run_buyer(args.request, settings, sink))
    except TradeServerUnreachable as exc:  # includes TradeServerRefused (401, with the reason)
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        sink.close()
    print(f"\nOutcome: {result.outcome or 'no order placed'}")
    return 1 if result.error else 0


if __name__ == "__main__":
    sys.exit(main())
