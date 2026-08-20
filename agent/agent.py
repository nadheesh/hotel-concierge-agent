"""Hotel booking agent — FastAPI service exposing POST /chat.

Implements the WSO2 Agent Manager chat contract:
  Request:  {message: string, session_id: string, context: JSON}
  Response: {response: string}

Tools come from two places, deliberately:
  * Native, in-process (tools.py) — menu and local recommendations. These are
    not governable by an MCP proxy, which is the contrast the least-privilege
    exercise depends on.
  * hotel-mcp over an MCP proxy (mcp_client.py) — everything to do with
    bookings, split into read-scoped and write-scoped tools.

Conversation state is per-process and keyed by session_id. Single-replica
scope; a multi-replica deploy would need shared state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from openai import APIError, OpenAIError, RateLimitError
from pydantic import BaseModel

import auth
from config import settings
from mcp_client import load_mcp_tools
from system_prompt import select_prompt, with_caller
from tools import NATIVE_TOOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hotel-agent")

# A single turn adds 2-4 entries (user, tool_calls, tool results, reply), so
# 40 covers roughly ten turns.
MAX_SESSION_MESSAGES = 40
FRIENDLY_FALLBACK = (
    "I'm having trouble reaching our systems right now — could you try that again in a moment?"
)

SESSIONS: dict[str, list[BaseMessage]] = {}
SESSION_LOCKS: dict[str, asyncio.Lock] = {}

BASE_PROMPT = select_prompt(settings.system_prompt_variant)

# MCP tools are discovered once at startup so a broken proxy shows up at boot
# rather than in front of a guest. The LLM client is built lazily on first use,
# because a missing or wrong model credential must still leave /health and the
# READY line reachable — an operator diagnosing a bad secret needs the agent to
# come up and report what is wrong, not to crash-loop.
_mcp_tools: list = []
_agent = None


def _llm_kwargs() -> dict[str, Any]:
    """OPENAI_URL presence is the mode gate. In governed mode the AM gateway
    expects the key on an ``API-Key`` header rather than ``Authorization:
    Bearer``, so the SDK's default Authorization header is suppressed. In BYO
    mode we go straight to OpenAI with OPENAI_API_KEY_DEFAULT."""
    if settings.governed:
        # openai>=1.50 rejects an empty api_key before default_headers can
        # override anything, so pass a sentinel. default_headers blanks
        # Authorization, so the sentinel never reaches the wire.
        return {
            "base_url": settings.openai_url,
            "api_key": "unused",
            "default_headers": {"API-Key": settings.openai_api_key, "Authorization": ""},
        }
    return {"api_key": settings.openai_api_key_default}


async def _discover_tools() -> None:
    """Startup: pull hotel-mcp's tool list. Never raises; an unreachable proxy
    degrades the agent to native tools only."""
    global _mcp_tools
    _mcp_tools = await load_mcp_tools()


def _get_agent():
    """Lazy. ChatOpenAI validates credentials at construction, so building this
    on first request rather than at boot is what keeps /health available when
    the model credential is missing or wrong."""
    global _agent
    if _agent is None:
        all_tools = NATIVE_TOOLS + _mcp_tools
        llm = ChatOpenAI(model=settings.openai_model, **_llm_kwargs())
        _agent = create_react_agent(llm, tools=all_tools)
        log.info("agent built with %d tool(s): %s", len(all_tools),
                 [t.name for t in all_tools])
    return _agent


def _ready_payload() -> dict[str, Any]:
    """Single source of truth for /health and the startup log line. Everything
    an operator needs to confirm the environment injection landed: which model,
    whether the LLM is governed, which MCP endpoint, which credential mode, and
    which tools actually loaded."""
    return {
        "ok": True,
        "model": settings.openai_model,
        "governed": settings.governed,
        "prompt_variant": settings.system_prompt_variant,
        "mcp_configured": settings.mcp_configured,
        "mcp_tools_loaded": [t.name for t in _mcp_tools],
        "llm_client_built": _agent is not None,
        "legacy_date_compat": settings.legacy_date_compat,
        "outbound_auth": auth.describe_credential(),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Discover MCP tools up front so a broken proxy shows at startup rather
    than on the first guest message, then emit a greppable READY line. Agent
    Manager's Workload schema exposes no readiness probe, so this log line is
    the only in-band signal during the cold-start window."""
    await _discover_tools()
    log.info("READY %s", json.dumps(_ready_payload()))
    yield


app = FastAPI(title="Grand Meridian Booking Agent", lifespan=lifespan)
# Local dev only (static site on :5500 -> agent on :8000). On an Agent Manager
# deploy the Envoy gateway in front handles CORS and this is redundant.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str
    context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    response: str


@app.get("/health")
async def health() -> dict[str, Any]:
    return _ready_payload()


def _truncate(history: list[BaseMessage]) -> list[BaseMessage]:
    """Keep the most recent messages, but never begin the slice on a
    ToolMessage — orphaned from its AIMessage tool_calls it is an invalid
    prompt."""
    if len(history) <= MAX_SESSION_MESSAGES:
        return history
    cut = len(history) - MAX_SESSION_MESSAGES
    while cut < len(history) and isinstance(history[cut], ToolMessage):
        cut += 1
    return history[cut:]


def _final_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                ).strip()
    return ""


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    started = time.perf_counter()

    if not req.message.strip():
        return ChatResponse(response="How can I help you today?")
    if not req.session_id:
        log.warning("empty session_id; conversation continuity disabled for this turn")

    sid = req.session_id or "_anonymous_"
    ctx = req.context or {}
    prompt = with_caller(BASE_PROMPT, ctx.get("guest_name"), ctx.get("guest_id"))

    lock = SESSION_LOCKS.setdefault(sid, asyncio.Lock())
    async with lock:
        history = SESSIONS.get(sid, []) + [HumanMessage(content=req.message)]
        if ctx:
            log.info("session=%s context=%s", sid, json.dumps(ctx)[:500])

        try:
            # The system message is prepended per turn rather than baked into
            # the graph, because it carries the caller identity from `context`
            # and that changes between sessions. It is stripped before the
            # history is stored so it never accumulates.
            result = await _get_agent().ainvoke(
                {"messages": [SystemMessage(content=prompt)] + history},
                config={
                    "recursion_limit": 25,
                    "configurable": {"thread_id": sid},
                    "metadata": {"session_id": sid, "guest_id": ctx.get("guest_id")},
                },
            )
            history = [m for m in result["messages"] if not isinstance(m, SystemMessage)]
            reply = _final_text(history) or FRIENDLY_FALLBACK
        except GraphRecursionError:
            log.warning("session=%s langgraph recursion limit exceeded", sid)
            reply = "I'm still working that out — could you give me a moment and ask again?"
        except RateLimitError:
            log.warning("session=%s openai rate limit", sid)
            reply = FRIENDLY_FALLBACK
        except APIError as e:
            log.warning("session=%s openai api error: %s", sid, e)
            reply = FRIENDLY_FALLBACK
        except OpenAIError as e:
            # Missing or invalid credential surfaces at client construction,
            # not as an APIError. Must come after APIError, which subclasses it.
            # /health stays up reporting llm_client_built false — that is the
            # diagnostic an operator needs for a bad secret.
            log.error("session=%s model credential problem: %s", sid, e)
            reply = FRIENDLY_FALLBACK
        except Exception as e:
            log.exception("session=%s unhandled error in /chat: %s", sid, e)
            reply = FRIENDLY_FALLBACK

        SESSIONS[sid] = _truncate(history)

    log.info(
        "session=%s reply_chars=%d elapsed_ms=%d",
        sid,
        len(reply),
        int((time.perf_counter() - started) * 1000),
    )
    return ChatResponse(response=reply)
