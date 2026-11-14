"""The demo screens: approval page (phone), decision log, live agent chat, and a stage view.

The pages are plain HTML and JavaScript in web/static. This server:
- serves them,
- forwards /api/approvals and /api/log calls to the trade server's HTTP endpoints
  (Contract B), so the browser only ever talks to one origin,
- collects the agent's events (POST /api/events) and streams them to the chat page (SSE),
- serves per-account views (/api/accounts/...) read-only from state.db, each scoped to one
  buyer so no account sees another's data,
- lets a buyer edit and re-sign its own mandate (PUT /api/accounts/{id}/mandate; the only
  writes to state.db, see web/mandate_edit.py),
- serves the Valio Aimo operations view (/api/admin/...), which sees every account,
- serves the built React frontend at /app/.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import mimetypes
import os
import sqlite3
from collections import deque
from contextlib import asynccontextmanager
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (FileResponse, JSONResponse, PlainTextResponse, RedirectResponse,
                                 Response, StreamingResponse)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from agent.identity import ensure_agent_key
from onboarding.build import build, new_buyer_id, problems
from onboarding.enroll import BUYERS_DIR, EnrollError, enroll
from onboarding.options import options as onboarding_options
from server.db import STATE_DB
from web import accounts, admin, mandate_edit, profile_edit

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).parent / "static"
PAGES = {"/": "stage.html", "/approvals": "approvals.html", "/log": "log.html", "/chat": "chat.html",
         "/onboarding": "onboarding.html"}
MANDATE_DIR = REPO_ROOT / "server" / "mandates"
BUYER_KEYS_DIR = REPO_ROOT / "data" / "buyer_keys"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
NOT_BUILT = "Frontend not built. Run: cd frontend && npm install && npm run build"
HEARTBEAT_S = 15

# Some Windows machines map .js to text/plain, which browsers refuse for module scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def buyer_filter(buyer: str | None) -> Callable[[dict[str, Any]], bool]:
    """Which events one account's page may see: its own, plus 'clear'. No buyer: all."""
    if not buyer:
        return lambda event: True
    return lambda event: event.get("kind") == "clear" or event.get("buyer") == buyer


def _error(code: str, message: str, status: int, retryable: bool = False) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "retryable": retryable}, status)


def _default_catalog() -> Any:
    """Same choice as server.app.load_catalog, but any failure just means no product details."""
    try:
        if (REPO_ROOT / "catalog" / "api.py").exists():
            return importlib.import_module("catalog.api")
        from server import fake_catalog
        return fake_catalog
    except Exception:
        return None


class EventHub:
    """Keeps recent agent events and pushes new ones to every open chat page."""

    def __init__(self, keep: int = 2000):
        self.history: deque[dict[str, Any]] = deque(maxlen=keep)
        self.subscribers: set[asyncio.Queue] = set()
        self.next_id = 1
        self.active_buyer: str | None = None

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        event = dict(event, id=self.next_id)
        self.next_id += 1
        if event.get("kind") in ("run_start", "scene") and event.get("buyer"):
            self.active_buyer = event["buyer"]
        self.history.append(event)
        for q in list(self.subscribers):
            q.put_nowait(event)
        return event

    def clear(self) -> None:
        self.history.clear()
        self.active_buyer = None
        self.publish({"kind": "clear"})
        self.history.clear()

    def close(self) -> None:
        for q in list(self.subscribers):
            q.put_nowait(None)


def _frame(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(trade_http: str | None = None, buyers_dir: Path | None = None, *,
               state_db: str | Path | None = None, mandate_dir: str | Path | None = None,
               catalog: Any = None, frontend_dist: str | Path | None = None,
               buyer_keys_dir: str | Path | None = None) -> Starlette:
    trade = (trade_http or os.environ.get("TRADE_HTTP_URL", "http://localhost:8000")).rstrip("/")
    buyers = Path(buyers_dir) if buyers_dir is not None else BUYERS_DIR
    hub = EventHub()
    state_path = Path(state_db) if state_db is not None else STATE_DB
    mandates = accounts.MandateFiles(Path(mandate_dir) if mandate_dir is not None else MANDATE_DIR,
                                     buyers)
    buyer_keys = Path(buyer_keys_dir) if buyer_keys_dir is not None else BUYER_KEYS_DIR
    mandate_lock = threading.Lock()  # one mandate edit at a time, so versions never collide
    dist = (Path(frontend_dist) if frontend_dist is not None else FRONTEND_DIST).resolve()
    catalog_box: dict[str, Any] = {"catalog": catalog, "loaded": catalog is not None}

    def get_catalog() -> Any:
        if not catalog_box["loaded"]:  # imported lazily: the real catalog loads a big file
            catalog_box["catalog"], catalog_box["loaded"] = _default_catalog(), True
        return catalog_box["catalog"]

    def with_db(work: Callable[[sqlite3.Connection], Response]) -> Response:
        """Run work on a fresh read-only connection. state.db belongs to the trade server."""
        try:
            conn = accounts.open_ro(state_path)
        except sqlite3.Error:
            return _error("state_db_unavailable", "The trade server's database cannot be read yet. "
                          "Start the trade server first.", 503, retryable=True)
        try:
            return work(conn)
        except sqlite3.OperationalError:
            return _error("state_db_unavailable", "The trade server's database is busy or not set up.",
                          503, retryable=True)
        finally:
            conn.close()

    def for_buyer(request: Request, work: Callable[[sqlite3.Connection, str], Any]) -> Response:
        """Only for a known account. work returns data, or a Response for its own errors."""
        buyer_id = request.path_params["buyer_id"]

        def run(conn: sqlite3.Connection) -> Response:
            if not accounts.buyer_exists(conn, buyer_id):
                return _error("account_not_found", f"No account {buyer_id}.", 404)
            result = work(conn, buyer_id)
            return result if isinstance(result, Response) else JSONResponse(result)

        return with_db(run)

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

    async def events_get(request: Request) -> JSONResponse:
        keep = buyer_filter(request.query_params.get("buyer"))
        return JSONResponse([e for e in hub.history if keep(e)])

    async def events_clear(_: Request) -> JSONResponse:
        hub.clear()
        return JSONResponse({"ok": True})

    async def events_stream(request: Request) -> StreamingResponse:
        replay_only = request.query_params.get("replay_only") == "1"
        after = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)
        keep = buyer_filter(request.query_params.get("buyer"))

        async def gen() -> AsyncIterator[str]:
            q: asyncio.Queue = asyncio.Queue()
            backlog = [e for e in hub.history if e["id"] > after and keep(e)]
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
                    if keep(e):
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
        return JSONResponse({"trade_http": trade, "phone_url": os.environ.get("PHONE_URL"),
                             "active_buyer": hub.active_buyer})

    # Per-account views. Sync handlers, so Starlette runs them on a worker thread.

    def account_list(_: Request) -> Response:
        return with_db(lambda conn: JSONResponse(
            accounts.list_accounts(conn, mandates, date.today())))

    def account_orders(request: Request) -> Response:
        return for_buyer(request, accounts.list_orders)

    def account_order(request: Request) -> Response:
        order_id = request.path_params["order_id"]

        def work(conn: sqlite3.Connection, buyer_id: str) -> Any:
            order = accounts.get_order(conn, buyer_id, order_id, get_catalog())
            return order if order is not None else _error(
                "order_not_found", "This account has no order with that id.", 404)

        return for_buyer(request, work)

    def account_approvals(request: Request) -> Response:
        return for_buyer(request, accounts.pending_approvals)

    def account_log(request: Request) -> Response:
        return for_buyer(request, accounts.buyer_log)

    async def account_decide(request: Request) -> Response:
        approval_id, action = request.path_params["approval_id"], request.path_params["action"]

        def check(conn: sqlite3.Connection, buyer_id: str) -> Any:
            if action not in ("approve", "reject"):
                return _error("bad_action", action, 404)
            if not accounts.approval_belongs(conn, buyer_id, approval_id):
                return _error("approval_not_found", "This account has no approval with that id.", 404)
            return {"ok": True}

        verdict = await run_in_threadpool(for_buyer, request, check)
        if verdict.status_code != 200:
            return verdict
        return await forward(request, "POST", f"/approvals/{approval_id}/{action}")

    def mandate_put(request: Request, change: Any) -> Response:
        """The buyer edits its own mandate. web/ signs it with the buyer's key."""
        buyer_id = request.path_params["buyer_id"]
        today = date.today()

        def lookup(conn: sqlite3.Connection) -> Response:
            account = accounts.get_account(conn, buyer_id, mandates, today)
            if account is None:
                return _error("account_not_found", f"No account {buyer_id}.", 404)
            return JSONResponse(account)

        found = with_db(lookup)
        if found.status_code != 200:
            return found
        name = json.loads(found.body)["name"]
        try:
            with mandate_lock:
                changed = mandate_edit.update_mandate(
                    buyer_id=buyer_id, buyer_name=name, change=change, files=mandates,
                    keys_dir=buyer_keys, state_db=state_path, today=today)
        except mandate_edit.EditError as e:
            return _error(e.code, str(e), 409 if e.code == "key_mismatch" else 400)
        except sqlite3.OperationalError:
            return _error("state_db_unavailable", "The mandate was signed, but the trade server's "
                          "database is busy. Try again.", 503, retryable=True)
        return with_db(lookup) if changed else found

    async def account_mandate(request: Request) -> Response:
        try:
            change = await request.json()
        except ValueError:
            return _error("bad_field", "Send a JSON object with only the fields to change.", 400)
        return await run_in_threadpool(mandate_put, request, change)

    def account_profile_get(request: Request) -> Response:
        def work(_: sqlite3.Connection, buyer_id: str) -> Any:
            try:
                return profile_edit.read_profile(mandates, buyer_id)
            except mandate_edit.EditError as e:
                return _error(e.code, str(e), 404)

        return for_buyer(request, work)

    async def account_profile_put(request: Request) -> Response:
        try:
            change = await request.json()
        except ValueError:
            return _error("bad_field", "Send a JSON object with only the fields to change.", 400)

        def work(_: sqlite3.Connection, buyer_id: str) -> Any:
            try:
                with mandate_lock:  # a mandate edit may rewrite the same profile.json
                    return profile_edit.update_profile(buyer_id=buyer_id, change=change, files=mandates)
            except mandate_edit.EditError as e:
                return _error(e.code, str(e), 404 if e.code == "profile_not_found" else 400)

        return await run_in_threadpool(for_buyer, request, work)

    # Valio Aimo operations: every account. Events are copied on the event loop first.

    def _since_until(request: Request) -> tuple[datetime | None, datetime | None]:
        times = []
        for name in ("since", "until"):
            text = request.query_params.get(name)
            times.append(admin.parse_time(text) if text else None)
        return times[0], times[1]

    def bad_date() -> Response:
        return _error("bad_date", "since and until must be ISO times like 2026-11-14T10:00:00Z.", 400)

    async def admin_clients(_: Request) -> Response:
        events, now = list(hub.history), datetime.now(timezone.utc)
        return await run_in_threadpool(with_db, lambda conn: JSONResponse(
            admin.clients(conn, mandates, date.today(), events, now)))

    def admin_orders(request: Request) -> Response:
        try:
            since, until = _since_until(request)
        except ValueError:
            return bad_date()
        return with_db(lambda conn: JSONResponse(admin.all_orders(conn, since, until)))

    def admin_order(request: Request) -> Response:
        order_id = request.path_params["order_id"]

        def work(conn: sqlite3.Connection) -> Response:
            order = admin.any_order(conn, order_id, get_catalog())
            return JSONResponse(order) if order is not None else _error(
                "order_not_found", "There is no order with that id.", 404)

        return with_db(work)

    def admin_log(request: Request) -> Response:
        try:
            since, _ = _since_until(request)
        except ValueError:
            return bad_date()
        return with_db(lambda conn: JSONResponse(admin.full_log(conn, mandates, since)))

    # The built React frontend, with an SPA fallback to index.html.

    async def app_root(_: Request) -> Response:
        return RedirectResponse("/app/", status_code=307)

    async def app_files(request: Request) -> Response:
        index = dist / "index.html"
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=404)
        rel = request.path_params.get("path", "")
        if rel:
            target = (dist / rel).resolve()
            if target.is_relative_to(dist) and target.is_file():
                return FileResponse(target)
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    routes = [Route(path, page) for path in PAGES] + [
        Route("/api/accounts", account_list),
        Route("/api/accounts/{buyer_id}/orders", account_orders),
        Route("/api/accounts/{buyer_id}/orders/{order_id}", account_order),
        Route("/api/accounts/{buyer_id}/approvals", account_approvals),
        Route("/api/accounts/{buyer_id}/approvals/{approval_id}/{action}", account_decide,
              methods=["POST"]),
        Route("/api/accounts/{buyer_id}/log", account_log),
        Route("/api/accounts/{buyer_id}/mandate", account_mandate, methods=["PUT"]),
        Route("/api/accounts/{buyer_id}/profile", account_profile_get, methods=["GET"]),
        Route("/api/accounts/{buyer_id}/profile", account_profile_put, methods=["PUT"]),
        Route("/api/admin/clients", admin_clients),
        Route("/api/admin/orders", admin_orders),
        Route("/api/admin/orders/{order_id}", admin_order),
        Route("/api/admin/log", admin_log),
        Route("/app", app_root),
        Route("/app/{path:path}", app_files),
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
