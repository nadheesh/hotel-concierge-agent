"""Entry point matching the WSO2 Agent Manager start-command convention.

Agent Manager invokes `python main.py` after build.

No instrumentation is set up here on purpose. Tracing comes from the platform:
leave Agent Manager's "Enable auto-instrumentation" toggle ON and it covers the
LangChain and LangGraph spans this agent produces without any code in the repo.
Adding a second OTEL init in-process would double-instrument and distort the
trace shape the study is meant to evaluate.
"""

from __future__ import annotations

import uvicorn

from agent import app

# Pinned, deliberately not read from PORT. Agent Manager injects PORT=8080, so
# honouring it left the app on 8080 while the probe and the declared endpoint
# looked for 8000: nothing inbound ever reached uvicorn, the liveness check
# failed, and the pod was SIGTERMed and recycled every few minutes with a clean
# shutdown and no error to explain it. 8000 is what the rest of the repo
# assumes -- agent/README.md, docs/facilitator-guide.md, scripts/dev_up.sh and
# the web client. If the platform probe ever targets 8080 instead, change this
# constant rather than restoring the PORT lookup, so the bind port stays
# something the repo states outright.
PORT = 8000

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
