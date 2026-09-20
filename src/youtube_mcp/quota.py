"""Quota costs for YouTube Data API v3, in units per call.

Source: https://developers.google.com/youtube/v3/determine_quota_cost
Default project quota: 10,000 units/day, resetting at midnight Pacific Time.
"""
from __future__ import annotations

DAILY_QUOTA_UNITS = 10_000

QUOTA_COSTS: dict[str, int] = {
    # Reads
    "search.list": 100,
    "videos.list": 1,
    "channels.list": 1,
    "playlists.list": 1,
    "playlistItems.list": 1,
    "subscriptions.list": 1,
    # Writes
    "playlists.insert": 50,
    "playlists.update": 50,
    "playlists.delete": 50,
    "playlistItems.insert": 50,
    "playlistItems.update": 50,
    "playlistItems.delete": 50,
    "subscriptions.insert": 50,
    "subscriptions.delete": 50,
}


def cost_of(method: str) -> int:
    """Quota units charged for one call of ``method`` (default 1)."""
    return QUOTA_COSTS.get(method, 1)
