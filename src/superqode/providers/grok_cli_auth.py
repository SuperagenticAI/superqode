"""Grok CLI session-token reuse (opt-in).

The official Grok CLI stores its subscription session token in
``~/.grok/auth.json`` after ``grok login``. xAI's own CLI documentation shows
how to reuse that token for direct API calls against the CLI chat proxy::

    curl -s -N -X POST "https://cli-chat-proxy.grok.com/v1/chat/completions" \\
      -H "Authorization: Bearer $(jq -r '."https://accounts.x.ai/sign-in".key' ~/.grok/auth.json)" \\
      -H "X-XAI-Token-Auth: xai-grok-cli" \\
      -H "x-grok-model-override: grok-build" \\
      -H "x-grok-client-version: 0.1.202" ...

The proxy rejects requests without ``x-grok-client-version`` (HTTP 426,
version reported as ``none``) and requires at least ``0.1.202``. SuperQode
sends the installed CLI version when available.

``:connect grok`` / ``:grok connect`` import the session token into SuperQode's
local auth store (``~/.superqode/auth.json``, 0600) under the ``grok-cli``
provider so SuperQode's harness can use the subscription. Grok Build ACP
(``:connect acp grok``) leaves credentials entirely to the CLI.

CLI session tokens last about 7 days and are refreshed by the official CLI,
not by SuperQode — when the token expires, re-run ``grok login`` and
``:grok api``.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from superqode.auth import OAuthAuth, get as get_local_auth, remove as remove_local_auth
from superqode.auth import set as set_local_auth

# Provider id used in the registry, the auth store, and BYOK connect.
PROVIDER_ID = "grok-cli"

# Where the official CLI keeps its login (documented in the CLI README).
GROK_AUTH_FILE = Path.home() / ".grok" / "auth.json"
GROK_VERSION_FILE = Path.home() / ".grok" / "version.json"
GROK_SIGNIN_KEY = "https://accounts.x.ai/sign-in"

# Documented lifetime of a CLI session token ("Tokens expire after 7 days").
CLI_SESSION_LIFETIME_SECONDS = 7 * 24 * 3600

# Minimum version the CLI chat proxy accepts (HTTP 426 below this / when missing).
MIN_CLI_VERSION = "0.1.202"

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.]+)?)")


def _parse_version_string(text: str) -> Optional[str]:
    """Extract a dotted CLI version from a ``grok --version`` line or free text."""
    if not text:
        return None
    match = _VERSION_RE.search(text.strip())
    return match.group(1) if match else None


@lru_cache(maxsize=1)
def detect_cli_version() -> str:
    """Return the installed Grok CLI version for the chat-proxy version header.

    Prefers ``~/.grok/version.json`` (written by the installer), then
    ``grok --version``. Falls back to :data:`MIN_CLI_VERSION` so the proxy
    still accepts the request when the binary is missing but a token was
    imported earlier.
    """
    try:
        if GROK_VERSION_FILE.is_file():
            data = json.loads(GROK_VERSION_FILE.read_text())
            if isinstance(data, dict):
                for key in ("version", "stable_version"):
                    parsed = _parse_version_string(str(data.get(key) or ""))
                    if parsed:
                        return parsed
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass

    grok_bin = shutil.which("grok")
    if grok_bin:
        try:
            proc = subprocess.run(
                [grok_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
            parsed = _parse_version_string(combined)
            if parsed:
                return parsed
        except (OSError, subprocess.SubprocessError):
            pass

    return MIN_CLI_VERSION


def clear_cli_version_cache() -> None:
    """Drop the cached CLI version (tests / after ``grok update``)."""
    detect_cli_version.cache_clear()


_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


def parse_cli_models_output(text: str) -> Dict[str, Any]:
    """Parse ``grok models`` output into ``{"default": str, "models": [ids]}``.

    The command prints a ``Default model:`` line and an ``Available models:``
    section (empty when the CLI is not authenticated). Model lines may carry
    bullets or trailing descriptions; only the leading id token is kept.
    """
    default = ""
    models: list[str] = []
    in_models = False
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("default model:"):
            candidate = line.split(":", 1)[1].strip()
            if _MODEL_ID_RE.match(candidate):
                default = candidate
            continue
        if lowered.startswith("available models"):
            in_models = True
            continue
        if not in_models:
            continue
        if line.endswith(":"):  # a new section header ends the model list
            break
        token = line.lstrip("-*• \t").split()[0].rstrip(",") if line.lstrip("-*• \t") else ""
        token = token.strip("()")
        if token and _MODEL_ID_RE.match(token) and token not in models:
            models.append(token)
    return {"default": default, "models": models}


_cli_models_cache: Optional[Dict[str, Any]] = None
_cli_models_fetched = False


def cached_cli_models() -> Dict[str, Any]:
    """Subscription model catalog as reported by ``grok models``, cached.

    Returns ``{"default": str, "models": [ids]}``; the model list is empty when
    the CLI is missing or not authenticated. Fetched once per process so
    pickers stay fast; ``clear_cli_models_cache`` resets (tests, re-login).
    """
    global _cli_models_cache, _cli_models_fetched
    if _cli_models_fetched and _cli_models_cache is not None:
        return _cli_models_cache
    _cli_models_fetched = True
    result: Dict[str, Any] = {"default": "", "models": []}
    grok_bin = shutil.which("grok")
    if grok_bin:
        try:
            proc = subprocess.run(
                [grok_bin, "models"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            result = parse_cli_models_output(f"{proc.stdout or ''}\n{proc.stderr or ''}")
        except (OSError, subprocess.SubprocessError):
            pass
    _cli_models_cache = result
    return result


def clear_cli_models_cache() -> None:
    """Drop the cached CLI model catalog (tests / after ``grok login``)."""
    global _cli_models_cache, _cli_models_fetched
    _cli_models_cache = None
    _cli_models_fetched = False


def _jwt_expiry(token: str) -> int:
    """Best-effort ``exp`` claim from a JWT-shaped token, else 0."""
    if not token or token.count(".") < 2:
        return 0
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        if isinstance(exp, (int, float)) and exp > 0:
            return int(exp)
    except Exception:  # noqa: BLE001 - opaque tokens are fine
        pass
    return 0


def read_cli_token(path: Optional[Path] = None) -> Optional[Tuple[str, int]]:
    """Read the CLI session token and an expiry estimate (epoch seconds).

    Returns ``None`` when there is no usable login. Expiry comes from the
    token's JWT ``exp`` claim when present, otherwise from the auth file's
    mtime plus the documented 7-day session lifetime.
    """
    auth_file = path or GROK_AUTH_FILE
    if not auth_file.exists():
        return None
    try:
        data: Any = json.loads(auth_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    token = ""
    entry = data.get(GROK_SIGNIN_KEY)
    if isinstance(entry, dict):
        token = str(entry.get("key") or "")
    elif isinstance(entry, str):
        token = entry
    if not token:
        # Other sign-in hosts (enterprise OIDC) use the same {url: {key: ...}}
        # shape; a bare {"access_token": ...} covers external auth providers.
        for value in data.values():
            if isinstance(value, dict) and value.get("key"):
                token = str(value["key"])
                break
        if not token and data.get("access_token"):
            token = str(data["access_token"])
    if not token:
        return None

    expires = _jwt_expiry(token)
    if not expires:
        try:
            expires = int(auth_file.stat().st_mtime) + CLI_SESSION_LIFETIME_SECONDS
        except OSError:
            expires = 0
    return token, expires


def import_cli_token(path: Optional[Path] = None) -> Optional[OAuthAuth]:
    """Copy the CLI session token into SuperQode's local auth store.

    Explicit opt-in only — called from ``:grok api``. Returns the stored
    credential, or ``None`` when no CLI login exists.
    """
    found = read_cli_token(path)
    if found is None:
        return None
    token, expires = found
    auth = OAuthAuth(access=token, refresh="", expires=expires)
    set_local_auth(PROVIDER_ID, auth)
    return auth


def remove_cli_token() -> bool:
    """Remove a previously imported CLI token from the local auth store."""
    return remove_local_auth(PROVIDER_ID)


def cli_token_status(path: Optional[Path] = None) -> Dict[str, Any]:
    """Non-secret status summary for ``:grok status``."""
    found = read_cli_token(path)
    imported = get_local_auth(PROVIDER_ID)
    imported_oauth = imported if isinstance(imported, OAuthAuth) else None
    return {
        "cli_login": found is not None,
        "cli_expires": found[1] if found else 0,
        "imported": imported_oauth is not None,
        "imported_expired": bool(imported_oauth and imported_oauth.is_expired()),
        "imported_expires": imported_oauth.expires if imported_oauth else 0,
    }
