"""Saved A2A client connection: a card URL and an optional Bearer token.

Mirrors the UHP connection file. The address is resolved first, then the
client fetches the Agent Card and speaks the first advertised binding it can.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

URL_ENV = "SUPERQODE_A2A_URL"
TOKEN_ENV = "SUPERQODE_A2A_CLIENT_TOKEN"
#: Also accepted so a token minted for the public agent can be reused as a client.
TOKEN_FALLBACK_ENV = "SUPERQODE_A2A_TOKEN"
CERT_ENV = "SUPERQODE_A2A_TLS_CERT"
KEY_ENV = "SUPERQODE_A2A_TLS_KEY"

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
    headers: dict[str, str] = field(default_factory=dict)
    cert: str = ""
    key: str = ""
    name: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"url": self.url, "token": self.token}
        if self.headers:
            payload["headers"] = dict(self.headers)
        if self.cert:
            payload["cert"] = self.cert
        if self.key:
            payload["key"] = self.key
        if self.name:
            payload["name"] = self.name
        return payload


def parse_header_options(values: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Parse repeated ``NAME:VALUE`` flags into a header map."""
    headers: dict[str, str] = {}
    for item in values:
        name, sep, value = item.partition(":")
        if not sep or not name.strip():
            raise ValueError(f"Expected NAME:VALUE, got {item!r}")
        headers[name.strip()] = value.strip()
    return headers


def parse_header_line(text: str) -> dict[str, str]:
    """Parse a TUI line of ``NAME:VALUE; NAME:VALUE`` extra headers."""
    chunks = [part.strip() for part in text.replace("\n", ";").split(";") if part.strip()]
    if not chunks:
        return {}
    return parse_header_options(tuple(chunks))


def format_header_line(headers: dict[str, str]) -> str:
    """Render extra headers for the TUI field."""
    return "; ".join(f"{name}: {value}" for name, value in headers.items() if name)


def client_auth(settings: A2ASettings) -> dict[str, object]:
    """Keyword arguments ``A2AClient`` needs for a saved connection."""
    return {
        "bearer_token": settings.token or None,
        "extra_headers": settings.headers or None,
        "client_cert": settings.cert or None,
        "client_key": settings.key or None,
    }


def resolve_settings(
    url: str | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
    cert: str | None = None,
    key: str | None = None,
) -> A2ASettings:
    """Options, then the environment, then the saved file."""
    saved = load_saved_connection()
    resolved_url = normalize_url(url or os.environ.get(URL_ENV) or saved.url)
    resolved_token = (
        token or os.environ.get(TOKEN_ENV) or os.environ.get(TOKEN_FALLBACK_ENV) or saved.token
    ).strip()
    resolved_headers = dict(saved.headers)
    if headers:
        resolved_headers.update(headers)
    resolved_cert = (cert or os.environ.get(CERT_ENV) or saved.cert).strip()
    resolved_key = (key or os.environ.get(KEY_ENV) or saved.key).strip()
    resolved_name = saved.name if resolved_url == saved.url else ""
    return A2ASettings(
        url=resolved_url,
        token=resolved_token,
        headers=resolved_headers,
        cert=resolved_cert,
        key=resolved_key,
        name=resolved_name,
    )


def load_saved_connection() -> A2ASettings:
    path = connection_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return A2ASettings()
    if not isinstance(payload, dict):
        return A2ASettings()
    raw_headers = payload.get("headers") or {}
    headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        headers = {str(key): str(value) for key, value in raw_headers.items() if str(key).strip()}
    return A2ASettings(
        url=str(payload.get("url") or ""),
        token=str(payload.get("token") or ""),
        headers=headers,
        cert=str(payload.get("cert") or ""),
        key=str(payload.get("key") or ""),
        name=str(payload.get("name") or ""),
    )


def save_connection(settings: A2ASettings) -> Path:
    """Persist the connection with owner-only permissions.

    A token that came from the environment is never copied to disk.
    """
    path = connection_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.to_dict()
    previous = load_saved_connection()
    env_token = (os.environ.get(TOKEN_ENV) or os.environ.get(TOKEN_FALLBACK_ENV) or "").strip()
    if env_token and payload.get("token") == env_token:
        payload["token"] = previous.token if previous.token and previous.token != env_token else ""
    env_cert = (os.environ.get(CERT_ENV) or "").strip()
    if env_cert and payload.get("cert") == env_cert:
        if previous.cert and previous.cert != env_cert:
            payload["cert"] = previous.cert
        else:
            payload.pop("cert", None)
    env_key = (os.environ.get(KEY_ENV) or "").strip()
    if env_key and payload.get("key") == env_key:
        if previous.key and previous.key != env_key:
            payload["key"] = previous.key
        else:
            payload.pop("key", None)
    body = json.dumps(payload, indent=2) + "\n"
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(body)
    path.chmod(0o600)
    return path
