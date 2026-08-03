"""Connection profiles — the product/account-level choices in ``:connect``.

A *connection source* is what the user is connecting SuperQode to (a vendor
subscription, a BYOK provider, a local model, an ACP agent). Each
profile declares a ``connector`` that the TUI/CLI dispatches on:

    runtime      self-contained runtime (own model+auth), e.g. codex-sdk
    copilot      one Copilot subscription entry with SDK/CLI route selection
    acp          a specific ACP agent by short_name, e.g. "claude" or "grok"
    byok         the BYOK provider/model picker, optionally pinned to one provider
    local        the local provider/model picker
    acp-picker   the generic "pick any ACP agent" list
    harness-picker optional non-ACP harness integrations
    subscription-picker vendor plans authenticated by their own local CLI/OAuth state
    external-cli a local vendor TUI that does not expose ACP/headless events yet

Profiles are grouped into **menus** that form an ownership ladder, so the first
screen asks one question ("who runs the coding loop?") instead of mixing two
different axes:

    root      the three owners: a ready-made agent, a SuperQode harness, or
              a harness you build
    agents    vendor and ACP coding agents; their harness comes with them
    models    where a model comes from for a SuperQode harness: local, your
              own API key, or a plan you already pay for
    build     ways to author a repository-owned HarnessSpec

Every profile stays directly reachable by id (``:connect codex``) regardless of
which menu shows it, and the pre-ladder ids (``local``, ``byok``, ``acp``,
``subscriptions``, ``other-harnesses``) keep working.

API-key-only products do not belong in the plan menu. They are reached through
BYOK or an explicit runtime command instead.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .env_introspect import missing_extra_hint


#: The ``:connect`` screens. ``root`` is what opens by default.
CONNECT_MENU_ROOT = "root"
CONNECT_MENU_AGENTS = "agents"
CONNECT_MENU_VENDORS = "vendors"
CONNECT_MENU_ACP = "acp-agents"
CONNECT_MENU_HARNESS = "harness"
CONNECT_MENU_MODELS = "models"
CONNECT_MENU_PLAN = "plan"
CONNECT_MENU_BUILD = "build"
#: ``:connect subscriptions`` means the vendor plan list, which is what this
#: name has always described.
CONNECT_MENU_SUBSCRIPTIONS = CONNECT_MENU_VENDORS
CONNECT_MENUS = (
    CONNECT_MENU_ROOT,
    CONNECT_MENU_AGENTS,
    CONNECT_MENU_VENDORS,
    CONNECT_MENU_ACP,
    CONNECT_MENU_HARNESS,
    CONNECT_MENU_MODELS,
    CONNECT_MENU_PLAN,
    CONNECT_MENU_BUILD,
)

#: Screen names that used to exist, mapped to where their content lives now.
_LEGACY_MENUS = {
    "subscriptions": CONNECT_MENU_VENDORS,
    "acp": CONNECT_MENU_ACP,
    "byok": CONNECT_MENU_MODELS,
}

#: Each screen's parent, so Esc walks back the way the user came.
_MENU_PARENTS = {
    CONNECT_MENU_VENDORS: CONNECT_MENU_AGENTS,
    CONNECT_MENU_ACP: CONNECT_MENU_AGENTS,
    CONNECT_MENU_MODELS: CONNECT_MENU_HARNESS,
    CONNECT_MENU_PLAN: CONNECT_MENU_MODELS,
}


def parent_menu(menu: str) -> str:
    """Return the screen to show when the user backs out of ``menu``."""
    return _MENU_PARENTS.get(normalize_menu(menu), CONNECT_MENU_ROOT)


def normalize_menu(menu: str | None) -> str:
    """Return a menu that actually has rows.

    An unrecognised name would render a titled screen with nothing under it,
    which reads as a broken command rather than a stale one. Old names land on
    their successor, everything else falls back to the root question.
    """
    name = str(menu or "").strip().lower()
    if name in CONNECT_MENUS:
        return name
    return _LEGACY_MENUS.get(name, CONNECT_MENU_ROOT)


@dataclass(frozen=True)
class ConnectionProfile:
    """A product/account-level connection source shown in ``:connect``."""

    id: str
    label: str
    description: str
    connector: str  # runtime | copilot | acp | byok | local | pickers | external-cli
    group: str = ""
    menu: str = CONNECT_MENU_ROOT
    runtime: Optional[str] = None  # for connector == "runtime"
    acp_agent: Optional[str] = None  # for connector == "acp"
    byok_provider: Optional[str] = None  # for connector == "byok"
    self_contained: bool = False
    # Probe (no network) for whether this source is ready to use right now.
    detect: Optional[Callable[[], bool]] = None
    # Probe for whether the vendor's own product is present, regardless of
    # whether SuperQode can drive it yet. Somebody with Codex installed and
    # signed in is not in the same position as somebody who has never heard of
    # it, even when both are "unavailable" because our optional extra is
    # missing. Without this they sort into the same bucket, and the product a
    # user already owns ends up below a list of things they do not.
    product_detect: Optional[Callable[[], bool]] = None
    # Shown when detect() is False, to tell the user how to enable it.
    unavailable_hint: str = ""
    # Row badges. Openness is two independent facts (the harness code licence
    # and the model weights), never one bucket: Codex CLI is an open harness on
    # closed models, and an open harness mostly gets run on closed models. A
    # 2x2 would mislabel most of this list, so each row states its own facts.
    harness_openness: str = ""  # "open" | "closed"
    model_openness: str = ""  # "open weights" | "closed" | "multi-model" | "any model"
    transport: str = ""  # "ACP" | "SDK" | "CLI"

    @property
    def available(self) -> bool:
        if self.detect is None:
            return True
        try:
            return bool(self.detect())
        except Exception:  # noqa: BLE001 - availability probes must never raise
            return False

    @property
    def product_present(self) -> bool:
        """Whether the vendor product itself is installed or signed in here."""
        if self.available:
            return True
        if self.product_detect is None:
            return False
        try:
            return bool(self.product_detect())
        except Exception:  # noqa: BLE001 - detection must never raise
            return False

    @property
    def badges(self) -> List[str]:
        """Short, factual row badges in display order.

        The transport reads as "via SDK" rather than a bare acronym, because on
        its own "SDK" looks like a property of the product instead of the route
        SuperQode takes to reach it.
        """
        return [
            value
            for value in (
                f"{self.harness_openness} harness" if self.harness_openness else "",
                self.model_openness,
                f"via {self.transport}" if self.transport else "",
            )
            if value
        ]


# --- availability probes (cheap, local-only) ---------------------------------


def _codex_ready() -> bool:
    """codex-sdk extra installed AND a local Codex login present."""
    if importlib.util.find_spec("openai_codex") is None:
        return False
    return (Path.home() / ".codex" / "auth.json").exists()


def _codex_product_present() -> bool:
    """The user's own Codex is here, even if our SDK extra is not."""
    return shutil.which("codex") is not None or (Path.home() / ".codex" / "auth.json").exists()


def _copilot_product_present() -> bool:
    """A Copilot CLI or an existing Copilot login is here."""
    return (
        shutil.which("copilot") is not None or (Path.home() / ".config" / "github-copilot").exists()
    )


def _copilot_sdk_ready() -> bool:
    """The optional official GitHub Copilot SDK is importable."""
    try:
        return importlib.util.find_spec("copilot") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _copilot_acp_ready() -> bool:
    """The GitHub Copilot CLI needed for the ACP route is on PATH."""
    return shutil.which("copilot") is not None


def _copilot_subscription_ready() -> bool:
    """At least one supported Copilot subscription integration is installed."""
    return _copilot_sdk_ready() or _copilot_acp_ready()


def _kimi_code_ready() -> bool:
    """Moonshot AI's official Kimi Code CLI is available for ACP."""
    return shutil.which("kimi") is not None


def _qwen_code_ready() -> bool:
    """QwenLM's official Qwen Code CLI is available for ACP."""
    return shutil.which("qwen") is not None


def _antigravity_cli_ready() -> bool:
    """The CLI exists and meets the minimum safe subprocess version."""
    from superqode.runtime.antigravity_status import probe_antigravity_cli

    return probe_antigravity_cli().compatible


def _glm_cli_ready() -> bool:
    """The GLM ACP agent CLI is on PATH."""
    return shutil.which("glm-acp-agent") is not None


def _devin_cli_ready() -> bool:
    """Cognition's Devin CLI is installed (it owns its own sign-in)."""
    return shutil.which("devin") is not None


def _cursor_cli_ready() -> bool:
    """Cursor Agent CLI is installed; Cursor owns its local account login."""
    return shutil.which("cursor-agent") is not None


def _amp_cli_ready() -> bool:
    """Amp and its ACP adapter are installed; Amp owns account authentication."""
    return shutil.which("amp") is not None and shutil.which("acp-amp") is not None


def _droid_cli_ready() -> bool:
    """Factory Droid is installed; the CLI owns its account authentication."""
    return shutil.which("droid") is not None


def _kiro_cli_ready() -> bool:
    """Kiro CLI is installed; its OAuth/IAM login remains vendor-managed."""
    return shutil.which("kiro-cli") is not None


def _grok_cli_ready() -> bool:
    """Official Grok CLI installed with a locally managed subscription login."""
    return shutil.which("grok") is not None and (Path.home() / ".grok" / "auth.json").exists()


def _env_key_set(*names: str) -> bool:
    """Whether any of these API-key environment variables is set."""
    return any(os.environ.get(name, "").strip() for name in names)


def _zai_ready() -> bool:
    """A first-party Z.AI general-API key is available locally."""
    from .credentials import provider_api_key
    from .registry import PROVIDERS

    return bool(provider_api_key(PROVIDERS["zai"]))


_BYOK_KEY_ENVS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "ZAI_API_KEY",
)


def _byok_ready() -> bool:
    return any(os.environ.get(env) for env in _BYOK_KEY_ENVS)


# --- registry -----------------------------------------------------------------

# The root menu asks exactly one question: who runs the coding loop? Three
# answers, each a different owner, so no row overlaps another. Everything that
# used to sit here (local, ACP, BYOK, subscriptions, other harnesses) is one
# level down, where those options are finally peers of each other.
_ROOT_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="agents",
        label="Connect an existing harness",
        description="Codex, Claude Code, Copilot, Cursor, Devin and more",
        connector="agent-picker",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="models",
        label="Connect a harness with your model",
        description="Core, Workbench or a preset, running the model you choose",
        connector="harness-picker-menu",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="build",
        label="Build your own harness",
        description="Import existing config, start from a preset, or run the wizard",
        connector="build-picker",
        detect=lambda: True,
    ),
]

# Step one of the harness route: which harness runs. Core leads because it is
# the right default. The model is chosen after this, not alongside it.
_HARNESS_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="harness-core",
        label="Core (recommended)",
        description="Default harness. Small tool set, quick to start",
        connector="harness-use",
        runtime="core",
        menu=CONNECT_MENU_HARNESS,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="harness-pipy",
        label="PiPy (Pi Like Harness)",
        description="Inspired by pi. Parallel tools, session tree, no approvals or sandbox",
        connector="harness-use",
        runtime="pipy",
        menu=CONNECT_MENU_HARNESS,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="harness-workbench",
        label="Workbench",
        description="All native tools. For refactors and multi-file work",
        connector="harness-use",
        runtime="workbench",
        menu=CONNECT_MENU_HARNESS,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="harness-presets",
        label="Tuned presets",
        description="Presets for Qwen, GLM, Kimi, MiniMax, DS4 and Gemma",
        connector="harness-catalog",
        menu=CONNECT_MENU_HARNESS,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="harness-repo",
        label="This repository's harness",
        description="A harness.yaml or .superqode/harnesses spec in this project",
        connector="harness-catalog",
        menu=CONNECT_MENU_HARNESS,
        detect=lambda: True,
    ),
]

# Step two: where the model comes from. Each answers that one question.
_MODEL_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="local",
        label="Local",
        description="Ollama, LM Studio, MLX, vLLM and other local servers",
        connector="local",
        runtime="builtin",
        menu=CONNECT_MENU_MODELS,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="byok",
        label="BYOK (use your own API key)",
        description="OpenAI, Anthropic, Google, Z.AI and 40 more providers",
        connector="byok",
        runtime="builtin",
        menu=CONNECT_MENU_MODELS,
        detect=_byok_ready,
        unavailable_hint="set a provider API key (e.g. OPENAI_API_KEY), or pick one to see setup",
    ),
    ConnectionProfile(
        id="plan",
        label="Subscription",
        description="Plan credits instead of metered API billing",
        connector="plan-picker",
        runtime="builtin",
        menu=CONNECT_MENU_MODELS,
        detect=lambda: True,
    ),
]

# Plans whose credits can drive a harness through a model endpoint. Shorter
# than the agents list on purpose: most vendors sell an agent rather than model
# access, and a plan with no endpoint another harness can call does not belong
# here. Those are reachable on the agents screen instead.
_PLAN_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="plan-zai",
        label="GLM Coding Plan",
        description="Z.AI GLM models on a coding plan",
        connector="byok",
        byok_provider="zai",
        menu=CONNECT_MENU_PLAN,
        detect=_zai_ready,
        unavailable_hint="set ZAI_API_KEY from your coding plan",
    ),
    ConnectionProfile(
        id="plan-grok",
        label="Grok subscription",
        description="X / SuperGrok plan credits",
        connector="grok-api",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _grok_cli_ready() or _env_key_set("XAI_API_KEY"),
        unavailable_hint="run `grok` and sign in, or set XAI_API_KEY",
    ),
    ConnectionProfile(
        id="plan-copilot",
        label="Copilot models",
        description="Models provided by your GitHub Copilot plan",
        connector="byok",
        byok_provider="github-copilot",
        menu=CONNECT_MENU_PLAN,
        detect=_copilot_subscription_ready,
        unavailable_hint="sign in with `copilot login`",
    ),
    ConnectionProfile(
        id="plan-moonshot",
        label="Moonshot Kimi",
        description="Kimi models on a Moonshot plan",
        connector="byok",
        byok_provider="moonshot",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _env_key_set("MOONSHOT_API_KEY"),
        unavailable_hint="set MOONSHOT_API_KEY",
    ),
    ConnectionProfile(
        id="plan-qwen",
        label="Qwen / DashScope",
        description="Qwen models through DashScope",
        connector="byok",
        byok_provider="alibaba",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _env_key_set("DASHSCOPE_API_KEY", "ALIBABA_API_KEY"),
        unavailable_hint="set DASHSCOPE_API_KEY",
    ),
    ConnectionProfile(
        id="plan-opencode",
        label="OpenCode Zen",
        description="OpenCode Zen credits",
        connector="byok",
        byok_provider="opencode",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _env_key_set("OPENCODE_API_KEY"),
        unavailable_hint="set OPENCODE_API_KEY",
    ),
    ConnectionProfile(
        id="plan-ollama-cloud",
        label="Ollama Cloud",
        description="Hosted Ollama models on your account",
        connector="byok",
        byok_provider="ollama-cloud",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _env_key_set("OLLAMA_API_KEY"),
        unavailable_hint="set OLLAMA_API_KEY",
    ),
    ConnectionProfile(
        id="plan-deepseek",
        label="DeepSeek",
        description="DeepSeek platform credits",
        connector="byok",
        byok_provider="deepseek",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _env_key_set("DEEPSEEK_API_KEY"),
        unavailable_hint="set DEEPSEEK_API_KEY",
    ),
    ConnectionProfile(
        id="plan-minimax",
        label="MiniMax",
        description="MiniMax platform credits",
        connector="byok",
        byok_provider="minimax",
        menu=CONNECT_MENU_PLAN,
        detect=lambda: _env_key_set("MINIMAX_API_KEY"),
        unavailable_hint="set MINIMAX_API_KEY",
    ),
]

# Ways to author a repository-owned HarnessSpec, cheapest first. Importing what
# the repo already has beats any wizard as a first step, because it produces a
# working harness from work the user has already done.
_BUILD_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="build-import",
        label="Import what's already here",
        description="Turn existing .claude/, AGENTS.md or agent config into a portable HarnessSpec",
        connector="harness-import",
        menu=CONNECT_MENU_BUILD,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="build-preset",
        label="Start from a SuperQode preset",
        description="Clone a tuned built-in harness (core, workbench, or a model-family preset)",
        connector="harness-preset",
        menu=CONNECT_MENU_BUILD,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="build-wizard",
        label="Wizard",
        description="Answer a short series of plain questions and write a ready-to-edit spec",
        connector="harness-wizard",
        menu=CONNECT_MENU_BUILD,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="build-blank",
        label="Blank harness.yaml",
        description="Scaffold the minimum valid spec, for people who know the schema",
        connector="harness-blank",
        menu=CONNECT_MENU_BUILD,
        detect=lambda: True,
    ),
]

# Vendor and first-party coding agents. Rows carry no static group: the picker
# groups them by readiness on this machine, which is what a user can act on.
# Geography is not a decision axis for picking a coding agent.
_AGENT_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="codex",
        harness_openness="open",
        model_openness="OpenAI models",
        transport="SDK",
        label="Codex subscription",
        description="Drive OpenAI Codex with your ChatGPT/Codex login (~/.codex)",
        connector="runtime",
        menu=CONNECT_MENU_VENDORS,
        runtime="codex-sdk",
        self_contained=True,
        detect=_codex_ready,
        product_detect=_codex_product_present,
        unavailable_hint=missing_extra_hint("codex-sdk", suffix="then run `codex login`"),
    ),
    ConnectionProfile(
        id="cursor",
        harness_openness="closed",
        model_openness="multi-model",
        transport="ACP",
        label="Cursor subscription",
        description=(
            "Use Cursor Agent over ACP through the account already signed in to Cursor CLI"
        ),
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="cursor",
        self_contained=True,
        detect=_cursor_cli_ready,
        unavailable_hint=(
            "install with `curl https://cursor.com/install -fsS | bash`, "
            "then run `cursor-agent login`"
        ),
    ),
    ConnectionProfile(
        id="amp",
        harness_openness="closed",
        model_openness="multi-model",
        transport="ACP",
        label="Amp subscription",
        description="Use Amp through its local account login and ACP adapter",
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="amp",
        self_contained=True,
        detect=_amp_cli_ready,
        unavailable_hint=(
            "install Amp and run `amp login`, then install its adapter with "
            "`uv tool install acp-amp`"
        ),
    ),
    ConnectionProfile(
        id="antigravity",
        harness_openness="closed",
        model_openness="Gemini models",
        transport="CLI",
        label="Antigravity CLI",
        description="Use Google's Antigravity agent with your Google Sign-In",
        connector="runtime",
        menu=CONNECT_MENU_VENDORS,
        runtime="antigravity-cli",
        self_contained=True,
        detect=_antigravity_cli_ready,
        unavailable_hint=(
            "install or update agy from https://antigravity.google/docs/cli-install "
            "(SuperQode requires 1.1.1+)"
        ),
    ),
    ConnectionProfile(
        id="grok",
        harness_openness="closed",
        model_openness="Grok models",
        transport="ACP",
        label="Grok subscription",
        description=(
            "Grok Build coding agent on your X/SuperGrok login (xAI's own harness, "
            "over ACP). SuperQode harness on the same plan: :grok api"
        ),
        # Subscriptions default to the vendor's own agent. Running SuperQode's
        # harness on this plan is the explicit opt-in `:grok api [model]`
        # (grok-cli provider).
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="grok",
        detect=_grok_cli_ready,
        unavailable_hint="install the Grok CLI, then run `grok login` (or `grok login --device-auth`)",
    ),
    ConnectionProfile(
        id="copilot",
        harness_openness="closed",
        model_openness="multi-model",
        transport="SDK or CLI",
        label="GitHub Copilot",
        description=(
            "Use your Copilot plan; prefers the SDK for per-tool approvals and "
            "resumable sessions, otherwise uses the official CLI directly"
        ),
        connector="copilot",
        menu=CONNECT_MENU_VENDORS,
        runtime="copilot-sdk",
        acp_agent="copilot",
        self_contained=True,
        detect=_copilot_subscription_ready,
        product_detect=_copilot_product_present,
        unavailable_hint=(
            f"{missing_extra_hint('copilot-sdk')}; or run "
            "`npm install -g @github/copilot`; then run `copilot login`"
        ),
    ),
    # Gemini CLI is deliberately absent. Antigravity superseded it for
    # consumer Google accounts, so promoting it would send users to the older
    # route; it stays reachable from the ACP catalogue for anyone who needs it.
    # It is also an
    # enterprise/API-key route rather than a subscription one, and Google has
    # moved consumer plans to Antigravity. Subscriptions must never put a user
    # on metered API billing. The agent is still reachable through the ACP
    # channel with `:connect acp gemini` for anyone who still runs it.
    ConnectionProfile(
        id="devin",
        harness_openness="closed",
        model_openness="multi-model",
        transport="ACP",
        label="Devin",
        description="Cognition's Devin CLI on your Devin account, through its native ACP server",
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="devin",
        self_contained=True,
        detect=_devin_cli_ready,
        unavailable_hint=(
            "run `curl -fsSL https://cli.devin.ai/install.sh | bash`, then run `devin auth login`"
        ),
    ),
    ConnectionProfile(
        id="droid",
        harness_openness="closed",
        model_openness="any model + BYOK",
        transport="ACP",
        label="Factory Droid subscription",
        description="Use Factory Droid through its locally authenticated CLI and ACP mode",
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="droid",
        self_contained=True,
        detect=_droid_cli_ready,
        unavailable_hint="install Factory Droid, then complete the vendor CLI sign-in",
    ),
    ConnectionProfile(
        id="kiro",
        harness_openness="closed",
        model_openness="multi-model",
        transport="ACP",
        label="Kiro subscription",
        description=("Use a Kiro or Amazon Q Developer plan over ACP through Kiro CLI sign-in"),
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="kiro",
        self_contained=True,
        detect=_kiro_cli_ready,
        unavailable_hint=(
            "install Kiro CLI from https://kiro.dev/docs/cli/, then sign in "
            "with your Kiro or Amazon Q Developer account"
        ),
    ),
    ConnectionProfile(
        id="glm-cli",
        harness_openness="closed",
        model_openness="GLM models",
        transport="ACP",
        label="GLM Coding Plan",
        description="Use a paid GLM Coding Plan through its authenticated ACP agent",
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="glm",
        detect=_glm_cli_ready,
        unavailable_hint=(
            "run `npm install -g glm-acp-agent`, then set your Z.AI key for the agent"
        ),
    ),
    ConnectionProfile(
        id="qwen-code",
        harness_openness="open",
        model_openness="open weights",
        transport="ACP",
        label="Qwen Code",
        description=("QwenLM's first-party open-source coding agent through its stable ACP mode"),
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="qwen",
        self_contained=True,
        detect=_qwen_code_ready,
        unavailable_hint=("run `npm install -g @qwen-code/qwen-code`, then run `qwen auth`"),
    ),
    ConnectionProfile(
        id="kimi-code",
        harness_openness="open",
        model_openness="open weights",
        transport="ACP",
        label="Kimi Code",
        description=("Moonshot AI's first-party coding agent through its official ACP server"),
        connector="acp",
        menu=CONNECT_MENU_VENDORS,
        acp_agent="kimi",
        self_contained=True,
        detect=_kimi_code_ready,
        unavailable_hint=(
            "run `curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash`, "
            "then run `kimi` and complete `/login`"
        ),
    ),
]

# The three kinds of existing harness, as one screen you choose from. Signing
# in to a vendor plan, launching a local ACP process, and bolting on a non-ACP
# integration are different enough that mixing them into one list reads as
# noise; each category owns its own screen.
_AGENT_CATEGORY_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="agent-subscriptions",
        label="Subscriptions",
        description="Vendor plans you sign in to: Codex, Claude Code, Copilot, Cursor and more",
        connector="vendor-picker",
        menu=CONNECT_MENU_AGENTS,
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="agent-acp",
        label="ACP agents",
        description="OpenCode, Goose, Aider, Cline and every other ACP agent",
        connector="acp-picker",
        menu=CONNECT_MENU_AGENTS,
        transport="ACP",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="other-harnesses",
        label="Other harnesses",
        description="Optional non-ACP integrations, including Hugging Face Tau",
        connector="harness-picker",
        menu=CONNECT_MENU_AGENTS,
        detect=lambda: True,
    ),
]

# ``:connect acp`` predates the categories and still opens the ACP catalogue.
_ACP_MENU_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="acp",
        label="ACP agents",
        description="OpenCode, Goose, Aider, Cline and every other ACP agent",
        connector="acp-picker",
        menu=CONNECT_MENU_ACP,
        transport="ACP",
        detect=lambda: True,
    ),
]

_PROFILES: List[ConnectionProfile] = [
    *_ROOT_PROFILES,
    *_AGENT_CATEGORY_PROFILES,
    *_AGENT_PROFILES,
    *_ACP_MENU_PROFILES,
    *_HARNESS_PROFILES,
    *_MODEL_PROFILES,
    *_PLAN_PROFILES,
    *_BUILD_PROFILES,
]

#: Pre-ladder alias kept for callers that import the old list name.
_SUBSCRIPTION_PROFILES = _AGENT_PROFILES

# Compatibility-only profiles remain directly resolvable without appearing in
# the Connect picker or its completion list.
_LEGACY_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="copilot-cli",
        label="GitHub Copilot CLI",
        description="Official Copilot CLI over ACP; also available in the ACP picker",
        connector="acp",
        acp_agent="copilot",
        self_contained=True,
        detect=_copilot_acp_ready,
        unavailable_hint="run `npm install -g @github/copilot`, then run `copilot login`",
    ),
    ConnectionProfile(
        id="copilot-acp",
        label="GitHub Copilot ACP",
        description="Older alias for the GitHub Copilot CLI route",
        connector="acp",
        acp_agent="copilot",
        detect=_copilot_acp_ready,
        unavailable_hint="run `npm install -g @github/copilot`, then run `copilot login`",
    ),
    ConnectionProfile(
        id="claude-api",
        label="Claude Agent SDK (API key)",
        description="Compatibility route for the Anthropic API-key runtime; prefer BYOK",
        connector="runtime",
        runtime="claude-agent-sdk",
        self_contained=True,
        detect=lambda: importlib.util.find_spec("claude_agent_sdk") is not None
        and bool(os.environ.get("ANTHROPIC_API_KEY")),
        unavailable_hint=missing_extra_hint(
            "claude-agent-sdk", suffix="then set ANTHROPIC_API_KEY"
        ),
    ),
    ConnectionProfile(
        id="zai",
        label="Z.AI GLM API",
        description="Compatibility route for the Z.AI general API; prefer BYOK",
        connector="byok",
        runtime="builtin",
        byok_provider="zai",
        detect=_zai_ready,
        unavailable_hint="set ZAI_API_KEY",
    ),
    # `:connect subscriptions` predates the ownership ladder and opened the
    # vendor list directly. Keep that shortcut exact for scripts and muscle
    # memory even though new users reach it through Existing harnesses.
    ConnectionProfile(
        id="subscriptions",
        label="Subscriptions",
        description="Vendor coding agents you sign in to with an existing plan",
        connector="vendor-picker",
        detect=lambda: True,
    ),
]

_BY_ID = {p.id: p for p in (*_PROFILES, *_LEGACY_PROFILES)}

_BY_MENU = {
    CONNECT_MENU_ROOT: _ROOT_PROFILES,
    CONNECT_MENU_AGENTS: _AGENT_CATEGORY_PROFILES,
    CONNECT_MENU_VENDORS: _AGENT_PROFILES,
    CONNECT_MENU_ACP: _ACP_MENU_PROFILES,
    CONNECT_MENU_HARNESS: _HARNESS_PROFILES,
    CONNECT_MENU_MODELS: _MODEL_PROFILES,
    CONNECT_MENU_PLAN: _PLAN_PROFILES,
    CONNECT_MENU_BUILD: _BUILD_PROFILES,
}

#: Human titles and subtitles for each ``:connect`` screen.
CONNECT_MENU_TITLES = {
    CONNECT_MENU_ROOT: (
        "Connect",
        "Who should run the coding loop?",
    ),
    CONNECT_MENU_AGENTS: (
        "Existing harnesses",
        "Each brings its own tools and model. Pick how you connect.",
    ),
    CONNECT_MENU_VENDORS: (
        "Subscriptions",
        "Vendor plans you sign in to with your own account.",
    ),
    CONNECT_MENU_ACP: (
        "ACP agents",
        "Agents that speak Agent Client Protocol.",
    ),
    CONNECT_MENU_HARNESS: (
        "Select a harness",
        "Step 1 of 2. You choose the model next.",
    ),
    CONNECT_MENU_MODELS: (
        "Select a model",
        "Step 2 of 2. Where the model comes from.",
    ),
    CONNECT_MENU_PLAN: (
        "Subscription",
        "Plans whose credits can run the harness you picked.",
    ),
    CONNECT_MENU_BUILD: (
        "Build your own harness",
        "Saved as YAML in this repository.",
    ),
}


def list_connection_profiles(menu: Optional[str] = None) -> List[ConnectionProfile]:
    """Profiles for one ``:connect`` menu, or every visible profile.

    ``menu=None`` returns the flat list (root, agents, models, build) used for
    completion and name lookup. Pass a menu id to get exactly what that screen
    shows, in display order.
    """
    if menu is None:
        return list(_PROFILES)
    return list(_BY_MENU.get(menu, ()))


def get_connection_profile(id_or_label: str) -> Optional[ConnectionProfile]:
    """Look up a profile by id (preferred) or, failing that, by label match."""
    key = (id_or_label or "").strip().lower()
    if key in _BY_ID:
        return _BY_ID[key]
    for profile in _PROFILES:
        if profile.label.lower() == key:
            return profile
    return None


def connection_profile_ids(
    *, include_legacy: bool = False, menu: Optional[str] = None
) -> List[str]:
    """Visible profile ids, optionally scoped to a menu or including aliases."""
    profiles = list_connection_profiles(menu)
    if include_legacy and menu is None:
        profiles = [*profiles, *_LEGACY_PROFILES]
    return [p.id for p in profiles]


#: Readiness buckets for the agents screen, in display order. Grouping by what
#: is usable right now beats grouping by vendor or region, because readiness is
#: the only axis the user can act on without leaving the picker.
AGENT_READINESS_GROUPS = ("Ready now", "One step away", "Installable", "More")

#: Connectors that navigate to another screen rather than connecting anything.
#: They are pinned last so they never compete with named products for the top
#: of the list, and they carry no readiness of their own.
_BROWSE_CONNECTORS = frozenset({"acp-picker", "harness-picker", "plan-picker"})


def group_profiles_by_readiness(
    profiles: List[ConnectionProfile],
) -> List[tuple[str, List[ConnectionProfile]]]:
    """Bucket agent profiles by whether they can be used on this machine.

    "One step away" is a profile whose product is installed but not yet
    authenticated, which the detect probes report as unavailable with a hint
    that mentions signing in rather than installing.
    """
    buckets: dict[str, List[ConnectionProfile]] = {name: [] for name in AGENT_READINESS_GROUPS}
    for profile in profiles:
        if profile.connector in _BROWSE_CONNECTORS:
            buckets["More"].append(profile)
            continue
        if profile.available:
            buckets["Ready now"].append(profile)
            continue
        if profile.product_present:
            # They own it already; only our side is missing. Sorting this with
            # products they have never installed buries the fastest option.
            buckets["One step away"].append(profile)
            continue
        hint = (profile.unavailable_hint or "").lower()
        needs_install = any(
            token in hint for token in ("install", "npm ", "curl ", "brew ", "uv tool")
        )
        signin_only = ("login" in hint or "auth" in hint or "sign in" in hint) and not needs_install
        buckets["One step away" if signin_only else "Installable"].append(profile)
    return [(name, buckets[name]) for name in AGENT_READINESS_GROUPS if buckets[name]]


def grouped_menu_profiles(menu: str) -> List[tuple[str, List[ConnectionProfile]]]:
    """Return one screen's profiles in the order they are drawn.

    Every screen is flat and in registry order. Sorting the subscription list
    by readiness moved products around depending on what happened to be
    installed, so the row a user reached for was never in the same place twice;
    the setup each one still needs is on its own row instead.

    Keeping this in one place matters because the picker's keyboard navigation
    and its renderer must agree on the order, or the highlight lands on a row
    other than the one the arrow keys appeared to move to.
    """
    name = normalize_menu(menu)
    profiles = list_connection_profiles(name)

    return [("", list(profiles))]


def display_ordered_profiles(menu: str) -> List[ConnectionProfile]:
    """Flatten :func:`grouped_menu_profiles` into on-screen order.

    Selection and navigation index this, so it has to be the same sequence the
    renderer draws, including any rows built dynamically for that screen.
    """
    return [profile for _group, profiles in grouped_menu_profiles(menu) for profile in profiles]


def detected_sources(repo_root: Optional[Path] = None, *, limit: int = 5) -> List[str]:
    """Short labels for what is already usable here, for the connect header.

    Every probe is local and cheap (``which``, a file check, an env var). No
    network calls: this renders on the first frame of ``:connect``, and a slow
    header would make the picker feel broken.
    """
    agents = [
        profile.label.replace(" subscription", "")
        for profile in _AGENT_PROFILES
        if profile.connector not in _BROWSE_CONNECTORS and profile.available
    ]

    extras: List[str] = []
    try:
        from superqode.local.servers import SPECS, ServerManager

        manager = ServerManager()
        engines = [engine for engine in SPECS if manager.is_installed(engine)]
        if engines:
            extras.append(
                engines[0] if len(engines) == 1 else f"{engines[0]} +{len(engines) - 1} local"
            )
    except Exception:  # noqa: BLE001 - a detection header must never break connect
        pass

    keyed = [env for env in _BYOK_KEY_ENVS if os.environ.get(env)]
    if keyed:
        extras.append(f"{len(keyed)} API key{'s' if len(keyed) > 1 else ''}")

    root = repo_root or Path.cwd()
    for marker in (".claude", "AGENTS.md", "CLAUDE.md", ".cursor"):
        try:
            if (root / marker).exists():
                extras.append(f"{marker} in this repo")
                break
        except OSError:
            break

    # Local engines, keys and repo config are the interesting finds, so they
    # keep their slots while a long agent list gets summarised.
    budget = max(1, limit - len(extras))
    if len(agents) > budget:
        agents = [*agents[: budget - 1], f"+{len(agents) - budget + 1} more agents"]
    return [*agents, *extras]


__all__ = [
    "AGENT_READINESS_GROUPS",
    "CONNECT_MENUS",
    "CONNECT_MENU_AGENTS",
    "CONNECT_MENU_BUILD",
    "CONNECT_MENU_ACP",
    "CONNECT_MENU_HARNESS",
    "CONNECT_MENU_MODELS",
    "CONNECT_MENU_PLAN",
    "CONNECT_MENU_ROOT",
    "CONNECT_MENU_SUBSCRIPTIONS",
    "CONNECT_MENU_VENDORS",
    "CONNECT_MENU_TITLES",
    "ConnectionProfile",
    "detected_sources",
    "group_profiles_by_readiness",
    "list_connection_profiles",
    "normalize_menu",
    "parent_menu",
    "get_connection_profile",
    "connection_profile_ids",
]
