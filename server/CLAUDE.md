# Runner 2: Server

You own `server/` and `data/state.db`. Branch: `server`. Do not edit `catalog/`, `agent/`, `web/` or `demo/`.

## Goal

An MCP server through which an AI agent can search, get a quote and place an order, where only plain code decides whether an order goes through.

You call **Contract A** (Runner 1's functions) and provide **Contract B** (six MCP tools plus HTTP endpoints). Both are in `docs/runner-tasks.md`. Your done-checklist is in the same file under "Prompts for each runner → Runner 2".

## Context you need

- First deliverable: a skeleton with all six tools returning fake data in the Contract B shape. Merge it early so Runner 3 can connect. Use a fake catalog until Runner 1's functions land.
- Server name `valio-aimo-trade`, at `http://localhost:8000/mcp`. Official MCP Python SDK.
- Only `request_quote` triggers Valio Aimo API calls (through the catalog). Search and product details are static.
- The mandate JSON shape and the "who decides" table are in `docs/valio-aimo-discussion.md`, section 4. Each table row is one test.
- Outcomes: `confirmed`, `needs_clarification` (more than 5× the buyer's usual amount), `pending_approval`, `rejected` (no override possible).
- The buyer's "usual amount" comes from made-up order history that you seed for the demo buyers: a hotel, a café and a school.
- The stock hold on a quote is simulated in `state.db`. The mock API has no reservations.
- Log entries: `seq, time, actor, action, reason, prev_hash, hash`. The reason is plain language a kitchen manager can read.

## Don't

- Don't put any limit, allergen or delivery rule in an AI prompt. Policy is code.
- Don't expose the API key, raw stock numbers or other buyers' data through any tool.
- Don't create a second order when `place_order` is retried with the same `quote_id`.
