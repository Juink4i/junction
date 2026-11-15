"""The order box: start the buyer agent from the browser for one account.

The agent runs as its own process (`python -m agent`), exactly as from the command line, and
streams its events back to this server's chat feed. When the agent asks the buyer something
(ask_buyer), the next text typed in the box is piped to it as the answer. One run per account
at a time and at most
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

Launcher = Callable[[str, str, "asyncio.Queue[str]"], Awaitable[tuple[int, str]]]


async def launch_agent(buyer: str, text: str, answers: "asyncio.Queue[str]", *, mcp_url: str,
                       web_url: str) -> tuple[int, str]:
    """Run `python -m agent` once, piping in answers. Returns (exit code, last stderr line)."""
    env = {k: v for k, v in os.environ.items() if k != "VALIO_API_KEY"}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "agent", "--buyer", buyer, "--server", mcp_url, "--web", web_url,
        "--wait", str(APPROVAL_WAIT_S), "--answers-on-stdin", "--", text,
        env=env, stdin=asyncio.subprocess.PIPE, stdout=None, stderr=asyncio.subprocess.PIPE)

    async def feed() -> None:
        while True:
            answer = await answers.get()
            proc.stdin.write(answer.encode("utf-8") + b"\n")
            await proc.stdin.drain()

    async def finish() -> bytes:
        err = await proc.stderr.read()
        await proc.wait()
        return err

    feeder = asyncio.create_task(feed())
    try:
        err = await asyncio.wait_for(finish(), RUN_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "it took too long and was stopped."
    finally:
        feeder.cancel()
    lines = [ln for ln in (err or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
    if lines:
        print("\n".join(lines), file=sys.stderr)  # into the server's own log
    return proc.returncode or 0, lines[-1].strip() if lines else ""


class AgentRuns:
    def __init__(self, launch: Launcher, publish: Callable[[dict[str, Any]], Any],
                 max_runs: int = MAX_RUNS):
        self.launch, self.publish, self.max_runs = launch, publish, max_runs
        self.running: set[str] = set()
        self.asking: set[str] = set()  # accounts whose agent waits for the buyer's answer
        self.answers: dict[str, asyncio.Queue[str]] = {}
        self.tasks: set[asyncio.Task] = set()

    def status(self, buyer: str) -> dict[str, bool]:
        return {"running": buyer in self.running, "asking": buyer in self.asking}

    def saw(self, event: dict[str, Any]) -> None:
        """Every agent event passes here: an 'ask' opens the box for an answer, an 'answer' closes it."""
        buyer = event.get("buyer")
        if event.get("kind") == "ask" and buyer in self.running:
            self.asking.add(buyer)
        elif event.get("kind") == "answer":
            self.asking.discard(buyer)

    def start(self, buyer: str, text: str) -> tuple[int, dict[str, Any]]:
        """(HTTP status, body): a new run, or the answer to the running agent's question."""
        if buyer in self.asking:
            self.asking.discard(buyer)  # one answer per question
            self.answers[buyer].put_nowait(text)
            return 202, {"answered": True}
        if buyer in self.running:
            return 409, {"code": "agent_busy", "retryable": True,
                         "message": "Your agent is still working on your last request."}
        if len(self.running) >= self.max_runs:
            return 429, {"code": "too_many_runs", "retryable": True,
                         "message": "Other kitchens' agents are busy right now. Try again in a minute."}
        self.running.add(buyer)
        self.answers[buyer] = asyncio.Queue()
        task = asyncio.create_task(self._run(buyer, text))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return 202, {"started": True}

    async def _run(self, buyer: str, text: str) -> None:
        try:
            try:
                code, last = await self.launch(buyer, text, self.answers[buyer])
            except Exception as exc:  # the process could not even start
                code, last = -1, type(exc).__name__
            if code != 0:
                self.publish({"kind": "agent", "buyer": buyer, "ts": datetime.now(timezone.utc).isoformat(),
                              "text": f"The agent stopped: {last[:300] or 'no reason given.'}"})
        finally:
            self.running.discard(buyer)
            self.asking.discard(buyer)
            self.answers.pop(buyer, None)


def clean_text(body: Any) -> str | None:
    """The request text, trimmed, or None when it is missing, empty or too long."""
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    return text if 0 < len(text) <= MAX_CHARS else None
