"""Connection profiles — the product/account-level choices in ``:connect``.

A *connection source* is what the user is connecting SuperQode to (Codex
subscription, Claude, a BYOK provider, a local model, an ACP agent). Each
profile declares a ``connector`` that the TUI/CLI dispatches on:

    runtime      self-contained runtime (own model+auth), e.g. codex-sdk
    acp          a specific ACP agent by short_name, e.g. "claude" or "grok"
    byok         the BYOK provider/model picker
    local        the local provider/model picker
    acp-picker   the generic "pick any ACP agent" list
    external-cli a local vendor TUI that does not expose ACP/headless events yet

This module has no TUI dependencies so it can be unit-tested and reused by both
the TUI and the CLI. New products (Claude Agent SDK, Antigravity) slot in as new
profiles without touching the connect flow.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .env_introspect import missing_extra_hint


@dataclass(frozen=True)
class ConnectionProfile:
    """A product/account-level connection source shown in ``:connect``."""

    id: str
    label: str
    description: str
    connector: str  # runtime | acp | byok | local | acp-picker | external-cli
    runtime: Optional[str] = None  # for connector == "runtime"
    acp_agent: Optional[str] = None  # for connector == "acp"
    self_contained: bool = False
    # Probe (no network) for whether this source is ready to use right now.
    detect: Optional[Callable[[], bool]] = None
    # Shown when detect() is False, to tell the user how to enable it.
    unavailable_hint: str = ""

    @property
    def available(self) -> bool:
        if self.detect is None:
            return True
        try:
            return bool(self.detect())
        except Exception:  # noqa: BLE001 - availability probes must never raise
            return False


# --- availability probes (cheap, local-only) ---------------------------------


def _codex_ready() -> bool:
    """codex-sdk extra installed AND a local Codex login present."""
    if importlib.util.find_spec("openai_codex") is None:
        return False
    return (Path.home() / ".codex" / "auth.json").exists()


def _claude_agent_ready() -> bool:
    """Claude Agent SDK installed + an Anthropic API key set (API-key runtime)."""
    if importlib.util.find_spec("claude_agent_sdk") is None:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _antigravity_cli_ready() -> bool:
    """The signed-in CLI owns Google OAuth; the runtime validates its version."""
    return shutil.which("agy") is not None


def _grok_cli_ready() -> bool:
    """Official Grok CLI installed with a locally managed subscription login."""
    return shutil.which("grok") is not None and (Path.home() / ".grok" / "auth.json").exists()


_BYOK_KEY_ENVS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
)


def _byok_ready() -> bool:
    return any(os.environ.get(env) for env in _BYOK_KEY_ENVS)


# --- registry -----------------------------------------------------------------

# Display order (local-first product positioning): Local, BYOK, ACP, Codex, Claude, Antigravity, Grok.
_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="local",
        label="Local model",
        description="Local/self-hosted — Ollama / MLX / vLLM / LM Studio …",
        connector="local",
        runtime="builtin",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="byok",
        label="BYOK provider",
        description="Bring your own API key — OpenAI / Anthropic / Gemini / …",
        connector="byok",
        runtime="builtin",
        detect=_byok_ready,
        unavailable_hint="set a provider API key (e.g. OPENAI_API_KEY) — or pick one to see setup",
    ),
    ConnectionProfile(
        id="acp",
        label="ACP agent",
        description="Connect any external ACP-compatible coding agent (incl. local Claude Code)",
        connector="acp-picker",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="codex",
        label="Codex subscription",
        description="Drive OpenAI Codex with your ChatGPT/Codex login (~/.codex)",
        connector="runtime",
        runtime="codex-sdk",
        self_contained=True,
        detect=_codex_ready,
        unavailable_hint=missing_extra_hint("codex-sdk", suffix="then run `codex login`"),
    ),
    ConnectionProfile(
        id="claude",
        label="Claude Agent SDK",
        description="Use your Anthropic API key via claude-agent-sdk "
        "(local Claude Code over ACP is available under 'ACP agent')",
        connector="runtime",
        runtime="claude-agent-sdk",
        self_contained=True,
        detect=_claude_agent_ready,
        unavailable_hint=missing_extra_hint(
            "claude-agent-sdk", suffix="add the Claude Code CLI, then set ANTHROPIC_API_KEY"
        ),
    ),
    ConnectionProfile(
        id="antigravity",
        label="Antigravity CLI",
        description="Use Google's Antigravity agent with your Google Sign-In",
        connector="runtime",
        runtime="antigravity-cli",
        self_contained=True,
        detect=_antigravity_cli_ready,
        unavailable_hint="install agy from https://antigravity.google/docs/cli-install",
    ),
    ConnectionProfile(
        id="grok",
        label="Grok subscription",
        description=(
            "Grok Build coding agent on your X/SuperGrok login (xAI's own harness, "
            "via the official CLI). SuperQode harness on the same plan: :grok api"
        ),
        # Subscriptions default to the vendor's own agent, matching the Codex
        # and Claude profiles. Running SuperQode's harness on this plan is the
        # explicit opt-in `:grok api [model]` (grok-cli provider).
        connector="acp",
        acp_agent="grok",
        detect=_grok_cli_ready,
        unavailable_hint="install the Grok CLI, then run `grok login` (or `grok login --device-auth`)",
    ),
]

_BY_ID = {p.id: p for p in _PROFILES}


def list_connection_profiles() -> List[ConnectionProfile]:
    """All connection profiles, in local-first display order (Local, BYOK, ACP, Codex, …)."""
    return list(_PROFILES)


def get_connection_profile(id_or_label: str) -> Optional[ConnectionProfile]:
    """Look up a profile by id (preferred) or, failing that, by label match."""
    key = (id_or_label or "").strip().lower()
    if key in _BY_ID:
        return _BY_ID[key]
    for profile in _PROFILES:
        if profile.label.lower() == key:
            return profile
    return None


def connection_profile_ids() -> List[str]:
    """Profile ids — useful for CLI ``click.Choice`` and completion."""
    return [p.id for p in _PROFILES]


__all__ = [
    "ConnectionProfile",
    "list_connection_profiles",
    "get_connection_profile",
    "connection_profile_ids",
]
