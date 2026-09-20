"""Thin httpx-based client for YouTube Data API v3.

Auth model (mirrors the API's own split):
  * ``auth="key"``   -> API key sent as the ``key`` query parameter. Sufficient
    for public reads (search, video/channel/playlist details).
  * ``auth="oauth"`` -> OAuth 2.0 user access token sent as a Bearer header.
    Required for private reads (``mine=true``) and for every write.

The transport is injectable so unit tests can run against httpx.MockTransport
without touching the network.
"""
from __future__ import annotations

from typing import Any, Literal

import httpx

from .config import BASE_URL, Settings
from .errors import (
    AuthRequiredError,
    ConfigurationError,
    NotFoundError,
    QuotaExceededError,
    YouTubeAPIError,
    YouTubeConnectorError,
)

AuthMode = Literal["key", "oauth"]

_QUOTA_REASONS = {
    "quotaExceeded",
    "dailyLimitExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "quotaExceededWithRetry",
}


class YouTubeClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        # trust_env=False: never route API calls through ambient proxy env vars
        # (which may be absent, wrong, or unparseable on the host). An egress
        # proxy can still be set explicitly via YOUTUBE_HTTP(S)_PROXY.
        proxy = settings.http_proxy or settings.https_proxy or None
        self._http = httpx.Client(
            base_url=BASE_URL, transport=transport, timeout=30.0,
            trust_env=False, proxy=proxy,
        )

    # -- capability probes (fail fast with a helpful message) ----------------
    @property
    def has_api_key(self) -> bool:
        return bool(self._settings.api_key)

    @property
    def has_oauth(self) -> bool:
        return bool(self._settings.oauth_token)

    # -- low-level request ----------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth: AuthMode = "key",
    ) -> dict[str, Any]:
        params = dict(params or {})
        headers: dict[str, str] = {}
        if auth == "key":
            if not self._settings.api_key:
                raise ConfigurationError(
                    "This tool needs a YouTube API key for public reads. "
                    "Set the YOUTUBE_API_KEY environment variable."
                )
            params["key"] = self._settings.api_key
        else:
            if not self._settings.oauth_token:
                raise AuthRequiredError(
                    "This tool needs the user's YouTube OAuth authorization "
                    "(scopes: youtube.readonly, youtube.force-ssl). "
                    "Complete the OAuth flow and set YOUTUBE_OAUTH_TOKEN."
                )
            headers["Authorization"] = f"Bearer {self._settings.oauth_token}"
        try:
            resp = self._http.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise YouTubeConnectorError(f"Network error calling YouTube API: {exc}") from exc
        return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code < 400:
            return resp.json() if resp.content else {}
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        err = payload.get("error") or {}
        errors = err.get("errors") or []
        reason = errors[0].get("reason", "") if errors else ""
        message = err.get("message") or resp.text[:500]
        status = resp.status_code
        if status == 401:
            raise AuthRequiredError(
                f"YouTube authorization failed ({reason or 'unauthorized'}): {message}. "
                "The OAuth token is missing, expired or revoked — re-run the OAuth flow."
            )
        if status == 403 and reason in _QUOTA_REASONS:
            raise QuotaExceededError(
                f"YouTube API quota exhausted ({reason}): {message}. "
                "The 10,000-units/day project quota resets at midnight Pacific Time."
            )
        if status == 404:
            raise NotFoundError(f"YouTube resource not found ({reason or 'notFound'}): {message}")
        raise YouTubeAPIError(status, reason or "unknown", message)

    # -- convenience verbs ----------------------------------------------------
    def get(self, path: str, *, params: dict[str, Any] | None = None, auth: AuthMode = "key") -> dict[str, Any]:
        return self.request("GET", path, params=params, auth=auth)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth: AuthMode = "oauth",
    ) -> dict[str, Any]:
        return self.request("POST", path, params=params, json=json, auth=auth)

    def delete(self, path: str, *, params: dict[str, Any] | None = None, auth: AuthMode = "oauth") -> dict[str, Any]:
        return self.request("DELETE", path, params=params, auth=auth)

    def list_all(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        auth: AuthMode = "key",
        max_pages: int = 10,
    ) -> tuple[list[dict[str, Any]], int]:
        """Follow ``nextPageToken`` and merge ``items``.

        Returns ``(items, pages_fetched)``. Each page costs one quota unit.
        """
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        pages = 0
        while pages < max_pages:
            page_params = dict(params or {})
            if page_token:
                page_params["pageToken"] = page_token
            data = self.get(path, params=page_params, auth=auth)
            items.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            pages += 1
            if not page_token:
                break
        return items, pages
