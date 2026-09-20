"""Unit tests for every MCP tool: happy path, API errors, auth/quota failures,
empty results, pagination, and the approval-gating contract."""
from __future__ import annotations

import pytest

from youtube_mcp import tools as yt
from youtube_mcp.approvals import ApprovalStore
from youtube_mcp.config import SAVE_FOR_LATER_PLAYLIST_TITLE
from youtube_mcp.errors import QuotaExceededError, YouTubeAPIError

from conftest import (
    FakeYouTubeClient,
    channel_item,
    playlist_entry,
    playlist_video_item,
    search_item,
    sub_item,
    video_item,
)


def _store(ttl=600):
    return ApprovalStore(ttl_seconds=ttl)


# ---------------------------------------------------------------------------
# search_videos
# ---------------------------------------------------------------------------

def test_search_videos_happy_path():
    client = FakeYouTubeClient(routes=[
        (("GET", "/search"), lambda p, j: {"items": [
            search_item("vid1", "First video"), search_item("vid2", "Second video")]})
    ])
    res = yt.search_videos(client, "python tutorial", max_results=5)
    assert res["status"] == "ok"
    assert res["auth"] == "api_key"
    assert res["quota_cost_units"] == 100
    assert res["count"] == 2
    first = res["data"]["videos"][0]
    assert first["video_id"] == "vid1"
    assert first["title"] == "First video"
    assert first["url"] == "https://www.youtube.com/watch?v=vid1"
    # query params passed through
    assert client.calls[0]["params"]["q"] == "python tutorial"
    assert client.calls[0]["params"]["maxResults"] == 5
    assert client.calls[0]["params"]["type"] == "video"


def test_search_videos_empty_results():
    client = FakeYouTubeClient(routes=[(("GET", "/search"), lambda p, j: {"items": []})])
    res = yt.search_videos(client, "zzzznothing")
    assert res["status"] == "ok"
    assert res["count"] == 0
    assert res["data"]["videos"] == []
    assert "No videos found" in res["message"]


def test_search_videos_filters_non_video_kinds():
    client = FakeYouTubeClient(routes=[(("GET", "/search"), lambda p, j: {"items": [
        {"id": {"kind": "youtube#channel", "channelId": "ch9"}, "snippet": {"title": "A channel"}},
        search_item("vid1"),
    ]})])
    res = yt.search_videos(client, "x")
    assert res["count"] == 1
    assert res["data"]["videos"][0]["video_id"] == "vid1"


def test_search_videos_quota_error():
    client = FakeYouTubeClient(routes=[
        (("GET", "/search"), lambda p, j: QuotaExceededError("quota gone"))])
    res = yt.search_videos(client, "x")
    assert res["status"] == "error"
    assert res["error_type"] == "quota_exceeded"
    assert "midnight Pacific" in res["hint"]


def test_search_videos_without_api_key():
    client = FakeYouTubeClient(has_api_key=False)
    res = yt.search_videos(client, "x")
    assert res["status"] == "error"
    assert res["error_type"] == "configuration_error"


def test_search_videos_empty_query():
    client = FakeYouTubeClient()
    res = yt.search_videos(client, "   ")
    assert res["status"] == "error"
    assert res["error_type"] == "invalid_input"


# ---------------------------------------------------------------------------
# my_subscriptions
# ---------------------------------------------------------------------------

def test_my_subscriptions_happy_path():
    client = FakeYouTubeClient(routes=[(("GET", "/subscriptions"), lambda p, j: {
        "items": [sub_item("ch1", "Chan One"), sub_item("ch2", "Chan Two")]})])
    res = yt.my_subscriptions(client)
    assert res["status"] == "ok"
    assert res["auth"] == "oauth"
    assert res["quota_cost_units"] == 1
    assert res["count"] == 2
    assert res["data"]["subscriptions"][0]["channel_id"] == "ch1"
    assert res["data"]["subscriptions"][0]["url"] == "https://www.youtube.com/channel/ch1"


def test_my_subscriptions_pagination():
    def handler(params, _json):
        if params.get("pageToken") == "p2":
            return {"items": [sub_item("ch3", "Chan Three")]}
        return {"items": [sub_item("ch1"), sub_item("ch2")], "nextPageToken": "p2"}

    client = FakeYouTubeClient(routes=[(("GET", "/subscriptions"), handler)])
    res = yt.my_subscriptions(client, max_results=100)
    assert res["count"] == 3
    assert res["quota_cost_units"] == 2  # one unit per page


def test_my_subscriptions_empty():
    client = FakeYouTubeClient(routes=[(("GET", "/subscriptions"), lambda p, j: {"items": []})])
    res = yt.my_subscriptions(client)
    assert res["status"] == "ok" and res["count"] == 0


def test_my_subscriptions_requires_oauth():
    client = FakeYouTubeClient(has_oauth=False)
    res = yt.my_subscriptions(client)
    assert res["status"] == "error"
    assert res["error_type"] == "auth_required"


def test_my_subscriptions_api_error():
    client = FakeYouTubeClient(routes=[
        (("GET", "/subscriptions"), lambda p, j: YouTubeAPIError(500, "backendError", "x"))])
    res = yt.my_subscriptions(client)
    assert res["status"] == "error"
    assert res["error_type"] == "youtube_api_error"


# ---------------------------------------------------------------------------
# catch_me_up
# ---------------------------------------------------------------------------

def _digest_client(**kwargs):
    """Two subscriptions; UU1 has a fresh + a stale video; UU2 has one fresh."""
    routes = [
        (("GET", "/subscriptions"), lambda p, j: {
            "items": [sub_item("ch1", "Chan One"), sub_item("ch2", "Chan Two")]}),
        (("GET", "/channels"), lambda p, j: {
            "items": [channel_item("ch1", "UU1"), channel_item("ch2", "UU2")]}),
        (("GET", "/playlistItems"), lambda p, j: {
            "items": [
                playlist_video_item("v-new-1", published="2026-09-19T12:00:00Z", title="Fresh one"),
                playlist_video_item("v-old", published="2026-08-01T00:00:00Z", title="Stale one"),
            ]} if p.get("playlistId") == "UU1" else {
            "items": [playlist_video_item("v-new-2", published="2026-09-18T08:00:00Z",
                                          title="Also fresh", channel_id="ch2")]}),
    ]
    return FakeYouTubeClient(routes=routes, **kwargs)


def test_catch_me_up_happy_path_filters_and_sorts():
    res = yt.catch_me_up(_digest_client(), since_days=7)
    assert res["status"] == "ok"
    assert res["auth"] == "oauth"
    videos = res["data"]["videos"]
    assert [v["video_id"] for v in videos] == ["v-new-1", "v-new-2"]  # stale excluded, newest first
    assert res["data"]["channels_checked"] == 2
    # quota: 1 sub page + 1 channels batch + 2 playlist pages = 4
    assert res["quota_cost_units"] == 4


def test_catch_me_up_no_new_uploads():
    client = FakeYouTubeClient(routes=[
        (("GET", "/subscriptions"), lambda p, j: {"items": [sub_item("ch1")]}),
        (("GET", "/channels"), lambda p, j: {"items": [channel_item("ch1", "UU1")]}),
        (("GET", "/playlistItems"), lambda p, j: {"items": [
            playlist_video_item("v-old", published="2025-01-01T00:00:00Z")]}),
    ])
    res = yt.catch_me_up(client, since_days=7)
    assert res["status"] == "ok"
    assert res["data"]["video_count"] == 0
    assert "No new uploads" in res["message"]


def test_catch_me_up_no_subscriptions():
    client = FakeYouTubeClient(routes=[
        (("GET", "/subscriptions"), lambda p, j: {"items": []})])
    res = yt.catch_me_up(client)
    assert res["status"] == "ok"
    assert res["data"]["channels_checked"] == 0
    assert res["data"]["videos"] == []


def test_catch_me_up_skips_channels_without_uploads_playlist():
    client = FakeYouTubeClient(routes=[
        (("GET", "/subscriptions"), lambda p, j: {"items": [sub_item("ch1")]}),
        (("GET", "/channels"), lambda p, j: {"items": [
            {"id": "ch1", "contentDetails": {"relatedPlaylists": {}}}]}),
    ])
    res = yt.catch_me_up(client)
    assert res["status"] == "ok"
    assert res["data"]["videos"] == []
    assert not [c for c in client.calls if c["path"] == "/playlistItems"]


def test_catch_me_up_api_error_midway():
    client = FakeYouTubeClient(routes=[
        (("GET", "/subscriptions"), lambda p, j: {"items": [sub_item("ch1")]}),
        (("GET", "/channels"), lambda p, j: YouTubeAPIError(500, "backendError", "x")),
    ])
    res = yt.catch_me_up(client)
    assert res["status"] == "error"
    assert res["error_type"] == "youtube_api_error"


def test_catch_me_up_requires_oauth():
    res = yt.catch_me_up(FakeYouTubeClient(has_oauth=False))
    assert res["status"] == "error"
    assert res["error_type"] == "auth_required"


# ---------------------------------------------------------------------------
# get_video_details
# ---------------------------------------------------------------------------

def test_get_video_details_happy_path():
    client = FakeYouTubeClient(routes=[(("GET", "/videos"), lambda p, j: {
        "items": [video_item("v1", "First"), video_item("v2", "Second")]})])
    res = yt.get_video_details(client, ["v1", "v2"])
    assert res["status"] == "ok"
    assert res["quota_cost_units"] == 1
    assert res["count"] == 2
    first = res["data"]["videos"][0]
    assert first["title"] == "First"
    assert first["view_count"] == "12345"
    assert first["duration"] == "PT12M34S"
    assert res["data"]["not_found"] == []
    assert client.calls[0]["params"]["id"] == "v1,v2"  # single batched call


def test_get_video_details_reports_missing_ids():
    client = FakeYouTubeClient(routes=[(("GET", "/videos"), lambda p, j: {
        "items": [video_item("v1")]})])
    res = yt.get_video_details(client, ["v1", "gone"])
    assert res["status"] == "ok"
    assert res["data"]["not_found"] == ["gone"]


def test_get_video_details_empty_input():
    res = yt.get_video_details(FakeYouTubeClient(), [])
    assert res["status"] == "error"
    assert res["error_type"] == "invalid_input"


def test_get_video_details_api_error():
    client = FakeYouTubeClient(routes=[
        (("GET", "/videos"), lambda p, j: YouTubeAPIError(400, "invalidValue", "bad id"))])
    res = yt.get_video_details(client, ["???"])
    assert res["status"] == "error"
    assert res["error_type"] == "youtube_api_error"


# ---------------------------------------------------------------------------
# my_playlists
# ---------------------------------------------------------------------------

def test_my_playlists_happy_path():
    client = FakeYouTubeClient(routes=[(("GET", "/playlists"), lambda p, j: {
        "items": [playlist_entry("PL1", "Cooking"), playlist_entry("PL2", "Music")]})])
    res = yt.my_playlists(client)
    assert res["status"] == "ok"
    assert res["count"] == 2
    assert res["data"]["playlists"][0]["playlist_id"] == "PL1"
    assert res["data"]["playlists"][0]["url"] == "https://www.youtube.com/playlist?list=PL1"


def test_my_playlists_requires_oauth():
    res = yt.my_playlists(FakeYouTubeClient(has_oauth=False))
    assert res["status"] == "error" and res["error_type"] == "auth_required"


# ---------------------------------------------------------------------------
# write tools: approval-gating contract
# ---------------------------------------------------------------------------

def test_create_playlist_returns_pending_and_executes_nothing():
    client = FakeYouTubeClient()
    res = yt.create_playlist(client, _store(), "Weekend cooking", privacy_status="unlisted")
    assert res["status"] == "pending_confirmation"
    assert res["confirmation_token"]
    assert res["expires_in_seconds"] == 600
    assert res["action"]["type"] == "playlists.insert"
    assert res["action"]["quota_cost_units"] == 50
    assert "Weekend cooking" in res["action"]["description"]
    assert client.calls == []  # nothing executed


def test_create_playlist_invalid_privacy():
    res = yt.create_playlist(FakeYouTubeClient(), _store(), "x", privacy_status="everyone")
    assert res["status"] == "error" and res["error_type"] == "invalid_input"


def test_create_playlist_empty_title():
    res = yt.create_playlist(FakeYouTubeClient(), _store(), "  ")
    assert res["status"] == "error" and res["error_type"] == "invalid_input"


def test_create_playlist_requires_oauth_upfront():
    res = yt.create_playlist(FakeYouTubeClient(has_oauth=False), _store(), "x")
    assert res["status"] == "error" and res["error_type"] == "auth_required"


def test_add_to_playlist_returns_pending():
    client = FakeYouTubeClient()
    res = yt.add_to_playlist(client, _store(), "PL1", "vid9")
    assert res["status"] == "pending_confirmation"
    assert res["action"]["type"] == "playlistItems.insert"
    assert res["action"]["quota_cost_units"] == 50
    assert client.calls == []


def test_add_to_playlist_invalid_input():
    res = yt.add_to_playlist(FakeYouTubeClient(), _store(), "", "vid9")
    assert res["status"] == "error" and res["error_type"] == "invalid_input"


def test_save_for_later_existing_playlist():
    client = FakeYouTubeClient(routes=[(("GET", "/playlists"), lambda p, j: {
        "items": [playlist_entry("PLWL", SAVE_FOR_LATER_PLAYLIST_TITLE)]})])
    res = yt.save_for_later(client, _store(), "vid9")
    assert res["status"] == "pending_confirmation"
    assert res["action"]["type"] == "save_for_later"
    assert res["action"]["quota_cost_units"] == 50
    assert "native Watch Later" in res["action"]["description"]
    assert not [c for c in client.calls if c["method"] == "POST"]


def test_save_for_later_creates_playlist_when_missing():
    client = FakeYouTubeClient(routes=[(("GET", "/playlists"), lambda p, j: {"items": []})])
    res = yt.save_for_later(client, _store(), "vid9")
    assert res["status"] == "pending_confirmation"
    assert res["action"]["quota_cost_units"] == 100  # insert + insert
    assert "Create private playlist" in res["action"]["description"]


def test_save_for_later_requires_oauth_before_any_read():
    client = FakeYouTubeClient(has_oauth=False)
    res = yt.save_for_later(client, _store(), "vid9")
    assert res["status"] == "error" and res["error_type"] == "auth_required"
    assert client.calls == []


def test_remove_from_playlist_returns_pending():
    client = FakeYouTubeClient()
    res = yt.remove_from_playlist(client, _store(), "pli123")
    assert res["status"] == "pending_confirmation"
    assert res["action"]["type"] == "playlistItems.delete"
    assert res["action"]["quota_cost_units"] == 50
    assert client.calls == []


# ---------------------------------------------------------------------------
# confirm / cancel
# ---------------------------------------------------------------------------

def test_confirm_add_to_playlist_executes_insert():
    client = FakeYouTubeClient(routes=[
        (("POST", "/playlistItems"), lambda p, j: {"id": "pli-new"})])
    approvals = _store()
    pending = yt.add_to_playlist(client, approvals, "PL1", "vid9")
    res = yt.confirm_action(client, approvals, pending["confirmation_token"])
    assert res["status"] == "ok"
    assert res["data"]["playlist_item_id"] == "pli-new"
    assert res["data"]["video_id"] == "vid9"
    body = client.calls[-1]["json"]
    assert body["snippet"]["playlistId"] == "PL1"
    assert body["snippet"]["resourceId"] == {"kind": "youtube#video", "videoId": "vid9"}


def test_confirm_token_is_single_use():
    client = FakeYouTubeClient(routes=[(("POST", "/playlistItems"), lambda p, j: {"id": "x"})])
    approvals = _store()
    token = yt.add_to_playlist(client, approvals, "PL1", "v")["confirmation_token"]
    assert yt.confirm_action(client, approvals, token)["status"] == "ok"
    second = yt.confirm_action(client, approvals, token)
    assert second["status"] == "error"
    assert second["error_type"] == "invalid_or_expired_token"


def test_confirm_unknown_token():
    res = yt.confirm_action(FakeYouTubeClient(), _store(), "bogus")
    assert res["status"] == "error"
    assert res["error_type"] == "invalid_or_expired_token"


def test_confirm_expired_token():
    client = FakeYouTubeClient()
    approvals = ApprovalStore(ttl_seconds=0)
    token = yt.add_to_playlist(client, approvals, "PL1", "v")["confirmation_token"]
    res = yt.confirm_action(client, approvals, token)
    assert res["status"] == "error"
    assert res["error_type"] == "invalid_or_expired_token"


def test_confirm_create_playlist():
    client = FakeYouTubeClient(routes=[(("POST", "/playlists"), lambda p, j: {
        "id": "PL9", "snippet": {"title": p and "Weekend"}})])
    approvals = _store()
    token = yt.create_playlist(client, approvals, "Weekend")["confirmation_token"]
    res = yt.confirm_action(client, approvals, token)
    assert res["status"] == "ok"
    assert res["data"]["playlist_id"] == "PL9"
    assert res["data"]["url"] == "https://www.youtube.com/playlist?list=PL9"
    body = client.calls[-1]["json"]
    assert body["status"]["privacyStatus"] == "private"


def test_confirm_save_for_later_existing_playlist_single_insert():
    client = FakeYouTubeClient(routes=[
        (("GET", "/playlists"), lambda p, j: {"items": [playlist_entry("PLWL", SAVE_FOR_LATER_PLAYLIST_TITLE)]}),
        (("POST", "/playlistItems"), lambda p, j: {"id": "pli-x"}),
    ])
    approvals = _store()
    token = yt.save_for_later(client, approvals, "vid9")["confirmation_token"]
    res = yt.confirm_action(client, approvals, token)
    assert res["status"] == "ok"
    assert res["data"]["playlist_id"] == "PLWL"
    posts = [c for c in client.calls if c["method"] == "POST"]
    assert len(posts) == 1 and posts[0]["path"] == "/playlistItems"


def test_confirm_save_for_later_creates_then_inserts():
    client = FakeYouTubeClient(routes=[
        (("GET", "/playlists"), lambda p, j: {"items": []}),
        (("POST", "/playlists"), lambda p, j: {"id": "PLNEW", "snippet": {"title": "x"}}),
        (("POST", "/playlistItems"), lambda p, j: {"id": "pli-y"}),
    ])
    approvals = _store()
    token = yt.save_for_later(client, approvals, "vid9")["confirmation_token"]
    res = yt.confirm_action(client, approvals, token)
    assert res["status"] == "ok"
    assert res["data"]["playlist_id"] == "PLNEW"
    assert [s["step"] for s in res["data"]["steps"]] == ["playlists.insert", "playlistItems.insert"]


def test_confirm_remove_from_playlist():
    client = FakeYouTubeClient(routes=[(("DELETE", "/playlistItems"), lambda p, j: {})])
    approvals = _store()
    token = yt.remove_from_playlist(client, approvals, "pli123")["confirmation_token"]
    res = yt.confirm_action(client, approvals, token)
    assert res["status"] == "ok"
    assert res["data"] == {"deleted": True, "playlist_item_id": "pli123"}
    assert client.calls[-1]["params"]["id"] == "pli123"


def test_confirm_api_failure_returns_error_and_consumes_token():
    client = FakeYouTubeClient(routes=[
        (("POST", "/playlistItems"), lambda p, j: YouTubeAPIError(403, "forbidden", "denied"))])
    approvals = _store()
    token = yt.add_to_playlist(client, approvals, "PL1", "v")["confirmation_token"]
    res = yt.confirm_action(client, approvals, token)
    assert res["status"] == "error"
    assert res["error_type"] == "youtube_api_error"
    retry = yt.confirm_action(client, approvals, token)
    assert retry["error_type"] == "invalid_or_expired_token"


def test_cancel_action_discards_pending():
    client = FakeYouTubeClient()
    approvals = _store()
    token = yt.add_to_playlist(client, approvals, "PL1", "v")["confirmation_token"]
    cancelled = yt.cancel_action(approvals, token)
    assert cancelled["status"] == "ok" and cancelled["cancelled"] is True
    after = yt.confirm_action(client, approvals, token)
    assert after["error_type"] == "invalid_or_expired_token"
    assert client.calls == []


def test_cancel_unknown_token():
    res = yt.cancel_action(_store(), "bogus")
    assert res["status"] == "ok" and res["cancelled"] is False
