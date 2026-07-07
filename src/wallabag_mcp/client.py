"""wallabag REST API client."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

# Refresh tokens this many seconds before the server-reported expiry.
_TOKEN_EXPIRY_SKEW = 30.0


class WallabagError(RuntimeError):
    """Raised when the wallabag API returns an error."""


def _api_path(path: str) -> str:
    return f"/api{path}.json"


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        embedded = data.get("_embedded")
        if isinstance(embedded, dict) and isinstance(embedded.get("items"), list):
            return embedded["items"]
        if isinstance(data.get("items"), list):
            return data["items"]
    if isinstance(data, list):
        return data
    return []


def pagination(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return {k: data.get(k) for k in ("page", "pages", "limit", "total") if k in data}


class WallabagClient:
    """Async wallabag API client with token caching, refresh grant, and connection reuse."""

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self.reset()

    def reset(self) -> None:
        """Clear configuration and all cached state."""
        self._base_url: str | None = None
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at = 0.0
        self._timeout = 20.0
        self._http = None

    def configure(
        self,
        *,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """Set configuration. Providing any credential drops the cached token."""
        auth_fields = (client_id, client_secret, username, password, access_token, refresh_token)
        if any(value is not None for value in auth_fields):
            self._access_token = None
            self._refresh_token = None
            self._token_expires_at = 0.0
        if base_url is not None:
            self._base_url = base_url.rstrip("/")
        if client_id is not None:
            self._client_id = client_id
        if client_secret is not None:
            self._client_secret = client_secret
        if username is not None:
            self._username = username
        if password is not None:
            self._password = password
        if access_token is not None:
            self._access_token = access_token
        if refresh_token is not None:
            self._refresh_token = refresh_token
        if timeout is not None:
            self._timeout = float(timeout)
        self._http = None

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self._timeout, headers={"Accept": "application/json"})
        return self._http

    def _resolve_base_url(self) -> str:
        base = (self._base_url or os.environ.get("WALLABAG_BASE_URL") or "").rstrip("/")
        if not base:
            raise WallabagError("WALLABAG_BASE_URL is required")
        return base

    def _credentials(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (
            self._client_id or os.environ.get("WALLABAG_CLIENT_ID"),
            self._client_secret or os.environ.get("WALLABAG_CLIENT_SECRET"),
            self._username or os.environ.get("WALLABAG_USERNAME"),
            self._password or os.environ.get("WALLABAG_PASSWORD"),
        )

    def _current_refresh_token(self) -> str | None:
        return self._refresh_token or os.environ.get("WALLABAG_REFRESH_TOKEN")

    def _can_acquire_token(self) -> bool:
        client_id, client_secret, username, password = self._credentials()
        if not (client_id and client_secret):
            return False
        return bool(self._current_refresh_token() or (username and password))

    async def _token(self, *, force_new: bool = False) -> str:
        if not force_new:
            token = self._access_token or os.environ.get("WALLABAG_ACCESS_TOKEN")
            if token and (not self._token_expires_at or time.time() < self._token_expires_at - _TOKEN_EXPIRY_SKEW):
                return token
        return await self._acquire_token()

    async def _acquire_token(self) -> str:
        client_id, client_secret, username, password = self._credentials()
        refresh_token = self._current_refresh_token()
        refresh_error: WallabagError | None = None
        if refresh_token and client_id and client_secret:
            try:
                return await self._grant(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                )
            except WallabagError as exc:
                refresh_error = exc
        if client_id and client_secret and username and password:
            return await self._grant(
                {
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                }
            )
        if refresh_error is not None:
            raise refresh_error
        raise WallabagError(
            "Authentication requires WALLABAG_ACCESS_TOKEN or WALLABAG_CLIENT_ID, WALLABAG_CLIENT_SECRET, WALLABAG_USERNAME, and WALLABAG_PASSWORD"
        )

    async def _grant(self, data: dict[str, str]) -> str:
        grant_type = data.get("grant_type", "unknown")
        try:
            response = await self._client().post(f"{self._resolve_base_url()}/oauth/v2/token", data=data)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WallabagError(
                f"OAuth {grant_type} grant failed: HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WallabagError(f"OAuth {grant_type} grant failed: {exc}") from exc
        payload = response.json()
        self._access_token = str(payload["access_token"])
        self._refresh_token = payload.get("refresh_token") or self._refresh_token
        self._token_expires_at = time.time() + int(payload.get("expires_in") or 3600)
        return self._access_token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._authorized(method, path, params, json_body)
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        text = response.text.strip()
        return {"ok": True, "text": text} if text else {"ok": True}

    async def _authorized(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._send(method, path, params, json_body, token=await self._token())
            if response.status_code == 401 and self._can_acquire_token():
                response = await self._send(method, path, params, json_body, token=await self._token(force_new=True))
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WallabagError(
                f"{method} {path} failed: HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WallabagError(f"{method} {path} failed: {exc}") from exc
        return response

    async def _send(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        *,
        token: str,
    ) -> httpx.Response:
        return await self._client().request(
            method,
            f"{self._resolve_base_url()}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=_drop_none(params or {}),
            json=json_body,
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify authentication and basic API connectivity with a tiny read-only request."""
        data = await self.list_entries(page=1, per_page=1)
        return {"ok": True, "entries_seen": len(data.get("items", [])), "pagination": data.get("pagination", {})}

    async def list_entries(
        self,
        *,
        page: int = 1,
        per_page: int = 30,
        sort: str = "created",
        order: str = "desc",
        archive: int | None = None,
        starred: int | None = None,
        domain_name: str | None = None,
        since: int | None = None,
        tags: str | None = None,
        detail: str = "metadata",
    ) -> dict[str, Any]:
        params = {
            "page": page,
            "perPage": per_page,
            "sort": sort,
            "order": order,
            "archive": archive,
            "starred": starred,
            "domain_name": domain_name,
            "since": since,
            "tags": tags,
            "detail": detail,
        }
        data = await self.request("GET", _api_path("/entries"), params=params)
        return {"items": _items(data), "pagination": pagination(data)}

    async def search_entries(self, term: str, *, page: int = 1, per_page: int = 30) -> dict[str, Any]:
        params = {"term": term, "page": page, "perPage": per_page}
        data = await self.request("GET", _api_path("/search"), params=params)
        return {"items": _items(data), "pagination": pagination(data)}

    async def entry_exists(self, url: str) -> dict[str, Any]:
        data = await self.request("GET", _api_path("/entries/exists"), params={"url": url, "return_id": 1})
        return data if isinstance(data, dict) else {"exists": data}

    async def export_entry(self, entry_id: int, fmt: str = "txt") -> str:
        """Return an entry rendered in a text-based export format (txt, json, xml, csv)."""
        response = await self._authorized("GET", f"/api/entries/{entry_id}/export.{fmt}")
        return response.text

    async def get_entry(self, entry_id: int) -> dict[str, Any]:
        data = await self.request("GET", _api_path(f"/entries/{entry_id}"))
        if not isinstance(data, dict):
            raise WallabagError(f"Expected entry object for {entry_id}, got {type(data).__name__}")
        return data

    async def create_entry(self, url: str, **kwargs: Any) -> dict[str, Any]:
        data = await self.request("POST", _api_path("/entries"), json_body=_drop_none({"url": url, **kwargs}))
        if not isinstance(data, dict):
            raise WallabagError(f"Expected entry object after create, got {type(data).__name__}")
        return data

    async def update_entry(self, entry_id: int, **kwargs: Any) -> dict[str, Any]:
        data = await self.request("PATCH", _api_path(f"/entries/{entry_id}"), json_body=_drop_none(kwargs))
        if isinstance(data, dict) and data.get("ok") and len(data) <= 2:
            return await self.get_entry(entry_id)
        if not isinstance(data, dict):
            return await self.get_entry(entry_id)
        return data

    async def delete_entry(self, entry_id: int) -> dict[str, Any]:
        data = await self.request("DELETE", _api_path(f"/entries/{entry_id}"))
        return data if isinstance(data, dict) else {"deleted": True, "id": entry_id}

    async def reload_entry(self, entry_id: int) -> dict[str, Any]:
        data = await self.request("PATCH", _api_path(f"/entries/{entry_id}/reload"))
        return data if isinstance(data, dict) else await self.get_entry(entry_id)

    async def list_tags(self) -> list[dict[str, Any]]:
        data = await self.request("GET", _api_path("/tags"))
        return _items(data) or (data if isinstance(data, list) else [])

    async def add_tags(self, entry_id: int, tags: str) -> dict[str, Any]:
        data = await self.request("POST", _api_path(f"/entries/{entry_id}/tags"), json_body={"tags": tags})
        return data if isinstance(data, dict) else await self.get_entry(entry_id)

    async def remove_tag_from_entry(self, entry_id: int, tag_id: int) -> dict[str, Any]:
        data = await self.request("DELETE", _api_path(f"/entries/{entry_id}/tags/{tag_id}"))
        return data if isinstance(data, dict) else await self.get_entry(entry_id)

    async def delete_tag(self, tag_id: int) -> dict[str, Any]:
        data = await self.request("DELETE", _api_path(f"/tags/{tag_id}"))
        return data if isinstance(data, dict) else {"deleted": True, "id": tag_id}

    async def list_annotations(self, entry_id: int) -> list[dict[str, Any]]:
        data = await self.request("GET", _api_path(f"/entries/{entry_id}/annotations"))
        return _items(data) or (data if isinstance(data, list) else [])

    async def create_annotation(
        self,
        entry_id: int,
        text: str,
        quote: str,
        ranges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        data = await self.request(
            "POST",
            _api_path(f"/entries/{entry_id}/annotations"),
            json_body=_drop_none({"text": text, "quote": quote, "ranges": ranges}),
        )
        if not isinstance(data, dict):
            raise WallabagError(f"Expected annotation object after create, got {type(data).__name__}")
        return data

    async def update_annotation(self, annotation_id: int, text: str) -> dict[str, Any]:
        data = await self.request("PUT", _api_path(f"/annotations/{annotation_id}"), json_body={"text": text})
        if not isinstance(data, dict):
            raise WallabagError(f"Expected annotation object after update, got {type(data).__name__}")
        return data

    async def delete_annotation(self, annotation_id: int) -> dict[str, Any]:
        data = await self.request("DELETE", _api_path(f"/annotations/{annotation_id}"))
        return data if isinstance(data, dict) else {"deleted": True, "id": annotation_id}


default_client = WallabagClient()
