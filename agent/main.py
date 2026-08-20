"""Entry point matching the WSO2 Agent Manager start-command convention.

Agent Manager invokes `python main.py` after build.

No instrumentation is set up here on purpose. Tracing comes from the platform:
leave Agent Manager's "Enable auto-instrumentation" toggle ON and it covers the
LangChain and LangGraph spans this agent produces without any code in the repo.
Adding a second OTEL init in-process would double-instrument and distort the
trace shape the study is meant to evaluate.
"""

from __future__ import annotations

import os

import uvicorn

from agent import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
