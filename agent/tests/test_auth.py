"""Egress credential selection.

auth.py is the only place that decides what this agent presents to hotel-mcp.
Getting the precedence wrong is silent: the agent keeps working, against the
wrong identity, until someone audits it. Hence tests.
"""

from __future__ import annotations

import importlib

import pytest

VARS = (
    "HOTEL_MCP_API_KEY",
    "HOTEL_MCP_API_KEY_HEADER",
    "HOTEL_MCP_TOKEN_URL",
    "HOTEL_MCP_CLIENT_ID",
    "HOTEL_MCP_CLIENT_SECRET",
    "HOTEL_MCP_SCOPES",
)


def _reload(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key in VARS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config

    importlib.reload(config)
    import auth

    return importlib.reload(auth)


class TestNoCredential:
    def test_returns_empty_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An unsecured endpoint is a legitimate setup. Going out bare must be
        # allowed so the gateway, not the agent, produces any rejection.
        auth = _reload(monkeypatch)
        assert auth.mcp_auth_headers() == {}

    def test_describes_itself_as_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _reload(monkeypatch)
        assert auth.describe_credential()["mode"] == "none"
        assert auth.describe_credential()["credential_present"] is False


class TestApiKey:
    def test_default_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _reload(monkeypatch, HOTEL_MCP_API_KEY="k123")
        assert auth.mcp_auth_headers() == {"API-Key": "k123"}

    def test_header_name_is_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # AM's own docs disagree between API-Key and X-API-Key.
        auth = _reload(monkeypatch, HOTEL_MCP_API_KEY="k123", HOTEL_MCP_API_KEY_HEADER="X-API-Key")
        assert auth.mcp_auth_headers() == {"X-API-Key": "k123"}

    def test_describes_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _reload(monkeypatch, HOTEL_MCP_API_KEY="k123")
        described = auth.describe_credential()
        assert described["mode"] == "api-key"
        assert described["api_key_header"] == "API-Key"


class TestOAuth2:
    def _configured(self, monkeypatch: pytest.MonkeyPatch, **extra: str):
        return _reload(
            monkeypatch,
            HOTEL_MCP_TOKEN_URL="https://idp.example/token",
            HOTEL_MCP_CLIENT_ID="cid",
            HOTEL_MCP_CLIENT_SECRET="csecret",
            **extra,
        )

    def test_bearer_header_from_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = self._configured(monkeypatch)
        calls: list = []

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"access_token": "tok-1", "expires_in": 300, "scope": "booking:read"}

        def fake_post(url, **kw):
            calls.append((url, kw))
            return FakeResponse()

        monkeypatch.setattr(auth.httpx, "post", fake_post)
        assert auth.mcp_auth_headers() == {"Authorization": "Bearer tok-1"}
        url, kw = calls[0]
        assert url == "https://idp.example/token"
        assert kw["data"] == {"grant_type": "client_credentials"}
        assert kw["auth"] == ("cid", "csecret")

    def test_scopes_are_requested_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = self._configured(monkeypatch, HOTEL_MCP_SCOPES="booking:read booking:write")
        seen: dict = {}

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"access_token": "t", "expires_in": 300}

        monkeypatch.setattr(auth.httpx, "post", lambda url, **kw: (seen.update(kw), FakeResponse())[1])
        auth.mcp_auth_headers()
        assert seen["data"]["scope"] == "booking:read booking:write"

    def test_token_is_cached_between_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = self._configured(monkeypatch)
        count = {"n": 0}

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"access_token": "tok", "expires_in": 300}

        def fake_post(url, **kw):
            count["n"] += 1
            return FakeResponse()

        monkeypatch.setattr(auth.httpx, "post", fake_post)
        auth.mcp_auth_headers()
        auth.mcp_auth_headers()
        auth.mcp_auth_headers()
        assert count["n"] == 1

    def test_expired_token_is_refetched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = self._configured(monkeypatch)
        count = {"n": 0}

        class FakeResponse:
            def raise_for_status(self): pass
            # Shorter than the refresh margin, so the cache can never serve it.
            def json(self): return {"access_token": "tok", "expires_in": 1}

        def fake_post(url, **kw):
            count["n"] += 1
            return FakeResponse()

        monkeypatch.setattr(auth.httpx, "post", fake_post)
        auth.mcp_auth_headers()
        auth.mcp_auth_headers()
        assert count["n"] == 2

    def test_oauth2_wins_over_a_stale_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A key left behind after migrating to OAuth2 must not silently
        # downgrade the agent's identity.
        auth = self._configured(monkeypatch, HOTEL_MCP_API_KEY="stale-key")

        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"access_token": "tok", "expires_in": 300}

        monkeypatch.setattr(auth.httpx, "post", lambda url, **kw: FakeResponse())
        assert auth.mcp_auth_headers() == {"Authorization": "Bearer tok"}


class TestPartialOAuth2Config:
    """A half-filled OAuth2 config is a misconfiguration, not a fallback cue.
    It must not be mistaken for a working setup, and /health has to say so."""

    def test_falls_back_to_api_key_but_flags_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _reload(
            monkeypatch,
            HOTEL_MCP_TOKEN_URL="https://idp.example/token",
            HOTEL_MCP_CLIENT_ID="cid",  # secret missing
            HOTEL_MCP_API_KEY="k123",
        )
        assert auth.mcp_auth_headers() == {"API-Key": "k123"}
        described = auth.describe_credential()
        assert described["mode"] == "api-key"
        assert described["oauth2_partially_configured"] is True

    def test_flagged_even_with_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _reload(monkeypatch, HOTEL_MCP_CLIENT_ID="cid")
        assert auth.mcp_auth_headers() == {}
        assert auth.describe_credential()["oauth2_partially_configured"] is True

    def test_complete_config_is_not_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _reload(
            monkeypatch,
            HOTEL_MCP_TOKEN_URL="https://idp.example/token",
            HOTEL_MCP_CLIENT_ID="cid",
            HOTEL_MCP_CLIENT_SECRET="csecret",
        )
        assert auth.describe_credential()["oauth2_partially_configured"] is False
