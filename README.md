# Hotel Booking Agent — WSO2 Agent Manager test fixture

A complete, deliberately imperfect agent system for the Agent Manager
end-to-end UX study. Everything here exists to let a participant take a
realistic agent from source to a controlled production deployment, and to let a
facilitator see exactly where the platform helps and where it does not.

This is a **test fixture, not a sample application.** It ships with a seeded
defect, a seeded authorisation weakness and two deliberate prompt omissions.
All of them are load-bearing, all are pinned by tests, and all are documented.

> **Start here:** [`docs/facilitator-guide.md`](docs/facilitator-guide.md) for
> the four stages, the seeded defects and the reference solutions.
> [`docs/participant-briefs.md`](docs/participant-briefs.md) for what the
> participants actually see. Do not give them the facilitator guide.

## Layout

```
agent/      The agent under test. LangGraph + OpenAI, Chat Agent contract.
mcp/hotel-mcp/          Booking MCP server. 7 tools split read/write, seeded data.
evaluators/security/    7 category judges + shared rubric.
evaluators/quality/     Which built-in evaluator to use where, + 1 custom judge.
fixtures/               36 quality cases with ground truth, 43 security cases.
scripts/                Traffic generation, cost burn, fixture reset, bring-up.
web/                    Guest console. The OAuth2 client for Exercise 1.
docs/                   Facilitator guide and participant briefs.
vip_crew/               External CrewAI agent, for the external-agent extension.
```

## What is deliberately wrong

| # | Where | What | Used by |
|---|---|---|---|
| 1 | `agent/mcp_client.py` | Date compatibility layer writes the wrong date and echoes the request back, so the reply looks correct | Exercise 1 |
| 2 | `agent/auth.py` | No credential configured, so MCP calls go out bare and every deployment can do everything | Exercise 3 |
| 3 | `mcp/hotel-mcp` | Unsecured by design — nothing below the agent scopes access per guest | Exercise 4, category 4 |
| 4 | `agent/system_prompt.py` | No injection hardening, no terms-and-conditions instruction | Exercises 2 and 4 |
| 5 | `mcp/hotel-mcp/seed/bookings.json`, `policies.py` | Two planted injection payloads, in a booking record and in a policy document | Exercise 4, categories 2 and 3 |
| 6 | `agent/system_prompt.py` | `SYSTEM_PROMPT_VARIANT=broken` strips grounding without touching a tool | Exercise 4 regression |

`agent/tests/` pins 1 and 4 in place. Run `pytest tests/ -q` before
every session; 55 tests, a couple of seconds. If they fail, someone has repaired
the fixture and the exercises they support no longer work.

## The four exercises at a glance

| | Goal | Turns on |
|---|---|---|
| **1** | Deploy, find why a plausible answer is wrong, promote, recover | Reading a trace to separate the model's decision from the agent's behaviour |
| **2** | Cost ceiling, injection guardrail, terms-and-conditions decorator | Platform controls applied without touching business logic |
| **3** | Read-only customer agent, read-write ops agent, same source | Per-agent credentials and gateway-enforced tool scopes |
| **4** | Quality and security evaluation, then production monitoring | Whether a score can be traced back to evidence |

## Quick start

```bash
# 1. booking server (unsecured: expose only behind a gateway)
cd mcp/hotel-mcp && pip install -r requirements.txt
python server.py &                              # -> :9000/mcp

# 2. agent
cd ../../agent && pip install -r requirements.txt
pytest tests/ -q                                # 55 passed
export OPENAI_API_KEY_DEFAULT=sk-...
export HOTEL_MCP_URL=http://localhost:9000/mcp
python main.py &                                # -> :8000

# 3. confirm the Exercise 1 defect reproduces
curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' -d '{
  "message": "This is Priya Raman, booking reference GM-4471. Please move my stay to check in on 6 April 2026, still three nights.",
  "session_id": "check", "context": {"guest_id": "guest-priya", "guest_name": "Priya Raman"}}' | jq -r .response
# says 6 April

curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' -d '{
  "message": "Read that booking back to me.", "session_id": "check",
  "context": {"guest_id": "guest-priya", "guest_name": "Priya Raman"}}' | jq -r .response
# says 4 June
```

If those two replies disagree, the fixture is healthy.

## Running the evaluation suites

```bash
python scripts/run_script_a.py --agent-url https://<agent>/chat --token <jwt>
python scripts/run_script_b.py --agent-url https://<customer>/chat --deployment customer
python scripts/run_script_b.py --agent-url https://<ops>/chat --deployment ops
```

Every request uses the case id as its session id, so any result in the console
traces back to exactly one fixture line. Every security score is **resilience**:
higher is better.

Between participants:

```bash
HOTEL_MCP_ADMIN_TOKEN=... python scripts/reset_fixture.py --mcp-url https://<mcp>
```

## The console

`web/` is the guest-facing site and chat widget, and the client the participant
connects in Exercise 1. It runs in one of three modes, chosen by a flag and a
config file:

```bash
python web/serve.py --no-auth     # no security: browser calls the agent directly
python web/serve.py               # secured: an OAuth2 access token on every call
```

Secured mode has two shapes. `broker` keeps the client id and secret on the dev
server and hands the browser only a short-lived token; `pkce` uses
authorization-code + PKCE and involves no secret at all.

The agent performs **no** authentication. The platform gateway in front of it
validates the token, and `agent/agent.py` contains no inbound auth
logic — verified, and it must stay that way. An agent that checks its own tokens
is not testing the platform. Full detail in [`web/README.md`](web/README.md).

## Tracing

None in this repository, by design. Agent Manager's auto-instrumentation supplies
it; keep that toggle ON. Exercise 1 is unsolvable without those spans, so confirm
they arrive before the first session. Do not add a local OTEL init — it would
double-instrument and distort the trace shape under evaluation.

## Credentials

No credential is committed anywhere in this repository, and none should be.
Every value arrives as an environment variable or a platform secret. The web
widget in `agent/web/` runs in the browser and must never be given
a key — watching whether a participant respects that is part of Exercise 1.

`mcp/hotel-mcp` is unsecured by design and must sit behind a gateway that is
never bypassable — anything that can reach it directly can cancel any booking.
Generate your own `HOTEL_MCP_ADMIN_TOKEN`, and give development and production
different credentials throughout. Environment isolation is one of the things the
study observes.

## Before the first session

Four things in the facilitator guide need settling against the live console,
because each one changes the setup or the brief: whether MCP scoping works per
tool or only per proxy, whether evaluators can see tool calls, whether results
can be grouped by a custom category label, and whether a cost ceiling can be
scoped to a single agent. See
[Open questions](docs/facilitator-guide.md#open-questions-to-settle-before-the-first-session).
