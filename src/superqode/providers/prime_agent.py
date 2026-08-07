"""Prime Agent CLI introspection for the ``:prime`` command surface.

Prime advertises no ``availableModels`` over ACP and fixes its model, goal,
autonomous policy and recursion depth at process startup, so those settings
travel as launch arguments and environment rather than over the protocol.

Provider names are read from ``auth.json``; the credentials themselves are not.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BINARY = "prime-agent"
INSTALL_HINT = "curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh"

# `prime-agent model list` prints a fixed-width table with a header row.
_MODEL_COLUMNS = 6
_LIST_TIMEOUT = 20.0
_VERSION_TIMEOUT = 10.0


@dataclass(frozen=True)
class PrimeModel:
    """One row of ``prime-agent model list``."""

    provider: str
    model: str
    context: str = ""
    max_output: str = ""
    thinking: bool = False
    images: bool = False

    @property
    def id(self) -> str:
        """The ``provider/model`` selector Prime accepts on the CLI."""
        return f"{self.provider}/{self.model}"

    @property
    def label(self) -> str:
        extras = []
        if self.context:
            extras.append(self.context)
        if self.thinking:
            extras.append("thinking")
        if self.images:
            extras.append("images")
        suffix = f"  ({', '.join(extras)})" if extras else ""
        return f"{self.model}{suffix}"


def agent_home() -> Path:
    """Prime Agent's config directory, honoring its own override."""
    override = os.environ.get("PRIME_AGENT_CODING_AGENT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".prime" / "agent"


def binary_path() -> Optional[str]:
    """Absolute path to the ``prime-agent`` binary, or None when missing."""
    return shutil.which(BINARY)


def is_installed() -> bool:
    return binary_path() is not None


def version() -> Optional[str]:
    """Installed Prime Agent version, or None when it cannot be determined."""
    if not is_installed():
        return None
    try:
        proc = subprocess.run(
            [BINARY, "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    return out.splitlines()[0].strip() if out else None


def _parse_bool(cell: str) -> bool:
    return cell.strip().lower() in {"yes", "true", "y"}


def parse_model_table(stdout: str) -> list[PrimeModel]:
    """Parse ``prime-agent model list`` output into models.

    The header row is skipped by shape rather than by matching its text, so a
    renamed column does not silently drop every model.
    """
    models: list[PrimeModel] = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0] == "provider" and parts[1] == "model":
            continue
        provider, model = parts[0], parts[1]
        rest = parts[2:]
        context = rest[0] if len(rest) > 0 else ""
        max_output = rest[1] if len(rest) > 1 else ""
        thinking = _parse_bool(rest[2]) if len(rest) > 2 else False
        images = _parse_bool(rest[3]) if len(rest) > 3 else False
        if len(parts) < _MODEL_COLUMNS and not context:
            continue
        models.append(
            PrimeModel(
                provider=provider,
                model=model,
                context=context,
                max_output=max_output,
                thinking=thinking,
                images=images,
            )
        )
    return models


@dataclass(frozen=True)
class PrimeAgentSession:
    """One entry from ``prime-agent list``."""

    session_id: str
    name: str
    lifecycle: str = ""
    activity: str = ""
    runtime_kind: str = "top-level"
    rlm_depth: int = 0
    active: bool = False

    @property
    def is_subagent(self) -> bool:
        """RLM children report ``subagent`` and a depth above zero."""
        return self.runtime_kind == "subagent" or self.rlm_depth > 0


def _run_json(args: list[str]) -> Any:
    """Run a Prime subcommand that supports ``--json`` and parse its output.

    Pass only exact registered command paths. Prime treats an unrecognized
    argument as a prompt to the model, which costs a request and returns prose.
    """
    if not is_installed():
        return None
    try:
        proc = subprocess.run(
            [BINARY, *args, "--json"],
            capture_output=True,
            text=True,
            timeout=_LIST_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for stream in (proc.stdout, proc.stderr):
        text = (stream or "").strip()
        if not text.startswith(("{", "[")):
            continue
        try:
            return json.loads(text)
        except ValueError:
            continue
    return None


def list_agents() -> list[PrimeAgentSession]:
    """Return the agent sessions Prime's background service is holding."""
    payload = _run_json(["list"])
    rows = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    sessions: list[PrimeAgentSession] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            depth = int(row.get("rlmDepth") or 0)
        except (TypeError, ValueError):
            depth = 0
        sessions.append(
            PrimeAgentSession(
                session_id=str(row.get("sessionId") or row.get("id") or ""),
                name=str(row.get("sessionName") or ""),
                lifecycle=str(row.get("lifecycle") or ""),
                activity=str(row.get("activity") or ""),
                runtime_kind=str(row.get("runtimeKind") or "top-level"),
                rlm_depth=depth,
                active=bool(row.get("isSessionActive")),
            )
        )
    return sessions


def daemon_status() -> list[dict[str, Any]]:
    """Return Prime's background service records."""
    payload = _run_json(["status"])
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def doctor() -> list[dict[str, Any]]:
    """Return Prime's background service health records."""
    payload = _run_json(["doctor"])
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def list_schedules() -> list[dict[str, Any]]:
    """Return scheduled and recurring prompts."""
    payload = _run_json(["schedule", "list"])
    rows = payload.get("jobs") if isinstance(payload, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def list_packages() -> list[str]:
    """Return installed capability package names.

    ``package list`` has no ``--json`` form, so plain output is split to lines.
    """
    if not is_installed():
        return []
    try:
        proc = subprocess.run(
            [BINARY, "package", "list"],
            capture_output=True,
            text=True,
            timeout=_LIST_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    lines = [
        line.strip()
        for line in f"{proc.stdout or ''}\n{proc.stderr or ''}".splitlines()
        if line.strip()
    ]
    return [line for line in lines if not line.lower().startswith("no packages")]


def list_models(search: str = "") -> list[PrimeModel]:
    """Return the models Prime Agent reports for the current credentials.

    Returns an empty list when Prime is not installed or the probe fails;
    callers show an install or login hint rather than an error.
    """
    if not is_installed():
        return []
    cmd = [BINARY, "model", "list"]
    if search.strip():
        cmd.append(search.strip())
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_LIST_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    # Prime keeps stdout clear for protocol output and prints the table on stderr.
    return parse_model_table(f"{proc.stdout or ''}\n{proc.stderr or ''}")


def auth_providers() -> list[str]:
    """Provider names present in Prime's ``auth.json``. Never reads secrets."""
    path = agent_home() / "auth.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return sorted(str(k) for k in data) if isinstance(data, dict) else []


def custom_providers() -> list[str]:
    """Provider names from Prime's ``models.json`` (local Ollama, vLLM, ...)."""
    path = agent_home() / "models.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    providers = data.get("providers") if isinstance(data, dict) else None
    return sorted(str(k) for k in providers) if isinstance(providers, dict) else []


# SuperQode uses these as "no model chosen" across the TUI. Passing one to
# Prime as a real id makes it resolve against a provider the user never picked
# and fail on a missing key, so they resolve to unset here.
_UNSET_MODELS = {"auto", "default", "none", "-"}


# Embedding and reranking models cannot drive an agent loop, so registering
# them would put dead entries in the picker.
_NON_CHAT_HINTS = ("embed", "rerank", "bge-", "nomic-")

# Prime's OpenAI-compatible provider names, keyed by SuperQode's provider type.
_LOCAL_PROVIDER_NAMES = {
    "ollama": "ollama",
    "lmstudio": "lmstudio",
    "llamacpp": "llamacpp",
    "vllm": "vllm",
}


def is_chat_model(model_id: str) -> bool:
    """False for embedding and reranking models, which cannot drive an agent."""
    lowered = str(model_id).lower()
    return not any(hint in lowered for hint in _NON_CHAT_HINTS)


def local_model_id(model: Any) -> str:
    """Model id from a discovery result, which yields objects rather than ids."""
    ident = getattr(model, "id", None)
    return str(ident if ident else model).strip()


def local_provider_name(provider_type: Any) -> str:
    """Map a SuperQode local provider type onto Prime's provider name."""
    raw = getattr(provider_type, "value", provider_type)
    key = str(raw or "").strip().lower().replace("-", "").replace("_", "").replace(".", "")
    return _LOCAL_PROVIDER_NAMES.get(key, "")


def local_models_config(discovered: dict[str, Any]) -> dict[str, Any]:
    """Build Prime's ``models.json`` provider block from discovered servers.

    ``discovered`` maps a provider name to ``(base_url, [model ids])``. Prime
    reads these as OpenAI-compatible endpoints, so the same shape covers Ollama,
    LM Studio, llama.cpp and vLLM.
    """
    providers: dict[str, Any] = {}
    for name, (base_url, model_ids) in sorted(discovered.items()):
        models = [{"id": mid} for mid in sorted(set(model_ids)) if is_chat_model(mid)]
        if not models:
            continue
        providers[name] = {
            "baseUrl": base_url.rstrip("/"),
            "api": "openai-completions",
            "apiKey": name,
            # Local servers commonly reject the developer role and the
            # reasoning_effort field that reasoning-capable models use.
            "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
            "models": models,
        }
    return {"providers": providers}


def merge_local_models(discovered: dict[str, Any]) -> tuple[int, int, Path]:
    """Register discovered local models in Prime's ``models.json``.

    Providers SuperQode did not discover are left untouched, so a hand-written
    entry is never dropped. Returns the provider and model counts written and
    the file path.
    """
    path = agent_home() / "models.json"
    try:
        existing = json.loads(path.read_text())
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    providers = existing.get("providers")
    providers = dict(providers) if isinstance(providers, dict) else {}
    fresh = local_models_config(discovered)["providers"]
    providers.update(fresh)
    existing["providers"] = providers

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n")
    model_count = sum(len(block.get("models", [])) for block in fresh.values())
    return len(fresh), model_count, path


def split_selector(selector: str) -> tuple[str, str]:
    """Split ``provider/model``. A bare id leaves the provider to Prime."""
    raw = (selector or "").strip()
    if not raw or raw.lower() in _UNSET_MODELS:
        return "", ""
    if "/" not in raw:
        return "", raw
    provider, _, model = raw.partition("/")
    if model.strip().lower() in _UNSET_MODELS:
        return provider.strip(), ""
    return provider.strip(), model.strip()


@dataclass(frozen=True)
class PrimeLaunchOptions:
    """Settings Prime accepts only at process start.

    Exposed in a Prime session as ``/goal``, ``/autonomous`` and
    ``/rlm-max-depth``. Changing one requires relaunching.
    """

    model: str = ""
    goal: str = ""
    goal_token_budget: int | None = None
    autonomous: bool = False
    gates: tuple[str, ...] = ()
    max_depth: int | None = None

    def env(self) -> dict[str, str]:
        """Environment overrides for the agent process."""
        if self.max_depth is None:
            return {}
        return {"RLM_MAX_DEPTH": str(self.max_depth)}

    def describe(self) -> list[str]:
        """Human-readable summary of what is pinned."""
        parts: list[str] = []
        if self.model:
            parts.append(f"model {self.model}")
        if self.max_depth is not None:
            parts.append(f"depth {self.max_depth}")
        if self.goal:
            parts.append(f"goal {self.goal[:40]!r}")
        if self.autonomous:
            gates = f" with {len(self.gates)} gate(s)" if self.gates else ""
            parts.append(f"autonomous{gates}")
        return parts


def _quote(value: str) -> str:
    """Quote one argument for the shell the ACP client launches through."""
    return shlex.quote(str(value))


def acp_command(
    selector: str = "",
    *,
    base: str = "",
    options: PrimeLaunchOptions | None = None,
) -> str:
    """Build the ACP launch command with the start-time settings applied."""
    command = (base or f"{BINARY} --mode acp").strip()
    opts = options or PrimeLaunchOptions()

    provider, model = split_selector(selector or opts.model)
    if provider:
        command += f" --provider {_quote(provider)}"
    if model:
        command += f" --model {_quote(model)}"

    if opts.goal:
        command += f" --goal {_quote(opts.goal)}"
        if opts.goal_token_budget and opts.goal_token_budget > 0:
            command += f" --goal-token-budget {int(opts.goal_token_budget)}"

    if opts.autonomous:
        command += " --autonomous"
        for gate in opts.gates:
            if str(gate).strip():
                command += f" --autonomous-gate {_quote(str(gate).strip())}"

    return command
