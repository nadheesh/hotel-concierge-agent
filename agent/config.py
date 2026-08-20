"""Configuration for the hotel booking agent.

Every value below arrives as an environment variable. Nothing is read from a
committed file and nothing is hardcoded, so the same image runs in development
and production and as the customer-facing or the operations deployment.

The MCP variable names match what Agent Manager injects when the corresponding
Tool Configuration is attached. If you name things differently in the console,
change the aliases here rather than renaming anything in the console.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Model -----------------------------------------------------------
    openai_model: str = Field(default="gpt-4o", validation_alias="OPENAI_MODEL")
    # One key slot for both modes. OPENAI_URL presence is the only mode gate:
    # set it and the key goes to the AM gateway on an API-Key header, leave it
    # empty and the same key goes straight to OpenAI.
    openai_url: str = Field(default="", validation_alias="OPENAI_URL")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")

    # --- hotel-mcp endpoint -----------------------------------------------
    hotel_mcp_url: str = Field(default="", validation_alias="HOTEL_MCP_URL")

    # --- hotel-mcp credential (egress) ------------------------------------
    # Whatever the gateway in front of hotel-mcp expects. Three shapes are
    # supported and auth.py picks between them; supply one, or none if the
    # endpoint is unsecured. See auth.py for the precedence rule.
    #
    # Shape 1: API key.
    hotel_mcp_api_key: str = Field(default="", validation_alias="HOTEL_MCP_API_KEY")
    # Header the gateway reads the key from. Agent Manager's own docs are
    # inconsistent between API-Key and X-API-Key, so it is configurable.
    hotel_mcp_api_key_header: str = Field(
        default="API-Key", validation_alias="HOTEL_MCP_API_KEY_HEADER"
    )
    # Shape 2: OAuth2 client credentials. Any client the gateway trusts; this
    # does not assume an Agent Manager Agent Identity, which may not exist yet.
    hotel_mcp_token_url: str = Field(default="", validation_alias="HOTEL_MCP_TOKEN_URL")
    hotel_mcp_client_id: str = Field(default="", validation_alias="HOTEL_MCP_CLIENT_ID")
    hotel_mcp_client_secret: str = Field(default="", validation_alias="HOTEL_MCP_CLIENT_SECRET")
    hotel_mcp_scopes: str = Field(default="", validation_alias="HOTEL_MCP_SCOPES")

    # --- Behaviour flags --------------------------------------------------
    system_prompt_variant: str = Field(default="baseline", validation_alias="SYSTEM_PROMPT_VARIANT")
    # See mcp_client.py. Ships enabled. Read that module before changing it.
    legacy_date_compat: bool = Field(default=True, validation_alias="HOTEL_MCP_LEGACY_DATE_COMPAT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def governed(self) -> bool:
        return bool(self.openai_url)

    @property
    def mcp_configured(self) -> bool:
        return bool(self.hotel_mcp_url)

    @property
    def mcp_oauth_configured(self) -> bool:
        """All three parts must be present. A half-filled OAuth2 config is a
        misconfiguration, not a reason to quietly fall back to an API key."""
        return bool(self.hotel_mcp_token_url and self.hotel_mcp_client_id
                    and self.hotel_mcp_client_secret)


settings = Settings()
