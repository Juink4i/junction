"""The order box: start the buyer agent from the browser for one account.

The agent runs as its own process (`python -m agent`), exactly as from the command line, and
streams its events back to this server's chat feed. One run per account at a time and at most
`max_runs` at once, so a public demo can't run up the Gemini bill. The agent process gets the
Gemini key but never the Valio Aimo key, as on the command line.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

MAX_CHARS = 300
MAX_RUNS = 2
APPROVAL_WAIT_S = 240   # how long the agent waits for a person to approve
RUN_TIMEOUT_S = 360     # then the process is stopped, whatever it is doing

Launcher = Callable[[str, str], Awaitable[tuple[int, str]]]


async def launch_agent(buyer: str, text: str, *, mcp_url: str, web_url: str) -> tuple[int, str]:
    """Run `python -m agent` once. Returns (exit code, its last stderr line)."""
    env = {k: v for k, v in os.environ.items() if k != "VALIO_API_KEY"}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "agent", "--buyer", buyer, "--server", mcp_url, "--web", web_url,
        "--wait", str(APPROVAL_WAIT_S), "--", text,
        env=env, stdout=None, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), RUN_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "it took too long and was stopped."
    lines = [ln for ln in (err or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
    if lines:
        print("\n".join(lines), file=sys.stderr)  # into the server's own log
    return proc.returncode or 0, lines[-1].strip() if lines else ""


class AgentRuns:
    def __init__(self, launch: Launcher, publish: Callable[[dict[str, Any]], Any],
                 max_runs: int = MAX_RUNS):
        self.launch, self.publish, self.max_runs = launch, publish, max_runs
        self.running: set[str] = set()
        self.tasks: set[asyncio.Task] = set()

    def start(self, buyer: str, text: str) -> tuple[int, dict[str, Any]]:
        """(HTTP status, body). Starts the run in the background when the status is 202."""
        if buyer in self.running:
            return 409, {"code": "agent_busy", "retryable": True,
                         "message": "Your agent is still working on your last request."}
        if len(self.running) >= self.max_runs:
            return 429, {"code": "too_many_runs", "retryable": True,
                         "message": "Other kitchens' agents are busy right now. Try again in a minute."}
        self.running.add(buyer)
        task = asyncio.create_task(self._run(buyer, text))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return 202, {"started": True}

    async def _run(self, buyer: str, text: str) -> None:
        try:
            try:
                code, last = await self.launch(buyer, text)
            except Exception as exc:  # the process could not even start
                code, last = -1, type(exc).__name__
            if code != 0:
                self.publish({"kind": "agent", "buyer": buyer, "ts": datetime.now(timezone.utc).isoformat(),
                              "text": f"The agent stopped: {last[:300] or 'no reason given.'}"})
        finally:
            self.running.discard(buyer)


def clean_text(body: Any) -> str | None:
    """The request text, trimmed, or None when it is missing, empty or too long."""
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    return text if 0 < len(text) <= MAX_CHARS else None
