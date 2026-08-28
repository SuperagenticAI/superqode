"""Saved A2A client connection: a card URL and an optional Bearer token.

Mirrors the UHP connection file. The address is resolved first, then the
client fetches the Agent Card and speaks the first advertised binding it can.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

URL_ENV = "SUPERQODE_A2A_URL"
TOKEN_ENV = "SUPERQODE_A2A_CLIENT_TOKEN"
#: Also accepted so a token minted for the public agent can be reused as a client.
TOKEN_FALLBACK_ENV = "SUPERQODE_A2A_TOKEN"

#: Public SuperQode A2A origin. The client fetches
#: ``/.well-known/agent-card.json`` from here.
DEFAULT_URL = "https://superqode.onrender.com"

_CARD_SUFFIXES = (
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
)


def normalize_url(url: str) -> str:
    """Strip a pasted well-known card path so the client can append its own."""
    trimmed = url.strip().rstrip("/")
    for suffix in _CARD_SUFFIXES:
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)]
    return trimmed


def connection_path() -> Path:
    """Return the file holding the saved A2A client connection."""
    return Path.home() / ".superqode" / "a2a.json"


@dataclass(frozen=True)
class A2ASettings:
    """Everything needed to reach one A2A agent."""

    url: str = ""
    token: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "token": self.token}


def resolve_settings(url: str | None = None, token: str | None = None) -> A2ASettings:
    """Options, then the environment, then the saved file."""
    saved = load_saved_connection()
    resolved_url = normalize_url(url or os.environ.get(URL_ENV) or saved.url)
    resolved_token = (
        token
        or os.environ.get(TOKEN_ENV)
        or os.environ.get(TOKEN_FALLBACK_ENV)
        or saved.token
    ).strip()
    return A2ASettings(url=resolved_url, token=resolved_token)


def load_saved_connection() -> A2ASettings:
    path = connection_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return A2ASettings()
    if not isinstance(payload, dict):
        return A2ASettings()
    return A2ASettings(
        url=str(payload.get("url") or ""),
        token=str(payload.get("token") or ""),
    )


def save_connection(settings: A2ASettings) -> Path:
    """Persist the connection with owner-only permissions.

    A token that came from the environment is never copied to disk.
    """
    path = connection_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.to_dict()
    env_token = (os.environ.get(TOKEN_ENV) or os.environ.get(TOKEN_FALLBACK_ENV) or "").strip()
    if env_token and payload["token"] == env_token:
        previous = load_saved_connection().token
        payload["token"] = previous if previous and previous != env_token else ""
    body = json.dumps(payload, indent=2) + "\n"
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(body)
    path.chmod(0o600)
    return path
