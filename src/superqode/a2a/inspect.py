"""A short trace of how SuperQode read an Agent Card and spoke to it.

The tester needs three things a status line cannot hold: which binding was
chosen, what went on the wire, and why a card was refused. Events are
summaries plus a clipped detail dict. Authorization headers are stripped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BODY_LIMIT = 800

_REDACT_HEADERS = frozenset({"authorization", "x-api-key", "cookie", "set-cookie"})
_REDACT_PARTS = ("authorization", "api-key", "apikey", "secret", "token", "password")


@dataclass
class InspectEvent:
    """One step in a connect or send."""

    kind: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "summary": self.summary}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class InspectLog:
    """Ordered events from one A2AClient."""

    def __init__(self) -> None:
        self.events: list[InspectEvent] = []

    def add(self, kind: str, summary: str, **detail: Any) -> InspectEvent:
        cleaned = {key: value for key, value in detail.items() if value not in (None, "", {}, [])}
        event = InspectEvent(kind=kind, summary=summary, detail=cleaned)
        self.events.append(event)
        return event

    def request(
        self,
        method: str,
        url: str,
        *,
        note: str = "",
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        suffix = f"  {note}" if note else ""
        safe_url = redact_url(url)
        self.add(
            "request",
            f"{method} {safe_url}{suffix}",
            body=clip(redact_text(body)),
            headers=redact_headers(headers),
        )

    def response(self, status: int, method: str, url: str, *, body: str = "") -> None:
        safe_url = redact_url(url)
        self.add(
            "response",
            f"{status} {method} {safe_url}",
            status=status,
            body=clip(redact_text(body)),
        )

    def error(self, summary: str, **detail: Any) -> None:
        cleaned = dict(detail)
        if "url" in cleaned and isinstance(cleaned["url"], str):
            cleaned["url"] = redact_url(cleaned["url"])
        self.add("error", redact_text(summary), **cleaned)

    def choice(
        self,
        selected: tuple[str, str, str] | None,
        skipped: list[dict[str, str]],
        *,
        note: str = "",
    ) -> None:
        if selected is None:
            summary = "No speakable interface"
        else:
            url, binding, version = selected
            summary = f"Chose {binding} {version} at {url}"
        if note:
            summary += f" ({note})"
        self.add("choice", summary, selected=_selected_dict(selected), skipped=skipped)

    def auth(self, summary: str, **detail: Any) -> None:
        self.add("auth", summary, **detail)

    def lines(self) -> list[str]:
        return [event.summary for event in self.events]

    def to_dict(self) -> dict[str, Any]:
        return {"events": [event.to_dict() for event in self.events]}


def clip(text: str | None, limit: int = BODY_LIMIT) -> str:
    """Trim a body so a card or task dump cannot flood the log."""
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n")
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if _secret_header(key):
            redacted[key] = "Bearer ***" if str(value).lower().startswith("bearer ") else "***"
        else:
            redacted[key] = value
    return redacted


def _secret_header(key: str) -> bool:
    lower = key.lower()
    if lower in _REDACT_HEADERS:
        return True
    return any(part in lower for part in _REDACT_PARTS)


def auth_summary(card: dict) -> str:
    """Describe advertised schemes and whether the card requires them."""
    from superqode.a2a.security import describe_auth

    return describe_auth(card)


_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)\S+")
_SQK_LIVE = re.compile(r"(?i)(sqk_live_)[A-Za-z0-9_\-]+")
_SK_PREFIX = re.compile(r"(?i)\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{8,}")
_LABELED_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|access_token|refresh_token|password|secret|token)\s*[:=]\s*)\S+"
)


def redact_text(text: str | None) -> str:
    """Strip credential-shaped values from inspect bodies and messages."""
    if not text:
        return ""
    redacted = _BEARER_VALUE.sub(r"\1***", text)
    redacted = _SQK_LIVE.sub(r"\1***", redacted)
    redacted = _SK_PREFIX.sub("***", redacted)
    return _LABELED_SECRET.sub(r"\1***", redacted)


def redact_url(url: str) -> str:
    """Hide secret query parameters such as api_key=."""
    if not url or "?" not in url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _secret_header(key) or key.lower() in {"key", "api_key", "access_token", "token"}:
            pairs.append((key, "***"))
        else:
            pairs.append((key, value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs, safe="*"), parts.fragment)
    )


def _selected_dict(selected: tuple[str, str, str] | None) -> dict[str, str]:
    if selected is None:
        return {}
    url, binding, version = selected
    return {"url": url, "binding": binding, "version": version}
