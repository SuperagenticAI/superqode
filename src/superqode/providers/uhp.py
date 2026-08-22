"""Connection settings for a Unified Harness Protocol server.

A UHP server is a remote catalog rather than a local process, so connecting
takes a URL and a credential before SuperQode knows which harnesses exist.
This module resolves those settings from explicit arguments, the environment,
or the saved connection file, and is shared by the CLI and the TUI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

BASE_URL_ENV = "SUPERQODE_UHP_BASE_URL"
API_KEY_ENV = "SUPERQODE_UHP_API_KEY"
HARNESS_ENV = "SUPERQODE_UHP_HARNESS"


def connection_path() -> Path:
    """Return the file holding the saved UHP connection."""
    return Path.home() / ".superqode" / "uhp.json"


@dataclass(frozen=True)
class UHPSettings:
    """Everything needed to reach one UHP server."""

    base_url: str = ""
    api_key: str = ""
    harness_id: str = ""

    @property
    def configured(self) -> bool:
        """Whether a server address is known.  Some servers need no key."""
        return bool(self.base_url)

    def to_dict(self) -> dict[str, str]:
        return {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "harness_id": self.harness_id,
        }


def load_saved_connection() -> UHPSettings:
    """Return the saved connection, or empty settings when there is none."""
    path = connection_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UHPSettings()
    if not isinstance(payload, dict):
        return UHPSettings()
    return UHPSettings(
        base_url=str(payload.get("base_url") or ""),
        api_key=str(payload.get("api_key") or ""),
        harness_id=str(payload.get("harness_id") or ""),
    )


def save_connection(settings: UHPSettings) -> Path:
    """Persist the connection with owner-only permissions and return its path.

    A key that came from the environment is never copied to disk, so a
    credential exported per shell stays in that shell.  Stripping it must not
    discard a different key the user previously saved with ``--api-key``.
    """
    path = connection_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.to_dict()
    env_key = os.environ.get(API_KEY_ENV)
    if env_key and payload["api_key"] == env_key:
        previous = load_saved_connection().api_key
        payload["api_key"] = previous if previous and previous != env_key else ""
    body = json.dumps(payload, indent=2) + "\n"
    # Create the file already private rather than widening then narrowing it.
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(body)
    path.chmod(0o600)
    return path


def resolve_settings(
    base_url: str | None = None,
    api_key: str | None = None,
    harness_id: str | None = None,
) -> UHPSettings:
    """Resolve settings from arguments, then the environment, then the file."""
    saved = load_saved_connection()
    return UHPSettings(
        base_url=(base_url or os.environ.get(BASE_URL_ENV) or saved.base_url or "").strip(),
        api_key=(api_key or os.environ.get(API_KEY_ENV) or saved.api_key or "").strip(),
        harness_id=(harness_id or os.environ.get(HARNESS_ENV) or saved.harness_id or "").strip(),
    )


def is_configured() -> bool:
    """Whether a UHP server address is available without prompting."""
    return resolve_settings().configured


def setup_hint() -> str:
    """Tell the user how to point SuperQode at a UHP server."""
    return (
        "Set a server with `superqode connect uhp --base-url https://your-server` "
        f"or export {BASE_URL_ENV} (and {API_KEY_ENV} when the server needs a key)."
    )
