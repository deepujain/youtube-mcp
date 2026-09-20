# DRAFT — Privacy Policy: 1xAI Connectors (YouTube)

> Status: draft for review. Intended to be published at 1xaispark.com/connectors/privacy.
> Placeholders in [BRACKETS] must be filled before publishing.

**Effective date:** 2026-09-20
**Controller:** 1xAI, onexai.inc@gmail.com

## What this connector does

The 1xAI YouTube Connector is an MCP (Model Context Protocol) server that lets
AI assistants you authorize (e.g. Meta Muse) call the YouTube Data API v3 on
your behalf: searching public videos, reading your subscriptions and playlists,
building "catch me up" digests, and managing your playlists with your explicit
approval.

## Data we handle

- **Google OAuth tokens.** Private reads (subscriptions, playlists) and all
  writes require your Google account authorization. Tokens are supplied at
  connect time through your AI client's secure credential flow. We do not
  display, log, or export token values, and we never ask for them in chat or
  email.
- **YouTube API key.** Used only for public reads (search, video details). It
  lives in server-side configuration, never in client-visible output.
- **Your requests and results.** Search queries, video IDs, and playlist names
  you ask about are transmitted to Google's YouTube Data API v3 to fulfill the
  request. We do not build profiles, sell data, or use your activity for
  advertising.
- **Pending-action tokens.** Write actions (create playlist, add/remove videos)
  are held as short-lived, single-use confirmation tokens (default 10 minutes)
  until you approve them. Unapproved actions are discarded, never executed.

## Google API Services User Data Policy

Our use and transfer of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements: data is used only to provide the
connector features you invoked, never for advertising, and never sold.

## Retention

We retain no personal data beyond what is needed to serve an in-flight request.
OAuth tokens are held only for the session / as configured by your AI client's
credential store. Server logs contain operational metadata (timestamps, error
codes), not video content or credentials.

## Your choices

- Revoke the connector's access at any time at
  https://myaccount.google.com/permissions — this immediately stops all
  private reads and writes.
- Contact onexai.inc@gmail.com for access, correction, or deletion requests.

## Changes

We will post material changes to this policy at 1xaispark.com/connectors/privacy
with an updated effective date.
