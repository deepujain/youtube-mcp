"""Unit tests for YouTubeClient: auth injection, error mapping, pagination."""
from __future__ import annotations

import httpx
import pytest

from youtube_mcp.client import YouTubeClient
from youtube_mcp.config import Settings
from youtube_mcp.errors import (
    AuthRequiredError,
    ConfigurationError,
    NotFoundError,
    QuotaExceededError,
    YouTubeAPIError,
    YouTubeConnectorError,
)


def _client(handler, api_key="test-key", oauth_token="test-token"):
    return YouTubeClient(
        Settings(api_key=api_key, oauth_token=oauth_token),
        transport=httpx.MockTransport(handler),
    )


def _ok(payload):
    return httpx.Response(200, json=payload)


def _err(status, reason, message="boom"):
    return httpx.Response(
        status,
        json={"error": {"code": status, "message": message,
                        "errors": [{"reason": reason, "message": message}]}},
    )


def test_api_key_sent_as_query_param():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return _ok({"items": []})

    _client(handler).get("/search", params={"q": "x"}, auth="key")
    assert seen["key"] == "test-key"
    assert seen["q"] == "x"


def test_oauth_sent_as_bearer_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return _ok({"items": []})

    _client(handler).get("/subscriptions", auth="oauth")
    assert seen["auth"] == "Bearer test-token"


def test_missing_api_key_raises_configuration_error():
    client = _client(lambda r: _ok({}), api_key=None)
    with pytest.raises(ConfigurationError):
        client.get("/search", auth="key")


def test_missing_oauth_token_raises_auth_required():
    client = _client(lambda r: _ok({}), oauth_token=None)
    with pytest.raises(AuthRequiredError):
        client.get("/subscriptions", auth="oauth")


def test_401_maps_to_auth_required():
    client = _client(lambda r: _err(401, "authError"))
    with pytest.raises(AuthRequiredError):
        client.get("/subscriptions", auth="oauth")


@pytest.mark.parametrize("reason", ["quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"])
def test_quota_reasons_map_to_quota_exceeded(reason):
    client = _client(lambda r: _err(403, reason))
    with pytest.raises(QuotaExceededError):
        client.get("/search", auth="key")


def test_403_other_reason_maps_to_api_error():
    client = _client(lambda r: _err(403, "forbidden"))
    with pytest.raises(YouTubeAPIError) as excinfo:
        client.get("/search", auth="key")
    assert excinfo.value.reason == "forbidden"
    assert excinfo.value.status_code == 403


def test_404_maps_to_not_found():
    client = _client(lambda r: _err(404, "notFound"))
    with pytest.raises(NotFoundError):
        client.get("/videos", auth="key")


def test_400_maps_to_api_error():
    client = _client(lambda r: _err(400, "invalidValue"))
    with pytest.raises(YouTubeAPIError) as excinfo:
        client.get("/search", auth="key")
    assert excinfo.value.status_code == 400


def test_500_maps_to_api_error():
    client = _client(lambda r: _err(500, "backendError"))
    with pytest.raises(YouTubeAPIError):
        client.get("/search", auth="key")


def test_non_json_error_body_still_raises():
    client = _client(lambda r: httpx.Response(503, text="unavailable"))
    with pytest.raises(YouTubeAPIError):
        client.get("/search", auth="key")


def test_network_error_wrapped():
    def handler(request):
        raise httpx.ConnectError("dns failure")

    with pytest.raises(YouTubeConnectorError, match="Network error"):
        _client(handler).get("/search", auth="key")


def test_list_all_follows_pagination():
    pages = [
        {"items": [{"id": "a"}], "nextPageToken": "tok2"},
        {"items": [{"id": "b"}]},
    ]

    def handler(request):
        token = request.url.params.get("pageToken")
        return _ok(pages[1] if token == "tok2" else pages[0])

    items, count = _client(handler).list_all("/subscriptions", auth="oauth", max_pages=5)
    assert [i["id"] for i in items] == ["a", "b"]
    assert count == 2


def test_list_all_respects_max_pages():
    def handler(request):
        return _ok({"items": [{"id": "a"}], "nextPageToken": "more"})

    items, count = _client(handler).list_all("/subscriptions", auth="oauth", max_pages=3)
    assert count == 3
    assert len(items) == 3


def test_list_all_empty_result():
    items, count = _client(lambda r: _ok({"items": []})).list_all("/search", auth="key")
    assert items == [] and count == 1


def test_post_defaults_to_oauth_and_sends_json():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        import json as _json
        seen["body"] = _json.loads(request.content.decode())
        return _ok({"id": "PL9"})

    result = _client(handler).post("/playlists", json={"snippet": {"title": "x"}})
    assert result == {"id": "PL9"}
    assert seen["auth"] == "Bearer test-token"
    assert seen["body"] == {"snippet": {"title": "x"}}
