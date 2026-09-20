"""Muse YouTube connector — MCP server over streamable HTTP.

Run:
    python -m youtube_mcp.server
(or ``youtube-mcp`` after install). Muse connects to
``http://<host>:<port>/mcp`` with a streamable-HTTP MCP client.

Credentials are never hard-coded: the server reads YOUTUBE_API_KEY /
YOUTUBE_OAUTH_TOKEN from the environment, and Muse's own credential flow
supplies them at connect time.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import tools as yt
from .approvals import ApprovalStore
from .client import YouTubeClient
from .config import Settings

settings = Settings.from_env()
_client = YouTubeClient(settings)
_approvals = ApprovalStore(ttl_seconds=settings.approval_ttl_seconds)

mcp = FastMCP(
    "youtube-connector",
    host=settings.host,
    port=settings.port,
    instructions=(
        "YouTube connector: search public videos, read your subscriptions and "
        "playlists, build a 'catch me up' digest of recent uploads, and manage "
        "playlists. Write actions (create_playlist, add_to_playlist, "
        "save_for_later, remove_from_playlist) never execute directly — they "
        "return a pending_confirmation payload. Surface the action description "
        "to the user and call confirm_action only after they approve."
    ),
)

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


@mcp.tool(annotations=READ)
def search_videos(query: str, max_results: int = 10, order: str = "relevance") -> dict:
    """Search public YouTube videos by keyword.

    Auth: API key only. Costs 100 quota units per call — prefer get_video_details
    (1 unit) when you already know video IDs.
    """
    return yt.search_videos(_client, query, max_results=max_results, order=order)


@mcp.tool(annotations=READ)
def my_subscriptions(max_results: int = 50) -> dict:
    """List the channels the user is subscribed to. Auth: OAuth (youtube.readonly). Costs 1 unit per page."""
    return yt.my_subscriptions(_client, max_results=max_results)


@mcp.tool(annotations=READ)
def catch_me_up(since_days: int = 7, max_channels: int = 50, max_videos_per_channel: int = 5) -> dict:
    """Digest of recent uploads from the user's subscriptions, newest first.

    Quota-efficient (~1 unit per channel checked; never uses search).
    Auth: OAuth (youtube.readonly).
    """
    return yt.catch_me_up(
        _client,
        since_days=since_days,
        max_channels=max_channels,
        max_videos_per_channel=max_videos_per_channel,
    )


@mcp.tool(annotations=READ)
def get_video_details(video_ids: list[str]) -> dict:
    """Title, channel, stats and duration for up to 50 videos in one call.

    Auth: API key only. Costs 1 unit total.
    """
    return yt.get_video_details(_client, video_ids)


@mcp.tool(annotations=READ)
def my_playlists(max_results: int = 25) -> dict:
    """List the user's own playlists. Auth: OAuth (youtube.readonly). Costs 1 unit per page."""
    return yt.my_playlists(_client, max_results=max_results)


@mcp.tool(annotations=WRITE)
def create_playlist(title: str, description: str = "", privacy_status: str = "private") -> dict:
    """Propose creating a YouTube playlist. APPROVAL-GATED: returns a
    pending_confirmation payload; nothing is created until confirm_action is
    called with the token. Auth: OAuth (youtube.force-ssl). Costs 50 units on confirm."""
    return yt.create_playlist(_client, _approvals, title, description=description, privacy_status=privacy_status)


@mcp.tool(annotations=WRITE)
def add_to_playlist(playlist_id: str, video_id: str) -> dict:
    """Propose adding a video to one of the user's playlists. APPROVAL-GATED:
    returns pending_confirmation; call confirm_action after user approval.
    Auth: OAuth (youtube.force-ssl). Costs 50 units on confirm."""
    return yt.add_to_playlist(_client, _approvals, playlist_id, video_id)


@mcp.tool(annotations=WRITE)
def save_for_later(video_id: str) -> dict:
    """Propose saving a video to the user's 'Watch Later (via Muse)' playlist.

    NOTE: YouTube's API cannot touch the native Watch Later playlist, so this
    uses a personal playlist as the supported replacement (created on first use).
    APPROVAL-GATED: returns pending_confirmation. Auth: OAuth (youtube.force-ssl).
    Costs 50 units on confirm (100 if the playlist must be created first).
    """
    return yt.save_for_later(_client, _approvals, video_id)


@mcp.tool(annotations=WRITE)
def remove_from_playlist(playlist_item_id: str) -> dict:
    """Propose removing an item from a playlist (playlistItem ID, not video ID).
    APPROVAL-GATED: returns pending_confirmation. Auth: OAuth (youtube.force-ssl).
    Costs 50 units on confirm."""
    return yt.remove_from_playlist(_client, _approvals, playlist_item_id)


@mcp.tool(annotations=WRITE)
def confirm_action(confirmation_token: str) -> dict:
    """Execute a previously approved pending action. Tokens are single-use and expire."""
    return yt.confirm_action(_client, _approvals, confirmation_token)


@mcp.tool(annotations=WRITE)
def cancel_action(confirmation_token: str) -> dict:
    """Discard a pending action without executing it."""
    return yt.cancel_action(_approvals, confirmation_token)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
