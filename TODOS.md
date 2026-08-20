# TODOS

> Historical log from the original concierge demo, kept for the dependency
> notes. Paths have moved: `requirements.txt`, `agent.py` and `tests/` are now
> under `agent/`. For the current fixture see
> [docs/facilitator-guide.md](docs/facilitator-guide.md).

## Pre-flight: hello-world deploy validation

**What:** Push a 5-line `print("hello")` agent stub to a throwaway GitHub repo, connect it to Agent Manager, deploy. Verify the repo layout assumption (`agent.py` + `requirements.txt`, no Procfile/Dockerfile needed) before writing the real agent.

**Why:** Plan assumes "treat as standard Python: `agent.py` + `requirements.txt`." If Agent Manager expects a different layout (Procfile, Dockerfile, specific entry name, runtime.txt), you discover it Day 1 morning mid-build and waste hours debugging the deploy pipeline instead of building the agent.

**Pros:** ~20 min now removes the highest-blast-radius unknown in the plan. De-risks Day 1 morning.

**Cons:** ~20 min added if redundant. If user already knows Agent Manager's expected layout from prior work, this is unnecessary.

**Context:** Agent Manager builds from GitHub repo. Standard Python convention is `requirements.txt` + named entry point (`agent.py` / `main.py` / `app.py`). Platform-specific layouts (Heroku Procfile, Cloud Run Dockerfile, fly.io fly.toml) differ. Unclear which family Agent Manager belongs to. Verifying with a stub keeps the cost of being wrong low.

**Depends on / blocked by:** Agent Manager access, ability to create a throwaway GitHub repo.

**When to do this:** Before Day 1 morning build, OR the moment Day 1 morning's real-agent deploy fails for a structural reason.

**Status (2026-04-30):** Done. Real agent shipped, pre-flight assumption held.

## Drop `wrapt<2` pin once upstream ships fix

**RESOLVED 2026-08-20, differently.** Local instrumentation was removed from the
agent entirely: `tracing.py`, its tests, and both the `traceloop-sdk` and
`wrapt<2` pins are gone. Tracing now comes from Agent Manager's
auto-instrumentation, so the platform owns that dependency resolution and this
repository has no opinion on the wrapt version. The notes below are kept only as
background on why the pin existed.


**What:** Remove the `wrapt<2` pin in `requirements.txt` and let it resolve to wrapt 2.x.

**Why:** The pin is load-bearing today because no released `opentelemetry-instrumentation-langchain` handles wrapt 2.x. Once upstream ships the fix, the pin becomes dead weight and blocks adopting any future dep that requires wrapt 2.x.

**Unblock conditions (all four must hold):**
1. openllmetry PR #4048 OR #4025 merges — https://github.com/traceloop/openllmetry/pull/4048 / https://github.com/traceloop/openllmetry/pull/4025
2. `opentelemetry-instrumentation-langchain` cuts a release that includes the fix (was 0.60.0 on 2026-04-19; check pypi for ≥0.61.x).
3. `traceloop-sdk` re-pins to that release.
4. We bump our pinned `traceloop-sdk` version in `requirements.txt` and verify the LangChain instrumentor initializes under wrapt 2.x.

**Context:** See the memory file `project_amp_instrumentation_wrapt_pin.md` for full background. Issue traceloop/openllmetry#4009 was filed 2026-04-16 and has been open ~2 weeks. CodeRabbit was still iterating on review feedback as of 2026-04-29.

**Verify after unpinning:** Redeploy with auto-instrumentation OFF, run Q10 against the deployed instance, confirm trace panel shows nested LangGraph spans + tool spans. If broken, revert.

**Depends on / blocked by:** Upstream merges + releases. No internal blockers.
