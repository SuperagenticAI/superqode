"""A short trace of how SuperQode read an Agent Card and spoke to it.

The tester needs three things a status line cannot hold: which binding was
chosen, what went on the wire, and why a card was refused. Events are
summaries plus a clipped detail dict. Authorization headers are stripped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BODY_LIMIT = 800

_REDACT_HEADERS = frozenset({"authorization", "x-api-key", "cookie", "set-cookie"})


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
        self.add(
            "request",
            f"{method} {url}{suffix}",
            body=clip(body),
            headers=redact_headers(headers),
        )

    def response(self, status: int, method: str, url: str, *, body: str = "") -> None:
        self.add(
            "response",
            f"{status} {method} {url}",
            status=status,
            body=clip(body),
        )

    def error(self, summary: str, **detail: Any) -> None:
        self.add("error", summary, **detail)

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
        if key.lower() in _REDACT_HEADERS:
            redacted[key] = "Bearer ***" if str(value).lower().startswith("bearer ") else "***"
        else:
            redacted[key] = value
    return redacted


def _selected_dict(selected: tuple[str, str, str] | None) -> dict[str, str]:
    if selected is None:
        return {}
    url, binding, version = selected
    return {"url": url, "binding": binding, "version": version}
