"""VIP crew tools."""

import json
from pathlib import Path
from crewai.tools import tool
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)
_TOOL_NAME = "lookup_guest_history"


def _load_vip_guests():
    """Load VIP_GUESTS from parent hotel_data.py (runtime file read).

    vip_crew runs in its own venv (not editable-installed), so direct
    import of hotel_data would fail. Instead, we read hotel_data.py at
    runtime. Single source of truth held in ../hotel_data.py.
    """
    hotel_data_path = Path(__file__).parent.parent / "agent" / "hotel_data.py"
    with open(hotel_data_path) as f:
        code = f.read()
    namespace: dict = {}
    exec(code, namespace)
    return namespace.get("VIP_GUESTS", {})


@tool
def lookup_guest_history(guest_id: str) -> dict:
    """Look up VIP guest history and preferences.

    Args:
        guest_id: Guest ID (e.g., "VIP-042")

    Returns:
        Guest dict with name, tier, previous_stays, preferences, notes.
        Returns empty dict if guest not found.
    """
    args = {"guest_id": guest_id}
    with _tracer.start_as_current_span(f"execute_tool {_TOOL_NAME}") as span:
        # Standard OTEL GenAI semconv
        span.set_attribute("gen_ai.tool.name", _TOOL_NAME)
        span.set_attribute("gen_ai.tool.call.arguments", json.dumps(args))
        # Traceloop entity convention — what AM's trace panel reads to render
        # tool spans the same way it does for LangGraph traces in Acts 1-3
        span.set_attribute("traceloop.span.kind", "tool")
        span.set_attribute("traceloop.entity.name", _TOOL_NAME)
        span.set_attribute("traceloop.entity.input", json.dumps(args))
        result = _load_vip_guests().get(guest_id, {})
        result_json = json.dumps(result)
        span.set_attribute("gen_ai.tool.call.result", result_json)
        span.set_attribute("traceloop.entity.output", result_json)
        return result
