from conftest import make_settings, member, role

from discord_scim.mapper import (
    build_desired_groups,
    build_desired_users,
    role_external_id,
    user_external_id,
)

# The default ownership prefix is guild-scoped: "<prefix>:<guild_id>".
PREFIX = make_settings().ownership_prefix  # "discord:100"


def test_build_desired_users_skips_bots_by_default():
    members = [
        member("1", "alice"),
        member("2", "botty", bot=True),
    ]
    users = build_desired_users(members, make_settings())
    assert set(users) == {user_external_id(PREFIX, "1")}


def test_build_desired_users_includes_bots_when_configured():
    members = [member("2", "botty", bot=True)]
    users = build_desired_users(members, make_settings(include_bots=True))
    assert user_external_id(PREFIX, "2") in users


def test_display_name_prefers_nick_then_global_name():
    members = [
        member("1", "alice", nick="Ally"),
        member("2", "bob", global_name="Bobby"),
        member("3", "carol"),
    ]
    users = build_desired_users(members, make_settings())
    names = {u.display_name for u in users.values()}
    assert names == {"Ally", "Bobby", "carol"}


def test_email_synthesis_and_username():
    members = [member("42", "Alice Cooper!")]
    users = build_desired_users(members, make_settings(email_domain="example.com"))
    u = next(iter(users.values()))
    # The snowflake is appended so the address is unique and stable.
    assert u.email == "alice.cooper.42@example.com"
    # userName becomes the email when a domain is configured.
    assert u.user_name == "alice.cooper.42@example.com"


def test_username_includes_snowflake_for_uniqueness():
    users = build_desired_users([member("77", "alice")], make_settings())
    u = next(iter(users.values()))
    assert u.user_name == "alice.77"


def test_colliding_usernames_stay_unique():
    # Two members whose sanitized emails would otherwise collapse to "a.b"
    # ("a b" has its space replaced with a dot).
    members = [member("1", "a b"), member("2", "a.b")]
    settings = make_settings(email_domain="example.com")
    users = build_desired_users(members, settings)
    emails = {u.email for u in users.values()}
    user_names = {u.user_name for u in users.values()}
    assert emails == {"a.b.1@example.com", "a.b.2@example.com"}
    assert len(user_names) == 2


def test_build_desired_groups_excludes_everyone_and_managed():
    settings = make_settings()  # guild id 100
    roles = [
        role("100", "@everyone"),  # implicit everyone role == guild id
        role("200", "Staff"),
        role("300", "IntegrationBot", managed=True),
    ]
    members = [member("1", "alice", roles=["200"])]
    groups = build_desired_groups(members, roles, settings)
    assert set(groups) == {role_external_id(PREFIX, "200")}
    staff = groups[role_external_id(PREFIX, "200")]
    assert staff.member_external_ids == [user_external_id(PREFIX, "1")]


def test_ownership_prefix_is_guild_scoped():
    # The same Discord user in two different guilds yields distinct externalIds,
    # so two guilds sharing one SCIM app never own each other's resources.
    a = build_desired_users([member("1", "alice")], make_settings(discord_guild_id="100"))
    b = build_desired_users([member("1", "alice")], make_settings(discord_guild_id="200"))
    assert set(a).isdisjoint(set(b))
    assert user_external_id("discord:100", "1") in a
    assert user_external_id("discord:200", "1") in b


def test_groups_disabled_returns_empty():
    settings = make_settings(manage_groups=False)
    groups = build_desired_groups([member("1", "a", roles=["200"])], [role("200", "S")], settings)
    assert groups == {}
