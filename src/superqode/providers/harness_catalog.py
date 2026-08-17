"""Join table for Open/Closed connect membership (openness + auth modes).

This is not a fifth runtime registry. Profiles, Hub, ACP, and
``HarnessDefinition`` remain the implementations. v1 the catalog drives Open
and Closed membership only; Subscriptions and ACP keep their existing
renderers. ``connect_menus()`` is a consistency helper, not a TUI renderer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

from superqode.providers.registry import PROVIDERS, ProviderCategory

AuthMode = str  # "subscription" | "acp" | "byok" | "local"
Openness = str  # "open" | "closed" | "unknown"
AfterAuth = str  # switch-and-model | acp-attach | vendor-key-acp | vendor-key-cli | vendor-key-rpc | setup-card | inspect

CONNECT_MENU_DEFAULT = "v1"
CONNECT_MENU_VALUES = frozenset({"v1", "v2"})
CONNECT_MENU_ENV = "SUPERQODE_CONNECT_MENU"
_USER_CONFIG_PATH = Path.home() / ".superqode" / "config.json"


@dataclass(frozen=True)
class HarnessAuthSpec:
    """One supported way to authenticate a known harness."""

    mode: AuthMode
    connector: str  # existing ConnectionProfile.connector values
    profile_id: str  # :connect <id> / --connect <id>
    after_auth: AfterAuth
    env_vars: Tuple[str, ...] = ()
    optional_env: Tuple[str, ...] = ()
    base_url_env: Optional[str] = None  # process inherit for DSH, not ProviderDef
    default_base_url: Optional[str] = None
    byok_provider: Optional[str] = None
    # None = all native picker ids (do not enumerate; they drift).
    # () = this mode is not offered. Non-empty = allow-list.
    byok_providers: Optional[Tuple[str, ...]] = ()
    local_providers: Optional[Tuple[str, ...]] = ()
    detect: Optional[Callable[[], bool]] = None
    unavailable_hint: str = ""
    notes: str = ""
    inject_env: bool = False  # Closed Factory: child-only extra env


@dataclass(frozen=True)
class HarnessCatalogEntry:
    id: str
    label: str
    description: str
    openness: Openness
    license: str = ""
    repository: str = ""
    homepage: str = ""
    auth: Tuple[HarnessAuthSpec, ...] = ()
    harness_id: Optional[str] = None  # HarnessDefinition.id when SuperQode-hosted
    acp_agent: Optional[str] = None
    hub_id: Optional[str] = None  # key into _OPENNESS_BY_ID
    readiness: str = "ready"  # ready | setup-required | not-supported
    support_note: str = ""
    vendor_owned: bool = True  # True if a third party owns the loop
    wired: bool = False  # False until the connect path exists
    list_visible: bool = False  # False = catalog-only (ZCode, unwired)
    show_in_closed: bool = False  # reserved; ZCode stays False until a surface ships
    show_in_open: bool = False  # unused; no inspect-only Open rows

    def modes(self) -> Tuple[str, ...]:
        return tuple(spec.mode for spec in self.auth)

    def connect_menus(self) -> Tuple[str, ...]:
        """Menus this entry *belongs* on. The TUI still filters with list_entries()."""
        menus = []
        if "subscription" in self.modes():
            menus.append("vendors")
        if "acp" in self.modes():
            menus.append("acp")
        keyish = bool({"byok", "local"} & set(self.modes()))
        if self.openness == "open" and (keyish or self.show_in_open):
            menus.append("open")
        if self.openness == "closed" and (keyish or self.show_in_closed):
            menus.append("closed")
        return tuple(menus)


def list_entries(menu: str) -> list[HarnessCatalogEntry]:
    """What the Open/Closed TUI actually draws."""
    return [e for e in HARNESS_CATALOG if menu in e.connect_menus() and e.list_visible]


def get_entry(entry_id: str) -> Optional[HarnessCatalogEntry]:
    """Return the catalog row with this id, or None."""
    for entry in HARNESS_CATALOG:
        if entry.id == entry_id:
            return entry
    return None


def parse_connect_menu_flag(
    env: Mapping[str, str] | None = None,
    *,
    config_path: Path | None = None,
) -> str:
    """Resolve ``v1``/``v2``: env overrides config.json overrides the compiled default.

    Reads ``connect_menu`` from raw JSON so unknown keys are not dropped by the
    typed Config schema. Invalid values fall through. The TUI does not consult
    this in PR 1.
    """
    source = os.environ if env is None else env
    raw = str(source.get(CONNECT_MENU_ENV, "") or "").strip().lower()
    if raw in CONNECT_MENU_VALUES:
        return raw
    path = _USER_CONFIG_PATH if config_path is None else config_path
    from_file = _connect_menu_from_config(path)
    if from_file is not None:
        return from_file
    return CONNECT_MENU_DEFAULT


def _connect_menu_from_config(path: Path) -> Optional[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    value = str(data.get("connect_menu", "") or "").strip().lower()
    return value if value in CONNECT_MENU_VALUES else None


def _local_ids_with_base_url() -> Tuple[str, ...]:
    """Local engines SuperQode already knows an OpenAI-compat URL for."""
    return tuple(
        pid
        for pid, pdef in PROVIDERS.items()
        if pdef.category == ProviderCategory.LOCAL
        and (pdef.base_url_env or pdef.default_base_url)
        and pid != "ollama-cloud"
    )


# Explicit OpenAI-compat locals that resolve a base_url. MLX / llama.cpp are
# included because their ProviderDefs expose a URL.
_DSH_LOCAL_PROVIDERS = _local_ids_with_base_url()

# Documented LangChain extras: langchain-ollama, langchain-openai.
_DEEPAGENTS_LOCAL_PROVIDERS = (
    "ollama",
    "lmstudio",
    "mlx",
    "llamacpp",
    "openai-compatible",
)

_PRIME_BYOK_PROVIDERS = ("anthropic", "openai", "google", "groq", "openrouter")
_QWEN_LOCAL_PROVIDERS = ("ollama", "vllm", "lmstudio")
_POOLSIDE_LOCAL_PROVIDERS = ("ollama", "vllm", "llamacpp")


def _key_auth(
    profile_id: str,
    after_auth: AfterAuth,
    *,
    connector: str = "key-harness",
    byok_providers: Optional[Tuple[str, ...]] = None,
    local_providers: Optional[Tuple[str, ...]] = None,
    env_vars: Tuple[str, ...] = (),
    optional_env: Tuple[str, ...] = (),
    base_url_env: Optional[str] = None,
    inject_env: bool = False,
) -> Tuple[HarnessAuthSpec, ...]:
    return (
        HarnessAuthSpec(
            mode="byok",
            connector=connector,
            profile_id=profile_id,
            after_auth=after_auth,
            env_vars=env_vars,
            optional_env=optional_env,
            base_url_env=base_url_env,
            byok_providers=byok_providers,
            local_providers=(),
            inject_env=inject_env,
        ),
        HarnessAuthSpec(
            mode="local",
            connector=connector,
            profile_id=profile_id,
            after_auth=after_auth,
            env_vars=env_vars,
            optional_env=optional_env,
            base_url_env=base_url_env,
            byok_providers=(),
            local_providers=local_providers,
            inject_env=inject_env,
        ),
    )


def _plan_auth(
    profile_id: str,
    *,
    connector: str,
    include_acp: bool = False,
) -> Tuple[HarnessAuthSpec, ...]:
    specs = [
        HarnessAuthSpec(
            mode="subscription",
            connector=connector,
            profile_id=profile_id,
            after_auth="acp-attach" if connector == "acp" else "inspect",
        )
    ]
    if include_acp:
        specs.append(
            HarnessAuthSpec(
                mode="acp",
                connector="acp",
                profile_id=profile_id,
                after_auth="acp-attach",
            )
        )
    return tuple(specs)


def _vendor_key_auth(
    profile_id: str,
    after_auth: AfterAuth,
    *,
    connector: str,
    env_vars: Tuple[str, ...],
    optional_env: Tuple[str, ...] = (),
    inject_env: bool = False,
) -> Tuple[HarnessAuthSpec, ...]:
    # byok_providers=() hides the native model picker; the key is the vendor's.
    return (
        HarnessAuthSpec(
            mode="byok",
            connector=connector,
            profile_id=profile_id,
            after_auth=after_auth,
            env_vars=env_vars,
            optional_env=optional_env,
            byok_providers=(),
            local_providers=(),
            inject_env=inject_env,
        ),
    )


HARNESS_CATALOG: Tuple[HarnessCatalogEntry, ...] = (
    HarnessCatalogEntry(
        id="tau",
        label="Tau (Hugging Face)",
        description="Open-source harness. Connect with your API key or a local model.",
        openness="open",
        license="MIT",
        repository="https://github.com/huggingface/tau",
        auth=_key_auth("tau", "switch-and-model", byok_providers=None, local_providers=None),
        harness_id="tau",
        hub_id="tau",
        vendor_owned=True,
        wired=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="deepseek-harness",
        label="DeepSeek Harness",
        description="Open-source DeepSeek loop. DeepSeek BYOK or an OpenAI-compat local URL.",
        openness="open",
        license="MIT",
        repository="https://github.com/deepseek-ai/deepseek-harness",
        auth=_key_auth(
            "deepseek-harness",
            "switch-and-model",
            byok_providers=("deepseek",),
            local_providers=_DSH_LOCAL_PROVIDERS,
            base_url_env="DEEPSEEK_BASE_URL",
        ),
        harness_id="deepseek-harness",
        hub_id="deepseek-harness",
        vendor_owned=True,
        wired=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="deepagents",
        label="DeepAgents (SDK)",
        description="LangChain DeepAgents SDK on Anthropic, Google, or a documented local extra.",
        openness="open",
        license="MIT",
        repository="https://github.com/langchain-ai/deepagents",
        auth=_key_auth(
            "deepagents",
            "switch-and-model",
            byok_providers=("anthropic", "google"),
            local_providers=_DEEPAGENTS_LOCAL_PROVIDERS,
        ),
        harness_id="deepagents",
        hub_id="deepagents",
        vendor_owned=False,
        wired=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="deepagents-code",
        label="Deep Agents Code",
        description="LangChain's terminal coding agent over its own ACP server.",
        openness="open",
        license="MIT",
        repository="https://github.com/langchain-ai/deepagents",
        auth=_plan_auth("deepagents-code", connector="acp", include_acp=True),
        acp_agent="deepagents-code",
        hub_id="deepagents-code",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="opencode",
        label="OpenCode",
        description="Open-source harness over ACP. The agent keeps its own login.",
        openness="open",
        license="MIT",
        repository="https://github.com/opencode-ai/opencode",
        auth=(
            HarnessAuthSpec(
                mode="acp",
                connector="acp",
                profile_id="opencode",
                after_auth="acp-attach",
            ),
        ),
        acp_agent="opencode",
        hub_id="acp:opencode",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="opencode-key",
        label="OpenCode (API key)",
        description="Attach OpenCode over ACP after you provide a key or a local model.",
        openness="open",
        license="MIT",
        repository="https://github.com/opencode-ai/opencode",
        auth=_key_auth(
            "opencode-key",
            "acp-attach",
            byok_providers=None,
            local_providers=None,
        ),
        acp_agent="opencode",
        hub_id="acp:opencode",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="prime-agent",
        label="Prime Agent (RLM)",
        description="Prime Intellect's RLM coding agent on a subscription provider.",
        openness="open",
        license="MIT",
        repository="https://github.com/PrimeIntellect-ai/prime-agent",
        auth=_plan_auth("prime-agent", connector="prime-rpc", include_acp=True),
        acp_agent="prime-agent",
        hub_id="prime-agent",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="prime-agent-key",
        label="Prime Agent (API key)",
        description="Prime Agent with a provider key or a local model. Prime owns the loop.",
        openness="open",
        license="MIT",
        repository="https://github.com/PrimeIntellect-ai/prime-agent",
        auth=_key_auth(
            "prime-agent-key",
            "vendor-key-rpc",
            connector="key-harness",
            byok_providers=_PRIME_BYOK_PROVIDERS,
            local_providers=_DSH_LOCAL_PROVIDERS,
        ),
        hub_id="prime-agent",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="jcode",
        label="jcode",
        description="Open-source harness. Install and configure jcode; SuperQode cannot launch it yet.",
        openness="open",
        license="MIT",
        repository="https://github.com/1jehuang/jcode",
        auth=(
            HarnessAuthSpec(
                mode="byok",
                connector="key-harness",
                profile_id="jcode",
                after_auth="setup-card",
                byok_providers=(),
                local_providers=(),
            ),
        ),
        hub_id="ecosystem:jcode",
        readiness="setup-required",
        vendor_owned=True,
        show_in_open=True,
    ),
    HarnessCatalogEntry(
        id="droid",
        label="Factory Droid",
        description="Factory Droid through its locally authenticated CLI and ACP mode.",
        openness="closed",
        auth=_plan_auth("droid", connector="acp", include_acp=True),
        acp_agent="droid",
        hub_id="droid",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="droid-key",
        label="Factory Droid (API key)",
        description="Factory Droid with FACTORY_API_KEY. Not the Droid CLI login.",
        openness="closed",
        auth=_vendor_key_auth(
            "droid-key",
            "vendor-key-acp",
            connector="vendor-key",
            env_vars=("FACTORY_API_KEY",),
            inject_env=True,
        ),
        acp_agent="droid",
        hub_id="droid",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="grok",
        label="Grok",
        description="Grok Build on your X/SuperGrok login over ACP.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/xai-org/grok-build",
        auth=_plan_auth("grok", connector="acp", include_acp=True),
        acp_agent="grok",
        hub_id="grok",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="grok-key",
        label="Grok Build (API key)",
        description="Grok Build with GROK_CODE_XAI_API_KEY or a local OpenAI-compat endpoint.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/xai-org/grok-build",
        auth=_key_auth(
            "grok-key",
            "acp-attach",
            env_vars=("GROK_CODE_XAI_API_KEY",),
            optional_env=("XAI_API_KEY",),
            byok_providers=None,
            local_providers=_DSH_LOCAL_PROVIDERS,
        ),
        acp_agent="grok",
        hub_id="grok",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="muse",
        label="Muse Code",
        description="Meta's Muse Code agent with your Meta account sign-in.",
        openness="closed",
        auth=_plan_auth("muse", connector="external-cli"),
        hub_id="muse",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="muse-key",
        label="Muse Code (API key)",
        description="Muse Code with META_API_KEY. Not SuperQode's Meta BYOK provider.",
        openness="closed",
        auth=_vendor_key_auth(
            "muse-key",
            "vendor-key-cli",
            connector="external-cli",
            env_vars=("META_API_KEY",),
            inject_env=True,
        ),
        hub_id="muse",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="zcode",
        label="ZCode",
        description="Z.AI desktop harness. Catalogued until a SuperQode-supported surface exists.",
        openness="closed",
        auth=(),
        hub_id="ecosystem:zcode",
        readiness="not-supported",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="qwen-code",
        label="Qwen Code",
        description="QwenLM's first-party open-source coding agent through its ACP mode.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/QwenLM/qwen-code",
        auth=_plan_auth("qwen-code", connector="acp", include_acp=True),
        acp_agent="qwen",
        hub_id="qwen-code",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="qwen-code-key",
        label="Qwen Code (API key)",
        description="Qwen Code with a DashScope key or an OpenAI-compat local endpoint.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/QwenLM/qwen-code",
        auth=_key_auth(
            "qwen-code-key",
            "acp-attach",
            env_vars=("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
            byok_providers=("alibaba",),
            local_providers=_QWEN_LOCAL_PROVIDERS,
        ),
        acp_agent="qwen",
        hub_id="qwen-code",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="fast-agent",
        label="fast-agent",
        description="Open-source ACP agent. Key or local attach ships in a later PR.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/evalstate/fast-agent",
        auth=(
            HarnessAuthSpec(
                mode="acp",
                connector="acp",
                profile_id="fast-agent",
                after_auth="acp-attach",
            ),
            *_key_auth(
                "fast-agent",
                "acp-attach",
                byok_providers=None,
                local_providers=None,
            ),
        ),
        acp_agent="fast-agent",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="pi",
        label="Pi",
        description="Minimal open-source harness. Key or local attach ships in a later PR.",
        openness="open",
        license="MIT",
        repository="https://github.com/earendil-works/pi",
        auth=(
            HarnessAuthSpec(
                mode="acp",
                connector="acp",
                profile_id="pi",
                after_auth="acp-attach",
            ),
            *_key_auth(
                "pi",
                "acp-attach",
                byok_providers=None,
                local_providers=None,
            ),
        ),
        acp_agent="pi",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="qoder-key",
        label="Qoder CLI (API key)",
        description="Proprietary Qoder CLI with QODER_PERSONAL_ACCESS_TOKEN.",
        openness="closed",
        auth=_vendor_key_auth(
            "qoder-key",
            "vendor-key-acp",
            connector="vendor-key",
            env_vars=("QODER_PERSONAL_ACCESS_TOKEN",),
            inject_env=True,
        ),
        acp_agent="qoder",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="poolside-key",
        label="Poolside (API key)",
        description="Poolside with POOLSIDE_API_KEY or a local OpenAI-compat endpoint.",
        openness="closed",
        auth=_key_auth(
            "poolside-key",
            "vendor-key-acp",
            connector="vendor-key",
            env_vars=("POOLSIDE_API_KEY",),
            optional_env=("POOLSIDE_STANDALONE_BASE_URL",),
            base_url_env="POOLSIDE_STANDALONE_BASE_URL",
            byok_providers=("poolside",),
            local_providers=_POOLSIDE_LOCAL_PROVIDERS,
            inject_env=True,
        ),
        acp_agent="poolside",
        vendor_owned=True,
    ),
    HarnessCatalogEntry(
        id="codex",
        label="Codex",
        description="Drive OpenAI Codex with your ChatGPT/Codex login.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/openai/codex",
        auth=_plan_auth("codex", connector="runtime"),
        hub_id="codex",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="cursor",
        label="Cursor",
        description="Cursor Agent over ACP through the account signed in to Cursor CLI.",
        openness="closed",
        auth=_plan_auth("cursor", connector="acp", include_acp=True),
        acp_agent="cursor",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="amp",
        label="Amp",
        description="Amp through its local account login and ACP adapter.",
        openness="closed",
        auth=_plan_auth("amp", connector="acp", include_acp=True),
        acp_agent="amp",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="antigravity",
        label="Antigravity CLI",
        description="Google's Antigravity agent with your Google Sign-In.",
        openness="closed",
        auth=_plan_auth("antigravity", connector="runtime"),
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="copilot",
        label="GitHub Copilot",
        description="Use your Copilot plan; SDK when available, otherwise the official CLI.",
        openness="closed",
        auth=_plan_auth("copilot", connector="copilot", include_acp=True),
        acp_agent="copilot",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="devin",
        label="Devin",
        description="Cognition's Devin CLI on your Devin account, through its native ACP server.",
        openness="closed",
        auth=_plan_auth("devin", connector="acp", include_acp=True),
        acp_agent="devin",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="kiro",
        label="Kiro",
        description="A Kiro or Amazon Q Developer plan over ACP through Kiro CLI sign-in.",
        openness="closed",
        auth=_plan_auth("kiro", connector="acp", include_acp=True),
        acp_agent="kiro",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="glm-cli",
        label="GLM Coding Plan",
        description="A paid GLM Coding Plan through its authenticated ACP agent.",
        openness="closed",
        auth=_plan_auth("glm-cli", connector="acp", include_acp=True),
        acp_agent="glm",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="kimi-code",
        label="Kimi Code",
        description="Moonshot AI's first-party coding agent through its official ACP server.",
        openness="open",
        license="MIT",
        repository="https://github.com/MoonshotAI/kimi-code",
        auth=_plan_auth("kimi-code", connector="acp", include_acp=True),
        acp_agent="kimi",
        hub_id="kimi-code",
        vendor_owned=True,
        wired=True,
    ),
)


__all__ = [
    "AfterAuth",
    "AuthMode",
    "CONNECT_MENU_DEFAULT",
    "CONNECT_MENU_ENV",
    "CONNECT_MENU_VALUES",
    "HARNESS_CATALOG",
    "HarnessAuthSpec",
    "HarnessCatalogEntry",
    "Openness",
    "get_entry",
    "list_entries",
    "parse_connect_menu_flag",
]
