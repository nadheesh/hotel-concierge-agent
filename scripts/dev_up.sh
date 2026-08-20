#!/usr/bin/env bash
# Bring the whole fixture up locally: hotel-mcp and hotel-agent.
#
#   ./scripts/dev_up.sh
#   MCP_PORT=9100 AGENT_PORT=8000 ./scripts/dev_up.sh
#
# Generates dev/.env on first run with fresh local fixture keys. Put your model
# credential in there; everything else is filled in for you. dev/ is gitignored.
#
# Logs go to dev/mcp.log and dev/agent.log. Stop with ./scripts/dev_down.sh.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
VENV="$ROOT/.venv"
MCP_PORT="${MCP_PORT:-9100}"
AGENT_PORT="${AGENT_PORT:-8000}"
mkdir -p dev

# Creates .venv and installs dependencies if needed; a no-op once warm.
# shellcheck source=ensure_venv.sh
source scripts/ensure_venv.sh agent mcp/hotel-mcp

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
for spec in "MCP_PORT:$MCP_PORT" "AGENT_PORT:$AGENT_PORT"; do
  name=${spec%%:*}; port=${spec##*:}
  if port_busy "$port"; then
    echo "Port $port is already in use (needed for $name). Something else owns it:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN | tail -n +2 | awk '{print "  " $1 " (pid " $2 ")"}'
    echo "Pick another: $name=<port> ./scripts/dev_up.sh"
    exit 1
  fi
done

if [ ! -f dev/.env ]; then
  echo "Generating dev/.env with fresh local keys..."
  ADMIN=$("$VENV/bin/python" -c 'import secrets;print(secrets.token_urlsafe(24))')
  cat > dev/.env <<ENV
# Local fixture keys, generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Local use only.
# Never reuse these in a shared deployment.

# ---- PUT YOUR MODEL CREDENTIAL HERE -----------------------------------------
# Left COMMENTED so they cannot clobber a value already set in the repo root
# .env, which is sourced first.
#
# One key, both modes. Set OPENAI_URL as well to route through the AM gateway.
#OPENAI_API_KEY=sk-...
#OPENAI_URL=https://<project>-<component>.example/<endpoint>/

# Model is deliberately NOT set here. agent/.env owns it. Anything
# exported by this script beats that file, so pinning a model here would
# silently override your choice.
#OPENAI_MODEL=
# -----------------------------------------------------------------------------

HOTEL_MCP_ADMIN_TOKEN=$ADMIN

# Credential the agent presents to hotel-mcp. Empty locally: hotel-mcp enforces
# nothing, so there is nothing to present. Against a gateway-fronted endpoint,
# set HOTEL_MCP_API_KEY, or the HOTEL_MCP_TOKEN_URL/CLIENT_ID/CLIENT_SECRET
# trio for OAuth2. See agent/auth.py.
HOTEL_MCP_API_KEY=
HOTEL_MCP_TOKEN_URL=
HOTEL_MCP_CLIENT_ID=
HOTEL_MCP_CLIENT_SECRET=
HOTEL_MCP_SCOPES=

SYSTEM_PROMPT_VARIANT=baseline
HOTEL_MCP_LEGACY_DATE_COMPAT=true
ENV
  echo "  -> dev/.env created. Add a model credential before the agent can answer."
fi

# Root .env first (where a personal model credential usually lives), then
# dev/.env so the generated fixture values win on the keys they define.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
set -a; . dev/.env; set +a

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo
  echo "NOTE: OPENAI_API_KEY is not set, so the agent will start but cannot answer."
  echo "      /health will report llm_client_built false. Put a key in .env or dev/.env."
fi

export HOTEL_MCP_URL="http://127.0.0.1:${MCP_PORT}/mcp"

wait_for() {
  for _ in $(seq 1 60); do
    curl -sf "$1" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

echo
echo "Starting hotel-mcp on :${MCP_PORT} ..."
( cd mcp/hotel-mcp; PORT="$MCP_PORT" exec "$VENV/bin/python" server.py ) \
  >"$ROOT/dev/mcp.log" 2>&1 &
echo $! > "$ROOT/dev/mcp.pid"
wait_for "http://127.0.0.1:${MCP_PORT}/health" || { echo "hotel-mcp did not come up. Tail of dev/mcp.log:"; tail -20 dev/mcp.log; exit 1; }
curl -s "http://127.0.0.1:${MCP_PORT}/health" | jq .

echo
echo "Starting hotel-agent on :${AGENT_PORT} ..."
( cd agent; PORT="$AGENT_PORT" exec "$VENV/bin/python" main.py ) \
  >"$ROOT/dev/agent.log" 2>&1 &
echo $! > "$ROOT/dev/agent.pid"
wait_for "http://127.0.0.1:${AGENT_PORT}/health" || { echo "agent did not come up. Tail of dev/agent.log:"; tail -20 dev/agent.log; exit 1; }
curl -s "http://127.0.0.1:${AGENT_PORT}/health" | jq .

cat > dev/ports.env <<ENV
MCP_PORT=$MCP_PORT
AGENT_PORT=$AGENT_PORT
ENV

echo
echo "Both up. mcp_tools_loaded above should list 7 tools."
echo "  agent  http://127.0.0.1:${AGENT_PORT}/chat"
echo "  mcp    http://127.0.0.1:${MCP_PORT}/mcp"
echo "  logs   dev/agent.log  dev/mcp.log"
echo "  stop   ./scripts/dev_down.sh"
echo
echo "Console (separate, so the auth mode stays an explicit choice):"
echo "  python web/serve.py --no-auth     unsecured, straight to the agent"
echo "  python web/serve.py               secured, needs dev/web.env filled in"
