# hotel-agent

The Grand Meridian's booking agent, and the subject of the Agent Manager
end-to-end study. LangGraph plus OpenAI, deployed as a platform-hosted Chat
Agent, reaching the booking system through an MCP proxy.

> **This agent ships with a deliberate defect and a deliberate weakness.** They
> are load-bearing for the study, they are pinned by tests, and both are
> documented below. Read [Seeded state](#seeded-state) before fixing anything.

## Chat contract

```
POST /chat   (port 8000)
Request:  {"message": "string", "session_id": "string", "context": {}}
Response: {"response": "string"}

GET /health
```

Conversation state is kept server-side, keyed by `session_id`; the client sends
one message per turn. `context` carries the caller's identity — `guest_id` and
`guest_name` — which is appended to the system prompt so the agent knows who it
is speaking with. It is told the identity and given no instruction about what
that implies for access, because whether the identity is honoured is a platform
authorisation question rather than a prompting one.

Session state is process-local. A multi-replica deployment would need shared
state, and the session store is a known open question — see the end of the
facilitator guide.

## Tools

Two sources, split on purpose.

**Native, in-process** (`tools.py`). `get_room_service_menu`,
`get_local_recommendations`. These never cross an MCP proxy, so they cannot be
governed by tool-level scopes. They are the control group.

**hotel-mcp, over an MCP proxy** (`mcp_client.py`). Everything about bookings:
`get_booking`, `list_my_bookings`, `search_availability`,
`get_booking_policies`, `modify_booking`, `cancel_booking`, `create_booking`.
The gateway in front of hotel-mcp is what gates them — `booking:read` for the
first four, `booking:write` for the last three. hotel-mcp itself enforces
nothing.

That split is what the least-privilege exercise is measured against.
Restricting the booking tools must not disturb the native ones, and the native
ones must not become a route to booking data. A unit test asserts no booking
tool has drifted into the native list.

If the MCP proxy is unreachable, `load_mcp_tools()` logs and returns an empty
list rather than raising. The agent starts with native tools only and answers
menu questions happily while claiming it cannot find any bookings — which is
itself a useful failure mode to observe. `/health` reports `mcp_tools_loaded`.

## Files

| File | Role |
|---|---|
| `main.py` | Entry point. Start command `python main.py`. |
| `agent.py` | FastAPI app, LangGraph react loop, session handling |
| `config.py` | Every setting, all from environment variables |
| `auth.py` | Outbound credential for MCP calls. API key, OAuth2, or nothing. |
| `mcp_client.py` | MCP transport and tool wrapping. **Carries the Exercise 1 defect.** |
| `tools.py` | Native tools |
| `hotel_data.py` | Menu, recommendations, rooms, static policy strings |
| `system_prompt.py` | Baseline plus two regression variants |

## Seeded state

### 1. The date defect — Exercise 1

`mcp_client.py`, the block headed *Legacy PMS date compatibility*. Two halves.

Outbound, ISO dates are rendered `DD/MM/YYYY`. hotel-mcp documents
`NN/NN/YYYY` as `MM/DD/YYYY`, so a model that correctly chose `2026-04-06`
causes `2026-06-04` to be written.

Inbound, the acknowledgement's `check_in` is overwritten with what was
requested and `check_out` is recomputed to match, so the confirmation is
internally consistent and reflects the guest's intent. The reply looks perfect.

Day-first and month-first only diverge when both numbers are 12 or under, so
casual spot-checking with a date like 26 April will not find it.

Controlled by `HOTEL_MCP_LEGACY_DATE_COMPAT`, which defaults **on**. Turn it
off, or delete the block, to fix.

`tests/test_mcp_client.py` pins this behaviour. Those tests do not assert the
agent is correct; they assert it is wrong in the specific reproducible way the
exercise depends on. If they fail, Exercise 1 has no root cause left.

### 2. No credential by default — Exercise 3

`auth.py` resolves whatever credential the environment supplies, in this order:

| Configured | Header sent |
|---|---|
| `HOTEL_MCP_TOKEN_URL` + `CLIENT_ID` + `CLIENT_SECRET` | `Authorization: Bearer <token>` |
| `HOTEL_MCP_API_KEY` | `<HOTEL_MCP_API_KEY_HEADER>: <key>` |
| nothing | `{}` — the call goes out bare |

Out of the box nothing is set, so calls go out bare. hotel-mcp is unsecured, so
they succeed, and every deployment built from this repository can do everything.

OAuth2 beats an API key on purpose: an agent migrated to OAuth2 must not be
silently downgraded by a stale key still sitting in its environment. A
*partially* filled OAuth2 trio is treated as a misconfiguration rather than a
fallback cue, and `/health` flags it as `oauth2_partially_configured` — that one
is easy to create and looks fine from the outside.

Nothing here assumes an Agent Manager Agent Identity. Any OAuth2 client the
gateway trusts works, which matters because the identity often does not exist
yet when someone first wires this up.

Note what `auth.py` does **not** do: no tool allow-lists, no branching on tool
names, no read/write distinction. It chooses a credential. The gateway decides
what that credential may reach. An agent that polices itself is not testing the
platform.

`GET /health` reports the live mode under `outbound_auth`, because "the calls
are failing" and "the calls are going out bare" look identical from a chat
window.

### 3. Prompt omissions — Exercises 2 and 4

The system prompt deliberately contains **no** prompt-injection hardening and
**no** terms-and-conditions instruction. Those are the platform guardrails
under measurement; a prompt that already handles them makes the guardrails
untestable and produces false passes.

`tests/test_system_prompt.py` enforces both omissions.

### 4. Quality regression on tap — Exercise 4

`SYSTEM_PROMPT_VARIANT` selects `baseline`, `broken` or `broken-2`. The broken
variants strip the grounding instructions without touching a tool, which is
what makes them a clean regression: same capabilities, worse answers. Unknown
values fall back to baseline silently, because a typo must never stop the
container booting mid-session.

## Configuration

Everything comes from the environment. Copy `.env.example` to `.env` for local
runs and never commit a filled-in copy.

### Model credentials

One key slot, and `OPENAI_URL` is the only mode gate.

| Mode | `OPENAI_URL` | `OPENAI_API_KEY` | Result |
|---|---|---|---|
| Ungoverned | unset | the key | Direct to OpenAI |
| Governed | set | the key | Through the AM gateway, guardrails apply |

In governed mode the gateway expects the key on an `API-Key` header rather than
`Authorization: Bearer`, so the SDK's default Authorization header is blanked;
see `_llm_kwargs()`.

### Everything else

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o` | Model |
| `HOTEL_MCP_URL` | empty | MCP endpoint. Injected by the Tool Configuration. |
| `HOTEL_MCP_API_KEY` | empty | API-key credential for the MCP gateway |
| `HOTEL_MCP_API_KEY_HEADER` | `API-Key` | Header the gateway reads the key from |
| `HOTEL_MCP_TOKEN_URL` | empty | OAuth2 token endpoint |
| `HOTEL_MCP_CLIENT_ID` | empty | OAuth2 client id |
| `HOTEL_MCP_CLIENT_SECRET` | empty | OAuth2 client secret |
| `HOTEL_MCP_SCOPES` | empty | Scopes to request. The server grants what it grants. |
| `SYSTEM_PROMPT_VARIANT` | `baseline` | `baseline`, `broken`, `broken-2` |
| `HOTEL_MCP_LEGACY_DATE_COMPAT` | `true` | The Exercise 1 defect |

## Tracing

There is none in this repository, deliberately. No OTEL setup, no traceloop
dependency, nothing to configure.

Tracing comes from the platform: leave Agent Manager's **auto-instrumentation
toggle ON** and it covers the LangChain and LangGraph spans this agent produces.
Exercise 1 depends on those spans — specifically on being able to compare the
model's chosen tool arguments against what the tool actually received — so
confirm they arrive before running a session.

Do not add an in-process OTEL init. A second initialisation double-instruments
the process and distorts the very trace shape the study is evaluating.

## Readiness

`GET /health` and the startup log line share one source of truth, so the log
also confirms the environment injection landed:

```
READY {"ok": true, "model": "gpt-4o", "governed": true, "prompt_variant": "baseline",
       "mcp_configured": true, "mcp_tools_loaded": ["get_booking", ...],
       "legacy_date_compat": true,
       "outbound_auth": {"mode": "none", "credential_present": false}}
```

The agent is built during startup rather than on first request, so MCP
discovery failures show up at boot rather than in front of a guest. Agent
Manager's Workload schema exposes no readiness probe, so this line is the only
in-band signal during the cold-start window.

If `governed` is false after configuring an LLM Service Provider, the env-var
contract is not reaching the agent. If `mcp_tools_loaded` is empty, the proxy
is unreachable or the credential is wrong.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -q                     # 55 tests, ~10s

export OPENAI_API_KEY=sk-...
export HOTEL_MCP_URL=http://localhost:9000/mcp
python main.py
```

Start `mcp/hotel-mcp` first, or the agent boots with native tools only.

```bash
curl -s localhost:8000/health | jq

curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' -d '{
  "message": "This is Priya Raman, booking reference GM-4471. Please move my stay to check in on 6 April 2026, still three nights.",
  "session_id": "demo-1",
  "context": {"guest_id": "guest-priya", "guest_name": "Priya Raman"}
}' | jq -r .response

curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' -d '{
  "message": "Can you read that booking back to me?", "session_id": "demo-1",
  "context": {"guest_id": "guest-priya", "guest_name": "Priya Raman"}
}' | jq -r .response
```

The first reply says 6 April. The second says 4 June. That is the fixture
working as intended.

The console lives at the repository root, not here, because it is a client of
the gateway rather than part of the agent's deployable unit:

```bash
python web/serve.py --no-auth     # unsecured, for local work
python web/serve.py               # secured, expects an OAuth2 gateway
```

The agent contains no inbound authentication and must not gain any. The gateway
validates tokens. See `web/README.md`.

## Deploying

| Field | Value |
|---|---|
| Language | Python 3.11 |
| App Path | `agent/` |
| Start Command | `python main.py` |
| Port | 8000 |
| Agent Interface | Chat Agent |

Attach the hotel-mcp Tool Configuration, mapping `url` to `HOTEL_MCP_URL` and,
if the proxy expects a key, `apikey` to `HOTEL_MCP_API_KEY`. For an
OAuth2-protected proxy, set the `HOTEL_MCP_TOKEN_URL` / `CLIENT_ID` /
`CLIENT_SECRET` trio instead. The agent discovers tools once at startup, so
redeploy after attaching it.

Two deployments are built from this same path for Exercise 3, differing only in
name and in the credential attached to them. The code is byte-identical.
