"""A small SCIM 2.0 client for the target application (the service provider)."""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class ScimError(RuntimeError):
    """Raised when the SCIM service provider returns an error response."""


def _raise_for_status(resp: httpx.Response, action: str) -> None:
    if resp.status_code >= 400:
        raise ScimError(f"SCIM {action} failed: {resp.status_code} {resp.text}")


class ScimClient:
    """Thin wrapper over the SCIM 2.0 /Users and /Groups endpoints."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        *,
        client: httpx.Client | None = None,
    ):
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/scim+json",
                "Content-Type": "application/scim+json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ScimClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=16),
        reraise=True,
    )
    def _request(self, method: str, path: str, *, json: dict | None = None) -> httpx.Response:
        return self._client.request(method, path, json=json)

    def _list(self, resource: str) -> list[dict]:
        """Return all resources of a type, following SCIM pagination."""
        results: list[dict] = []
        start_index = 1
        count = 100
        while True:
            resp = self._client.get(
                f"/{resource}", params={"startIndex": start_index, "count": count}
            )
            _raise_for_status(resp, f"list {resource}")
            body = resp.json()
            page = body.get("Resources", [])
            results.extend(page)
            total = body.get("totalResults", len(results))
            if not page or len(results) >= total:
                break
            start_index += len(page)
        return results

    # --- Users ---
    def list_users(self) -> list[dict]:
        return self._list("Users")

    def create_user(self, payload: dict) -> dict:
        resp = self._request("POST", "/Users", json=payload)
        _raise_for_status(resp, "create user")
        return resp.json()

    def replace_user(self, user_id: str, payload: dict) -> dict:
        resp = self._request("PUT", f"/Users/{user_id}", json=payload)
        _raise_for_status(resp, "replace user")
        return resp.json()

    def deactivate_user(self, user_id: str) -> dict:
        ops = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        }
        resp = self._request("PATCH", f"/Users/{user_id}", json=ops)
        _raise_for_status(resp, "deactivate user")
        return resp.json()

    def delete_user(self, user_id: str) -> None:
        resp = self._request("DELETE", f"/Users/{user_id}")
        _raise_for_status(resp, "delete user")

    # --- Groups ---
    def list_groups(self) -> list[dict]:
        return self._list("Groups")

    def create_group(self, payload: dict) -> dict:
        resp = self._request("POST", "/Groups", json=payload)
        _raise_for_status(resp, "create group")
        return resp.json()

    def replace_group(self, group_id: str, payload: dict) -> dict:
        resp = self._request("PUT", f"/Groups/{group_id}", json=payload)
        _raise_for_status(resp, "replace group")
        return resp.json()

    def delete_group(self, group_id: str) -> None:
        resp = self._request("DELETE", f"/Groups/{group_id}")
        _raise_for_status(resp, "delete group")
