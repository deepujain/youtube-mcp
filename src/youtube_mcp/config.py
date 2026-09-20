"""Environment-based configuration. Secrets are never hard-coded anywhere."""
from __future__ import annotations

import os
from dataclasses import dataclass

BASE_URL = "https://www.googleapis.com/youtube/v3"

# YouTube's Data API cannot read or modify the native Watch Later playlist
# (deprecated August 2016; playlistItems.list returns watchLaterNotAccessible).
# save_for_later() therefore uses this user-owned playlist as the replacement.
SAVE_FOR_LATER_PLAYLIST_TITLE = "Watch Later (via Muse)"
SAVE_FOR_LATER_PLAYLIST_DESCRIPTION = (
    "Videos saved via the Muse YouTube connector. "
    "Note: YouTube's Data API does not allow third-party apps to read or "
    "modify the native Watch Later playlist, so this playlist acts as its replacement."
)


@dataclass(frozen=True)
class Settings:
    """All runtime configuration, sourced from environment variables."""

    api_key: str | None = None
    oauth_token: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    approval_ttl_seconds: int = 600
    http_proxy: str | None = None
    https_proxy: str | None = None

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        src = env if env is not None else os.environ

        def _int(key: str, default: int) -> int:
            try:
                return int(src.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        return cls(
            api_key=src.get("YOUTUBE_API_KEY") or None,
            oauth_token=src.get("YOUTUBE_OAUTH_TOKEN") or None,
            host=src.get("YOUTUBE_HOST", "127.0.0.1") or "127.0.0.1",
            port=_int("YOUTUBE_PORT", 8000),
            approval_ttl_seconds=_int("YOUTUBE_APPROVAL_TTL_SECONDS", 600),
            http_proxy=src.get("YOUTUBE_HTTP_PROXY") or None,
            https_proxy=src.get("YOUTUBE_HTTPS_PROXY") or None,
        )
