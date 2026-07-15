from conftest import make_settings, member, role

from discord_scim.mapper import (
    build_desired_groups,
    build_desired_users,
    role_external_id,
    user_external_id,
)


def test_build_desired_users_skips_bots_by_default():
    members = [
        member("1", "alice"),
        member("2", "botty", bot=True),
    ]
    users = build_desired_users(members, make_settings())
    assert set(users) == {user_external_id("discord", "1")}


def test_build_desired_users_includes_bots_when_configured():
    members = [member("2", "botty", bot=True)]
    users = build_desired_users(members, make_settings(include_bots=True))
    assert user_external_id("discord", "2") in users


def test_display_name_prefers_nick_then_global_name():
    members = [
        member("1", "alice", nick="Ally"),
        member("2", "bob", global_name="Bobby"),
        member("3", "carol"),
    ]
    users = build_desired_users(members, make_settings())
    names = {u.user_name: u.display_name for u in users.values()}
    assert names == {"alice": "Ally", "bob": "Bobby", "carol": "carol"}


def test_email_synthesis_and_username():
    members = [member("1", "Alice Cooper!")]
    users = build_desired_users(members, make_settings(email_domain="example.com"))
    u = next(iter(users.values()))
    assert u.email == "alice.cooper@example.com"
    # userName becomes the email when a domain is configured.
    assert u.user_name == "alice.cooper@example.com"


def test_build_desired_groups_excludes_everyone_and_managed():
    settings = make_settings()  # guild id 100
    roles = [
        role("100", "@everyone"),  # implicit everyone role == guild id
        role("200", "Staff"),
        role("300", "IntegrationBot", managed=True),
    ]
    members = [member("1", "alice", roles=["200"])]
    groups = build_desired_groups(members, roles, settings)
    assert set(groups) == {role_external_id("discord", "200")}
    staff = groups[role_external_id("discord", "200")]
    assert staff.member_external_ids == [user_external_id("discord", "1")]


def test_groups_disabled_returns_empty():
    settings = make_settings(manage_groups=False)
    groups = build_desired_groups([member("1", "a", roles=["200"])], [role("200", "S")], settings)
    assert groups == {}
