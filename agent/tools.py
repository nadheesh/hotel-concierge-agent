"""Native, in-process concierge tools.

These stay in the agent process on purpose. They are the non-booking half of
the agent's surface, and because they never cross an MCP proxy they cannot be
governed by tool-level scopes. That contrast is what the least-privilege
exercise is measured against: restricting the booking tools must not disturb
these, and these must not become a way to reach booking data.

Everything to do with bookings, availability, pricing and policy lives in
hotel-mcp and arrives through mcp_client.py.

Each tool validates defensively and returns either a result dict or
{"error": "<reason>"}. Tools never raise into the agent loop.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from hotel_data import MENU, RECOMMENDATIONS


def get_room_service_menu(vegetarian_only: bool | None = None) -> dict[str, Any]:
    """Return the in-room dining menu.

    Args:
        vegetarian_only: Filter to vegetarian items only. Optional, defaults to False.
    """
    veg = bool(vegetarian_only)
    items = [m for m in MENU if (not veg) or m["vegetarian"]]
    return {
        "items": items,
        "filtered": "vegetarian_only" if veg else "none",
        "count": len(items),
    }


def get_local_recommendations(category: str) -> dict[str, Any]:
    """Return curated recommendations near the hotel by category.

    Args:
        category: Which kind of recommendations. Must be one of:
            restaurants, family, nightlife, outdoors.
    """
    if not isinstance(category, str) or category not in RECOMMENDATIONS:
        return {
            "error": (
                f"No recommendations for that category. "
                f"Available: {', '.join(RECOMMENDATIONS.keys())}."
            )
        }
    return {
        "category": category,
        "recommendations": RECOMMENDATIONS[category],
        "count": len(RECOMMENDATIONS[category]),
    }


# Wrapped by calling tool(func) rather than decorating, so the plain functions
# stay directly callable from the unit tests.
NATIVE_TOOLS = [
    tool(get_room_service_menu),
    tool(get_local_recommendations),
]


__all__ = ["NATIVE_TOOLS", "get_room_service_menu", "get_local_recommendations"]
