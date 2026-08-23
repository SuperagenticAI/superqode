"""Best-effort request limits for the hosted A2A agent.

Counters live in memory, which means they reset when the process restarts or
an idle instance spins down. That is a deliberate trade rather than an
oversight: the alternative is a database on the request path, and the spend
behind a single query does not justify one. What these limits are for is
bounding a burst and a bad day, not metering to the request.

Two independent ceilings apply. A per-caller window stops one client
monopolising a small instance, and a global daily ceiling bounds the total
even if per-caller accounting has a gap. The global one exists precisely
because the per-caller one will eventually be wrong.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

#: Stop tracking callers once the table reaches this size, so a flood of
#: distinct addresses cannot grow it without bound.  Expired windows are
#: pruned first; only a genuinely large burst of live callers hits the cap.
MAX_TRACKED_CALLERS = 20_000


@dataclass(frozen=True)
class LimitDecision:
    """Whether a request may proceed under the configured limits."""

    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0
    scope: str = ""


@dataclass
class _Window:
    count: int = 0
    resets_at: float = 0.0


@dataclass
class RateLimitPolicy:
    """Per-tier request ceilings."""

    #: Requests per minute for a caller with no credential.
    anonymous_per_minute: int = 10
    #: Requests per minute for a caller presenting a valid key.
    keyed_per_minute: int = 60
    #: Requests per day across every caller. Zero disables the ceiling.
    global_per_day: int = 5_000
    #: Tiers exempt from per-caller limits. The operator credential is a
    #: break-glass path and should not be throttled by its own service.
    exempt_tiers: frozenset[str] = field(default_factory=lambda: frozenset({"operator"}))

    def per_minute_for(self, tier: str) -> int:
        if tier in self.exempt_tiers:
            return 0
        return self.anonymous_per_minute if tier == "anonymous" else self.keyed_per_minute


class RateLimiter:
    """Fixed-window counters, safe to share across request handlers."""

    def __init__(self, policy: RateLimitPolicy | None = None) -> None:
        self.policy = policy or RateLimitPolicy()
        self._callers: dict[str, _Window] = {}
        self._global = _Window()
        self._lock = threading.Lock()

    def check(self, identity: str, tier: str, *, now: float | None = None) -> LimitDecision:
        """Record a request and say whether it may proceed."""
        moment = now if now is not None else time.monotonic()

        with self._lock:
            global_limit = self.policy.global_per_day
            if global_limit > 0:
                decision = self._consume(self._global, global_limit, 86400, moment, "global")
                if not decision.allowed:
                    return decision

            per_minute = self.policy.per_minute_for(tier)
            if per_minute <= 0:
                return LimitDecision(True, scope="exempt")

            self._prune(moment)
            window = self._callers.get(identity)
            if window is None:
                if len(self._callers) >= MAX_TRACKED_CALLERS:
                    # Table is full of live callers. Allow rather than refuse:
                    # the global ceiling is still holding the real line, and
                    # refusing here would punish whoever arrived last.
                    return LimitDecision(True, scope="untracked")
                window = _Window()
                self._callers[identity] = window
            return self._consume(window, per_minute, 60, moment, "caller")

    def _consume(
        self, window: _Window, limit: int, seconds: int, moment: float, scope: str
    ) -> LimitDecision:
        if moment >= window.resets_at:
            window.count = 0
            window.resets_at = moment + seconds
        if window.count >= limit:
            return LimitDecision(
                False,
                reason=(
                    f"{'daily' if scope == 'global' else 'per-minute'} limit of "
                    f"{limit} requests reached"
                ),
                retry_after_seconds=max(1, int(window.resets_at - moment)),
                scope=scope,
            )
        window.count += 1
        return LimitDecision(True, scope=scope)

    def _prune(self, moment: float) -> None:
        """Drop windows that have already reset."""
        if len(self._callers) < 1_000:
            return
        stale = [key for key, window in self._callers.items() if moment >= window.resets_at]
        for key in stale:
            del self._callers[key]

    def snapshot(self) -> dict[str, int]:
        """Current counters, for a health endpoint."""
        with self._lock:
            return {
                "tracked_callers": len(self._callers),
                "global_requests_in_window": self._global.count,
            }


def caller_identity(key_id: str, client_host: str | None, forwarded_for: str | None) -> str:
    """Identify a caller for rate limiting.

    A key identifies its holder exactly, so it is preferred. Otherwise fall
    back to the address, reading the proxy header first because the hosted
    agent sits behind one and the socket address would be the proxy for every
    caller. The header is client-supplied and therefore weak, which is
    acceptable here: it shapes traffic rather than granting access, and the
    global ceiling covers the case where someone forges it.
    """
    if key_id:
        return f"key:{key_id}"
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return f"ip:{first}"
    return f"ip:{client_host or 'unknown'}"
