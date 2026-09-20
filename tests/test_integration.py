"""Integration tests against the real YouTube Data API v3.

These are SKIPPED unless credentials are present in the environment:

    YOUTUBE_API_KEY     -> enables public-read tests (search, video details)
    YOUTUBE_OAUTH_TOKEN -> enables private-read tests (subscriptions, playlists, digest)

They only exercise read tools — never writes — so they cannot mutate the
account. Each test's quota cost is noted; a full run costs ~110 units,
about 1% of the default 10,000-units/day quota.

Run:  YOUTUBE_API_KEY=... YOUTUBE_OAUTH_TOKEN=... pytest -m integration
"""
from __future__ import annotations

import os

import pytest

from youtube_mcp import tools as yt
from youtube_mcp.client import YouTubeClient
from youtube_mcp.config import Settings

pytestmark = pytest.mark.integration

requires_key = pytest.mark.skipif(
    not os.getenv("YOUTUBE_API_KEY"), reason="YOUTUBE_API_KEY not set"
)
requires_oauth = pytest.mark.skipif(
    not os.getenv("YOUTUBE_OAUTH_TOKEN"), reason="YOUTUBE_OAUTH_TOKEN not set"
)


def _client() -> YouTubeClient:
    return YouTubeClient(
        Settings(
            api_key=os.getenv("YOUTUBE_API_KEY"),
            oauth_token=os.getenv("YOUTUBE_OAUTH_TOKEN"),
            http_proxy=os.getenv("YOUTUBE_HTTP_PROXY"),
            https_proxy=os.getenv("YOUTUBE_HTTPS_PROXY"),
            ca_bundle=os.getenv("YOUTUBE_CA_BUNDLE"),
        )
    )


@requires_key
def test_search_videos_live():
    """~100 quota units."""
    res = yt.search_videos(_client(), "lofi hip hop radio", max_results=3)
    assert res["status"] == "ok", res
    assert res["count"] >= 1
    video = res["data"]["videos"][0]
    assert video["video_id"]
    assert video["url"].startswith("https://www.youtube.com/watch?v=")


@requires_key
def test_get_video_details_live():
    """~1 quota unit. Uses a long-lived public video as a stable fixture."""
    res = yt.get_video_details(_client(), ["dQw4w9WgXcQ"])
    assert res["status"] == "ok", res
    assert res["data"]["videos"][0]["title"]
    assert res["data"]["not_found"] == []


@requires_oauth
def test_my_subscriptions_live():
    """~1 quota unit per page."""
    res = yt.my_subscriptions(_client(), max_results=5)
    assert res["status"] == "ok", res
    assert isinstance(res["data"]["subscriptions"], list)


@requires_oauth
def test_my_playlists_live():
    """~1 quota unit per page."""
    res = yt.my_playlists(_client(), max_results=5)
    assert res["status"] == "ok", res
    assert isinstance(res["data"]["playlists"], list)


@requires_oauth
def test_catch_me_up_live():
    """~2 + N quota units (N = channels checked, capped at 5 here)."""
    res = yt.catch_me_up(_client(), since_days=30, max_channels=5, max_videos_per_channel=2)
    assert res["status"] == "ok", res
    assert res["data"]["video_count"] >= 0
