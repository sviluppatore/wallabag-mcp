"""Unit tests for wallabag API client."""

from __future__ import annotations

import httpx
import pytest
import respx

from wallabag_mcp.client import WallabagError
from wallabag_mcp.client import default_client as client


@pytest.fixture(autouse=True)
def configure_client():
    client.reset()
    client.configure(
        base_url="https://wallabag.example",
        client_id="client-id",
        client_secret="client-secret",
        username="user",
        password="pass",
        timeout=5,
    )
    yield
    client.reset()


def _mock_entries(items: list[dict] | None = None, **extra) -> respx.Route:
    payload = {"_embedded": {"items": items or []}, **extra}
    return respx.get("https://wallabag.example/api/entries.json").mock(
        return_value=httpx.Response(200, json=payload)
    )


@respx.mock
async def test_oauth_token_requested_and_used():
    token_route = respx.post("https://wallabag.example/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
    )
    entries_route = _mock_entries(page=1, pages=1, limit=30, total=0)

    data = await client.list_entries()

    assert data == {"items": [], "pagination": {"page": 1, "pages": 1, "limit": 30, "total": 0}}
    assert "grant_type=password" in token_route.calls[0].request.content.decode()
    assert entries_route.calls[0].request.headers["Authorization"] == "Bearer token-123"
    assert "detail=metadata" in str(entries_route.calls[0].request.url)


@respx.mock
async def test_access_token_skips_password_grant():
    client.configure(access_token="already-have-token")
    entries_route = _mock_entries([{"id": 1}])

    data = await client.list_entries(per_page=5, archive=0, starred=1)

    assert data["items"] == [{"id": 1}]
    assert entries_route.calls[0].request.headers["Authorization"] == "Bearer already-have-token"
    url = str(entries_route.calls[0].request.url)
    assert "perPage=5" in url
    assert "archive=0" in url
    assert "starred=1" in url


@respx.mock
async def test_expired_token_renewed_via_refresh_grant():
    token_route = respx.post("https://wallabag.example/oauth/v2/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "t1", "expires_in": 1, "refresh_token": "r1"}),
            httpx.Response(200, json={"access_token": "t2", "expires_in": 3600, "refresh_token": "r2"}),
        ]
    )
    entries_route = _mock_entries()

    await client.list_entries()
    await client.list_entries()

    assert token_route.call_count == 2
    second_grant = token_route.calls[1].request.content.decode()
    assert "grant_type=refresh_token" in second_grant
    assert "refresh_token=r1" in second_grant
    assert entries_route.calls[1].request.headers["Authorization"] == "Bearer t2"


@respx.mock
async def test_401_response_retried_once_with_fresh_token():
    token_route = respx.post("https://wallabag.example/oauth/v2/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "t1", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "t2", "expires_in": 3600}),
        ]
    )
    entries_route = respx.get("https://wallabag.example/api/entries.json").mock(
        side_effect=[
            httpx.Response(401, json={"error": "invalid_grant"}),
            httpx.Response(200, json={"_embedded": {"items": [{"id": 5}]}}),
        ]
    )

    data = await client.list_entries()

    assert data["items"] == [{"id": 5}]
    assert token_route.call_count == 2
    assert entries_route.call_count == 2
    assert entries_route.calls[1].request.headers["Authorization"] == "Bearer t2"


@respx.mock
async def test_401_with_static_token_and_no_credentials_not_retried():
    client.reset()
    client.configure(base_url="https://wallabag.example", access_token="static-token")
    entries_route = respx.get("https://wallabag.example/api/entries.json").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )

    with pytest.raises(WallabagError, match="HTTP 401"):
        await client.list_entries()

    assert entries_route.call_count == 1


@respx.mock
async def test_configure_credentials_drop_cached_token():
    token_route = respx.post("https://wallabag.example/oauth/v2/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "t1", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "t2", "expires_in": 3600}),
        ]
    )
    _mock_entries()

    await client.list_entries()
    client.configure(password="new-pass")
    await client.list_entries()

    assert token_route.call_count == 2
    assert "password=new-pass" in token_route.calls[1].request.content.decode()


@respx.mock
async def test_create_and_update_entry_payloads():
    client.configure(access_token="token")
    create_route = respx.post("https://wallabag.example/api/entries.json").mock(
        return_value=httpx.Response(200, json={"id": 7, "url": "https://example.com", "title": "Example"})
    )
    update_route = respx.patch("https://wallabag.example/api/entries/7.json").mock(
        return_value=httpx.Response(200, json={"id": 7, "is_archived": 1})
    )

    assert (await client.create_entry("https://example.com", title="Example"))["id"] == 7
    assert (await client.update_entry(7, archive=1))["is_archived"] == 1
    assert create_route.calls[0].request.content == b'{"url":"https://example.com","title":"Example"}'
    assert update_route.calls[0].request.content == b'{"archive":1}'


@respx.mock
async def test_update_entry_refetches_empty_response():
    client.configure(access_token="token")
    respx.patch("https://wallabag.example/api/entries/7.json").mock(return_value=httpx.Response(204))
    respx.get("https://wallabag.example/api/entries/7.json").mock(
        return_value=httpx.Response(200, json={"id": 7, "title": "Refetched"})
    )

    assert await client.update_entry(7, starred=1) == {"id": 7, "title": "Refetched"}


@respx.mock
async def test_search_entries():
    client.configure(access_token="token")
    search_route = respx.get("https://wallabag.example/api/search.json").mock(
        return_value=httpx.Response(200, json={"_embedded": {"items": [{"id": 3}]}, "page": 1, "pages": 1, "limit": 30, "total": 1})
    )

    data = await client.search_entries("python", per_page=10)

    assert data["items"] == [{"id": 3}]
    assert data["pagination"]["total"] == 1
    url = str(search_route.calls[0].request.url)
    assert "term=python" in url
    assert "perPage=10" in url


@respx.mock
async def test_entry_exists():
    client.configure(access_token="token")
    exists_route = respx.get("https://wallabag.example/api/entries/exists.json").mock(
        return_value=httpx.Response(200, json={"exists": 42})
    )

    assert (await client.entry_exists("https://example.com/article"))["exists"] == 42
    assert "return_id=1" in str(exists_route.calls[0].request.url)


@respx.mock
async def test_tags_and_annotations():
    client.configure(access_token="token")
    respx.get("https://wallabag.example/api/tags.json").mock(return_value=httpx.Response(200, json=[{"id": 2, "label": "ai"}]))
    add_tags_route = respx.post("https://wallabag.example/api/entries/7/tags.json").mock(
        return_value=httpx.Response(200, json={"id": 7, "tags": [{"label": "ai"}]})
    )
    remove_tag_route = respx.delete("https://wallabag.example/api/entries/7/tags/2.json").mock(
        return_value=httpx.Response(200, json={"id": 7, "tags": []})
    )
    respx.get("https://wallabag.example/api/entries/7/annotations.json").mock(
        return_value=httpx.Response(200, json=[{"id": 9, "text": "note"}])
    )

    assert await client.list_tags() == [{"id": 2, "label": "ai"}]
    assert (await client.add_tags(7, "ai"))["id"] == 7
    assert add_tags_route.calls[0].request.content == b'{"tags":"ai"}'
    assert (await client.remove_tag_from_entry(7, 2))["tags"] == []
    assert remove_tag_route.call_count == 1
    assert await client.list_annotations(7) == [{"id": 9, "text": "note"}]


@respx.mock
async def test_health_check_uses_tiny_read_only_request():
    client.configure(access_token="token")
    route = _mock_entries([{"id": 1}], page=1, pages=1, limit=1, total=5)

    assert await client.health_check() == {
        "ok": True,
        "entries_seen": 1,
        "pagination": {"page": 1, "pages": 1, "limit": 1, "total": 5},
    }
    assert "perPage=1" in str(route.calls[0].request.url)


@respx.mock
async def test_http_errors_are_readable():
    client.configure(access_token="token")
    respx.get("https://wallabag.example/api/entries/404.json").mock(return_value=httpx.Response(404, text="Not found"))

    with pytest.raises(WallabagError, match="HTTP 404"):
        await client.get_entry(404)
