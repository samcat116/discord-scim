import httpx
import respx

from discord_scim.scim_client import ScimClient


def _client() -> ScimClient:
    return ScimClient("https://app.example/scim/v2", "token")


@respx.mock
def test_deactivate_user_accepts_204_no_content():
    respx.patch("https://app.example/scim/v2/Users/u1").mock(
        return_value=httpx.Response(204)
    )
    # A 204 with no body must not raise a JSON decode error.
    assert _client().deactivate_user("u1") == {}


@respx.mock
def test_replace_group_accepts_empty_body():
    respx.put("https://app.example/scim/v2/Groups/g1").mock(
        return_value=httpx.Response(200, content=b"")
    )
    assert _client().replace_group("g1", {"displayName": "Staff"}) == {}


@respx.mock
def test_list_users_follows_pagination():
    route = respx.get("https://app.example/scim/v2/Users")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "Resources": [{"id": "1"}, {"id": "2"}],
                "totalResults": 3,
                "startIndex": 1,
            },
        ),
        httpx.Response(
            200,
            json={"Resources": [{"id": "3"}], "totalResults": 3, "startIndex": 3},
        ),
    ]
    users = _client().list_users()
    assert [u["id"] for u in users] == ["1", "2", "3"]
