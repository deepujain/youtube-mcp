"""Approval-gating for write tools.

Write tools NEVER execute directly. They return a pending-confirmation payload
carrying a single-use, expiring token. The agent surfaces the payload to the
user (e.g. as a Muse approval card); on approval it calls ``confirm_action``
with the token, which executes the stored action exactly once. ``cancel_action``
discards a pending action without executing it.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingAction:
    token: str
    action_type: str  # e.g. "playlistItems.insert" or the composite "save_for_later"
    description: str  # human-readable; shown on the approval card
    quota_cost_units: int  # quota charged when the action executes
    payload: dict[str, Any]  # everything needed to execute the action
    created_at: float = field(default_factory=time.time)


class ApprovalStore:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, PendingAction] = {}

    def propose(
        self,
        *,
        action_type: str,
        description: str,
        quota_cost_units: int,
        payload: dict[str, Any],
    ) -> PendingAction:
        self._purge_expired()
        action = PendingAction(
            token=secrets.token_urlsafe(24),
            action_type=action_type,
            description=description,
            quota_cost_units=quota_cost_units,
            payload=payload,
        )
        self._store[action.token] = action
        return action

    def get(self, token: str) -> PendingAction | None:
        self._purge_expired()
        return self._store.get(token)

    def consume(self, token: str) -> PendingAction | None:
        """Return and remove the action; tokens are single-use."""
        self._purge_expired()
        return self._store.pop(token, None)

    def cancel(self, token: str) -> bool:
        self._purge_expired()
        return self._store.pop(token, None) is not None

    def pending_count(self) -> int:
        self._purge_expired()
        return len(self._store)

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [t for t, a in self._store.items() if now - a.created_at > self._ttl]
        for t in expired:
            del self._store[t]
