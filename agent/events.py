"""What the agent is doing, sent to the terminal and to the chat page as it happens.

Events are small JSON objects: {"kind": ..., "ts": ..., "run_id": ..., ...}. Kinds:
run_start, user, request, agent, tool_call, tool_result, options, ask, answer, waiting,
decision, run_end, scene, verify, note.

Posting to the web server happens on a background thread and never blocks or fails the
agent: if the web page isn't running, events still go to the terminal.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

REDACTED = "[redacted]"


def scrub(data: Any, secrets: list[str]) -> Any:
    """Replace any secret value anywhere inside data."""
    if not secrets:
        return data
    text = json.dumps(data, ensure_ascii=False, default=str)
    for s in secrets:
        text = text.replace(s, REDACTED)
    return json.loads(text)


class EventSink:
    def __init__(self, web_url: str | None = None, *, secrets: list[str] | None = None,
                 console: bool = True, run_id: str | None = None, buyer: str | None = None):
        self.web_url = web_url.rstrip("/") if web_url else None
        self.secrets = [s for s in (secrets or []) if s]
        self.console = console
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.buyer = buyer
        self.history: list[dict[str, Any]] = []
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        if self.web_url:
            self._thread = threading.Thread(target=self._post_loop, daemon=True)
            self._thread.start()

    def add_secret(self, value: str) -> None:
        if value and len(value) >= 8:
            self.secrets.append(value)

    def publish(self, kind: str, **data: Any) -> dict[str, Any]:
        event = {"kind": kind, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "run_id": self.run_id, "buyer": self.buyer, **data}
        event = scrub(event, self.secrets)
        self.history.append(event)
        if self.console:
            line = format_event(event)
            if line:
                print(line, flush=True)
        if self._thread:
            self._queue.put(event)
        return event

    def close(self, timeout: float = 3.0) -> None:
        if self._thread:
            self._queue.put(None)
            self._thread.join(timeout)
            self._thread = None

    def _post_loop(self) -> None:
        warned = False
        with httpx.Client(timeout=2.0) as client:
            while (event := self._queue.get()) is not None:
                try:
                    client.post(f"{self.web_url}/api/events", json=event)
                except httpx.HTTPError:
                    if not warned:
                        print(f"  (chat page not reachable at {self.web_url}; continuing without it)",
                              file=sys.stderr)
                        warned = True


# --- Terminal output -------------------------------------------------------------------

def _eur(x: Any) -> str:
    try:
        return f"€{float(x):,.2f}"
    except (TypeError, ValueError):
        return "€?"


def _short(value: Any, limit: int = 140) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_result(tool: str, result: Any) -> str:
    """One readable line for a tool result."""
    if isinstance(result, dict) and "error" in result:
        return f"error {result['error'].get('code')}: {result['error'].get('message')}"
    if tool == "search_products" and isinstance(result, (list, dict)):
        items = result if isinstance(result, list) else result.get("products", [])
        names = [p.get("name_en") or p.get("name_fi") for p in items if isinstance(p, dict)][:4]
        more = "…" if len(items) > 4 else ""
        return f"{len(items)} products: " + "; ".join(n for n in names if n) + more
    if tool == "get_product" and isinstance(result, dict):
        return f"{result.get('id')} {result.get('name_en')}"
    if tool == "request_quote" and isinstance(result, dict):
        return (f"quote {result.get('quote_id')}: {len(result.get('lines', []))} line(s), "
                f"{_eur(result.get('total_eur'))}")
    if tool == "place_order" and isinstance(result, dict):
        return f"{result.get('status')}: " + " ".join(result.get("reasons", []))
    if tool == "get_approval_status" and isinstance(result, dict):
        who = f" by {result['decided_by']}" if result.get("decided_by") else ""
        return f"{result.get('status')}{who}"
    if tool == "get_audit_log" and isinstance(result, (list, dict)):
        items = result if isinstance(result, list) else result.get("entries", [])
        return f"{len(items)} log entries"
    return _short(result)


def format_event(e: dict[str, Any]) -> str | None:
    k = e["kind"]
    if k == "scene":
        bar = "═" * 72
        return f"\n{bar}\n  {e.get('title', '')}\n  {e.get('subtitle', '')}\n{bar}"
    if k == "run_start":
        return f"\n▶ {e.get('buyer_name', e.get('buyer'))}  ·  model {e.get('model')}"
    if k == "user":
        return f"\n🧑 Buyer: {e.get('text')}"
    if k == "request":
        r = e.get("request", {})
        must = ", ".join(r.get("must_have") or []) or "none"
        return (f"   📝 Request: {r.get('amount')} {r.get('unit')} of {r.get('product')}, "
                f"need by {r.get('need_by')}, must have: {must}")
    if k == "agent":
        return f"\n🤖 Agent: {e.get('text', '').strip()}"
    if k == "tool_call":
        return f"   → {e.get('tool')}({_short(e.get('args', {}), 110)})"
    if k == "tool_result":
        return f"   ← {summarize_result(e.get('tool', ''), e.get('result'))}"
    if k == "options":
        rows = [f"   ⚖ {e.get('title', 'Options')}"]
        for o in e.get("options", []):
            rows.append(f"     [{o.get('label')}] {o.get('name')} — {_eur(o.get('total_eur'))}, "
                        f"arrives {o.get('available_date')} · {o.get('trade_off')}")
        return "\n".join(rows)
    if k == "ask":
        return f"\n❓ Agent asks the buyer: {e.get('question')}"
    if k == "answer":
        return f"🧑 Buyer answers: {e.get('text')}"
    if k == "waiting":
        return f"   ⏳ Waiting for a person to approve {e.get('approval_id')} (up to {e.get('wait_s'):.0f}s)…"
    if k == "decision":
        icon = {"confirmed": "✅", "pending_approval": "👤", "needs_clarification": "❓",
                "rejected": "⛔", "approved": "✅"}.get(e.get("status"), "•")
        return f"   {icon} Server decision: {e.get('status')}"
    if k == "verify":
        return "\n🔒 Verify log: " + ("✅ intact" if e.get("ok") else f"❌ broken at row {e.get('broken_at_seq')}")
    if k == "note":
        return f"   ℹ {e.get('text')}"
    if k == "run_end":
        return None
    return None


def wait_for(predicate, timeout: float, every: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(every)
    return predicate()
