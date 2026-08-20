#!/usr/bin/env bash
# Run the Grand Meridian console locally, against an agent running anywhere.
#
#   ./web/run.sh --no-auth                       no security, straight to the agent
#   ./web/run.sh                                 secured, expects an OAuth2 gateway
#   AGENT_URL=https://<gateway>/chat ./web/run.sh
#   ./web/run.sh --no-auth --port 5501
#
# Creates .venv on first run. The console is stdlib-only, so nothing is
# installed into it — it shares the venv purely so the Python version matches
# the rest of the project. Arguments pass straight through to web/serve.py.
#
# The agent is expected to be running elsewhere: deployed behind the Agent
# Manager gateway, or locally via ./scripts/dev_up.sh. Point the console at it
# with AGENT_URL, or AGENT_URL in dev/web.env, or ?agent=<url> in the browser.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# shellcheck source=../scripts/ensure_venv.sh
source scripts/ensure_venv.sh

# Soft reachability note. Works for a remote gateway as well as localhost, and
# never blocks: the console is still worth opening to inspect the auth state
# even when the agent is down.
_url=${AGENT_URL:-$(sed -n 's/^AGENT_URL=//p' dev/web.env 2>/dev/null | tail -1)}
_url=${_url:-http://127.0.0.1:8000/chat}
_origin=$(printf '%s' "$_url" | sed -E 's#^(https?://[^/]+).*#\1#')
if ! curl -s -o /dev/null --max-time 4 "$_origin" 2>/dev/null; then
  echo
  echo "NOTE: could not reach $_origin"
  echo "      The console will still open. Point it at a live agent with:"
  echo "        AGENT_URL=<url> ./web/run.sh $*"
  echo "      or start one locally with ./scripts/dev_up.sh"
fi

exec "$VENV_PY" web/serve.py "$@"
