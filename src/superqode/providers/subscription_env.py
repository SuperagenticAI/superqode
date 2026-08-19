"""Keep subscription connections on the subscription, never on metered API keys.

A subscription connection means the user is spending a plan they already pay
for. Most vendor CLIs and SDKs prefer an API key over their own OAuth login
when one happens to be exported, so an unrelated key left in a shell can
silently move the session onto per-token billing. That is never what a
subscription connection asked for: SuperQode has a separate, dedicated BYOK
path for API-key use.

So subscription routes launch their vendor process with those keys removed, and
always tell the user which ones were ignored. Nothing is dropped silently.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

#: Vendor key -> environment variables that would divert that vendor onto
#: metered API billing. Keys are matched against a connection profile id, an
#: ACP agent short_name, or a runtime name, so callers can pass whichever they
#: have. Values are deliberately explicit rather than pattern-matched: removing
#: an unrelated variable would be its own bug.
VENDOR_API_KEY_ENVS: Dict[str, Tuple[str, ...]] = {
    "copilot": ("GH_TOKEN", "GITHUB_TOKEN"),
    "grok": ("GROK_CODE_XAI_API_KEY", "XAI_API_KEY"),
    "cursor": ("CURSOR_API_KEY",),
    "devin": ("DEVIN_API_KEY",),
    "droid": ("FACTORY_API_KEY",),
    "amp": ("AMP_API_KEY",),
    "kiro": ("KIRO_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
    "glm": ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY"),
    "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
    "kimi": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "codex": ("OPENAI_API_KEY",),
    "antigravity": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    # Muse Code documents this precedence explicitly: META_API_KEY wins over a
    # stored `muse login` session. META_MODEL_API_KEY is the BYOK provider key
    # and Muse never reads it, so it is deliberately not listed here.
    "muse": ("META_API_KEY",),
    "junie": ("JETBRAINS_API_KEY",),
    # OIDC is Vercel team identity, not a leftover metered key. Strip only
    # the Gateway API key so a subscription connect stays on `fx login`.
    "fx": ("AI_GATEWAY_API_KEY",),
}

#: Profile ids and runtime names that mean the same vendor as a dict key above.
_VENDOR_ALIASES: Dict[str, str] = {
    "copilot-sdk": "copilot",
    "copilot-cli": "copilot",
    "copilot-acp": "copilot",
    "codex-sdk": "codex",
    "antigravity-cli": "antigravity",
    "antigravity-sdk": "antigravity",
    "glm-cli": "glm",
    "qwen-code": "qwen",
    "kimi-code": "kimi",
    "gemini-cli": "gemini",
    "muse-code": "muse",
    "muse-cli": "muse",
    "junie-key": "junie",
    "fx-key": "fx",
}

#: Variables a user sets to deliberately opt a subscription route into an
#: explicit token. These are honoured rather than stripped.
EXPLICIT_OPT_IN_ENVS: Tuple[str, ...] = ("COPILOT_GITHUB_TOKEN",)


def resolve_vendor(name: str) -> Optional[str]:
    """Normalize a profile id, agent short_name, or runtime name to a vendor."""
    key = (name or "").strip().lower()
    if not key:
        return None
    key = _VENDOR_ALIASES.get(key, key)
    return key if key in VENDOR_API_KEY_ENVS else None


def diverting_api_keys(vendor: str, env: Optional[Mapping[str, str]] = None) -> List[str]:
    """API-key variables currently set that would bill this vendor per token.

    Returns the variable names only. Values are never read, logged, or copied.
    """
    resolved = resolve_vendor(vendor)
    if resolved is None:
        return []
    source = os.environ if env is None else env
    if any(source.get(name) for name in EXPLICIT_OPT_IN_ENVS):
        # The user explicitly supplied a token for this route; respect it.
        return []
    return [name for name in VENDOR_API_KEY_ENVS[resolved] if source.get(name)]


def subscription_child_env(
    vendor: str, env: Optional[Mapping[str, str]] = None
) -> Tuple[Dict[str, str], List[str]]:
    """Environment for a subscription process, plus the keys that were removed.

    The returned list is what the caller must show the user. An empty list
    means nothing was changed.
    """
    source = dict(os.environ if env is None else env)
    stripped = diverting_api_keys(vendor, source)
    for name in stripped:
        source.pop(name, None)
    return source, stripped


_VENDOR_KEY_AFTER_AUTH = frozenset({"vendor-key-acp", "vendor-key-cli"})


def _vendor_key_entry(vendor: str):
    """The drawn dedicated key row for this vendor, Open or Closed."""
    from superqode.providers.harness_catalog import HARNESS_CATALOG

    key = resolve_vendor(vendor)
    if key is None:
        return None
    for entry in HARNESS_CATALOG:
        if not entry.list_visible:
            continue
        if (entry.acp_agent or "").lower() != key:
            continue
        if any(spec.after_auth in _VENDOR_KEY_AFTER_AUTH for spec in entry.auth):
            return entry
    return None


def vendor_key_profile_id(vendor: str) -> Optional[str]:
    """Profile id for this vendor's dedicated key path, if one is drawn."""
    entry = _vendor_key_entry(vendor)
    return None if entry is None else entry.id


def closed_key_profile_id(vendor: str) -> Optional[str]:
    """Profile id for this vendor's Closed key path, if one is drawn."""
    entry = _vendor_key_entry(vendor)
    if entry is None or entry.openness != "closed":
        return None
    return entry.id


def subscription_notice(
    vendor_label: str,
    stripped: Iterable[str],
    *,
    vendor: str = "",
) -> List[str]:
    """User-facing lines explaining which keys were ignored, and why.

    Returns an empty list when nothing was stripped, so callers can simply
    extend their output with the result.
    """
    names = [str(name) for name in stripped]
    if not names:
        return []
    joined = ", ".join(names)
    plural = "keys are" if len(names) > 1 else "key is"
    entry = _vendor_key_entry(vendor) if vendor else None
    if entry is not None:
        menu = "Closed harnesses" if entry.openness == "closed" else "Open harnesses"
        spend_hint = f"Use :connect {entry.id} ({menu}) if you want to spend that API key instead."
    else:
        spend_hint = "Use :connect byok if you want to spend that API key instead."
    return [
        f"{joined} {'are' if len(names) > 1 else 'is'} set in this environment.",
        f"This is a subscription connection, so the API {plural} ignored and "
        f"{vendor_label} uses your subscription login instead.",
        spend_hint,
    ]
