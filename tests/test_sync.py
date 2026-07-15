from conftest import FakeDiscordClient, FakeScimClient, make_settings, member, role

from discord_scim.sync import SyncEngine


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
    scim, _ = run_sync([member("1", "alice", roles=["200"])], roles, settings)

    # Alice leaves the guild.
    _, report = run_sync([], roles, settings, scim=scim)
    assert report.users_deactivated == 1
    (user,) = scim.list_users()
    assert user["active"] is False


def test_leaving_member_is_deleted_when_configured():
    settings = make_settings(deprovision_action="delete")
    scim, _ = run_sync([member("1", "alice")], [], settings)
    _, report = run_sync([], [], settings, scim=scim)
    assert report.users_deleted == 1
    assert scim.list_users() == []


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


def test_dry_run_makes_no_changes():
    members = [member("1", "alice", roles=["200"])]
    roles = [role("200", "Staff")]
    scim, report = run_sync(members, roles, make_settings(), dry_run=True)
    assert report.users_created == 1
    assert report.groups_created == 1
    assert scim.list_users() == []
    assert scim.list_groups() == []


def test_foreign_scim_resources_are_untouched():
    scim = FakeScimClient()
    # A user owned by some other provisioning source.
    scim.create_user({"externalId": "okta:99", "userName": "external", "active": True})
    run_sync([member("1", "alice")], [], make_settings(), scim=scim)
    # The foreign user still exists and was not deactivated.
    foreign = [u for u in scim.list_users() if u["externalId"] == "okta:99"]
    assert foreign and foreign[0]["active"] is True
