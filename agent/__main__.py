"""Buyer agent command line.

    uv run python -m agent "I need 1,000 litres of lactose-free milk by Monday"
    uv run python -m agent --buyer cafe "200 litres of lactose-free milk for Tuesday"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from agent.config import (BUYERS, DEFAULT_MODEL, Settings, load_gemini_key, load_mandate, quiet_logs,
                          secret_values)
from agent.events import EventSink
from agent.mcp_link import TradeServerUnreachable
from agent.runner import check_model, run_buyer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m agent", description="Valio Aimo buyer agent.")
    ap.add_argument("request", help="What to buy, in plain words.")
    ap.add_argument("--buyer", choices=sorted(BUYERS), default="hotel")
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
    if not load_gemini_key():
        print("No Gemini key. Put GEMINI_API_KEY=... in .env at the repo root.", file=sys.stderr)
        return 2
    token, source = load_mandate(args.buyer, args.mandate)
    settings = Settings(
        buyer=args.buyer, server_url=args.server, web_url=args.web or None,
        model=args.model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
        mandate_token=token, mandate_source=source, approval_wait_s=args.wait,
        gullible=args.gullible, replies=args.reply)
    problem = check_model(settings.model)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    print(f"Mandate: {source}", file=sys.stderr)
    sink = EventSink(settings.web_url, secrets=secret_values(), buyer=settings.buyer)
    try:
        result = asyncio.run(run_buyer(args.request, settings, sink))
    except TradeServerUnreachable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        sink.close()
    print(f"\nOutcome: {result.outcome or 'no order placed'}")
    return 1 if result.error else 0


if __name__ == "__main__":
    sys.exit(main())
