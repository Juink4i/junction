# Runner 3: Bot and screens

You own `agent/`, `web/` and `demo/`. Branch: `bot`. Do not edit `catalog/` or `server/`.

## Goal

A demo a judge can follow in two minutes: an AI buyer agent orders through the MCP server, a human approves on a phone-sized page, and a log page proves what happened.

You call **Contract B** in `docs/runner-tasks.md` (six MCP tools plus HTTP endpoints). Your done-checklist is in the same file under "Prompts for each runner → Runner 3".

## Context you need

- One buyer agent, built with Google ADK and Gemini, connected to `http://localhost:8000/mcp` with the buyer's mandate as a bearer token. It passes the buyer's words on, quotes what the server kept, and orders the first option.
- Start against Runner 2's skeleton server. Don't wait for the real one.
- The agent must handle the three `place_order` results: `confirmed`, `pending_approval` (poll `get_approval_status`), `rejected` (explain, don't retry). `search_products` and `request_quote` can answer `needs_clarification` with a question.
- Screens: approval page (phone width), log page with a "Verify log" button, chat page showing messages and tool calls live. They are React + shadcn/ui in `web/ui/src/pages/`, built into `web/static/` (committed). After changing them: `cd web/ui && npm run build`, then commit both.
- Demo scenes are listed in `docs/valio-aimo-discussion.md`, section 5. The shortage and injection scenes are set up through `data/overrides.json`, which Runner 1 provides.
- In the injection scene the agent is allowed to be fooled. The point is that the server blocks the order.

## Don't

- Don't write spending, allergen or delivery rules into the agent's instructions. The server enforces them.
- Don't let the agent see or print any API key.
