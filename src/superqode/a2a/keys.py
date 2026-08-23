"""Stateless, time-boxed API keys for the hosted A2A agent.

A key carries its own claims and is signed with a server secret, so verifying
one is a signature check and a clock comparison. Nothing is stored, which
matters because the hosted agent runs on an instance whose filesystem does not
survive a deploy: a counter kept there would reset on every push, and a quota
that resets is not a quota.

The trade is deliberate. Time-boxing bounds a key's usefulness without needing
to count anything, and the spend behind one query is small enough that
best-effort throttling is the right amount of machinery. Revocation before
expiry uses a deny list supplied by the environment, which is sufficient while
keys are issued one per customer by hand.

Keys look like::

    sqk_live_<base64url(claims)>.<base64url(signature)>

The prefix is deliberate: it makes a leaked key greppable in logs and
recognisable to secret scanners.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

#: Secret used to sign and verify keys. Without it, keyed access is refused
#: rather than allowed: an unsigned key must never be treated as valid.
SECRET_ENV = "SUPERQODE_A2A_KEY_SECRET"

#: Comma-separated key ids that must be rejected before their expiry.
REVOKED_ENV = "SUPERQODE_A2A_REVOKED_KEYS"

LIVE_PREFIX = "sqk_live_"
TEST_PREFIX = "sqk_test_"

#: Claim schema version, so an older key can be rejected cleanly if the shape
#: ever changes.
CLAIMS_VERSION = 1


class KeyMintError(Exception):
    """Raised when a key cannot be minted."""


@dataclass(frozen=True)
class KeyClaims:
    """What a key asserts about its holder."""

    key_id: str
    customer: str
    tier: str
    expires_at: int
    issued_at: int

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def expires_in_days(self) -> float:
        return max(0.0, (self.expires_at - time.time()) / 86400)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": CLAIMS_VERSION,
            "kid": self.key_id,
            "cus": self.customer,
            "tier": self.tier,
            "exp": self.expires_at,
            "iat": self.issued_at,
        }


@dataclass(frozen=True)
class KeyVerdict:
    """The outcome of checking a presented key."""

    valid: bool
    reason: str = ""
    claims: KeyClaims | None = None

    @property
    def tier(self) -> str:
        return self.claims.tier if self.claims else "anonymous"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), sha256).digest()
    return _b64encode(digest)


def resolve_secret(secret: str | None = None) -> str | None:
    """Return the signing secret from an argument or the environment."""
    resolved = (secret if secret is not None else os.environ.get(SECRET_ENV, "")).strip()
    return resolved or None


def revoked_key_ids(raw: str | None = None) -> frozenset[str]:
    """Return key ids that must be rejected regardless of expiry."""
    source = raw if raw is not None else os.environ.get(REVOKED_ENV, "")
    return frozenset(part.strip() for part in source.split(",") if part.strip())


def mint_key(
    customer: str,
    *,
    tier: str = "trial",
    valid_days: int = 30,
    secret: str | None = None,
    live: bool = True,
    now: float | None = None,
) -> tuple[str, KeyClaims]:
    """Mint a signed key. The returned string is never recoverable again."""
    resolved = resolve_secret(secret)
    if resolved is None:
        raise KeyMintError(
            f"No signing secret. Set {SECRET_ENV} to a long random value before issuing keys."
        )
    if not customer.strip():
        raise KeyMintError("A key must name a customer.")
    if valid_days <= 0:
        raise KeyMintError("valid_days must be positive; a key that is already expired is useless.")

    issued = int(now if now is not None else time.time())
    claims = KeyClaims(
        key_id=secrets.token_hex(6),
        customer=customer.strip(),
        tier=tier.strip() or "trial",
        expires_at=issued + valid_days * 86400,
        issued_at=issued,
    )
    payload = _b64encode(
        json.dumps(claims.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    prefix = LIVE_PREFIX if live else TEST_PREFIX
    return f"{prefix}{payload}.{_sign(resolved, payload)}", claims


def verify_key(
    presented: str | None,
    *,
    secret: str | None = None,
    revoked: frozenset[str] | None = None,
    now: float | None = None,
) -> KeyVerdict:
    """Check a presented key without touching any store.

    Returns a verdict rather than raising, because the caller distinguishes
    "no key offered" from "bad key offered" and answers differently.
    """
    if not presented:
        return KeyVerdict(False, "no key presented")

    candidate = presented.strip()
    if not candidate.startswith((LIVE_PREFIX, TEST_PREFIX)):
        return KeyVerdict(False, "unrecognised key format")

    # Both prefixes are the same length today, but stripping by a constant
    # would break silently the moment that stops being true.
    prefix = LIVE_PREFIX if candidate.startswith(LIVE_PREFIX) else TEST_PREFIX
    body = candidate[len(prefix) :]
    payload, separator, signature = body.partition(".")
    if not separator or not payload or not signature:
        return KeyVerdict(False, "malformed key")

    resolved = resolve_secret(secret)
    if resolved is None:
        # Fail closed. Treating a key as valid because the server forgot its
        # secret would turn a misconfiguration into an open door.
        return KeyVerdict(False, "server has no signing secret configured")

    if not hmac.compare_digest(_sign(resolved, payload), signature):
        return KeyVerdict(False, "signature does not match")

    try:
        data = json.loads(_b64decode(payload))
        claims = KeyClaims(
            key_id=str(data["kid"]),
            customer=str(data["cus"]),
            tier=str(data["tier"]),
            expires_at=int(data["exp"]),
            issued_at=int(data["iat"]),
        )
        if int(data.get("v", 0)) != CLAIMS_VERSION:
            return KeyVerdict(False, "unsupported key version")
    except (ValueError, KeyError, TypeError):
        return KeyVerdict(False, "unreadable claims")

    if claims.key_id in (revoked if revoked is not None else revoked_key_ids()):
        return KeyVerdict(False, "key revoked", claims)

    moment = now if now is not None else time.time()
    if moment >= claims.expires_at:
        return KeyVerdict(False, "key expired", claims)

    return KeyVerdict(True, "ok", claims)


def bearer_from_header(header: str | None) -> str | None:
    """Extract the credential from an Authorization header."""
    if not header:
        return None
    scheme, _, value = header.strip().partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


#: Tier recorded for a caller who presented no credential at all.
ANONYMOUS_TIER = "anonymous"

#: Tier recorded for the operator's own static token, which predates signed
#: keys and stays supported so an existing deployment keeps working.
OPERATOR_TIER = "operator"


@dataclass(frozen=True)
class AccessDecision:
    """Whether a request may proceed, and as whom."""

    allowed: bool
    tier: str = ANONYMOUS_TIER
    customer: str = ""
    key_id: str = ""
    reason: str = ""

    @property
    def anonymous(self) -> bool:
        return self.tier == ANONYMOUS_TIER

    def to_state(self) -> dict[str, str]:
        """The shape carried through to the executor."""
        return {
            "tier": self.tier,
            "customer": self.customer,
            "key_id": self.key_id,
        }


def decide_access(
    authorization: str | None,
    *,
    static_token: str | None = None,
    secret: str | None = None,
    allow_anonymous: bool = True,
    revoked: frozenset[str] | None = None,
    now: float | None = None,
) -> AccessDecision:
    """Resolve an Authorization header into an access decision.

    Presenting no credential and presenting a bad one are answered
    differently. The first is an anonymous caller, who may be served a tier
    that costs nothing to answer. The second is someone holding a key that
    does not work, and telling them so is more useful than silently
    downgrading them to anonymous.
    """
    credential = bearer_from_header(authorization)

    if credential is None:
        if allow_anonymous:
            return AccessDecision(True, ANONYMOUS_TIER, reason="no credential presented")
        return AccessDecision(False, ANONYMOUS_TIER, reason="a key is required")

    if static_token and hmac.compare_digest(credential, static_token):
        return AccessDecision(True, OPERATOR_TIER, customer="operator", reason="operator token")

    verdict = verify_key(credential, secret=secret, revoked=revoked, now=now)
    if verdict.valid and verdict.claims is not None:
        return AccessDecision(
            True,
            verdict.claims.tier,
            customer=verdict.claims.customer,
            key_id=verdict.claims.key_id,
            reason="ok",
        )
    return AccessDecision(False, ANONYMOUS_TIER, reason=verdict.reason)
