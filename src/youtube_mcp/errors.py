"""Typed errors for the YouTube connector."""
from __future__ import annotations


class YouTubeConnectorError(Exception):
    """Base class for all connector errors."""


class ConfigurationError(YouTubeConnectorError):
    """Server misconfigured (e.g. API key missing for a key-authed tool)."""


class AuthRequiredError(YouTubeConnectorError):
    """Call needs user OAuth authorization (missing, expired or invalid token)."""


class QuotaExceededError(YouTubeConnectorError):
    """The Cloud project's daily YouTube Data API v3 quota is exhausted."""


class NotFoundError(YouTubeConnectorError):
    """The requested resource does not exist."""


class YouTubeAPIError(YouTubeConnectorError):
    """A generic YouTube Data API error."""

    def __init__(self, status_code: int, reason: str, message: str) -> None:
        super().__init__(f"YouTube API error {status_code} ({reason}): {message}")
        self.status_code = status_code
        self.reason = reason
        self.message = message
