"""MCP tool implementations.

Every tool is a pure function over an injected ``YouTubeClient`` (and, for
writes, an ``ApprovalStore``), returning a JSON-serializable dict with a
``status`` field:

  * ``"ok"``                   -> success; result under ``data``.
  * ``"pending_confirmation"`` -> a write tool produced an approval payload;
    nothing has been executed yet. The agent must surface ``action`` to the
    user and, on approval, call ``confirm_action`` with ``confirmation_token``.
  * ``"error"``                -> failure; ``error_type`` / ``message`` / ``hint``.

Auth per tool is declared in each docstring: ``API key`` (public reads) or
``OAuth`` (private reads and all writes).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .approvals import ApprovalStore, PendingAction
from .client import YouTubeClient
from .config import (
    SAVE_FOR_LATER_PLAYLIST_DESCRIPTION,
    SAVE_FOR_LATER_PLAYLIST_TITLE,
)
from .errors import (
    AuthRequiredError,
    ConfigurationError,
    NotFoundError,
    QuotaExceededError,
    YouTubeAPIError,
    YouTubeConnectorError,
)
from .quota import cost_of

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"
CHANNEL_URL = "https://www.youtube.com/channel/{channel_id}"


# ---------------------------------------------------------------------------
# response helpers
# ---------------------------------------------------------------------------

def _error_response(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, QuotaExceededError):
        return {
            "status": "error",
            "error_type": "quota_exceeded",
            "message": str(exc),
            "hint": (
                "The project's 10,000-units/day YouTube quota is exhausted; it resets at "
                "midnight Pacific. Prefer videos.list (1 unit) over search.list (100 units)."
            ),
        }
    if isinstance(exc, AuthRequiredError):
        return {
            "status": "error",
            "error_type": "auth_required",
            "message": str(exc),
            "hint": (
                "Complete the YouTube OAuth flow (scopes youtube.readonly + "
                "youtube.force-ssl) and set YOUTUBE_OAUTH_TOKEN."
            ),
        }
    if isinstance(exc, ConfigurationError):
        return {
            "status": "error",
            "error_type": "configuration_error",
            "message": str(exc),
            "hint": "Create an API key for the Cloud project and set YOUTUBE_API_KEY.",
        }
    if isinstance(exc, NotFoundError):
        return {"status": "error", "error_type": "not_found", "message": str(exc), "hint": None}
    if isinstance(exc, (YouTubeAPIError, YouTubeConnectorError)):
        return {
            "status": "error",
            "error_type": "youtube_api_error",
            "message": str(exc),
            "hint": None,
        }
    return {
        "status": "error",
        "error_type": "unexpected",
        "message": f"{type(exc).__name__}: {exc}",
        "hint": None,
    }


def _invalid_input(message: str) -> dict[str, Any]:
    return {"status": "error", "error_type": "invalid_input", "message": message, "hint": None}


def _pending_payload(action: PendingAction, expires_in_seconds: int) -> dict[str, Any]:
    return {
        "status": "pending_confirmation",
        "confirmation_token": action.token,
        "expires_in_seconds": expires_in_seconds,
        "action": {
            "type": action.action_type,
            "description": action.description,
            "quota_cost_units": action.quota_cost_units,
        },
        "next_step": (
            "Show the action description to the user for approval. If they approve, "
            "call confirm_action with the confirmation_token. "
            "To abort, call cancel_action with the token."
        ),
    }


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------

def _parse_search_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("id", {}).get("kind") != "youtube#video":
        return None
    video_id = item["id"].get("videoId", "")
    snippet = item.get("snippet", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "description": (snippet.get("description") or "")[:300],
        "url": WATCH_URL.format(video_id=video_id),
    }


def _parse_playlist_item(item: dict[str, Any]) -> dict[str, Any] | None:
    snippet = item.get("snippet", {})
    content = item.get("contentDetails", {})
    video_id = content.get("videoId") or snippet.get("resourceId", {}).get("videoId", "")
    if not video_id:
        return None
    return {
        "video_id": video_id,
        "playlist_item_id": item.get("id"),
        "title": snippet.get("title"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "url": WATCH_URL.format(video_id=video_id),
    }


def _parse_video(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    video_id = item.get("id", "")
    return {
        "video_id": video_id,
        "title": snippet.get("title"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "description": (snippet.get("description") or "")[:500],
        "duration": content.get("duration"),
        "view_count": stats.get("viewCount"),
        "like_count": stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
        "url": WATCH_URL.format(video_id=video_id),
    }


# ---------------------------------------------------------------------------
# read tools (API key unless noted)
# ---------------------------------------------------------------------------

def search_videos(
    client: YouTubeClient,
    query: str,
    max_results: int = 10,
    order: str = "relevance",
    published_after: str | None = None,
) -> dict[str, Any]:
    """Search public YouTube videos. Auth: API key. Quota: 100 units/call."""
    try:
        if not query or not query.strip():
            return _invalid_input("query must be a non-empty string.")
        max_results = max(1, min(50, int(max_results)))
        params: dict[str, Any] = {
            "part": "snippet",
            "q": query.strip(),
            "type": "video",
            "maxResults": max_results,
            "order": order,
        }
        if published_after:
            params["publishedAfter"] = published_after
        data = client.get("/search", params=params, auth="key")
        videos = [v for v in (_parse_search_item(i) for i in data.get("items", [])) if v]
        return {
            "status": "ok",
            "auth": "api_key",
            "quota_cost_units": cost_of("search.list"),
            "count": len(videos),
            "data": {"videos": videos},
            "message": f"Found {len(videos)} video(s)." if videos else "No videos found for this query.",
        }
    except Exception as exc:  # noqa: BLE001 - mapped to a structured payload
        return _error_response(exc)


def my_subscriptions(client: YouTubeClient, max_results: int = 50) -> dict[str, Any]:
    """List the user's channel subscriptions. Auth: OAuth (youtube.readonly). Quota: 1 unit/page."""
    try:
        max_results = max(1, int(max_results))
        pages = max(1, -(-max_results // 50))
        items, pages_fetched = client.list_all(
            "/subscriptions",
            params={"part": "snippet", "mine": "true", "maxResults": 50, "order": "alphabetical"},
            auth="oauth",
            max_pages=pages,
        )
        subs = []
        for item in items[:max_results]:
            snippet = item.get("snippet", {})
            channel_id = snippet.get("resourceId", {}).get("channelId", "")
            subs.append(
                {
                    "channel_id": channel_id,
                    "channel_title": snippet.get("title"),
                    "description": (snippet.get("description") or "")[:200],
                    "subscribed_at": snippet.get("publishedAt"),
                    "url": CHANNEL_URL.format(channel_id=channel_id),
                }
            )
        return {
            "status": "ok",
            "auth": "oauth",
            "quota_cost_units": pages_fetched * cost_of("subscriptions.list"),
            "count": len(subs),
            "data": {"subscriptions": subs},
        }
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


def catch_me_up(
    client: YouTubeClient,
    since_days: int = 7,
    max_channels: int = 50,
    max_videos_per_channel: int = 5,
) -> dict[str, Any]:
    """Digest of recent uploads from the user's subscriptions, newest first.

    Quota-efficient: subscriptions.list + one channels.list batch + one
    playlistItems.list per channel (1 unit each). Never uses search.list.
    Auth: OAuth (youtube.readonly).
    """
    try:
        since_days = max(1, int(since_days))
        max_channels = max(1, int(max_channels))
        max_videos_per_channel = max(1, int(max_videos_per_channel))
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

        subs, sub_pages = client.list_all(
            "/subscriptions",
            params={"part": "snippet", "mine": "true", "maxResults": 50},
            auth="oauth",
            max_pages=10,
        )
        subs = subs[:max_channels]
        channel_ids = [s.get("snippet", {}).get("resourceId", {}).get("channelId", "") for s in subs]
        channel_ids = [c for c in channel_ids if c]

        uploads: dict[str, str] = {}
        channel_pages = 0
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i : i + 50]
            data = client.get("/channels", params={"part": "contentDetails", "id": ",".join(batch)}, auth="oauth")
            channel_pages += 1
            for ch in data.get("items", []):
                playlist_id = (ch.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
                if playlist_id:
                    uploads[ch.get("id", "")] = playlist_id

        videos: list[dict[str, Any]] = []
        playlist_pages = 0
        for channel_id in channel_ids:
            playlist_id = uploads.get(channel_id)
            if not playlist_id:
                continue
            data = client.get(
                "/playlistItems",
                params={"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50},
                auth="oauth",
            )
            playlist_pages += 1
            per_channel = 0
            for item in data.get("items", []):
                parsed = _parse_playlist_item(item)
                if not parsed:
                    continue
                try:
                    published = datetime.fromisoformat((parsed["published_at"] or "").replace("Z", "+00:00"))
                except ValueError:
                    continue
                if published < cutoff:
                    continue
                videos.append(parsed)
                per_channel += 1
                if per_channel >= max_videos_per_channel:
                    break

        videos.sort(key=lambda v: v.get("published_at") or "", reverse=True)
        quota_spent = sub_pages + channel_pages + playlist_pages  # 1 unit each
        return {
            "status": "ok",
            "auth": "oauth",
            "quota_cost_units": quota_spent,
            "data": {
                "since": cutoff.isoformat(),
                "channels_checked": len(channel_ids),
                "video_count": len(videos),
                "videos": videos,
            },
            "message": (
                f"{len(videos)} new video(s) from {len(channel_ids)} subscription(s) "
                f"in the last {since_days} day(s)."
                if videos
                else f"No new uploads from your subscriptions in the last {since_days} day(s)."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


def get_video_details(client: YouTubeClient, video_ids: list[str]) -> dict[str, Any]:
    """Details + statistics for up to 50 videos in one call. Auth: API key. Quota: 1 unit."""
    try:
        ids = [v.strip() for v in (video_ids or []) if v and v.strip()][:50]
        if not ids:
            return _invalid_input("video_ids must be a non-empty list of YouTube video IDs.")
        data = client.get(
            "/videos",
            params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids)},
            auth="key",
        )
        videos = [_parse_video(i) for i in data.get("items", [])]
        found_ids = {v["video_id"] for v in videos}
        return {
            "status": "ok",
            "auth": "api_key",
            "quota_cost_units": cost_of("videos.list"),
            "count": len(videos),
            "data": {"videos": videos, "not_found": [i for i in ids if i not in found_ids]},
        }
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


def my_playlists(client: YouTubeClient, max_results: int = 25) -> dict[str, Any]:
    """List the user's own playlists. Auth: OAuth (youtube.readonly). Quota: 1 unit/page."""
    try:
        max_results = max(1, int(max_results))
        items, pages_fetched = client.list_all(
            "/playlists",
            params={"part": "snippet,contentDetails", "mine": "true", "maxResults": 50},
            auth="oauth",
            max_pages=max(1, -(-max_results // 50)),
        )
        playlists = []
        for item in items[:max_results]:
            snippet = item.get("snippet", {})
            playlists.append(
                {
                    "playlist_id": item.get("id", ""),
                    "title": snippet.get("title"),
                    "description": (snippet.get("description") or "")[:200],
                    "item_count": (item.get("contentDetails") or {}).get("itemCount"),
                    "privacy": snippet.get("status", {}).get("privacyStatus"),
                    "url": PLAYLIST_URL.format(playlist_id=item.get("id", "")),
                }
            )
        return {
            "status": "ok",
            "auth": "oauth",
            "quota_cost_units": pages_fetched * cost_of("playlists.list"),
            "count": len(playlists),
            "data": {"playlists": playlists},
        }
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


# ---------------------------------------------------------------------------
# write tools — approval-gated (return pending_confirmation, never execute)
# ---------------------------------------------------------------------------

def _require_oauth(client: YouTubeClient) -> dict[str, Any] | None:
    if not client.has_oauth:
        return _error_response(
            AuthRequiredError(
                "This write tool needs the user's YouTube OAuth authorization "
                "(scopes: youtube.readonly, youtube.force-ssl). "
                "Complete the OAuth flow and set YOUTUBE_OAUTH_TOKEN."
            )
        )
    return None


def create_playlist(
    client: YouTubeClient,
    approvals: ApprovalStore,
    title: str,
    description: str = "",
    privacy_status: str = "private",
) -> dict[str, Any]:
    """Propose creating a playlist. Returns pending_confirmation. Auth: OAuth (youtube.force-ssl). Quota on confirm: 50."""
    try:
        if not title or not title.strip():
            return _invalid_input("title must be a non-empty string.")
        if privacy_status not in ("private", "unlisted", "public"):
            return _invalid_input("privacy_status must be one of: private, unlisted, public.")
        missing = _require_oauth(client)
        if missing:
            return missing
        action = approvals.propose(
            action_type="playlists.insert",
            description=f"Create YouTube playlist '{title.strip()}' ({privacy_status}) on your account.",
            quota_cost_units=cost_of("playlists.insert"),
            payload={
                "title": title.strip(),
                "description": description,
                "privacy_status": privacy_status,
            },
        )
        return _pending_payload(action, approvals._ttl)
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


def add_to_playlist(
    client: YouTubeClient,
    approvals: ApprovalStore,
    playlist_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Propose adding a video to a playlist. Returns pending_confirmation. Auth: OAuth. Quota on confirm: 50."""
    try:
        if not playlist_id or not video_id:
            return _invalid_input("playlist_id and video_id are both required.")
        missing = _require_oauth(client)
        if missing:
            return missing
        action = approvals.propose(
            action_type="playlistItems.insert",
            description=f"Add video {video_id} ({WATCH_URL.format(video_id=video_id)}) to playlist {playlist_id}.",
            quota_cost_units=cost_of("playlistItems.insert"),
            payload={"playlist_id": playlist_id, "video_id": video_id},
        )
        return _pending_payload(action, approvals._ttl)
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


def save_for_later(client: YouTubeClient, approvals: ApprovalStore, video_id: str) -> dict[str, Any]:
    """Propose saving a video to your personal 'Watch Later (via Muse)' playlist.

    NOTE: YouTube's Data API cannot read or modify the *native* Watch Later
    playlist (support removed August 2016 — the API returns
    ``watchLaterNotAccessible``). This tool uses a user-owned playlist of the
    same name as the supported replacement, creating it on first use.

    Returns pending_confirmation. Auth: OAuth (youtube.force-ssl).
    Quota on confirm: 50 (up to 100 if the playlist must be created first).
    A small read (1 unit/page) is spent now to locate the playlist.
    """
    try:
        if not video_id or not video_id.strip():
            return _invalid_input("video_id is required.")
        video_id = video_id.strip()
        missing = _require_oauth(client)
        if missing:
            return missing
        items, pages = client.list_all(
            "/playlists",
            params={"part": "snippet", "mine": "true", "maxResults": 50},
            auth="oauth",
            max_pages=10,
        )
        existing = next(
            (p for p in items if (p.get("snippet") or {}).get("title") == SAVE_FOR_LATER_PLAYLIST_TITLE),
            None,
        )
        if existing:
            payload: dict[str, Any] = {
                "playlist_id": existing.get("id"),
                "video_id": video_id,
                "create_playlist": False,
            }
            quota = cost_of("playlistItems.insert")
            description = (
                f"Save video {video_id} ({WATCH_URL.format(video_id=video_id)}) to your "
                f"'{SAVE_FOR_LATER_PLAYLIST_TITLE}' playlist "
                f"({PLAYLIST_URL.format(playlist_id=existing.get('id'))}). "
                "Note: this is a personal playlist acting as Watch Later, because "
                "YouTube's API cannot modify the native Watch Later list."
            )
        else:
            payload = {"video_id": video_id, "create_playlist": True}
            quota = cost_of("playlists.insert") + cost_of("playlistItems.insert")
            description = (
                f"Create private playlist '{SAVE_FOR_LATER_PLAYLIST_TITLE}' and save video "
                f"{video_id} ({WATCH_URL.format(video_id=video_id)}) to it. "
                "Note: this personal playlist acts as Watch Later, because "
                "YouTube's API cannot modify the native Watch Later list."
            )
        action = approvals.propose(
            action_type="save_for_later",
            description=description,
            quota_cost_units=quota,
            payload=payload,
        )
        response = _pending_payload(action, approvals._ttl)
        response["quota_spent_locating_playlist"] = pages * cost_of("playlists.list")
        return response
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


def remove_from_playlist(
    client: YouTubeClient,
    approvals: ApprovalStore,
    playlist_item_id: str,
) -> dict[str, Any]:
    """Propose removing an item from a playlist.

    ``playlist_item_id`` is the playlistItem ID (from playlistItems.list), not the
    video ID. Returns pending_confirmation. Auth: OAuth. Quota on confirm: 50.
    """
    try:
        if not playlist_item_id:
            return _invalid_input("playlist_item_id is required.")
        missing = _require_oauth(client)
        if missing:
            return missing
        action = approvals.propose(
            action_type="playlistItems.delete",
            description=f"Remove item {playlist_item_id} from its YouTube playlist.",
            quota_cost_units=cost_of("playlistItems.delete"),
            payload={"playlist_item_id": playlist_item_id},
        )
        return _pending_payload(action, approvals._ttl)
    except Exception as exc:  # noqa: BLE001
        return _error_response(exc)


# ---------------------------------------------------------------------------
# approval resolution
# ---------------------------------------------------------------------------

def _execute_playlists_insert(client: YouTubeClient, payload: dict[str, Any]) -> dict[str, Any]:
    data = client.post(
        "/playlists",
        params={"part": "snippet,status"},
        json={
            "snippet": {"title": payload["title"], "description": payload.get("description", "")},
            "status": {"privacyStatus": payload.get("privacy_status", "private")},
        },
        auth="oauth",
    )
    playlist_id = data.get("id", "")
    return {
        "playlist_id": playlist_id,
        "title": (data.get("snippet") or {}).get("title"),
        "url": PLAYLIST_URL.format(playlist_id=playlist_id),
    }


def _execute_playlist_items_insert(client: YouTubeClient, playlist_id: str, video_id: str) -> dict[str, Any]:
    data = client.post(
        "/playlistItems",
        params={"part": "snippet"},
        json={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
        auth="oauth",
    )
    return {
        "playlist_item_id": data.get("id"),
        "playlist_id": playlist_id,
        "video_id": video_id,
    }


def _execute_action(client: YouTubeClient, action: PendingAction) -> dict[str, Any]:
    payload = action.payload
    if action.action_type == "playlists.insert":
        return _execute_playlists_insert(client, payload)
    if action.action_type == "playlistItems.insert":
        return _execute_playlist_items_insert(client, payload["playlist_id"], payload["video_id"])
    if action.action_type == "playlistItems.delete":
        client.delete("/playlistItems", params={"id": payload["playlist_item_id"]}, auth="oauth")
        return {"deleted": True, "playlist_item_id": payload["playlist_item_id"]}
    if action.action_type == "save_for_later":
        steps: list[dict[str, Any]] = []
        playlist_id = payload.get("playlist_id")
        if payload.get("create_playlist") or not playlist_id:
            created = _execute_playlists_insert(
                client,
                {
                    "title": SAVE_FOR_LATER_PLAYLIST_TITLE,
                    "description": SAVE_FOR_LATER_PLAYLIST_DESCRIPTION,
                    "privacy_status": "private",
                },
            )
            playlist_id = created["playlist_id"]
            steps.append({"step": "playlists.insert", "result": created})
        added = _execute_playlist_items_insert(client, playlist_id, payload["video_id"])
        steps.append({"step": "playlistItems.insert", "result": added})
        return {"playlist_id": playlist_id, "video_id": payload["video_id"], "steps": steps}
    raise YouTubeConnectorError(f"Unknown action type: {action.action_type}")


def confirm_action(
    client: YouTubeClient, approvals: ApprovalStore, confirmation_token: str
) -> dict[str, Any]:
    """Execute a previously proposed write action. Tokens are single-use and expire."""
    action = approvals.consume(confirmation_token or "")
    if action is None:
        return {
            "status": "error",
            "error_type": "invalid_or_expired_token",
            "message": "Confirmation token is unknown or has expired. Propose the action again.",
            "hint": None,
        }
    try:
        result = _execute_action(client, action)
    except Exception as exc:  # noqa: BLE001 - token already consumed; surface the failure
        response = _error_response(exc)
        response["action"] = {"type": action.action_type, "description": action.description}
        return response
    return {
        "status": "ok",
        "action": {
            "type": action.action_type,
            "description": action.description,
            "quota_cost_units": action.quota_cost_units,
        },
        "data": result,
    }


def cancel_action(approvals: ApprovalStore, confirmation_token: str) -> dict[str, Any]:
    """Discard a pending write action without executing it."""
    cancelled = approvals.cancel(confirmation_token or "")
    return {
        "status": "ok",
        "cancelled": cancelled,
        "message": "Pending action cancelled." if cancelled else "No such pending action (unknown or expired token).",
    }
