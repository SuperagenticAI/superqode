"""Tests for stateless A2A API keys.

The security-relevant cases are the point of this file: a key must not verify
when it was signed with a different secret, when its claims were edited, when
it has expired, or when the server has no secret at all.
"""

from __future__ import annotations

import time

import pytest

from superqode.a2a.keys import (
    KeyMintError,
    bearer_from_header,
    mint_key,
    revoked_key_ids,
    verify_key,
)

SECRET = "a-long-random-signing-secret"
OTHER_SECRET = "a-different-signing-secret"


def test_a_minted_key_verifies_and_carries_its_claims():
    key, claims = mint_key("Acme Corp", tier="one-off", valid_days=30, secret=SECRET)
    assert key.startswith("sqk_live_")

    verdict = verify_key(key, secret=SECRET, revoked=frozenset())
    assert verdict.valid
    assert verdict.claims is not None
    assert verdict.claims.customer == "Acme Corp"
    assert verdict.claims.tier == "one-off"
    assert verdict.claims.key_id == claims.key_id
    assert verdict.tier == "one-off"


def test_a_key_signed_with_another_secret_is_rejected():
    key, _ = mint_key("Acme", secret=OTHER_SECRET)
    verdict = verify_key(key, secret=SECRET, revoked=frozenset())
    assert not verdict.valid
    assert verdict.reason == "signature does not match"


def test_edited_claims_are_rejected():
    """The claims are readable by anyone, so they must not be trustable.

    A holder can decode their own key and see the tier and expiry. Editing
    either must invalidate the signature rather than grant an upgrade.
    """
    import base64
    import json

    key, _ = mint_key("Acme", tier="trial", valid_days=1, secret=SECRET)
    payload, _, signature = key.removeprefix("sqk_live_").partition(".")

    decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
    decoded["tier"] = "enterprise"
    decoded["exp"] = int(time.time()) + 10_000_000
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps(decoded, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )

    forged = f"sqk_live_{forged_payload}.{signature}"
    verdict = verify_key(forged, secret=SECRET, revoked=frozenset())
    assert not verdict.valid
    assert verdict.reason == "signature does not match"


def test_an_expired_key_is_rejected():
    past = time.time() - 40 * 86400
    key, _ = mint_key("Acme", valid_days=30, secret=SECRET, now=past)
    verdict = verify_key(key, secret=SECRET, revoked=frozenset())
    assert not verdict.valid
    assert verdict.reason == "key expired"
    # The claims still come back, so a caller can say who it belonged to.
    assert verdict.claims is not None
    assert verdict.claims.customer == "Acme"


def test_a_revoked_key_is_rejected_before_it_expires():
    key, claims = mint_key("Acme", valid_days=30, secret=SECRET)
    verdict = verify_key(key, secret=SECRET, revoked=frozenset({claims.key_id}))
    assert not verdict.valid
    assert verdict.reason == "key revoked"


def test_verification_fails_closed_when_the_server_has_no_secret():
    """A missing secret must not be read as "nothing to check"."""
    key, _ = mint_key("Acme", secret=SECRET)
    verdict = verify_key(key, secret="", revoked=frozenset())
    assert not verdict.valid
    assert "no signing secret" in verdict.reason


def test_malformed_and_absent_keys_are_distinguished():
    assert verify_key(None, secret=SECRET, revoked=frozenset()).reason == "no key presented"
    assert verify_key("", secret=SECRET, revoked=frozenset()).reason == "no key presented"
    assert (
        verify_key("not-a-key", secret=SECRET, revoked=frozenset()).reason
        == "unrecognised key format"
    )
    assert verify_key("sqk_live_only", secret=SECRET, revoked=frozenset()).reason == "malformed key"
    assert (
        verify_key("sqk_live_$$$.$$$", secret=SECRET, revoked=frozenset()).reason
        == "signature does not match"
    )


def test_minting_requires_a_secret_and_a_customer():
    with pytest.raises(KeyMintError, match="signing secret"):
        mint_key("Acme", secret="")
    with pytest.raises(KeyMintError, match="name a customer"):
        mint_key("   ", secret=SECRET)
    with pytest.raises(KeyMintError, match="valid_days"):
        mint_key("Acme", valid_days=0, secret=SECRET)


def test_two_keys_for_the_same_customer_are_distinct():
    first, first_claims = mint_key("Acme", secret=SECRET)
    second, second_claims = mint_key("Acme", secret=SECRET)
    assert first != second
    assert first_claims.key_id != second_claims.key_id


def test_revocation_list_parsing():
    assert revoked_key_ids("") == frozenset()
    assert revoked_key_ids("abc, def ,, ghi") == frozenset({"abc", "def", "ghi"})


def test_bearer_header_parsing():
    assert bearer_from_header("Bearer sqk_live_x") == "sqk_live_x"
    assert bearer_from_header("bearer sqk_live_x") == "sqk_live_x"
    assert bearer_from_header("Basic abc") is None
    assert bearer_from_header("Bearer") is None
    assert bearer_from_header(None) is None
