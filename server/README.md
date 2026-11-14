# Server (Runner 2)

```
uv sync
uv run python -m server.make_mandate   # demo buyers + tokens in server/mandates/{hotel,cafe,school}.jwt
uv run python -m server                # MCP at http://localhost:8000/mcp
uv run pytest server
```

- State lives in `data/state.db`. Delete it to start clean, then run `make_mandate` again. Set `STATE_DB` to use another file.
- `make_mandate` issues new buyer keys each run, so older tokens stop working.
- Uses `catalog/api.py` when it exists, otherwise `server/fake_catalog.py` (made-up prices).

## Unusual-order check

`place_order` asks Google's Decisions API (`gemini-decision-1`, plain HTTPS, `GEMINI_API_KEY`) how likely the amount is to be unusual for this buyer. A score of 0.8 or more returns `needs_clarification`, the same as the 5× rule. The score can only add a question. If the API is down, slow (4 s timeout) or says "normal", the 5× rule still applies. Each score is logged as `unusual_score` by `gemini-decision-1`. Set `DECISIONS_API=off` to skip it.

## For the agent and the screens

- Pass the contents of `server/mandates/<buyer>.jwt` as `mandate_token`.
- Errors come back as the tool result: `{code, message, retryable}`. List tools wrap it as `{"result": ...}` in structured content.
- `insufficient_stock` errors say how much is available and name on-time substitutes in `message`.
- `GET /approvals` returns pending approvals only. Each has `approval_id, order_id, quote_id, status, buyer, approvers, reasons, agent_rationale, lines, total_eur, total_with_tax_eur, created_at`.
- `POST /approvals/{id}/approve|reject` takes an optional JSON body `{"decided_by": "..."}`. 404 if unknown, 409 if already decided.
- CORS is open so the pages can call from another port.

## Simulated, say so in the demo

Buyer order history, the stock hold on a quote, and buyer key registration. The approval endpoints have no login.
