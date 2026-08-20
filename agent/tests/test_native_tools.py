"""Unit tests for the native, in-process tools.

Everything booking-related now lives in hotel-mcp and is covered by that
project's tests. What remains here is the non-booking concierge surface.
"""

from __future__ import annotations

from tools import NATIVE_TOOLS, get_local_recommendations, get_room_service_menu


class TestRoomServiceMenu:
    def test_full_menu(self) -> None:
        r = get_room_service_menu()
        assert r["count"] == 6
        assert r["filtered"] == "none"

    def test_vegetarian_filter(self) -> None:
        r = get_room_service_menu(vegetarian_only=True)
        assert r["count"] == 4
        assert all(item["vegetarian"] for item in r["items"])
        assert r["filtered"] == "vegetarian_only"

    def test_none_is_treated_as_false(self) -> None:
        assert get_room_service_menu(None)["count"] == 6


class TestLocalRecommendations:
    def test_known_category(self) -> None:
        r = get_local_recommendations("restaurants")
        assert r["count"] == 3
        assert r["recommendations"][0]["name"] == "L'Ardoise"

    def test_unknown_category_returns_error_not_raise(self) -> None:
        r = get_local_recommendations("casinos")
        assert "error" in r
        assert "restaurants" in r["error"]

    def test_non_string_category(self) -> None:
        assert "error" in get_local_recommendations(None)  # type: ignore[arg-type]


class TestRegistration:
    """If a name or signature drifts, the model calls the wrong thing and the
    failure is silent rather than loud."""

    def test_names(self) -> None:
        assert {t.name for t in NATIVE_TOOLS} == {
            "get_room_service_menu",
            "get_local_recommendations",
        }

    def test_booking_tools_are_not_native(self) -> None:
        # Booking tools must arrive over MCP so they can be scope-governed.
        # A native booking tool would be invisible to the MCP proxy and would
        # quietly defeat the least-privilege exercise.
        names = {t.name for t in NATIVE_TOOLS}
        assert not names & {"get_booking", "modify_booking", "cancel_booking"}

    def test_descriptions_present(self) -> None:
        assert all((t.description or "").strip() for t in NATIVE_TOOLS)
