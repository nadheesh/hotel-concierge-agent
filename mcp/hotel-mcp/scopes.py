"""Which scope each tool should require — reference data, not enforcement.

This server enforces nothing. Authorisation on the way IN is the gateway's job:
in Agent Manager that is the MCP Proxy sitting in front of this endpoint. The
table below is what you configure there, and what a facilitator shows a
participant when explaining the authorisation model without reading tool bodies.

Keeping it here rather than in the gateway config means the agent repo, the
server and the proxy all describe the same split in the same words.
"""

READ = "booking:read"
WRITE = "booking:write"

TOOL_SCOPES: dict[str, str] = {
    "get_booking": READ,
    "list_my_bookings": READ,
    "search_availability": READ,
    "get_booking_policies": READ,
    "modify_booking": WRITE,
    "cancel_booking": WRITE,
    "create_booking": WRITE,
}

READ_TOOLS = sorted(t for t, s in TOOL_SCOPES.items() if s == READ)
WRITE_TOOLS = sorted(t for t, s in TOOL_SCOPES.items() if s == WRITE)
