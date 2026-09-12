"""Principal-bound A2A context ownership (A2ABreak).

The A2A spec lets a client supply ``contextId`` and does not bind it to a
caller. SuperQode binds each context to the caller principal (API key id,
operator, opaque ``X-SuperQode-Caller-Key``, or per-caller anonymous
isolation) and refuses cross-principal reuse.

This is not the SuperOptiX cookie model. SuperQode already has API keys and
an operator token. Anonymous callers can send an opaque caller key, otherwise
they are isolated by the same address identity used for rate limits.
"""

from __future__ import annotations

from typing import Any

from superqode.a2a.keys import ANONYMOUS_TIER, OPERATOR_TIER
from superqode.a2a.limits import caller_identity

#: Opaque per-caller key for anonymous isolation. Not a SuperOptiX cookie.
CALLER_HEADER = "x-superqode-caller-key"

CONTEXT_OWNERSHIP_MESSAGE = (
    "This contextId is bound to another caller. The A2A spec does not "
    "assign context ownership; SuperQode binds each context to the "
    "caller that created it."
)


class ContextOwnershipError(Exception):
    """Client-supplied contextId belongs to a different principal."""

    def __init__(self, context_id: str) -> None:
        super().__init__(CONTEXT_OWNERSHIP_MESSAGE)
        self.context_id = context_id


class SuperQodeA2AUser:
    """Caller principal presented to the official A2A task store.

    ``user_name`` is the owner key the SDK uses for List, Get, Cancel, and
    Subscribe. Anonymous callers still receive a non-empty name so they are
    not collapsed into one shared bucket.
    """

    def __init__(self, name: str, *, authenticated: bool) -> None:
        self._name = name
        self._authenticated = authenticated

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    @property
    def user_name(self) -> str:
        return self._name


class ContextOwnerStore:
    """In-process map of contextId to the principal that claimed it."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def owner_of(self, context_id: str) -> str | None:
        return self._owners.get(context_id)

    def claim(
        self,
        context_id: str,
        principal: str,
        *,
        stored_owner: str | None = None,
    ) -> None:
        """Bind ``context_id`` to ``principal``, or reject a cross-principal reuse."""
        existing = self._owners.get(context_id) or (stored_owner or "").strip() or None
        if existing:
            self._owners[context_id] = existing
            if existing != principal:
                raise ContextOwnershipError(context_id)
            return
        self._owners[context_id] = principal


def valid_caller_key(value: str) -> bool:
    """Accept a short opaque token, the same shape SuperOptiX uses on the header."""
    if not value or not (8 <= len(value) <= 128):
        return False
    return all(char.isalnum() or char in "-_" for char in value)


def request_principal(decision: Any, request: Any) -> str:
    """Resolve the principal for an HTTP request after access is decided."""
    tier = str(getattr(decision, "tier", "") or ANONYMOUS_TIER)
    key_id = str(getattr(decision, "key_id", "") or "")
    if tier == OPERATOR_TIER:
        return "operator"
    if key_id:
        return f"key:{key_id}"
    header = ""
    try:
        header = (request.headers.get(CALLER_HEADER) or "").strip()
    except AttributeError:
        header = ""
    if valid_caller_key(header):
        return f"caller:{header}"
    host = getattr(getattr(request, "client", None), "host", None)
    try:
        forwarded = request.headers.get("x-forwarded-for")
    except AttributeError:
        forwarded = None
    return caller_identity("", host, forwarded)


def caller_principal(context: Any) -> str:
    """Return the principal recorded on an executor call context."""
    call_context = getattr(context, "call_context", None)
    state = getattr(call_context, "state", None) or {}
    identity = str(state.get("identity") or "").strip()
    if identity:
        return identity
    user = getattr(call_context, "user", None)
    user_name = str(getattr(user, "user_name", "") or "").strip()
    if user_name:
        return user_name
    key_id = str(state.get("key_id") or "").strip()
    if key_id:
        return f"key:{key_id}"
    tier = str(state.get("tier") or ANONYMOUS_TIER)
    if tier == OPERATOR_TIER:
        return "operator"
    return "anonymous:unknown"
