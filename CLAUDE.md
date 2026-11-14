# Junction 2026: Valio Aimo "Trusted Trade Agents"

48-hour hackathon project. Final submission: **Sun 15 Nov 2026, 10:00 Helsinki time**. Favour working, demo-able code over polish.

## The challenge

Valio Aimo is a Finnish food wholesaler. AI agents will soon place orders for its customers (hotels, schools, restaurants). We build the interface that lets an outside agent buy from Valio Aimo safely, plus a demo buyer agent.

Their example request: "I need 1,000 litres of lactose-free milk by Monday."

Scoring: working end-to-end flow 30%, buys what was asked 20%, rules/approvals/logging 20%, exception handling 15%, open standards and path to production 15%.

## Our idea

**The AI suggests. Plain code decides.** No spending, allergen or delivery rule ever lives in an AI prompt.

```
Buyer agent (one agent, Google ADK + Gemini)        agent/
   │ MCP
MCP server: 6 tools, Policy, audit log (plain code)  server/
   │ shortlist only
Catalog: product search, unit maths, API client      catalog/
   │
Valio Aimo mock APIs (price, availability) + product file
```

- The buyer signs a **mandate** (JSON, Ed25519 JWS) saying what its agent may do. The server verifies it on every order.
- Quotes are signed and expire after 15 minutes.
- Every order ends as one of: `confirmed`, `needs_clarification`, `pending_approval`, `rejected`.
- Every step is written to a hash-chained log that both sides can read and verify.

## Facts about the data and APIs

- Valio Aimo gives us only a product file (17,546 products), two CSVs and two APIs: `POST /api/price` and `POST /api/availability`. Search, quotes, orders, approvals and order history are ours.
- Search the product file first. Call the APIs only for a shortlist. They have hidden rate limits.
- Every price is for **one sales unit**. A sales unit can be 1 L, a case of 5, or 2 × 10 L. Always convert.
- Product names mislead. Filter on tags (e.g. `FREE_FROM_LACTOSE`) and category codes (e.g. `10400` = milk).
- 46% of products have no allergen info. Unknown is never "safe".
- Stock numbers of 999999 or more are placeholders. Treat as unknown and never show them.
- `closingTime` is the order cut-off. Compare it with `timeNow`.
- The customer number does not change API responses.

## Rules for every session

- Python 3.12, `uv`, `pytest`, SQLite.
- Work only in your runner's folders and on your runner's branch. See the folder's own `CLAUDE.md`.
- Contracts A and B in `docs/runner-tasks.md` are fixed. Ask the user before changing either.
- Secrets live in `.env` (`VALIO_API_KEY`, `GEMINI_API_KEY`). Never print or commit them.
- `data/raw/` holds the Valio Aimo files and is git-ignored. The data may only be used for this event.
- Write the test first. Commit after each finished task. Merge to `main` in small pieces.
- If the data or API contradicts the plan, stop and tell the user.

## Where to read more

- `docs/valio-aimo-discussion.md`: the full plan, mandate example, decision and exception tables, demo script, pitch.
- `docs/runner-tasks.md`: the work split, Contracts A and B, checkpoints, and each runner's done-checklist.
