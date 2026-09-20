"""Unit tests for the approval store (TTL, single-use tokens, cancel)."""
from __future__ import annotations

from youtube_mcp.approvals import ApprovalStore


def _propose(store, action_type="playlistItems.insert"):
    return store.propose(
        action_type=action_type,
        description="do a thing",
        quota_cost_units=50,
        payload={"video_id": "v1"},
    )


def test_propose_and_get_roundtrip():
    store = ApprovalStore()
    action = _propose(store)
    assert action.token
    assert store.get(action.token) is action


def test_tokens_are_unique():
    store = ApprovalStore()
    tokens = {_propose(store).token for _ in range(50)}
    assert len(tokens) == 50


def test_get_unknown_token_returns_none():
    assert ApprovalStore().get("nope") is None


def test_consume_is_single_use():
    store = ApprovalStore()
    action = _propose(store)
    assert store.consume(action.token) is action
    assert store.consume(action.token) is None
    assert store.get(action.token) is None


def test_consume_unknown_token_returns_none():
    assert ApprovalStore().consume("nope") is None


def test_cancel_removes_action():
    store = ApprovalStore()
    action = _propose(store)
    assert store.cancel(action.token) is True
    assert store.get(action.token) is None


def test_cancel_unknown_token_returns_false():
    assert ApprovalStore().cancel("nope") is False


def test_expired_actions_are_invisible():
    store = ApprovalStore(ttl_seconds=0)  # everything expires immediately
    action = _propose(store)
    assert store.get(action.token) is None
    assert store.consume(action.token) is None


def test_pending_count_purges_expired():
    store = ApprovalStore(ttl_seconds=0)
    _propose(store)
    assert store.pending_count() == 0
    live = ApprovalStore(ttl_seconds=600)
    _propose(live)
    assert live.pending_count() == 1
