"""Map Discord members and roles onto SCIM desired-state objects."""

from __future__ import annotations

import re

from .config import Settings
from .models import DesiredGroup, DesiredUser

_EMAIL_LOCALPART = re.compile(r"[^a-zA-Z0-9._-]+")


def user_external_id(prefix: str, discord_user_id: str) -> str:
    return f"{prefix}:user:{discord_user_id}"


def role_external_id(prefix: str, role_id: str) -> str:
    return f"{prefix}:role:{role_id}"


def _display_name(member: dict) -> str:
    user = member["user"]
    return (
        member.get("nick")
        or user.get("global_name")
        or user.get("username")
        or user["id"]
    )


def _synthesize_email(username: str, discord_id: str, domain: str) -> str:
    local = _EMAIL_LOCALPART.sub(".", username).strip(".").lower() or "user"
    # Append the Discord snowflake so two members never collide, even when
    # sanitization collapses distinct usernames to the same local part.
    return f"{local}.{discord_id}@{domain}"


def build_desired_users(members: list[dict], settings: Settings) -> dict[str, DesiredUser]:
    """Return desired users keyed by SCIM externalId."""
    desired: dict[str, DesiredUser] = {}
    for member in members:
        user = member["user"]
        if user.get("bot") and not settings.include_bots:
            continue
        discord_id = user["id"]
        username = user.get("username") or discord_id
        ext_id = user_external_id(settings.ownership_prefix, discord_id)
        email = (
            _synthesize_email(username, discord_id, settings.email_domain)
            if settings.email_domain
            else None
        )
        # SCIM requires a unique userName, but Discord usernames are not
        # guaranteed unique. The snowflake makes it stable and collision-free.
        desired[ext_id] = DesiredUser(
            external_id=ext_id,
            user_name=email or f"{username}.{discord_id}",
            display_name=_display_name(member),
            active=True,
            email=email,
        )
    return desired


def build_desired_groups(
    members: list[dict],
    roles: list[dict],
    settings: Settings,
) -> dict[str, DesiredGroup]:
    """Return desired groups keyed by SCIM externalId, one per Discord role."""
    if not settings.manage_groups:
        return {}

    guild_id = settings.discord_guild_id
    groups: dict[str, DesiredGroup] = {}
    for role in roles:
        if settings.exclude_everyone_role and role["id"] == guild_id:
            continue
        if settings.exclude_managed_roles and role.get("managed"):
            continue
        ext_id = role_external_id(settings.ownership_prefix, role["id"])
        groups[ext_id] = DesiredGroup(
            external_id=ext_id,
            display_name=role["name"],
            member_external_ids=[],
        )

    for member in members:
        user = member["user"]
        if user.get("bot") and not settings.include_bots:
            continue
        member_ext_id = user_external_id(settings.ownership_prefix, user["id"])
        for role_id in member.get("roles", []):
            group_ext_id = role_external_id(settings.ownership_prefix, role_id)
            group = groups.get(group_ext_id)
            if group is not None:
                group.member_external_ids.append(member_ext_id)

    return groups
