"""Shared test fixtures and in-memory fakes."""

from __future__ import annotations

import itertools

from discord_scim.config import Settings


def make_settings(**overrides) -> Settings:
    base = dict(
        discord_bot_token="test-token",
        discord_guild_id="100",
        scim_base_url="https://app.example/scim/v2",
        scim_token="scim-token",
    )
    base.update(overrides)
    return Settings(**base)


class FakeScimClient:
    """In-memory stand-in for ScimClient that records SCIM resource state."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self._ids = itertools.count(1)

    def _new_id(self, kind: str) -> str:
        return f"{kind}-{next(self._ids)}"

    # users
    def list_users(self) -> list[dict]:
        return list(self.users.values())

    def create_user(self, payload: dict) -> dict:
        rec = dict(payload)
        rec["id"] = self._new_id("user")
        self.users[rec["id"]] = rec
        return rec

    def replace_user(self, user_id: str, payload: dict) -> dict:
        rec = dict(payload)
        rec["id"] = user_id
        self.users[user_id] = rec
        return rec

    def deactivate_user(self, user_id: str) -> dict:
        self.users[user_id]["active"] = False
        return self.users[user_id]

    def delete_user(self, user_id: str) -> None:
        self.users.pop(user_id, None)

    # groups
    def list_groups(self) -> list[dict]:
        return list(self.groups.values())

    def create_group(self, payload: dict) -> dict:
        rec = dict(payload)
        rec["id"] = self._new_id("group")
        self.groups[rec["id"]] = rec
        return rec

    def replace_group(self, group_id: str, payload: dict) -> dict:
        rec = dict(payload)
        rec["id"] = group_id
        self.groups[group_id] = rec
        return rec

    def delete_group(self, group_id: str) -> None:
        self.groups.pop(group_id, None)


class FakeDiscordClient:
    def __init__(self, members: list[dict], roles: list[dict]) -> None:
        self._members = members
        self._roles = roles

    def list_guild_members(self, guild_id: str) -> list[dict]:
        return self._members

    def list_guild_roles(self, guild_id: str) -> list[dict]:
        return self._roles


def member(user_id: str, username: str, roles=None, *, bot=False, nick=None, global_name=None):
    return {
        "user": {"id": user_id, "username": username, "bot": bot, "global_name": global_name},
        "nick": nick,
        "roles": roles or [],
    }


def role(role_id: str, name: str, *, managed=False):
    return {"id": role_id, "name": name, "managed": managed}
