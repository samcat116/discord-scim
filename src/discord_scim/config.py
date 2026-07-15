"""Runtime configuration, loaded from environment variables or a .env file."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Discord -> SCIM provisioning adapter.

    Values are read from environment variables (case-insensitive) or a local
    ``.env`` file. See ``.env.example`` for the full list.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Discord source ---
    discord_bot_token: str = Field(..., description="Bot token with the Server Members intent.")
    discord_guild_id: str = Field(..., description="ID of the guild to read members/roles from.")
    include_bots: bool = Field(False, description="Provision bot accounts as users too.")

    # --- SCIM target app ---
    scim_base_url: str = Field(..., description="Base URL of the app's SCIM 2.0 API, e.g. https://app/scim/v2")
    scim_token: str = Field(..., description="Bearer token for the SCIM API.")

    # --- Mapping / behaviour ---
    external_id_prefix: str = Field(
        "discord",
        description="Prefix for SCIM externalId so we only ever touch resources we own.",
    )
    email_domain: str | None = Field(
        None,
        description=(
            "If set, synthesize emails as <username>@<domain> "
            "(Discord bots cannot read real emails)."
        ),
    )
    manage_groups: bool = Field(True, description="Mirror Discord roles as SCIM groups.")
    exclude_everyone_role: bool = Field(
        True, description="Skip the implicit @everyone role (its id equals the guild id)."
    )
    exclude_managed_roles: bool = Field(
        True, description="Skip integration/bot-managed roles (e.g. per-bot roles)."
    )
    deprovision_action: Literal["deactivate", "delete"] = Field(
        "deactivate",
        description="What to do with users who leave the guild.",
    )
    allow_empty_guild: bool = Field(
        False,
        description=(
            "Allow a sync when Discord returns zero members, which would "
            "deprovision every managed user. Off by default as a safety guard "
            "against a missing Server Members intent or a transient API error."
        ),
    )

    # --- HTTP ---
    request_timeout: float = Field(30.0, description="Per-request timeout in seconds.")

    @property
    def scim_base_url_normalized(self) -> str:
        return self.scim_base_url.rstrip("/")

    @property
    def ownership_prefix(self) -> str:
        """externalId namespace, scoped per guild.

        Including the guild id means two guilds syncing into the same SCIM app
        never see each other's resources as "owned", so a run for one guild can
        never deprovision another guild's users or groups.
        """
        return f"{self.external_id_prefix}:{self.discord_guild_id}"
