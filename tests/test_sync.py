import pytest
from conftest import FakeDiscordClient, FakeScimClient, make_settings, member, role

from discord_scim.sync import EmptyGuildSnapshot, SyncEngine


def run_sync(members, roles, settings, *, scim=None, dry_run=False):
    scim = scim or FakeScimClient()
    discord = FakeDiscordClient(members, roles)
    engine = SyncEngine(discord, scim, settings)
    report = engine.run(dry_run=dry_run)
    return scim, report


def test_creates_users_and_groups():
    members = [
        member("1", "alice", roles=["200"]),
        member("2", "bob", roles=["200"]),
    ]
    roles = [role("100", "@everyone"), role("200", "Staff")]
    scim, report = run_sync(members, roles, make_settings())

    assert report.users_created == 2
    assert report.groups_created == 1
    # The group references both created users.
    (group,) = scim.list_groups()
    assert group["displayName"] == "Staff"
    member_ids = {m["value"] for m in group["members"]}
    assert member_ids == set(scim.users)


def test_second_run_is_idempotent():
    members = [member("1", "alice", roles=["200"])]
    roles = [role("200", "Staff")]
    settings = make_settings()
    scim, first = run_sync(members, roles, settings)
    _, second = run_sync(members, roles, settings, scim=scim)

    assert first.users_created == 1
    assert second.users_created == 0
    assert second.users_updated == 0
    assert second.groups_updated == 0


def test_leaving_member_is_deactivated():
    roles = [role("200", "Staff")]
    settings = make_settings()
    scim, _ = run_sync(
        [member("1", "alice", roles=["200"]), member("2", "bob", roles=["200"])],
        roles,
        settings,
    )

    # Alice leaves the guild; bob remains.
    _, report = run_sync([member("2", "bob", roles=["200"])], roles, settings, scim=scim)
    assert report.users_deactivated == 1
    alice = next(u for u in scim.list_users() if u["externalId"] == "discord:100:user:1")
    assert alice["active"] is False


def test_leaving_member_is_deleted_when_configured():
    settings = make_settings(deprovision_action="delete")
    scim, _ = run_sync([member("1", "alice"), member("2", "bob")], [], settings)
    _, report = run_sync([member("2", "bob")], [], settings, scim=scim)
    assert report.users_deleted == 1
    assert {u["externalId"] for u in scim.list_users()} == {"discord:100:user:2"}


def test_role_change_updates_group_membership():
    roles = [role("200", "Staff")]
    settings = make_settings()
    scim, _ = run_sync([member("1", "alice", roles=["200"])], roles, settings)

    # Alice loses the Staff role.
    _, report = run_sync([member("1", "alice", roles=[])], roles, settings, scim=scim)
    assert report.groups_updated == 1
    (group,) = scim.list_groups()
    assert group["members"] == []


def test_display_name_change_updates_user():
    settings = make_settings()
    scim, _ = run_sync([member("1", "alice")], [], settings)
    _, report = run_sync([member("1", "alice", nick="Ally")], [], settings, scim=scim)
    assert report.users_updated == 1
    (user,) = scim.list_users()
    assert user["displayName"] == "Ally"


def test_deleted_role_removes_group():
    settings = make_settings()
    scim, _ = run_sync([member("1", "a", roles=["200"])], [role("200", "Staff")], settings)
    _, report = run_sync([member("1", "a", roles=[])], [], settings, scim=scim)
    assert report.groups_deleted == 1
    assert scim.list_groups() == []


def test_group_with_null_members_is_in_sync():
    # A provider that stored an empty group as members: null must not crash the
    # next reconciliation of a role that has no members.
    settings = make_settings()
    scim = FakeScimClient()
    scim.create_group(
        {"externalId": "discord:100:role:200", "displayName": "Staff", "members": None}
    )
    _, report = run_sync([member("1", "a", roles=[])], [role("200", "Staff")], settings, scim=scim)
    assert report.groups_updated == 0
    assert report.groups_created == 0


def test_user_with_null_emails_updates_without_crashing():
    # A provider that stored the user with emails: null must not crash the
    # email comparison when EMAIL_DOMAIN is configured.
    settings = make_settings(email_domain="example.com")
    scim = FakeScimClient()
    scim.create_user(
        {
            "externalId": "discord:100:user:1",
            "userName": "alice.1@example.com",
            "displayName": "alice",
            "active": True,
            "emails": None,
        }
    )
    _, report = run_sync([member("1", "alice")], [], settings, scim=scim)
    assert report.users_updated == 1
    (user,) = scim.list_users()
    assert user["emails"] == [{"value": "alice.1@example.com", "primary": True, "type": "work"}]


def test_dry_run_makes_no_changes():
    members = [member("1", "alice", roles=["200"])]
    roles = [role("200", "Staff")]
    scim, report = run_sync(members, roles, make_settings(), dry_run=True)
    assert report.users_created == 1
    assert report.groups_created == 1
    assert scim.list_users() == []
    assert scim.list_groups() == []


def test_dry_run_counts_group_update_for_new_member():
    # A new member joining an existing role must show up as a would-be group
    # update in the dry-run report, even though the user isn't created yet.
    roles = [role("200", "Staff")]
    settings = make_settings()
    scim, _ = run_sync([member("1", "alice", roles=["200"])], roles, settings)

    _, report = run_sync(
        [member("1", "alice", roles=["200"]), member("2", "bob", roles=["200"])],
        roles,
        settings,
        scim=scim,
        dry_run=True,
    )
    assert report.users_created == 1  # bob
    assert report.groups_updated == 1  # Staff gains bob
    # Nothing actually changed on the SCIM side.
    assert len(scim.list_users()) == 1
    (group,) = scim.list_groups()
    assert len(group["members"]) == 1


def test_roles_not_fetched_when_groups_disabled():
    class NoRolesDiscord(FakeDiscordClient):
        def list_guild_roles(self, guild_id):
            raise AssertionError("roles must not be fetched when groups are disabled")

    discord = NoRolesDiscord([member("1", "alice", roles=["200"])], [])
    scim = FakeScimClient()
    report = SyncEngine(discord, scim, make_settings(manage_groups=False)).run()
    assert report.users_created == 1
    assert report.groups_created == 0
    assert scim.list_groups() == []


def test_foreign_scim_resources_are_untouched():
    scim = FakeScimClient()
    # A user owned by some other provisioning source.
    scim.create_user({"externalId": "okta:99", "userName": "external", "active": True})
    run_sync([member("1", "alice")], [], make_settings(), scim=scim)
    # The foreign user still exists and was not deactivated.
    foreign = [u for u in scim.list_users() if u["externalId"] == "okta:99"]
    assert foreign and foreign[0]["active"] is True


def test_empty_guild_refuses_to_deprovision():
    settings = make_settings()
    scim, _ = run_sync([member("1", "alice")], [], settings)
    # Discord now returns zero members (e.g. Server Members intent got disabled).
    with pytest.raises(EmptyGuildSnapshot):
        run_sync([], [], settings, scim=scim)
    # The existing user must be left fully intact — no deactivation.
    (user,) = scim.list_users()
    assert user["active"] is True


def test_empty_guild_allowed_when_configured():
    settings = make_settings(allow_empty_guild=True)
    scim, _ = run_sync([member("1", "alice")], [], settings)
    _, report = run_sync([], [], settings, scim=scim)
    assert report.users_deactivated == 1


def test_other_guilds_resources_are_not_deprovisioned():
    # A user provisioned by a *different* guild sharing the same SCIM app.
    scim = FakeScimClient()
    scim.create_user(
        {"externalId": "discord:200:user:9", "userName": "other", "active": True}
    )
    # Syncing guild 100 must not see guild 200's user as owned.
    run_sync([member("1", "alice")], [], make_settings(discord_guild_id="100"), scim=scim)
    other = [u for u in scim.list_users() if u["externalId"] == "discord:200:user:9"]
    assert other and other[0]["active"] is True
