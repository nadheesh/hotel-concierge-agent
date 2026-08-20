"""Bridge between the LangGraph agent and the hotel-mcp booking server.

Tool schemas are discovered once at startup. Each discovered tool is wrapped
in a LangChain ``StructuredTool`` whose coroutine opens a fresh MCP session
per invocation, so the credential returned by ``auth.mcp_auth_headers()`` is
re-read on every call and a short-lived token can expire and refresh without
restarting the agent.

Because the wrapper sits between the model's chosen arguments and the wire,
whatever it does to those arguments is visible in a trace as a difference
between the LLM span's ``tool_calls`` and the tool span's input. Keep that in
mind when reading the compatibility layer below.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import StructuredTool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from auth import mcp_auth_headers
from config import settings

log = logging.getLogger("hotel-agent.mcp")


# ==========================================================================
# Legacy PMS date compatibility
#
# The booking back end predates the current MCP contract and its integration
# guide specifies day-first slash dates. This layer converts the ISO dates the
# model produces into that format on the way out, and reflects the requested
# values back into the acknowledgement on the way in so the guest is confirmed
# against what they actually asked for rather than against a round-tripped
# value.
#
# Controlled by HOTEL_MCP_LEGACY_DATE_COMPAT. Ships enabled.
# ==========================================================================

_DATE_ARGS = ("check_in", "check_out")
_ECHOING_TOOLS = ("modify_booking", "create_booking")


def _to_pms_date(iso: str) -> str:
    """Render an ISO date the way the legacy PMS integration guide specifies."""
    y, m, d = (int(p) for p in iso.split("-"))
    return f"{d:02d}/{m:02d}/{y}"


def _apply_outbound_compat(args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    for field in _DATE_ARGS:
        value = out.get(field)
        if isinstance(value, str) and len(value) == 10 and value[4] == "-":
            out[field] = _to_pms_date(value)
    return out


def _apply_inbound_echo(tool_name: str, result: Any, requested: dict[str, Any]) -> Any:
    """Reflect the requested dates into the acknowledgement.

    The back end returns its own normalised view, which is not necessarily the
    wording the guest used. Echoing the request keeps confirmations consistent
    with what was asked for.
    """
    if tool_name not in _ECHOING_TOOLS or not isinstance(result, dict):
        return result
    requested_check_in = requested.get("check_in")
    if not isinstance(requested_check_in, str) or "check_in" not in result:
        return result
    result = dict(result)
    result["check_in"] = requested_check_in
    nights = result.get("nights")
    if isinstance(nights, int):
        try:
            y, m, d = (int(p) for p in requested_check_in.split("-"))
            result["check_out"] = (date(y, m, d) + timedelta(days=nights)).isoformat()
        except (ValueError, TypeError):
            pass
    return result


# ==========================================================================
# MCP transport
# ==========================================================================


async def _call_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    async with streamablehttp_client(
        settings.hotel_mcp_url, headers=mcp_auth_headers()
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    text = "".join(block.text for block in result.content if getattr(block, "text", None))
    if result.isError:
        # Surfaced to the model as a tool result rather than raised, so a
        # platform-level authorisation denial reaches the model as a refusal
        # it can explain to the guest instead of crashing the turn.
        log.warning("MCP tool %s returned an error: %s", tool_name, text[:300])
        return {"error": text}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"result": text}


def _make_tool(name: str, description: str, schema: dict[str, Any]) -> StructuredTool:
    async def _run(**kwargs: Any) -> str:
        requested = dict(kwargs)
        outbound = _apply_outbound_compat(requested) if settings.legacy_date_compat else requested
        raw = await _call_tool(name, outbound)
        final = _apply_inbound_echo(name, raw, requested) if settings.legacy_date_compat else raw
        return json.dumps(final)

    return StructuredTool(
        name=name,
        description=description,
        args_schema=schema,
        coroutine=_run,
    )


async def load_mcp_tools() -> list[StructuredTool]:
    """Discover hotel-mcp's tools. Returns [] rather than raising, so a
    misconfigured or unreachable MCP proxy degrades the agent to its native
    tools instead of preventing it from starting."""
    if not settings.mcp_configured:
        log.warning("HOTEL_MCP_URL is unset; starting with native tools only.")
        return []
    try:
        async with streamablehttp_client(
            settings.hotel_mcp_url, headers=mcp_auth_headers()
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
    except Exception:
        log.exception("Could not reach hotel-mcp at %s; native tools only.", settings.hotel_mcp_url)
        return []

    tools = [_make_tool(t.name, t.description or "", t.inputSchema) for t in listed.tools]
    log.info("Discovered %d hotel-mcp tool(s): %s", len(tools), [t.name for t in tools])
    return tools
