"""Internal desired-state models and SCIM schema constants."""

from __future__ import annotations

from dataclasses import dataclass, field

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


@dataclass(frozen=True)
class DesiredUser:
    """A user we want to exist in the target app, derived from a Discord member."""

    external_id: str
    user_name: str
    display_name: str
    active: bool = True
    email: str | None = None

    def to_scim(self) -> dict:
        payload: dict = {
            "schemas": [USER_SCHEMA],
            "externalId": self.external_id,
            "userName": self.user_name,
            "displayName": self.display_name,
            "name": {"formatted": self.display_name},
            "active": self.active,
        }
        if self.email:
            payload["emails"] = [{"value": self.email, "primary": True, "type": "work"}]
        return payload


@dataclass
class DesiredGroup:
    """A group we want to exist in the target app, derived from a Discord role."""

    external_id: str
    display_name: str
    member_external_ids: list[str] = field(default_factory=list)

    def to_scim(self, member_id_map: dict[str, str]) -> dict:
        """Render as a SCIM group. ``member_id_map`` maps user externalId -> SCIM user id."""
        members = [
            {"value": member_id_map[ext_id]}
            for ext_id in self.member_external_ids
            if ext_id in member_id_map
        ]
        return {
            "schemas": [GROUP_SCHEMA],
            "externalId": self.external_id,
            "displayName": self.display_name,
            "members": members,
        }
