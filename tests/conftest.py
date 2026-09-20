"""Shared fakes and canned YouTube API payloads for unit tests."""
from __future__ import annotations

import pytest

from youtube_mcp.errors import AuthRequiredError, ConfigurationError


class FakeYouTubeClient:
    """In-memory stand-in for YouTubeClient.

    ``routes`` maps (method, path) -> handler(params, json_body) returning a
    dict payload or raising an exception. Auth requirements mirror the real
    client: key-authed calls need has_api_key, oauth calls need has_oauth.
    """

    def __init__(self, routes=(), has_api_key=True, has_oauth=True):
        self._routes = list(routes)
        self.calls: list[dict] = []
        self._has_api_key = has_api_key
        self._has_oauth = has_oauth

    @property
    def has_api_key(self):
        return self._has_api_key

    @property
    def has_oauth(self):
        return self._has_oauth

    def _dispatch(self, method, path, params, json_body, auth):
        if auth == "key" and not self._has_api_key:
            raise ConfigurationError("This tool needs a YouTube API key.")
        if auth == "oauth" and not self._has_oauth:
            raise AuthRequiredError("This tool needs OAuth.")
        self.calls.append({"method": method, "path": path, "params": params, "json": json_body, "auth": auth})
        for (m, p), handler in self._routes:
            if m == method and p == path:
                result = handler(params or {}, json_body)
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected API call in test: {method} {path}")

    def get(self, path, *, params=None, auth="key"):
        return self._dispatch("GET", path, params, None, auth)

    def post(self, path, *, params=None, json=None, auth="oauth"):
        return self._dispatch("POST", path, params, json, auth)

    def delete(self, path, *, params=None, auth="oauth"):
        return self._dispatch("DELETE", path, params, None, auth)

    def list_all(self, path, *, params=None, auth="key", max_pages=10):
        items, pages = [], 0
        token = None
        while pages < max_pages:
            p = dict(params or {})
            if token:
                p["pageToken"] = token
            data = self.get(path, params=p, auth=auth)
            items.extend(data.get("items", []))
            token = data.get("nextPageToken")
            pages += 1
            if not token:
                break
        return items, pages


def search_item(video_id="vid1", title="Test video", channel_id="ch1",
                channel="Test channel", published="2026-09-18T10:00:00Z"):
    return {
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {
            "title": title, "channelId": channel_id, "channelTitle": channel,
            "publishedAt": published, "description": "A description",
        },
    }


def sub_item(channel_id="ch1", title="Test channel"):
    return {
        "snippet": {
            "title": title, "description": "Channel desc",
            "resourceId": {"kind": "youtube#channel", "channelId": channel_id},
            "publishedAt": "2020-01-01T00:00:00Z",
        }
    }


def channel_item(channel_id="ch1", uploads="UU1"):
    return {"id": channel_id, "contentDetails": {"relatedPlaylists": {"uploads": uploads}}}


def playlist_video_item(video_id="v1", published="2026-09-19T12:00:00Z",
                        title="Upload", channel_id="ch1", item_id="pli1"):
    return {
        "id": item_id,
        "snippet": {
            "title": title, "publishedAt": published, "channelId": channel_id,
            "channelTitle": "Test channel", "playlistId": "UU1",
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        },
        "contentDetails": {"videoId": video_id},
    }


def video_item(video_id="v1", title="Test video"):
    return {
        "id": video_id,
        "snippet": {
            "title": title, "channelId": "ch1", "channelTitle": "Test channel",
            "publishedAt": "2026-01-01T00:00:00Z", "description": "Long description",
        },
        "statistics": {"viewCount": "12345", "likeCount": "678", "commentCount": "90"},
        "contentDetails": {"duration": "PT12M34S"},
    }


def playlist_entry(playlist_id="PL1", title="My playlist"):
    return {
        "id": playlist_id,
        "snippet": {"title": title, "description": "Playlist desc"},
        "contentDetails": {"itemCount": 3},
    }
