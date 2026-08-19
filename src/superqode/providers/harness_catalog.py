"""Join table for Open/Closed connect membership (openness + auth modes).

This is not a fifth runtime registry. Profiles, Hub, ACP, and
``HarnessDefinition`` remain the implementations. v1 the catalog drives Open
and Closed membership only; Subscriptions and ACP keep their existing
renderers. ``connect_menus()`` is a consistency helper, not a TUI renderer.
"""

from __future__ import annotations

import json
import os
import shutil
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

#: Parsed ``connect_menu`` per config file, keyed by path and invalidated by
#: (mtime, size). Editing the file still takes effect on the next read.
_CONNECT_MENU_CACHE: dict[Path, Tuple[Tuple[int, int], Optional[str]]] = {}


def user_config_path() -> Path:
    """``~/.superqode/config.json``, resolved once per call rather than at import.

    The TUI writes this file through the same path, so both sides must agree
    even when ``HOME`` is redirected, as it is under test.
    """
    return Path.home() / ".superqode" / "config.json"


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


def auth_allowlist(entry: HarnessCatalogEntry, mode: str) -> Optional[Tuple[str, ...]]:
    """Picker ids for ``mode``. ``None`` = all native; ``()`` = hide; else allow-list."""
    spec = next((item for item in entry.auth if item.mode == mode), None)
    if spec is None:
        return ()
    return spec.byok_providers if mode == "byok" else spec.local_providers


def parse_connect_menu_flag(
    env: Mapping[str, str] | None = None,
    *,
    config_path: Path | None = None,
) -> str:
    """Resolve ``v1``/``v2``: env overrides config.json overrides the compiled default.

    Reads ``connect_menu`` from raw JSON so unknown keys are not dropped by the
    typed Config schema. Invalid values fall through.
    """
    source = os.environ if env is None else env
    raw = str(source.get(CONNECT_MENU_ENV, "") or "").strip().lower()
    if raw in CONNECT_MENU_VALUES:
        return raw
    path = user_config_path() if config_path is None else config_path
    from_file = _connect_menu_from_config(path)
    if from_file is not None:
        return from_file
    return CONNECT_MENU_DEFAULT


def _connect_menu_from_config(path: Path) -> Optional[str]:
    """Read ``connect_menu``, caching per (path, mtime, size).

    ``connect_menu_version()`` is consulted while drawing every picker row, so
    an uncached read means a stat and a parse per keystroke. The environment is
    still checked live above, which is what tests vary.
    """
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    cached = _CONNECT_MENU_CACHE.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    value = _read_connect_menu(path)
    _CONNECT_MENU_CACHE[path] = (stamp, value)
    return value


def _read_connect_menu(path: Path) -> Optional[str]:
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

# Documented LangChain extras: langchain-ollama (Ollama) and langchain-openai
# (LM Studio, MLX, llama.cpp, and generic OpenAI-compat endpoints).
_DEEPAGENTS_LOCAL_PROVIDERS = (
    "ollama",
    "lmstudio",
    "mlx",
    "llamacpp",
    "openai-compatible",
)

_PRIME_BYOK_PROVIDERS = ("anthropic", "openai", "google", "groq", "openrouter")

# Local engines SuperQode can hand Prime a base URL for. Narrower than the
# DeepSeek Harness list: Prime is pointed at an endpoint by registering it in
# its own models.json, so a provider with no resolvable URL cannot be offered.
_PRIME_LOCAL_PROVIDERS = ("ollama", "lmstudio", "llamacpp", "vllm", "mlx")
_QWEN_LOCAL_PROVIDERS = ("ollama", "vllm", "lmstudio")
_POOLSIDE_LOCAL_PROVIDERS = ("ollama", "vllm", "llamacpp")


def _key_auth(
    profile_id: str,
    after_auth: AfterAuth,
    *,
    connector: str = "key-harness",
    byok_provider: Optional[str] = None,
    byok_providers: Optional[Tuple[str, ...]] = None,
    local_providers: Optional[Tuple[str, ...]] = None,
    env_vars: Tuple[str, ...] = (),
    optional_env: Tuple[str, ...] = (),
    base_url_env: Optional[str] = None,
    inject_env: bool = False,
    detect: Optional[Callable[[], bool]] = None,
    unavailable_hint: str = "",
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
            byok_provider=byok_provider,
            byok_providers=byok_providers,
            local_providers=(),
            inject_env=inject_env,
            detect=detect,
            unavailable_hint=unavailable_hint,
        ),
        HarnessAuthSpec(
            mode="local",
            connector=connector,
            profile_id=profile_id,
            after_auth=after_auth,
            env_vars=env_vars,
            optional_env=optional_env,
            base_url_env=base_url_env,
            byok_provider=byok_provider,
            byok_providers=(),
            local_providers=local_providers,
            inject_env=inject_env,
            detect=detect,
            unavailable_hint=unavailable_hint,
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


def _droid_binary_present() -> bool:
    """Factory Droid CLI is on PATH. Same probe as the subscription row."""
    return shutil.which("droid") is not None


def _junie_binary_present() -> bool:
    """Junie CLI is on PATH. Same probe as the subscription row."""
    return shutil.which("junie") is not None


def _prime_agent_present() -> bool:
    """Prime Agent's own binary lookup, which is not a bare PATH name."""
    try:
        from superqode.providers import prime_agent

        return bool(prime_agent.is_installed())
    except Exception:  # noqa: BLE001 - a probe must never break the picker
        return False


def acp_agent_binary_present(short_name: str) -> bool:
    """Whether the command this ACP agent launches with is on PATH.

    Read from the agent's own registry entry rather than hand-written per row:
    the launcher is not always the obvious name (``pi`` attaches through
    ``pi-acp``, fast-agent through ``uvx``), and a guess would report a row as
    ready that cannot start.
    """
    try:
        from superqode.agents.acp_registry import get_registry_agent_by_short_name

        agent = get_registry_agent_by_short_name(short_name)
    except Exception:  # noqa: BLE001 - a probe must never break the picker
        return False
    command = str((agent or {}).get("run_command", "") or "").strip()
    if not command:
        return False
    return shutil.which(command.split()[0]) is not None


def _acp_probe(short_name: str) -> Callable[[], bool]:
    """Bind one agent's PATH probe without a late-binding lambda."""

    def _probe() -> bool:
        return acp_agent_binary_present(short_name)

    return _probe


def _vendor_key_auth(
    profile_id: str,
    after_auth: AfterAuth,
    *,
    connector: str,
    env_vars: Tuple[str, ...],
    optional_env: Tuple[str, ...] = (),
    inject_env: bool = False,
    byok_provider: Optional[str] = None,
    detect: Optional[Callable[[], bool]] = None,
    unavailable_hint: str = "",
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
            byok_provider=byok_provider,
            byok_providers=(),
            local_providers=(),
            inject_env=inject_env,
            detect=detect,
            unavailable_hint=unavailable_hint,
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
            detect=_acp_probe("opencode"),
            unavailable_hint="install OpenCode, then `opencode acp` must be runnable",
            byok_providers=None,
            local_providers=None,
        ),
        acp_agent="opencode",
        hub_id="acp:opencode",
        vendor_owned=True,
        list_visible=True,
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
            local_providers=_PRIME_LOCAL_PROVIDERS,
            detect=_prime_agent_present,
            unavailable_hint=(
                "install Prime Agent with "
                "`curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh`"
            ),
        ),
        hub_id="prime-agent",
        vendor_owned=True,
        list_visible=True,
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
        list_visible=True,
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
            byok_provider="factory",
            detect=_droid_binary_present,
            unavailable_hint="install Factory Droid, then complete the vendor CLI sign-in",
        ),
        acp_agent="droid",
        hub_id="droid",
        vendor_owned=True,
        wired=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="junie",
        label="Junie",
        description="JetBrains Junie through its CLI and ACP server on a JetBrains AI plan.",
        openness="closed",
        homepage="https://www.jetbrains.com/junie/",
        auth=_plan_auth("junie", connector="acp", include_acp=True),
        acp_agent="junie",
        hub_id="junie",
        vendor_owned=True,
        wired=True,
    ),
    HarnessCatalogEntry(
        id="junie-key",
        label="Junie (API key)",
        description="Junie CLI with JETBRAINS_API_KEY. Not the JetBrains account login.",
        openness="closed",
        homepage="https://www.jetbrains.com/junie/",
        auth=_vendor_key_auth(
            "junie-key",
            "vendor-key-acp",
            connector="vendor-key",
            env_vars=("JETBRAINS_API_KEY",),
            inject_env=True,
            detect=_junie_binary_present,
            unavailable_hint="run `npm install -g @jetbrains/junie`, then sign in with Junie CLI",
        ),
        acp_agent="junie",
        hub_id="junie",
        vendor_owned=True,
        wired=True,
        list_visible=True,
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
            detect=_acp_probe("grok"),
            unavailable_hint="install Grok Build, then `grok agent stdio` must be runnable",
            env_vars=("GROK_CODE_XAI_API_KEY",),
            optional_env=("XAI_API_KEY",),
            byok_providers=(),
            local_providers=_DSH_LOCAL_PROVIDERS,
        ),
        acp_agent="grok",
        hub_id="grok",
        vendor_owned=True,
        list_visible=True,
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
        homepage="https://dev.meta.ai/",
        auth=_vendor_key_auth(
            "muse-key",
            "vendor-key-cli",
            connector="external-cli",
            env_vars=("META_API_KEY",),
            inject_env=True,
        ),
        hub_id="muse",
        readiness="setup-required",
        support_note=(
            "Muse Code has no ACP server or headless mode SuperQode can drive, "
            "so run `muse` yourself. It prefers META_API_KEY over a stored "
            "`muse login` session, so the key is what gets billed."
        ),
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="zcode",
        label="ZCode",
        description="Z.AI desktop harness for GLM. No ACP or headless CLI yet — inspect only.",
        openness="closed",
        homepage="https://zcode.z.ai/en",
        auth=(
            HarnessAuthSpec(
                mode="byok",
                connector="key-harness",
                profile_id="zcode",
                after_auth="inspect",
                byok_providers=(),
                local_providers=(),
            ),
        ),
        hub_id="ecosystem:zcode",
        readiness="not-supported",
        support_note=(
            "ZCode is a desktop app. SuperQode cannot launch it until Z.AI ships "
            "ACP, a headless CLI, or a documented key API."
        ),
        vendor_owned=True,
        list_visible=True,
        show_in_closed=True,
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
            detect=_acp_probe("qwen"),
            unavailable_hint="run `npm install -g @qwen-code/qwen-code`, then `qwen --acp`",
            env_vars=("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
            byok_providers=("alibaba",),
            local_providers=_QWEN_LOCAL_PROVIDERS,
        ),
        acp_agent="qwen",
        hub_id="qwen-code",
        vendor_owned=True,
        list_visible=True,
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
                detect=_acp_probe("fast-agent"),
                unavailable_hint="install uv so `uvx` can run fast-agent-acp",
                byok_providers=None,
                local_providers=None,
            ),
        ),
        acp_agent="fast-agent",
        hub_id="acp:fast-agent",
        vendor_owned=True,
        list_visible=True,
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
                detect=_acp_probe("pi"),
                unavailable_hint="install the Pi ACP adapter so `pi-acp` is on PATH",
                byok_providers=None,
                local_providers=None,
            ),
        ),
        acp_agent="pi",
        hub_id="acp:pi",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="goose-key",
        label="Goose",
        description="Block Goose. Local-first open harness. Bring a provider key or a local model.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/block/goose",
        auth=_key_auth(
            "goose-key",
            "setup-card",
            byok_providers=None,
            local_providers=None,
        ),
        acp_agent="goose",
        hub_id="acp:goose",
        readiness="setup-required",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="cline-key",
        label="Cline",
        description="Cline. Model-agnostic open harness. Bring a provider key or a local model.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/cline/cline",
        auth=_key_auth(
            "cline-key",
            "setup-card",
            byok_providers=None,
            local_providers=None,
        ),
        acp_agent="cline",
        hub_id="acp:cline",
        readiness="setup-required",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="openhands-key",
        label="OpenHands",
        description="OpenHands. Cloud keys or Ollama / LM Studio / vLLM.",
        openness="open",
        license="MIT",
        repository="https://github.com/OpenHands/OpenHands",
        auth=_key_auth(
            "openhands-key",
            "setup-card",
            byok_providers=None,
            local_providers=None,
        ),
        acp_agent="openhands",
        hub_id="acp:openhands",
        readiness="setup-required",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="mistral-vibe-key",
        label="Mistral Vibe",
        description="Mistral Vibe. Mistral API key or an OpenAI-compat local endpoint.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/mistralai/mistral-vibe",
        acp_agent="mistral-vibe",
        hub_id="acp:mistral-vibe",
        auth=_key_auth(
            "mistral-vibe-key",
            "setup-card",
            env_vars=("MISTRAL_API_KEY",),
            byok_providers=None,
            local_providers=None,
        ),
        readiness="setup-required",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="hermes-key",
        label="Hermes Agent",
        description="Nous Hermes Agent. Any provider key, OpenRouter, or Ollama / vLLM.",
        openness="open",
        license="MIT",
        repository="https://github.com/nousresearch/hermes-agent",
        acp_agent="hermes",
        hub_id="acp:hermes",
        auth=_key_auth(
            "hermes-key",
            "setup-card",
            byok_providers=None,
            local_providers=None,
        ),
        readiness="setup-required",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="letta",
        label="Letta Code",
        description="Memory-first open harness. Letta Cloud, a provider key, or a local model.",
        openness="open",
        license="Apache-2.0",
        repository="https://github.com/letta-ai/letta-code",
        homepage="https://www.letta.com/",
        auth=_key_auth(
            "letta",
            "setup-card",
            env_vars=("LETTA_API_KEY",),
            byok_providers=None,
            local_providers=None,
        ),
        hub_id="ecosystem:letta",
        readiness="setup-required",
        support_note=(
            "Install with `npm install -g @letta-ai/letta-code`, then run `letta`. "
            "Use /connect for a provider key or /login for Letta Cloud."
        ),
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="warp",
        label="Warp Agent",
        description="Warp Agent CLI. Warp account, WARP_API_KEY, or a model Warp already routes.",
        openness="open",
        license="AGPL-3.0",
        repository="https://github.com/warpdotdev/warp",
        homepage="https://www.warp.dev/agent-cli",
        auth=_key_auth(
            "warp",
            "setup-card",
            env_vars=("WARP_API_KEY",),
            byok_providers=None,
            local_providers=None,
        ),
        hub_id="ecosystem:warp",
        readiness="setup-required",
        support_note=(
            "Install with `curl -fsSL https://app.warp.dev/download/agent-cli | bash`, "
            "then run `warp`. Sign in or export WARP_API_KEY."
        ),
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="kimi-code-key",
        label="Kimi Code (API key)",
        description="Kimi Code with MOONSHOT_API_KEY or a local open-weight endpoint.",
        openness="open",
        license="MIT",
        repository="https://github.com/MoonshotAI/kimi-code",
        # Same shape as qwen-code-key: its own key variables plus an ACP agent,
        # so the declared provider lists are reachable rather than decorative.
        auth=_key_auth(
            "kimi-code-key",
            "acp-attach",
            detect=_acp_probe("kimi"),
            unavailable_hint="install Kimi Code, then `kimi acp` must be runnable",
            env_vars=("MOONSHOT_API_KEY", "KIMI_API_KEY"),
            byok_provider="moonshot",
            byok_providers=("moonshot",),
            local_providers=_QWEN_LOCAL_PROVIDERS,
        ),
        acp_agent="kimi",
        hub_id="kimi-code",
        readiness="setup-required",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="qoder-key",
        label="Qoder CLI (API key)",
        description="Proprietary Qoder CLI with QODER_PERSONAL_ACCESS_TOKEN.",
        openness="closed",
        homepage="https://qoder.com",
        auth=_vendor_key_auth(
            "qoder-key",
            "vendor-key-acp",
            connector="vendor-key",
            env_vars=("QODER_PERSONAL_ACCESS_TOKEN",),
            inject_env=True,
            detect=_acp_probe("qoder"),
            unavailable_hint="run `npm install -g qoder-cli`, then sign in with Qoder CLI",
        ),
        acp_agent="qoder",
        hub_id="acp:qoder",
        vendor_owned=True,
        list_visible=True,
    ),
    HarnessCatalogEntry(
        id="poolside-key",
        label="Poolside (API key)",
        description="Poolside with POOLSIDE_API_KEY or a local OpenAI-compat endpoint.",
        openness="closed",
        homepage="https://poolside.ai",
        # `acp-attach`, not `vendor-key-acp`: Poolside names the variable for a
        # standalone endpoint, so the local half of this row is real. The key
        # path still connects without a model step when the key is exported.
        auth=_key_auth(
            "poolside-key",
            "acp-attach",
            env_vars=("POOLSIDE_API_KEY",),
            optional_env=("POOLSIDE_STANDALONE_BASE_URL",),
            base_url_env="POOLSIDE_STANDALONE_BASE_URL",
            # Poolside is a real ProviderDef, so `superqode auth login poolside`
            # stores a key this row must find rather than demand again.
            byok_provider="poolside",
            byok_providers=("poolside",),
            local_providers=_POOLSIDE_LOCAL_PROVIDERS,
            inject_env=True,
            detect=_acp_probe("poolside"),
            unavailable_hint="run `npm install -g @poolsideai/pool`, then sign in with Pool CLI",
        ),
        acp_agent="poolside",
        hub_id="acp:poolside",
        vendor_owned=True,
        list_visible=True,
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
    "auth_allowlist",
    "get_entry",
    "list_entries",
    "parse_connect_menu_flag",
]
