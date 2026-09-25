"""Local endpoint fingerprints for safe session resume.

Saved sessions that used a local / OpenAI-compatible endpoint remember a
non-secret fingerprint of the base URL and auth-slot env name. If either
changes, resume refuses to continue silently so the user must reconnect
explicitly. Rotating the value inside the same env var does not change the
slot.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Tuple

from superqode.session.harness_bridge import SessionResumeError

# Providers whose requests are bound to a local or custom OpenAI-compatible
# base URL. Cloud BYOK routes are not fingerprint-gated here.
LOCAL_ENDPOINT_PROVIDERS = frozenset(
    {
        "ollama",
        "lmstudio",
        "mlx",
        "vllm",
        "ds4",
        "sglang",
        "tgi",
        "llamacpp",
        "openai-compatible",
        "local",
    }
)


def is_local_endpoint_provider(provider: str) -> bool:
    """True when resume should enforce an endpoint fingerprint."""
    pid = str(provider or "").strip().lower()
    if not pid:
        return False
    if pid in LOCAL_ENDPOINT_PROVIDERS:
        return True
    try:
        from superqode.providers.registry import PROVIDERS, ProviderCategory

        definition = PROVIDERS.get(pid)
        return bool(definition is not None and definition.category == ProviderCategory.LOCAL)
    except Exception:
        return False


def auth_slot_for_provider(provider: str) -> str:
    """Env var name used as the auth slot (never the secret value)."""
    pid = str(provider or "").strip().lower()
    if not pid:
        return ""
    try:
        from superqode.providers.dynamic import resolve_provider_def

        definition = resolve_provider_def(pid)
    except Exception:
        definition = None
    env_vars = list(getattr(definition, "env_vars", None) or [])
    return str(env_vars[0]).strip() if env_vars else ""


def current_endpoint_binding(provider: str) -> Tuple[str, str]:
    """Return ``(normalized_base_url, auth_slot)`` for the live provider."""
    pid = str(provider or "").strip().lower()
    base_url = ""
    try:
        from superqode.providers.dynamic import resolve_base_url, resolve_provider_def

        definition = resolve_provider_def(pid)
        if definition is not None:
            base_url = str(resolve_base_url(definition) or "").strip()
    except Exception:
        base_url = ""
    if not base_url:
        # Fall back to common local env overrides without importing secrets.
        for env_name in (
            "OPENAI_COMPATIBLE_BASE_URL",
            f"{pid.upper().replace('-', '_')}_HOST",
            f"{pid.upper().replace('-', '_')}_BASE_URL",
        ):
            value = os.environ.get(env_name, "").strip()
            if value:
                base_url = value
                break
    return (normalize_base_url(base_url), auth_slot_for_provider(pid))


def normalize_base_url(base_url: str) -> str:
    """Normalize a base URL for stable fingerprint comparison."""
    text = str(base_url or "").strip().rstrip("/")
    return text.lower()


def fingerprint_endpoint(base_url: str, auth_slot: str = "") -> str:
    """Non-secret fingerprint of endpoint + auth-slot identity."""
    payload = f"{normalize_base_url(base_url)}|{str(auth_slot or '').strip()}"
    if payload == "|":
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def bind_endpoint_fields(
    metadata: Any,
    *,
    provider: str,
    base_url: str = "",
    auth_slot: str = "",
) -> bool:
    """Stamp endpoint fields onto session metadata. Returns True if local."""
    if not is_local_endpoint_provider(provider):
        return False
    live_url, live_slot = current_endpoint_binding(provider)
    url = normalize_base_url(base_url) or live_url
    slot = str(auth_slot or "").strip() or live_slot
    metadata.endpoint_base_url = url
    metadata.endpoint_auth_slot = slot
    metadata.endpoint_fingerprint = fingerprint_endpoint(url, slot)
    return True


def check_resume_endpoint(metadata: Any, *, provider: str = "") -> None:
    """Raise SessionResumeError when a stored local fingerprint no longer matches.

    Sessions without a stored fingerprint (legacy) are allowed through.
    """
    stored = str(getattr(metadata, "endpoint_fingerprint", "") or "").strip()
    if not stored:
        return
    provider_id = str(provider or getattr(metadata, "provider", "") or "").strip().lower()
    if not is_local_endpoint_provider(provider_id):
        return
    live_url, live_slot = current_endpoint_binding(provider_id)
    live = fingerprint_endpoint(live_url, live_slot)
    if live == stored:
        return
    stored_url = str(getattr(metadata, "endpoint_base_url", "") or "").strip() or "(unknown)"
    stored_slot = str(getattr(metadata, "endpoint_auth_slot", "") or "").strip() or "(none)"
    live_url_display = live_url or "(unset)"
    live_slot_display = live_slot or "(none)"
    raise SessionResumeError(
        "Cannot resume this local session: the endpoint or auth slot changed. "
        f"Stored {stored_url} / auth slot {stored_slot}; "
        f"current {live_url_display} / auth slot {live_slot_display}. "
        "Restore the original connection, or reconnect explicitly with "
        f":connect {provider_id} and start a new session."
    )


__all__ = [
    "LOCAL_ENDPOINT_PROVIDERS",
    "auth_slot_for_provider",
    "bind_endpoint_fields",
    "check_resume_endpoint",
    "current_endpoint_binding",
    "fingerprint_endpoint",
    "is_local_endpoint_provider",
    "normalize_base_url",
]
