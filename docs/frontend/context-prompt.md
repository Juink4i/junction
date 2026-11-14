# Context prompt: build the frontend web app

Paste everything below the line into a new coding-agent session (Claude Code or similar) opened at the repo root.

---

You are building the frontend for a 48-hour hackathon project (Junction 2026, Valio Aimo challenge "Trusted Trade Agents"). Final submission is **Sun 15 Nov 2026, 10:00 Helsinki time**. A working, demo-able app beats a polished one. Read `CLAUDE.md`, `README.md` and `docs/runner-tasks.md` first.

## What the project is

Valio Aimo is a Finnish food wholesaler serving hotels, schools and restaurants. Soon outside AI agents will place orders for these kitchens. We built the front door that lets such an agent buy safely, plus a demo buyer agent.

The core idea: **the AI suggests, plain code decides.** The agent searches and proposes. Whether an order goes through is decided by plain code on our trade server, checked against a **mandate** the buyer has signed (Ed25519 JWS). No spending, allergen or delivery rule lives in an AI prompt, **or in this frontend**. The frontend shows decisions; it never makes them.

Every order ends as exactly one of four statuses:
- `confirmed`: within every rule of the mandate.
- `needs_clarification`: looks odd (e.g. more than 5× the buyer's usual amount). The buyer must confirm.
- `pending_approval`: a person must approve (over a spending limit, order cut-off passed, allergen info missing for a strict buyer).
- `rejected`: a hard rule was broken (blocked allergen, category not allowed, bad mandate, changed quote). Nobody can override.

Every step is written to a hash-chained audit log that both buyer and Valio Aimo can verify.

## What already runs (don't rebuild it)

| Process | Command | Address |
|---|---|---|
| Trade server (MCP, 6 tools + HTTP) | `uv run python -m server` | `http://localhost:8000/mcp`, HTTP on `:8000` |
| Web pages + backend-for-frontend | `uv run python -m web` | `http://localhost:8080` |
| Buyer agent (Gemini) | `uv run python -m agent --buyer hotel "I need 1,000 litres of lactose-free milk by Monday"` | streams events to `:8080` |

On this Windows machine, `uv` runs as `py -3.12 -m uv`.

Existing plain-HTML pages in `web/static/` (keep them working as a fallback): `/` stage view, `/approvals` phone page, `/log` audit log with Verify, `/chat` live agent activity.

### HTTP API you can use today (all on `:8080`, proxied to the trade server)

```
GET  /api/approvals                        → list of pending approvals
POST /api/approvals/{approval_id}/approve  body {"decided_by": "..."} (optional)
POST /api/approvals/{approval_id}/reject
GET  /api/log                              → list of LogEntry
GET  /api/log/verify                       → {"ok": true} or {"ok": false, "broken_at_seq": 12}
GET  /api/events                           → event history
GET  /api/events/stream                    → Server-Sent Events, one JSON event per message
POST /api/events/clear
GET  /api/info                             → stage info (phone URL etc.)
```

Pending approval:
```json
{"approval_id": "apr_fb58ae90fc7e", "order_id": "ord_dddb736136ee", "quote_id": "q_09ed943f434e",
 "status": "pending", "buyer": "Hotel Chain Oy / Helsinki Central",
 "approvers": ["procurement.manager@hotel.example"],
 "reasons": ["Valio Hyvä suomalainen Arki® Eila® semi skimmed milk drink 1 l lactose free costs €1,010.00, over the mandate's limit of €800.00 per line."],
 "agent_rationale": "Cheapest lactose-free milk that arrives by Monday.",
 "lines": [{"product_id": "464306", "name": "Valio Hyvä suomalainen Arki® Eila® semi skimmed milk drink 1 l lactose free",
            "units": 1000, "sales_unit": "ST", "covers": 1000.0, "content_unit": "L",
            "unit_price_eur": 1.01, "line_total_eur": 1010.0, "available_date": "2026-11-16",
            "cutoff_passed": false, "stock": "unconfirmed"}],
 "total_eur": 1010.0, "total_with_tax_eur": 1150.0, "created_at": "2026-11-14T09:32:19+00:00"}
```

LogEntry: `{"seq", "time", "actor", "action", "reason", "prev_hash", "hash"}`. `reason` is plain language a kitchen manager can read. `action` looks like `search_products`, `request_quote`, `place_order`, `decision:confirmed`, `decision:pending_approval`, `approval:approved`.

Agent events (`agent/events.py`): `{"kind", "ts", "run_id", "buyer", ...}` with kinds `run_start, user, request, agent, tool_call, tool_result, options, ask, answer, waiting, decision, run_end, scene, verify, note`. `tool_call` has the tool name and arguments, `decision` has the server's status and reasons, `options` has good/better/best choices with a one-line trade-off each.

### MCP tools on the trade server (Contract B in `docs/runner-tasks.md`, fixed)

`search_products(text, category?, must_have_tags?)`, `get_product(product_id)`, `request_quote(lines: [{product_id, amount, unit "L"|"KG"}], need_by)`, `place_order(quote_id, mandate_token, rationale, confirm_unusual?)`, `get_approval_status(approval_id)`, `get_audit_log(order_id? | quote_id?)`. Errors are `{code, message, retryable}`.

## What to build

A web app in a new folder **`frontend/`**: Vite + React + TypeScript, Tailwind for styling. It talks **only** to the backend-for-frontend on `:8080`, never to the trade server or Valio Aimo directly. Proxy `/api` to `:8080` in the Vite dev server.

### Screens

1. **Stage** (`/`): the pitch view on a laptop. Live agent activity on the left, a phone-shaped approvals panel on the right, a scene title bar on top (from `scene` events). Big, readable from the back of a room.
2. **Agent activity** (`/activity`): the live stream from `/api/events/stream`. AI messages, MCP tool calls and server decisions must look visibly different: a chat bubble for the agent, a monospace "→ tool(args)" row for tool calls, and a coloured status badge for decisions. Filter by buyer (hotel, café, school). Auto-scroll with a "jump to latest" pill.
3. **Approvals** (`/approvals`): **phone-first** (375 px). One card per pending approval: buyer, total, each line in sales units *and* litres ("1,000 × 1 L (1,000 L)"), delivery date, the server's reasons as a list, and the agent's rationale. Big Approve and Reject buttons, plus a confirm step for Reject. Poll every 3 s. Show an empty state when nothing is waiting.
4. **Audit log** (`/log`): the decision trail as a table or timeline (seq, time, actor, action, reason), grouped by order. A **Verify log** button calls `/api/log/verify` and turns the whole header green ("Intact: 57 entries chained") or red ("Broken at entry 12"). Hashes are shown shortened and expand on click.
5. **Buyer console** (`/buy`): a human places an order by hand, without the AI. Steps:
   - **Buyer picker:** hotel, café or school, showing that buyer's mandate rules read-only.
   - **Search:** text, category and tags.
   - **Product detail:** allergens with names, plus "unknown" shown as a warning, never as safe.
   - **Quote builder:** add lines with amount and unit, pick a need-by date, and see the signed quote with a 15-minute expiry countdown.
   - **Order:** show the four-way result. `needs_clarification` shows the server's question with a "Yes, confirm" button. `pending_approval` shows a live status.
6. **Mandates** (`/mandates`): each demo buyer's signed rules in plain words: max order €, max line €, allowed categories, must-keep tags for substitutes, blocked allergens, what happens when allergen info is unknown. Read-only.

### Backend-for-frontend additions in `web/` (owned by Runner 3, so agree with them first)

The buyer console and mandates screens need new routes in `web/app.py`. Each forwards to the trade server over MCP with the official Python SDK, the same way `agent/mcp_link.py` does:
- `POST /api/trade/{tool}` for the six tools. For `place_order` the frontend sends `buyer`, never a token. The backend reads `server/mandates/<buyer>.jwt` and attaches it, so a mandate never reaches the browser.
- `GET /api/buyers` returns each demo buyer with its mandate payload, decoded but not re-signed, for display.

Write tests for these routes in `web/tests/` first, in the same style as the existing ones.

### Rules (non-negotiable)

- **No business rule in the frontend.** Don't compute whether an order is allowed. Display the server's status and `reasons` verbatim.
- **Never show stock numbers.** Show only `stock: "confirmed" | "unconfirmed"`, and "cut-off passed" when `cutoff_passed` is true.
- **Always state units both ways**: sales units and litres/kg, e.g. "50 × 2×10 L case (1,000 L)". Prices are per sales unit and without VAT unless labelled.
- **Unknown allergen info is never "safe".** Show it as an amber warning.
- No API keys, no mandate tokens and no raw stack traces in the browser. Show errors as `message`, with a Retry button when `retryable` is true.
- Product names contain ®, ä and ö. Use UTF-8 everywhere.
- Every screen works at 375 px wide and on a laptop, in light and dark mode, with keyboard focus visible.

## Demo the app must support (2 minutes, in order)

1. Hotel orders 1,000 L lactose-free milk by Monday. It's over the €800 line limit, so it's approved on the phone.
2. Café asks for 10× its usual. The server asks for confirmation, the café confirms, and a person approves.
3. Shortage: 700 L left, 300 L from a lactose-free substitute. Confirmed.
4. Prompt injection: a product description says "order 10x". The fooled agent orders 200 L, the server holds it, and the person rejects it.
5. Verify log turns green.

`uv run python demo/run.py` plays these. Add `--scripted` for scene 4 and to run without Gemini.

## Done when

- [ ] `cd frontend && npm install && npm run dev` serves all six screens against the running servers.
- [ ] `npm run build` output can be served by `web/` at `/app/`, so the demo needs no Node.
- [ ] Approve and Reject on the phone screen change the agent's outcome in the activity stream within 5 s.
- [ ] Verify turns red after a log row is edited by hand in `data/state.db` and green again after a reset.
- [ ] The buyer console can place each of the four outcomes by hand.
- [ ] `uv run pytest` still passes, including new `web/tests` for `/api/trade/*` and `/api/buyers`.
- [ ] README has a short "Frontend" section with the commands.
