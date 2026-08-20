"""Outbound credential for calls this agent makes to hotel-mcp.

This is the egress side only. Nothing here authenticates anyone: inbound
requests to the agent are the platform gateway's problem, and the agent has no
inbound auth logic at all.

WHAT THIS DECIDES
-----------------
``mcp_auth_headers()`` returns the headers attached to every outbound MCP
request. mcp_client.py calls it once per tool invocation, so a short-lived
credential can expire and refresh without restarting the agent.

Three shapes, in this precedence order:

  1. OAuth2 client credentials  -> ``Authorization: Bearer <token>``
     when HOTEL_MCP_TOKEN_URL, HOTEL_MCP_CLIENT_ID and HOTEL_MCP_CLIENT_SECRET
     are all set.
  2. API key                    -> ``<HOTEL_MCP_API_KEY_HEADER>: <key>``
     when HOTEL_MCP_API_KEY is set.
  3. Nothing                    -> ``{}``
     the endpoint is unsecured, or is secured by something this agent has not
     been given. Either way the call goes out bare and the gateway decides.

OAuth2 wins over an API key deliberately. An agent migrated to OAuth2 must not
be silently downgraded by a stale key still sitting in its environment, and a
downgrade is exactly the kind of thing nobody notices until an audit.

This does NOT assume an Agent Manager Agent Identity. Any OAuth2 client the
gateway trusts works, which matters because the identity may not exist yet when
someone first wires this up.

WHERE AUTHORISATION ACTUALLY HAPPENS
------------------------------------
Not here. This file chooses which credential to present. The gateway in front
of hotel-mcp validates it and decides which tools it may reach. Do not add tool
allow-lists or branch on tool names in this file: policy belongs to the
platform, and an agent that polices itself is not testing it.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from config import settings

log = logging.getLogger("hotel-agent.auth")

# Refresh this many seconds before the token actually expires, so a call in
# flight cannot land with a credential that died on the way.
_EXPIRY_MARGIN_S = 30

_lock = threading.Lock()
_token: str | None = None
_expires_at: float = 0.0
_warned_bare = False


def _oauth_token() -> str:
    """Fetch and cache a client-credentials token.

    The scopes on the returned token are whatever the authorisation server
    granted this client, which is not necessarily what was requested.
    HOTEL_MCP_SCOPES is an ask, not an entitlement, and that asymmetry is the
    whole mechanism behind per-agent least privilege.
    """
    global _token, _expires_at
    with _lock:
        if _token and time.time() < _expires_at - _EXPIRY_MARGIN_S:
            return _token

        form = {"grant_type": "client_credentials"}
        if settings.hotel_mcp_scopes:
            form["scope"] = settings.hotel_mcp_scopes

        response = httpx.post(
            settings.hotel_mcp_token_url,
            data=form,
            auth=(settings.hotel_mcp_client_id, settings.hotel_mcp_client_secret),
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()

        _token = payload["access_token"]
        _expires_at = time.time() + float(payload.get("expires_in", 300))
        log.info(
            "hotel-mcp token refreshed, granted scope=%r expires_in=%ss",
            payload.get("scope", "<not reported>"),
            payload.get("expires_in", 300),
        )
        return _token


def mcp_auth_headers() -> dict[str, str]:
    """Headers to attach to every outbound hotel-mcp request.

    Never raises on a missing credential — returning ``{}`` lets the gateway
    produce the rejection, which is a far more useful signal than the agent
    refusing to make the call. A genuine failure to *obtain* a configured token
    does propagate, because that is a misconfiguration worth surfacing loudly.
    """
    global _warned_bare

    if settings.mcp_oauth_configured:
        return {"Authorization": f"Bearer {_oauth_token()}"}

    if settings.hotel_mcp_api_key:
        return {settings.hotel_mcp_api_key_header: settings.hotel_mcp_api_key}

    if not _warned_bare:
        _warned_bare = True
        # Once, not per call: a bare endpoint is a legitimate local setup and
        # this should not drown the log during a session.
        log.warning(
            "No hotel-mcp credential configured; MCP calls will be made without one. "
            "Correct if the endpoint is unsecured, otherwise set HOTEL_MCP_API_KEY or "
            "the HOTEL_MCP_TOKEN_URL/CLIENT_ID/CLIENT_SECRET trio."
        )
    return {}


def describe_credential() -> dict[str, object]:
    """What this agent presents to hotel-mcp, surfaced on GET /health.

    An operator needs to tell from outside the process which credential is in
    play, because "the calls are failing" and "the calls are going out bare"
    look identical from the chat window.
    """
    if settings.mcp_oauth_configured:
        mode = "oauth2-client-credentials"
    elif settings.hotel_mcp_api_key:
        mode = "api-key"
    else:
        mode = "none"
    return {
        "mode": mode,
        "credential_present": mode != "none",
        "api_key_header": settings.hotel_mcp_api_key_header if mode == "api-key" else None,
        "token_url": settings.hotel_mcp_token_url if mode.startswith("oauth2") else None,
        "requested_scopes": settings.hotel_mcp_scopes or None,
        # A partially-filled OAuth2 config is a common and confusing mistake:
        # the agent silently uses the API key, or nothing, and looks fine.
        "oauth2_partially_configured": bool(
            (settings.hotel_mcp_token_url or settings.hotel_mcp_client_id
             or settings.hotel_mcp_client_secret)
            and not settings.mcp_oauth_configured
        ),
    }
