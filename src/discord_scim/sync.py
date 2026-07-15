"""Reconciliation engine: converge the SCIM app onto Discord's current state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import Settings
from .discord_client import DiscordClient
from .mapper import build_desired_groups, build_desired_users
from .models import DesiredGroup, DesiredUser
from .scim_client import ScimClient

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """Summary of the actions a sync run took (or would take, in dry-run)."""

    dry_run: bool = False
    users_created: int = 0
    users_updated: int = 0
    users_deactivated: int = 0
    users_deleted: int = 0
    groups_created: int = 0
    groups_updated: int = 0
    groups_deleted: int = 0
    actions: list[str] = field(default_factory=list)

    def record(self, message: str) -> None:
        self.actions.append(message)
        log.info("%s%s", "[dry-run] " if self.dry_run else "", message)

    def summary(self) -> str:
        return (
            f"users: +{self.users_created} ~{self.users_updated} "
            f"deactivated {self.users_deactivated} deleted {self.users_deleted}; "
            f"groups: +{self.groups_created} ~{self.groups_updated} deleted {self.groups_deleted}"
        )


def _user_needs_update(desired: DesiredUser, current: dict) -> bool:
    if current.get("userName") != desired.user_name:
        return True
    if current.get("displayName") != desired.display_name:
        return True
    if current.get("active", True) != desired.active:
        return True
    if desired.email:
        # A provider may serialize an unset multi-valued field as null.
        emails = {e.get("value") for e in (current.get("emails") or [])}
        if desired.email not in emails:
            return True
    return False


def _group_members(current: dict) -> set[str]:
    # A SCIM provider may return `members: null` for an empty group, so coalesce
    # to an empty list rather than iterating None.
    return {m.get("value") for m in (current.get("members") or [])}


def _owns(external_id: str | None, prefix: str) -> bool:
    return bool(external_id) and external_id.startswith(f"{prefix}:")


class EmptyGuildSnapshot(RuntimeError):
    """Raised when Discord returns no members and destructive sync is not allowed."""


class SyncEngine:
    """Drives a single reconciliation pass from Discord into the SCIM app."""

    def __init__(self, discord: DiscordClient, scim: ScimClient, settings: Settings):
        self.discord = discord
        self.scim = scim
        self.settings = settings

    def run(self, *, dry_run: bool = False) -> SyncReport:
        report = SyncReport(dry_run=dry_run)

        # 1. Read desired state from Discord. Only fetch roles when we actually
        # mirror them as groups, so a user-only deployment never fails on the
        # role endpoint.
        members = self.discord.list_guild_members(self.settings.discord_guild_id)

        # Fail-safe: an empty member list would deprovision every managed user.
        # This usually means the Server Members intent is off or the API hiccuped,
        # not that the guild is truly empty. Refuse unless explicitly allowed.
        if not members and not self.settings.allow_empty_guild:
            raise EmptyGuildSnapshot(
                "Discord returned zero members; refusing to deprovision every "
                "managed user. Check the bot's Server Members intent, or set "
                "ALLOW_EMPTY_GUILD=true if the guild is genuinely empty."
            )

        roles = (
            self.discord.list_guild_roles(self.settings.discord_guild_id)
            if self.settings.manage_groups
            else []
        )
        desired_users = build_desired_users(members, self.settings)
        desired_groups = build_desired_groups(members, roles, self.settings)

        # 2. Reconcile users; keep externalId -> SCIM id map for group membership.
        user_id_map = self._reconcile_users(desired_users, report)

        # 3. Reconcile groups (membership references SCIM user ids).
        if self.settings.manage_groups:
            self._reconcile_groups(desired_groups, user_id_map, report)

        log.info("Sync complete: %s", report.summary())
        return report

    # ------------------------------------------------------------------ users
    def _reconcile_users(
        self, desired_users: dict[str, DesiredUser], report: SyncReport
    ) -> dict[str, str]:
        prefix = self.settings.ownership_prefix
        current_users = self.scim.list_users()
        current_by_ext = {
            u["externalId"]: u
            for u in current_users
            if _owns(u.get("externalId"), prefix) and ":user:" in u["externalId"]
        }
        user_id_map: dict[str, str] = {}

        # Create or update desired users.
        for ext_id, desired in desired_users.items():
            current = current_by_ext.get(ext_id)
            if current is None:
                if report.dry_run:
                    report.users_created += 1
                    report.record(f"create user {desired.user_name}")
                    # Record a placeholder id so the group diff still counts
                    # this would-be user as a new member of any existing group.
                    user_id_map[ext_id] = f"dry-run:{ext_id}"
                    continue
                created = self.scim.create_user(desired.to_scim())
                user_id_map[ext_id] = created["id"]
                report.users_created += 1
                report.record(f"created user {desired.user_name} ({created['id']})")
            else:
                user_id_map[ext_id] = current["id"]
                if _user_needs_update(desired, current):
                    if report.dry_run:
                        report.users_updated += 1
                        report.record(f"update user {desired.user_name}")
                        continue
                    self.scim.replace_user(current["id"], desired.to_scim())
                    report.users_updated += 1
                    report.record(f"updated user {desired.user_name} ({current['id']})")

        # Deprovision users we own that are no longer in the guild.
        for ext_id, current in current_by_ext.items():
            if ext_id in desired_users:
                continue
            if self.settings.deprovision_action == "delete":
                if not report.dry_run:
                    self.scim.delete_user(current["id"])
                report.users_deleted += 1
                report.record(f"deleted user {current.get('userName')} ({current['id']})")
            else:
                if current.get("active", True) is False:
                    continue  # already deactivated
                if not report.dry_run:
                    self.scim.deactivate_user(current["id"])
                report.users_deactivated += 1
                report.record(f"deactivated user {current.get('userName')} ({current['id']})")

        return user_id_map

    # ----------------------------------------------------------------- groups
    def _reconcile_groups(
        self,
        desired_groups: dict[str, DesiredGroup],
        user_id_map: dict[str, str],
        report: SyncReport,
    ) -> None:
        prefix = self.settings.ownership_prefix
        current_groups = self.scim.list_groups()
        current_by_ext = {
            g["externalId"]: g
            for g in current_groups
            if _owns(g.get("externalId"), prefix) and ":role:" in g["externalId"]
        }

        for ext_id, desired in desired_groups.items():
            payload = desired.to_scim(user_id_map)
            current = current_by_ext.get(ext_id)
            if current is None:
                if report.dry_run:
                    report.groups_created += 1
                    report.record(f"create group {desired.display_name}")
                    continue
                created = self.scim.create_group(payload)
                report.groups_created += 1
                report.record(f"created group {desired.display_name} ({created['id']})")
            else:
                desired_members = {m["value"] for m in payload["members"]}
                if (
                    current.get("displayName") != desired.display_name
                    or _group_members(current) != desired_members
                ):
                    if report.dry_run:
                        report.groups_updated += 1
                        report.record(f"update group {desired.display_name}")
                        continue
                    self.scim.replace_group(current["id"], payload)
                    report.groups_updated += 1
                    report.record(f"updated group {desired.display_name} ({current['id']})")

        # Delete groups we own for roles that no longer exist.
        for ext_id, current in current_by_ext.items():
            if ext_id in desired_groups:
                continue
            if not report.dry_run:
                self.scim.delete_group(current["id"])
            report.groups_deleted += 1
            report.record(f"deleted group {current.get('displayName')} ({current['id']})")
