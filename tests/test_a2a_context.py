"""Principal-bound A2A contextId ownership (A2ABreak)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from superqode.a2a.context import (
    CONTEXT_OWNERSHIP_MESSAGE,
    ContextOwnerStore,
    ContextOwnershipError,
    caller_principal,
    request_principal,
    valid_caller_key,
)
from superqode.a2a.keys import AccessDecision, OPERATOR_TIER


def test_same_principal_can_reuse_a_context():
    store = ContextOwnerStore()
    store.claim("ctx-1", "key:alice")
    store.claim("ctx-1", "key:alice")
    assert store.owner_of("ctx-1") == "key:alice"


def test_cross_principal_reuse_is_rejected():
    store = ContextOwnerStore()
    store.claim("ctx-1", "key:alice")
    with pytest.raises(ContextOwnershipError, match="bound to another caller") as raised:
        store.claim("ctx-1", "key:bob")
    assert str(raised.value) == CONTEXT_OWNERSHIP_MESSAGE
    assert raised.value.context_id == "ctx-1"


def test_stored_owner_is_enforced_after_restart():
    store = ContextOwnerStore()
    with pytest.raises(ContextOwnershipError):
        store.claim("ctx-1", "key:bob", stored_owner="key:alice")
    store.claim("ctx-1", "key:alice", stored_owner="key:alice")
    assert store.owner_of("ctx-1") == "key:alice"


def test_request_principal_prefers_key_then_opaque_caller(monkeypatch):
    request = SimpleNamespace(
        headers={"x-superqode-caller-key": "alice-key-01", "x-forwarded-for": "1.2.3.4"},
        client=SimpleNamespace(host="testclient"),
    )
    keyed = AccessDecision(True, "standard", key_id="abc123")
    assert request_principal(keyed, request) == "key:abc123"
    operator = AccessDecision(True, OPERATOR_TIER, customer="operator")
    assert request_principal(operator, request) == "operator"
    anonymous = AccessDecision(True, "anonymous")
    assert request_principal(anonymous, request) == "caller:alice-key-01"
    bare = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.8"))
    assert request_principal(anonymous, bare) == "ip:10.0.0.8"


def test_caller_principal_reads_call_context_identity():
    context = SimpleNamespace(
        call_context=SimpleNamespace(state={"identity": "key:abc", "tier": "standard"})
    )
    assert caller_principal(context) == "key:abc"


def test_valid_caller_key_matches_superoptix_shape():
    assert valid_caller_key("alice-key-01")
    assert not valid_caller_key("short")
    assert not valid_caller_key("bad key!!")
