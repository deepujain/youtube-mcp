# YouTube Connector for Meta Muse

An MCP server (streamable HTTP) that connects Muse to the **YouTube Data API v3**:
search videos, read subscriptions and playlists, build a *"catch me up"*
digest of recent uploads, and manage playlists — with every write gated behind
an explicit approval step.

## How it works

Muse connects to this server's streamable-HTTP endpoint (`/mcp`) with its own
MCP client. Credentials are **never hard-coded**: the server reads
`YOUTUBE_API_KEY` / `YOUTUBE_OAUTH_TOKEN` from the environment, and in
production Muse's secure credential flow supplies them at connect time (the
agent itself only ever holds a surrogate token).

**Auth split** (mirrors the YouTube API itself):

| Tool kind | Credential | Why |
|---|---|---|
| Public reads (`search_videos`, `get_video_details`) | API key | Public data needs no user identity |
| Private reads (`my_subscriptions`, `my_playlists`, `catch_me_up`) | OAuth 2.0 user token | `mine=true` calls are per-user |
| All writes | OAuth 2.0 user token | Every mutation requires authorization |

**Approval gating:** write tools (`create_playlist`, `add_to_playlist`,
`save_for_later`, `remove_from_playlist`) **never execute directly**. They
return a `pending_confirmation` payload with a single-use, expiring token
(default 600 s). The agent surfaces the action description to the user; on
approval it calls `confirm_action` with the token, which executes exactly
once. `cancel_action` discards a pending action. This maps 1:1 onto Muse's
approval cards.

**Known API limitation:** YouTube's Data API cannot read or modify the
*native* Watch Later playlist (support removed August 2016; the API returns
`watchLaterNotAccessible`). `save_for_later` therefore uses a user-owned
playlist named **"Watch Later (via Muse)"** as the supported replacement,
creating it on first use.

## Setup

You need a Google Cloud project. Do **not** create anything from this repo —
these are manual steps in your own Google account:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create
   (or pick) a project.
2. **APIs & Services → Library** → search **"YouTube Data API v3"** → **Enable**.
3. **APIs & Services → Credentials → Create Credentials → API key** — for
   public reads. (Optional: restrict the key to the YouTube Data API v3.)
4. **OAuth consent screen** → user type **External** → fill app name, support
   email, developer contact → add scopes:
   - `https://www.googleapis.com/auth/youtube.readonly`
   - `https://www.googleapis.com/auth/youtube.force-ssl`
   
   > Tip: publish the consent screen to **Production**. Apps left in
   > *Testing* issue refresh tokens that expire after 7 days.
5. **Create Credentials → OAuth client ID** → type **Desktop app** (personal
   use) → run Google's OAuth flow once and capture an **access token**.
6. Copy `.env.example` to `.env` and fill in the values:
   - `YOUTUBE_API_KEY` — public reads
   - `YOUTUBE_OAUTH_TOKEN` — private reads + writes (refresh when it expires)
   - `YOUTUBE_HOST` / `YOUTUBE_PORT` — bind address (default `127.0.0.1:8000`)
   - `YOUTUBE_APPROVAL_TTL_SECONDS` — approval window (default `600`)
   - `YOUTUBE_HTTP_PROXY` / `YOUTUBE_HTTPS_PROXY` — only if your host needs an
     explicit egress proxy (ambient proxy env vars are intentionally ignored)

No billing account is needed: the API is free within the daily quota below.

## Quota budget

Default project quota: **10,000 units/day**, resetting at **midnight Pacific**.
Costs are per call (each result page costs the full amount again).

| Tool | API call(s) | Units |
|---|---|---|
| `search_videos` | `search.list` | **100** |
| `my_subscriptions` | `subscriptions.list` | 1 / page |
| `my_playlists` | `playlists.list` | 1 / page |
| `get_video_details` | `videos.list` (≤50 IDs batched) | **1** |
| `catch_me_up` | `subscriptions.list` + `channels.list` batch + `playlistItems.list` per channel | ≈ 2 + #channels |
| `create_playlist` (on confirm) | `playlists.insert` | **50** |
| `add_to_playlist` (on confirm) | `playlistItems.insert` | **50** |
| `remove_from_playlist` (on confirm) | `playlistItems.delete` | **50** |
| `save_for_later` (on confirm) | `playlistItems.insert` (+ `playlists.insert` first time) | 50 (100 first time) |

**Example daily budget:** 5 searches (500) + 3 digests over 40 subscriptions
(~126) + 20 detail lookups (20) + 10 playlist writes (500) ≈ **1,150 units** —
about 11% of the free quota. Design rule used throughout: never call
`search.list` when `videos.list`/`playlistItems.list` can answer the question.

On `quotaExceeded` (HTTP 403) every tool returns a structured
`quota_exceeded` error telling the user when the quota resets.

## Run the server

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then fill in your keys
.venv/bin/python -m youtube_mcp.server
# Muse connects to http://127.0.0.1:8000/mcp
```

## Run the tests

```bash
.venv/bin/python -m pytest -q            # unit tests (mocked HTTP): 71 tests
.venv/bin/python -m pytest -q -m integration \
  # integration tests against the real API (reads only, ~110 units):
YOUTUBE_API_KEY=... YOUTUBE_OAUTH_TOKEN=... .venv/bin/python -m pytest -m integration
```

Integration tests are skipped automatically when credentials are absent.
Write-path tests run against mocks only — real writes are exercised manually
through the propose → approve → `confirm_action` flow.

## Project layout

```
src/youtube_mcp/
  config.py     # env-var settings (no secrets in code)
  errors.py     # typed errors: auth, quota, not-found, API
  client.py     # httpx client: key/OAuth injection, error mapping, pagination
  quota.py      # quota cost table + daily budget
  approvals.py  # single-use expiring tokens for write approvals
  tools.py      # the 11 tool implementations (pure, fully tested)
  server.py     # FastMCP wiring → streamable HTTP
tests/
  test_client.py       # auth headers, error mapping, pagination
  test_approvals.py    # TTL, single-use, cancel
  test_tools.py        # every tool: happy path, errors, auth/quota, empty, paging
  test_integration.py  # real API, reads only, skipped without credentials
```

## Example prompts (for the Muse connector submission form)

1. "Catch me up on my subscriptions from this week — what did I miss?"
2. "Find me a video under 20 minutes that explains how sourdough starter works."
3. "Save this video for later: https://www.youtube.com/watch?v=…"
4. "What are the three most-viewed uploads from Marques Brownlee this month, and how long is each?"
5. "Make a private playlist called 'Weekend cooking' and add the pasta video you found yesterday."
