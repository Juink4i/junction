#!/usr/bin/env bash
# Start the hosted demo: trade server on 127.0.0.1:8000, screens on 0.0.0.0:$PORT.
# If either process stops, the container exits and the host restarts it.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8080}"
HOST="${SPACE_HOST:-${RAILWAY_PUBLIC_DOMAIN:-}}"  # set by Hugging Face Spaces / Railway
if [[ -n "$HOST" ]]; then PUBLIC="https://${HOST}"; else PUBLIC="http://localhost:${PORT}"; fi
export ONBOARDING_URL="${ONBOARDING_URL:-$PUBLIC/onboarding}"
export PHONE_URL="${PHONE_URL:-$PUBLIC/approvals}"
export SERVER_PORT="${TRADE_PORT:-8000}"  # the trade server, inside the container only
export TRADE_HTTP_URL="http://127.0.0.1:${SERVER_PORT}"
export TRADE_MCP_URL="${TRADE_HTTP_URL}/mcp"
export WEB_URL="http://127.0.0.1:${PORT}"

# Fresh demo kitchens, keys, mandates and order history on every boot (the disk is not kept).
if [[ ! -f server/mandates/hotel.jwt ]]; then
  python -m server.make_mandate
fi

python -m server &
TRADE_PID=$!
python -m web --port "$PORT" --trade "$TRADE_HTTP_URL" &
WEB_PID=$!
trap 'kill $TRADE_PID $WEB_PID 2>/dev/null' EXIT
while kill -0 "$TRADE_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 2; done
exit 1
