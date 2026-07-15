"""Minimal Discord REST client for reading guild members and roles."""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"
MEMBER_PAGE_SIZE = 1000


class DiscordError(RuntimeError):
    """Raised when the Discord API returns an unrecoverable error."""


class DiscordClient:
    """Reads members and roles from a single guild using a bot token.

    Requires the *Server Members Intent* to be enabled for the bot in the
    Discord developer portal, otherwise member listing returns an empty set.
    """

    def __init__(self, token: str, timeout: float = 30.0, *, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            base_url=DISCORD_API_BASE,
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "discord-scim (https://github.com/samcat116/discord-scim, 0.1.0)",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DiscordClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        # Respect Discord rate limits with a bounded retry on 429.
        for _attempt in range(5):
            resp = self._client.get(path, params=params)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                log.warning("Rate limited by Discord, sleeping %.2fs", retry_after)
                time.sleep(retry_after)
                continue
            if resp.status_code >= 400:
                raise DiscordError(
                    f"Discord GET {path} failed: {resp.status_code} {resp.text}"
                )
            return resp
        raise DiscordError(f"Discord GET {path} still rate limited after retries")

    def list_guild_roles(self, guild_id: str) -> list[dict]:
        return self._get(f"/guilds/{guild_id}/roles").json()

    def list_guild_members(self, guild_id: str) -> list[dict]:
        """Return every member of the guild, paginating on the snowflake cursor."""
        members: list[dict] = []
        after = "0"
        while True:
            page = self._get(
                f"/guilds/{guild_id}/members",
                params={"limit": MEMBER_PAGE_SIZE, "after": after},
            ).json()
            if not page:
                break
            members.extend(page)
            after = page[-1]["user"]["id"]
            if len(page) < MEMBER_PAGE_SIZE:
                break
        log.info("Fetched %d guild members", len(members))
        return members
