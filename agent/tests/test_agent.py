"""Agent surface: credential mode resolution, history truncation, readiness."""

from __future__ import annotations

import importlib

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _reload(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Re-import config and agent with a fresh environment. Settings are read
    once at import, matching how the deployed process behaves."""
    for key in (
        "OPENAI_URL",
        "OPENAI_API_KEY",
        "HOTEL_MCP_URL",
        "HOTEL_MCP_API_KEY",
        "HOTEL_MCP_TOKEN_URL",
        "HOTEL_MCP_CLIENT_ID",
        "HOTEL_MCP_CLIENT_SECRET",
        "SYSTEM_PROMPT_VARIANT",
        "HOTEL_MCP_LEGACY_DATE_COMPAT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config

    importlib.reload(config)
    import auth

    importlib.reload(auth)
    import agent

    return importlib.reload(agent)


class TestCredentialModes:
    def test_governed_mode_puts_key_on_api_key_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _reload(monkeypatch, OPENAI_URL="https://gw.example/v1", OPENAI_API_KEY="jwt-here")
        kwargs = agent._llm_kwargs()
        assert kwargs["base_url"] == "https://gw.example/v1"
        assert kwargs["default_headers"]["API-Key"] == "jwt-here"
        # Authorization must be blanked or the gateway sees two credentials.
        assert kwargs["default_headers"]["Authorization"] == ""
        assert kwargs["api_key"] == "unused"

    def test_ungoverned_mode_sends_the_key_straight_to_openai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _reload(monkeypatch, OPENAI_API_KEY="sk-local")
        kwargs = agent._llm_kwargs()
        assert kwargs == {"api_key": "sk-local"}
        assert "base_url" not in kwargs

    def test_same_key_slot_serves_both_modes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # One slot, so a key can no longer land in the "wrong" one and silently
        # leave the agent with no credential.
        agent = _reload(monkeypatch, OPENAI_API_KEY="k")
        assert agent._llm_kwargs()["api_key"] == "k"
        agent = _reload(monkeypatch, OPENAI_API_KEY="k", OPENAI_URL="https://gw.example/v1")
        assert agent._llm_kwargs()["default_headers"]["API-Key"] == "k"

    def test_no_key_at_all_is_not_a_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # /health must stay reachable so an operator can see what is missing.
        agent = _reload(monkeypatch)
        assert agent._llm_kwargs() == {"api_key": ""}


class TestReadyPayload:
    def test_reports_governed_and_mcp_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _reload(
            monkeypatch,
            OPENAI_URL="https://gw.example/v1",
            OPENAI_API_KEY="jwt",
            HOTEL_MCP_URL="https://mcp.example/mcp",
            HOTEL_MCP_API_KEY="k",
        )
        payload = agent._ready_payload()
        assert payload["governed"] is True
        assert payload["mcp_configured"] is True
        assert payload["legacy_date_compat"] is True
        assert payload["outbound_auth"]["mode"] == "api-key"

    def test_reports_ungoverned_and_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _reload(monkeypatch, OPENAI_API_KEY="sk-local")
        payload = agent._ready_payload()
        assert payload["governed"] is False
        assert payload["mcp_configured"] is False
        assert payload["outbound_auth"]["mode"] == "none"
        assert payload["outbound_auth"]["credential_present"] is False

    def test_imports_and_reports_health_with_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # CI, linters and cold /health checks must not need a key.
        agent = _reload(monkeypatch)
        assert agent._ready_payload()["ok"] is True


class TestTruncate:
    def test_no_truncation_under_cap(self) -> None:
        import agent

        history = [HumanMessage(content=str(i)) for i in range(5)]
        assert agent._truncate(history) == history

    def test_truncates_to_cap(self) -> None:
        import agent

        history = [HumanMessage(content=str(i)) for i in range(60)]
        assert len(agent._truncate(history)) == agent.MAX_SESSION_MESSAGES

    def test_never_starts_on_an_orphaned_tool_message(self) -> None:
        import agent

        # A ToolMessage without its preceding AIMessage tool_calls is an
        # invalid prompt and the provider rejects the whole turn.
        history: list = [HumanMessage(content="pad") for _ in range(agent.MAX_SESSION_MESSAGES)]
        history += [
            AIMessage(content="", tool_calls=[{"name": "get_booking", "args": {}, "id": "1"}]),
            ToolMessage(content="{}", tool_call_id="1"),
            AIMessage(content="done"),
        ]
        assert not isinstance(agent._truncate(history)[0], ToolMessage)


class TestFinalText:
    def test_reads_last_ai_message(self) -> None:
        import agent

        assert agent._final_text([HumanMessage(content="hi"), AIMessage(content=" reply ")]) == "reply"

    def test_flattens_content_blocks(self) -> None:
        import agent

        msg = AIMessage(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert agent._final_text([msg]) == "ab"

    def test_empty_when_no_ai_message(self) -> None:
        import agent

        assert agent._final_text([HumanMessage(content="hi")]) == ""
