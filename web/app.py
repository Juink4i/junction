"""The demo screens: approval page (phone), decision log, live agent chat, and a stage view.

The pages are plain HTML and JavaScript in web/static. This server:
- serves them,
- forwards /api/approvals and /api/log calls to the trade server's HTTP endpoints
  (Contract B), so the browser only ever talks to one origin,
- collects the agent's events (POST /api/events) and streams them to the chat page (SSE).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from agent.identity import ensure_agent_key
from onboarding.build import build, new_buyer_id, problems
from onboarding.enroll import BUYERS_DIR, EnrollError, enroll
from onboarding.options import options as onboarding_options

STATIC = Path(__file__).parent / "static"
PAGES = {"/": "stage.html", "/approvals": "approvals.html", "/log": "log.html", "/chat": "chat.html",
         "/onboarding": "onboarding.html"}
HEARTBEAT_S = 15


class EventHub:
    """Keeps recent agent events and pushes new ones to every open chat page."""

    def __init__(self, keep: int = 2000):
        self.history: deque[dict[str, Any]] = deque(maxlen=keep)
        self.subscribers: set[asyncio.Queue] = set()
        self.next_id = 1

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        event = dict(event, id=self.next_id)
        self.next_id += 1
        self.history.append(event)
        for q in list(self.subscribers):
            q.put_nowait(event)
        return event

    def clear(self) -> None:
        self.history.clear()
        self.publish({"kind": "clear"})
        self.history.clear()

    def close(self) -> None:
        for q in list(self.subscribers):
            q.put_nowait(None)


def _frame(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(trade_http: str | None = None, buyers_dir: Path | None = None) -> Starlette:
    trade = (trade_http or os.environ.get("TRADE_HTTP_URL", "http://localhost:8000")).rstrip("/")
    buyers = buyers_dir or BUYERS_DIR
    hub = EventHub()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.http = httpx.AsyncClient(timeout=10.0)
        yield
        hub.close()
        await app.state.http.aclose()

    async def forward(request: Request, method: str, path: str) -> Response:
        # POST bodies pass through unchanged. With no decided_by, the server records the
        # approver named in the buyer's mandate.
        body = await request.body() if method == "POST" else None
        headers = {"content-type": "application/json"} if body else None
        try:
            res = await request.app.state.http.request(method, f"{trade}{path}", content=body,
                                                       headers=headers)
        except httpx.HTTPError as exc:
            return JSONResponse({"code": "server_unreachable", "retryable": True,
                                 "message": f"The trade server at {trade} is not answering "
                                            f"({type(exc).__name__})."}, status_code=502)
        return Response(res.content, status_code=res.status_code,
                        media_type=res.headers.get("content-type", "application/json"))

    async def page(request: Request) -> FileResponse:
        return FileResponse(STATIC / PAGES[request.url.path], headers={"Cache-Control": "no-store"})

    async def approvals(request: Request) -> Response:
        return await forward(request, "GET", "/approvals")

    async def decide(request: Request) -> Response:
        approval_id, action = request.path_params["approval_id"], request.path_params["action"]
        if action not in ("approve", "reject"):
            return JSONResponse({"code": "bad_action", "message": action, "retryable": False}, 404)
        return await forward(request, "POST", f"/approvals/{approval_id}/{action}")

    async def log(request: Request) -> Response:
        return await forward(request, "GET", "/log")

    async def verify(request: Request) -> Response:
        return await forward(request, "GET", "/log/verify")

    async def events_post(request: Request) -> JSONResponse:
        event = await request.json()
        if not isinstance(event, dict) or "kind" not in event:
            return JSONResponse({"code": "bad_event", "message": "Need a JSON object with a kind.",
                                 "retryable": False}, 400)
        return JSONResponse(hub.publish(event))

    async def events_get(_: Request) -> JSONResponse:
        return JSONResponse(list(hub.history))

    async def events_clear(_: Request) -> JSONResponse:
        hub.clear()
        return JSONResponse({"ok": True})

    async def events_stream(request: Request) -> StreamingResponse:
        replay_only = request.query_params.get("replay_only") == "1"
        after = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)

        async def gen() -> AsyncIterator[str]:
            q: asyncio.Queue = asyncio.Queue()
            backlog = [e for e in hub.history if e["id"] > after]
            if not replay_only:
                hub.subscribers.add(q)
            try:
                yield "retry: 1500\n\n"
                for e in backlog:
                    yield _frame(e)
                while not replay_only:
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if e is None:
                        break
                    yield _frame(e)
            finally:
                hub.subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    async def read_answers(request: Request) -> dict | None:
        try:
            answers = await request.json()
        except ValueError:
            return None
        return answers if isinstance(answers, dict) else None

    def bad_answers(message: str) -> JSONResponse:
        return JSONResponse({"code": "bad_answers", "message": message, "retryable": False}, 400)

    async def onboarding_opts(_: Request) -> JSONResponse:
        return JSONResponse(onboarding_options())

    async def onboarding_preview(request: Request) -> JSONResponse:
        answers = await read_answers(request)
        if answers is None:
            return bad_answers("Send the answers as a JSON object.")
        found = problems(answers)
        sentences = [] if found else build(answers, "preview", date.today(),
                                           agent_public_pem="preview").sentences
        return JSONResponse({"problems": found, "sentences": sentences})

    async def onboarding_submit(request: Request) -> JSONResponse:
        answers = await read_answers(request)
        if answers is None:
            return bad_answers("Send the answers as a JSON object.")
        found = problems(answers)
        if found:
            return bad_answers(" ".join(found))
        buyer_id = new_buyer_id(answers["kitchen"]["name"])
        try:
            agent_pem = await run_in_threadpool(ensure_agent_key, buyer_id, buyers)
            built = await run_in_threadpool(enroll, answers, buyer_id, agent_pem, trade,
                                            buyers_dir=buyers)
        except EnrollError as exc:
            status = {"server_unreachable": 502, "buyer_exists": 409}.get(exc.code, 400)
            return JSONResponse({"code": exc.code, "message": exc.message,
                                 "retryable": exc.retryable}, status)
        except OSError as exc:
            return JSONResponse({"code": "save_failed", "retryable": False,
                                 "message": "The kitchen's files could not be saved "
                                            f"({type(exc).__name__}). Sign up again."}, 500)
        name = built.profile["name"]
        hub.publish({"kind": "onboarded", "buyer": buyer_id, "buyer_name": name,
                     "sentences": built.sentences})
        return JSONResponse({"buyer_id": buyer_id, "name": name, "sentences": built.sentences}, 201)

    async def info(request: Request) -> JSONResponse:
        return JSONResponse({"trade_http": trade, "phone_url": os.environ.get("PHONE_URL")})

    routes = [Route(path, page) for path in PAGES] + [
        Route("/api/approvals", approvals),
        Route("/api/approvals/{approval_id}/{action}", decide, methods=["POST"]),
        Route("/api/log", log),
        Route("/api/log/verify", verify),
        Route("/api/events", events_get, methods=["GET"]),
        Route("/api/events", events_post, methods=["POST"]),
        Route("/api/events/clear", events_clear, methods=["POST"]),
        Route("/api/events/stream", events_stream),
        Route("/api/onboarding/options", onboarding_opts),
        Route("/api/onboarding/preview", onboarding_preview, methods=["POST"]),
        Route("/api/onboarding", onboarding_submit, methods=["POST"]),
        Route("/api/info", info),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.hub = hub
    return app
