"""Grok CLI session-token reuse (opt-in).

The official Grok CLI stores its subscription session token in
``~/.grok/auth.json`` after ``grok login``. xAI's CLI reuses that token against
the CLI chat proxy with first-party headers::

    curl -s -N -X POST "https://cli-chat-proxy.grok.com/v1/chat/completions" \\
      -H "Authorization: Bearer <cli session key>" \\
      -H "X-XAI-Token-Auth: xai-grok-cli" \\
      -H "x-grok-model-override: grok-4.6" \\
      -H "x-grok-client-version: <installed grok version>" ...

The proxy rejects requests without ``x-grok-client-version`` (HTTP 426,
version reported as ``none``). SuperQode sends the installed CLI version
when available.

``:grok api`` imports the session token into SuperQode's local auth store
(``~/.superqode/auth.json``, 0600) under the ``grok-cli`` provider so
SuperQode's harness can use the subscription. The CLI owns refresh: current
``auth.json`` entries are keyed ``{oidc_issuer}::{client_id}``, carry
``expires_at`` (hours, not days), and a ``refresh_token`` SuperQode never
spends. Re-read the file when the imported snapshot is near expiry.

Grok Build ACP (``:connect grok`` / ``:connect acp grok``) leaves credentials
entirely to the CLI. The headless vendor loop is ``:runtime grok-cli``.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from superqode.auth import OAuthAuth, get as get_local_auth, remove as remove_local_auth
from superqode.auth import set as set_local_auth

# Provider id used in the registry, the auth store, and BYOK connect.
PROVIDER_ID = "grok-cli"

# Where the official CLI keeps its login (documented in the CLI README).
GROK_AUTH_FILE = Path.home() / ".grok" / "auth.json"
GROK_VERSION_FILE = Path.home() / ".grok" / "version.json"
GROK_MODELS_CACHE_FILE = Path.home() / ".grok" / "models_cache.json"
# Legacy key from early CLI docs. Current files use ``{oidc_issuer}::{client_id}``.
GROK_SIGNIN_KEY = "https://accounts.x.ai/sign-in"

# Re-read ``auth.json`` this many seconds before the imported snapshot lapses.
# The CLI rotates in place; we are not the refresh-token holder.
TOKEN_STALE_SECONDS = 300

# Last-resort ``x-grok-client-version`` when the binary is missing. The proxy
# 426s if the header is omitted entirely.
MIN_CLI_VERSION = "0.1.202"

# Builtin fallback when no live catalog is available.
DEFAULT_SUBSCRIPTION_MODEL = "grok-4.6"
# Trust ``models_cache.json`` for this long before preferring a live fetch.
MODELS_CACHE_MAX_AGE_SECONDS = 24 * 3600

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


def _empty_catalog() -> Dict[str, Any]:
    return {"default": "", "models": [], "details": {}, "source": ""}


def _catalog_from_ids(
    model_ids: list[str],
    default: str = "",
    details: Optional[Dict[str, Any]] = None,
    source: str = "",
) -> Dict[str, Any]:
    ids = [mid for mid in model_ids if mid]
    chosen = str(default or "").strip()
    if chosen and chosen not in ids:
        # Keep an explicit default even if the id list omitted it; the picker
        # prepends it. Never invent a default from dict/file order.
        pass
    elif not chosen:
        chosen = ""
    return {"default": chosen, "models": ids, "details": dict(details or {}), "source": source}


def _parse_iso_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return 0.0


def read_models_cache_file(path: Optional[Path] = None) -> Dict[str, Any]:
    """Parse ``~/.grok/models_cache.json`` for model ids and display metadata.

    Never copies ``api_key`` or request headers from the cache.
    """
    cache_file = path or GROK_MODELS_CACHE_FILE
    if not cache_file.exists():
        return _empty_catalog()
    try:
        data: Any = json.loads(cache_file.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return _empty_catalog()
    if not isinstance(data, dict):
        return _empty_catalog()
    if str(data.get("auth_method") or "").strip().lower() != "session":
        return _empty_catalog()
    fetched = _parse_iso_timestamp(data.get("fetched_at"))
    if fetched and (time.time() - fetched) > MODELS_CACHE_MAX_AGE_SECONDS:
        return _empty_catalog()
    raw_models = data.get("models")
    ids: list[str] = []
    details: Dict[str, Any] = {}
    if isinstance(raw_models, dict):
        for model_id, meta in raw_models.items():
            mid = str(model_id or "").strip()
            if not mid:
                continue
            ids.append(mid)
            info = meta.get("info") if isinstance(meta, dict) else None
            if isinstance(info, dict):
                details[mid] = {
                    "name": info.get("name") or mid,
                    "description": info.get("description") or "",
                    "context_window": int(info.get("context_window") or 0),
                    "max_output": int(info.get("max_completion_tokens") or 0),
                }
    elif isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, str) and item.strip():
                ids.append(item.strip())
            elif isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    # The real cache has no top-level default; do not invent one from key order.
    default = str(data.get("default") or "")
    return _catalog_from_ids(ids, default=default, details=details, source="cache")


def _proxy_models_url() -> str:
    from .registry import PROVIDERS

    pdef = PROVIDERS[PROVIDER_ID]
    base = (pdef.default_base_url or "https://cli-chat-proxy.grok.com/v1").rstrip("/")
    override = os.environ.get(pdef.base_url_env or "")
    if override:
        base = override.rstrip("/")
    return f"{base}/models"


def fetch_proxy_models(token: Optional[str] = None) -> Dict[str, Any]:
    """GET ``{cli-chat-proxy}/models`` with the current session token."""
    access = token or resolve_provider_token()
    if not access:
        return _empty_catalog()
    request = urllib.request.Request(
        _proxy_models_url(),
        headers={
            "Authorization": f"Bearer {access}",
            "X-XAI-Token-Auth": "xai-grok-cli",
            "x-grok-client-version": detect_cli_version(),
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return _empty_catalog()
    ids: list[str] = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or []
        default = str(payload.get("default") or "")
    elif isinstance(payload, list):
        rows = payload
        default = ""
    else:
        return _empty_catalog()
    if isinstance(rows, dict):
        ids = [str(key) for key in rows if key]
    else:
        for item in rows:
            if isinstance(item, str) and item.strip():
                ids.append(item.strip())
            elif isinstance(item, dict):
                mid = str(item.get("id") or item.get("model") or "").strip()
                if mid:
                    ids.append(mid)
    return _catalog_from_ids(ids, default=default, source="proxy")


def _fetch_cli_models_stdout() -> Dict[str, Any]:
    grok_bin = shutil.which("grok")
    if not grok_bin:
        return _empty_catalog()
    try:
        proc = subprocess.run(
            [grok_bin, "models"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _empty_catalog()
    if proc.returncode != 0:
        return _empty_catalog()
    parsed = parse_cli_models_output(proc.stdout or "")
    return _catalog_from_ids(
        list(parsed.get("models") or []),
        default=str(parsed.get("default") or ""),
        source="cli",
    )


def cached_cli_models() -> Dict[str, Any]:
    """Subscription catalog: cache file, then proxy, then ``grok models``.

    Returns ``{"default": str, "models": [ids], "details": {...}}``. The model
    list is empty when nothing is available. Fetched once per process;
    ``clear_cli_models_cache`` resets (tests, re-login).
    """
    global _cli_models_cache, _cli_models_fetched
    if _cli_models_fetched and _cli_models_cache is not None:
        return _cli_models_cache
    _cli_models_fetched = True

    def _load(loader):
        try:
            return loader()
        except Exception:  # noqa: BLE001 - catalog probing is best-effort
            return _empty_catalog()

    result = _load(read_models_cache_file)
    if not result.get("models"):
        result = _load(fetch_proxy_models)
    if not result.get("models"):
        result = _load(_fetch_cli_models_stdout)
    # The cache file lists ids but not the account default. Ask `grok models`
    # only for that field so we do not claim dict order is the default.
    if result.get("models") and not result.get("default"):
        stdout = _load(_fetch_cli_models_stdout)
        if stdout.get("default"):
            result = {**result, "default": stdout["default"]}
    _cli_models_cache = result if result.get("models") else _empty_catalog()
    return _cli_models_cache


def peek_cached_cli_models() -> Optional[Dict[str, Any]]:
    """In-process catalog if already fetched. Never probes disk, network, or CLI."""
    if _cli_models_fetched and _cli_models_cache is not None:
        return _cli_models_cache
    return None


def default_subscription_model() -> str:
    """Live CLI default, else the shipped fallback."""
    listing = cached_cli_models()
    return str(listing.get("default") or "") or DEFAULT_SUBSCRIPTION_MODEL


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


def _parse_expiry(value: Any) -> int:
    """Parse ``expires_at`` as epoch seconds. ISO-8601 or numeric. Else 0."""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        return 0


def _entry_token(entry: Any) -> str:
    if isinstance(entry, str) and entry.strip():
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("key") or "").strip()
    return ""


def _entry_expires(entry: Any, token: str) -> int:
    if isinstance(entry, dict):
        stamped = _parse_expiry(entry.get("expires_at"))
        if stamped:
            return stamped
    return _jwt_expiry(token)


def _iter_auth_entries(data: dict) -> Iterable[Any]:
    """Yield candidate credential entries, newest schema first.

    Current CLI files key entries ``{oidc_issuer}::{client_id}``. Older
    installs used ``https://accounts.x.ai/sign-in``. A bare
    ``access_token`` is last.
    """
    seen: set[int] = set()

    def _yield(entry: Any) -> Iterable[Any]:
        marker = id(entry)
        if marker in seen:
            return
        seen.add(marker)
        yield entry

    for key, value in data.items():
        if isinstance(key, str) and "::" in key:
            yield from _yield(value)
    if GROK_SIGNIN_KEY in data:
        yield from _yield(data[GROK_SIGNIN_KEY])
    for value in data.values():
        if isinstance(value, dict) and value.get("key"):
            yield from _yield(value)
    if data.get("access_token"):
        yield from _yield({"key": data.get("access_token")})


def read_cli_token(path: Optional[Path] = None) -> Optional[Tuple[str, int]]:
    """Read the CLI session token and an expiry estimate (epoch seconds).

    Returns ``None`` when there is no usable login. Expiry prefers the
    entry's ``expires_at``, then the token JWT ``exp``. Unknown expiry is
    ``0`` (``OAuthAuth`` treats that as not expired) — we do not invent a
    week-long lifetime from mtime. SuperQode never reads ``refresh_token``.
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

    best: Optional[Tuple[str, int]] = None
    for entry in _iter_auth_entries(data):
        token = _entry_token(entry)
        if not token:
            continue
        expires = _entry_expires(entry, token)
        if best is None or expires > best[1]:
            best = (token, expires)
    return best


def import_cli_token(path: Optional[Path] = None) -> Optional[OAuthAuth]:
    """Copy the CLI session token into SuperQode's local auth store.

    Explicit opt-in only — called from ``:grok api``. Returns the stored
    credential, or ``None`` when no CLI login exists. The refresh token
    stays in the CLI file; SuperQode never copies it.
    """
    found = read_cli_token(path)
    if found is None:
        return None
    token, expires = found
    auth = OAuthAuth(access=token, refresh="", expires=expires)
    set_local_auth(PROVIDER_ID, auth)
    return auth


def _oauth_is_stale(auth: OAuthAuth) -> bool:
    if not auth.access:
        return True
    if not auth.expires:
        return False
    return auth.expires < int(time.time()) + TOKEN_STALE_SECONDS


def resolve_provider_token(path: Optional[Path] = None) -> Optional[str]:
    """Token for ``grok-cli`` requests: live CLI file when the snapshot is stale.

    The official CLI refreshes ``~/.grok/auth.json`` in place. SuperQode's
    imported snapshot is only a cache. When it is near expiry, re-read the
    file instead of telling the user to log in again.

    Never creates a snapshot. ``:grok api`` is the only writer; status,
    models, and a bare ``provider_api_key`` lookup must not import a token
    the user has not opted into (or has just removed with ``:grok api off``).
    """
    stored = get_local_auth(PROVIDER_ID)
    stored_oauth = stored if isinstance(stored, OAuthAuth) else None
    if stored_oauth is None:
        return None
    if not _oauth_is_stale(stored_oauth):
        return stored_oauth.access or None

    found = read_cli_token(path)
    if found is None:
        return None
    token, expires = found
    if expires and expires < int(time.time()):
        return None
    set_local_auth(PROVIDER_ID, OAuthAuth(access=token, refresh="", expires=expires))
    return token


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
