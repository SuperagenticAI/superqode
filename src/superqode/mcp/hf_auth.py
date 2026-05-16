"""HuggingFace token auto-injection for MCP HTTP transports.

Why
---
HuggingFace's MCP server (``https://huggingface.co/mcp``) requires an
``HF_TOKEN`` for most endpoints. fast-agent auto-injects this when the
target URL is on a HF domain so users don't have to spell out an
``Authorization`` header for every connect.

We mirror that pattern: when the user does
``/connect https://huggingface.co/mcp`` (or any ``*.hf.co`` / ``*.hf.space``
URL), the MCP client adds ``Authorization: Bearer <HF_TOKEN>`` to the
HTTP transport headers automatically — same UX as fast-agent.

The token lookup order matches what most HF tooling does:

1. ``HF_TOKEN`` env var (the canonical CI/dev variable).
2. ``HUGGING_FACE_HUB_TOKEN`` env var (the variable name the
   ``huggingface_hub`` SDK historically uses).
3. ``~/.cache/huggingface/token`` (the file ``huggingface-cli login``
   writes).

Returning ``None`` from any of these means "no token available" — the
caller should fall through to the regular OAuth/no-auth path rather
than injecting a malformed header.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse


# Exact domain matches that should receive HF token auth.
# We use ``endswith`` on hostname components so subdomains like
# ``my-space.hf.space`` still match — but the leading dot in the
# pattern prevents a hostile ``hf.space.com`` from sneaking through.
_HF_HOSTS = (
    "huggingface.co",
    "hf.co",
)
# Wildcard suffixes (note leading dot — required for safe matching).
_HF_HOST_SUFFIXES = (
    ".hf.space",
    ".huggingface.co",
    ".hf.co",
)


def is_huggingface_url(url: str) -> bool:
    """Whether ``url`` points at a HuggingFace-owned host.

    Safe against the ``hf.space.com`` style spoof — we only match
    exact hostnames or ``*.<suffix>`` patterns with the leading dot.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in _HF_HOSTS:
        return True
    for suffix in _HF_HOST_SUFFIXES:
        if host.endswith(suffix):
            return True
    return False


def _read_token_file() -> Optional[str]:
    """Read the token file ``huggingface-cli login`` writes.

    Honors ``HF_HOME`` if set (per the SDK contract); otherwise looks
    in the standard cache location.
    """
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        path = Path(hf_home).expanduser() / "token"
    else:
        path = Path.home() / ".cache" / "huggingface" / "token"
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def get_huggingface_token(
    *, token_file_reader: Callable[[], Optional[str]] = _read_token_file
) -> Optional[str]:
    """Resolve the user's HuggingFace token, or ``None`` if not found.

    Lookup order (first non-empty wins):

    1. ``HF_TOKEN``
    2. ``HUGGING_FACE_HUB_TOKEN``
    3. ``$HF_HOME/token`` or ``~/.cache/huggingface/token``

    ``token_file_reader`` is parameterized so tests don't need to
    touch the user's actual cache directory.
    """
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(var, "").strip()
        if value:
            return value
    return token_file_reader()


def maybe_inject_hf_auth(url: str, headers: Optional[dict] = None) -> dict:
    """Return ``headers`` with HF Bearer auth added if applicable.

    No-op when:
    - the URL isn't a HF domain (preserves user-provided headers),
    - no token can be resolved (better to let the server 401 than
      to send a malformed empty Bearer header),
    - the caller already set ``Authorization`` (don't clobber).

    Returns a new dict; the input is not mutated.
    """
    out = dict(headers or {})
    if not is_huggingface_url(url):
        return out
    # Don't override an explicit user-provided auth header. Case-
    # insensitive check because some libraries title-case it.
    if any(k.lower() == "authorization" for k in out):
        return out
    token = get_huggingface_token()
    if not token:
        return out
    out["Authorization"] = f"Bearer {token}"
    return out
