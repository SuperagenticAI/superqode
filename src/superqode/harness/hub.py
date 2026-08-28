"""Versioned, presentation-neutral catalog for the SuperQode Harness Hub."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from superqode.app.harness_picker import HarnessPickerItem, harness_picker_items


HUB_SCHEMA_VERSION = "1.5"
DOCS_BASE = "https://superagenticai.github.io/superqode/"
PROJECT_REPOSITORY = "https://github.com/SuperagenticAI/superqode"

# One vocabulary for every surface. The terminal, the CLI and the website all
# describe the same state with the same words, so a user who reads "Needs
# setup" on the site finds "Needs setup" in the Hub.
READINESS_LABELS = {
    "ready": "Ready",
    "setup-required": "Needs setup",
    "not-supported": "Integration pending",
}
READINESS_VALUES = tuple(READINESS_LABELS)

# Harnesses SuperQode cannot run: browsable and inspectable, never selectable.
REFERENCE_ONLY_KINDS = frozenset({"ecosystem"})

OPENNESS_LABELS = {
    "open": "Open source",
    "closed": "Proprietary",
}
OPENNESS_VALUES = tuple(OPENNESS_LABELS)


def openness_label(openness: str) -> str:
    """Return the public label for an openness value, or an honest unknown."""
    return OPENNESS_LABELS.get(openness, "Not published")


def readiness_label(readiness: str) -> str:
    """Return the public label for a readiness value."""
    return READINESS_LABELS.get(readiness, str(readiness).replace("-", " ").capitalize())


_DOCS_BY_ID = {
    "codex": f"{DOCS_BASE}providers/codex/",
    "claude": f"{DOCS_BASE}providers/anthropic-claude/",
    "antigravity": f"{DOCS_BASE}providers/antigravity/",
    "muse": f"{DOCS_BASE}providers/muse-code/",
    "prime-agent": f"{DOCS_BASE}providers/prime-agent/",
    "grok": f"{DOCS_BASE}providers/grok/",
    "copilot": f"{DOCS_BASE}providers/github-copilot/",
    "devin": f"{DOCS_BASE}providers/devin/",
    "glm-cli": f"{DOCS_BASE}providers/zai/",
    "qwen-code": f"{DOCS_BASE}providers/qwen-code/",
    "kimi-code": f"{DOCS_BASE}providers/kimi/",
    "rlm": f"{DOCS_BASE}advanced/rlm/",
    "pipy": f"{DOCS_BASE}advanced/pipy/",
    "tau": f"{DOCS_BASE}advanced/tau/",
    "uhp": f"{DOCS_BASE}providers/uhp/",
    "deepseek-harness": f"{DOCS_BASE}advanced/deepseek-harness/",
    "deepagents": f"{DOCS_BASE}providers/deepagents/",
    "deepagents-code": f"{DOCS_BASE}providers/deepagents/",
    "junie": f"{DOCS_BASE}concepts/modes/",
    "fx": f"{DOCS_BASE}providers/fx/",
}

_HOMEPAGE_BY_ID = {
    "codex": "https://openai.com/codex/",
    "claude": "https://www.anthropic.com/claude-code",
    "cursor": "https://cursor.com/",
    "amp": "https://ampcode.com/",
    "antigravity": "https://antigravity.google/",
    "muse": "https://dev.meta.ai/",
    "prime-agent": "https://github.com/PrimeIntellect-ai/prime-agent",
    "grok": "https://x.ai/cli",
    "copilot": "https://github.com/features/copilot",
    "devin": "https://devin.ai/",
    "droid": "https://factory.ai/",
    "kiro": "https://kiro.dev/",
    "glm-cli": "https://z.ai/",
    "qwen-code": "https://github.com/QwenLM/qwen-code",
    "kimi-code": "https://github.com/MoonshotAI/kimi-code",
    "deepagents-code": "https://docs.langchain.com/deepagents-code",
    "junie": "https://www.jetbrains.com/junie/",
    "ecosystem:letta": "https://www.letta.com/",
    "ecosystem:warp": "https://www.warp.dev/agent-cli",
    "fx": "https://fx.sh",
}

_COMMANDS_BY_ID = {
    "codex": (":connect codex", ":codex status", ":codex models", ":codex sessions"),
    "copilot": (
        ":connect copilot",
        ":copilot status",
        ":copilot models",
        ":copilot sessions",
    ),
    "antigravity": (
        ":connect antigravity",
        ":agy status",
        ":agy agents",
        ":agy models",
        ":agy plugin list",
    ),
    "grok": (":connect grok", ":grok status", ":grok models", ":grok api"),
    "prime-agent": (
        ":prime connect",
        ":prime status",
        ":prime models",
        ":prime agents",
        ":prime local",
    ),
    "muse": (":connect muse", ":muse status", ":muse login"),
    "fx": (":connect fx", ":connect fx-key", ":fx status", ":fx login"),
}


@dataclass(frozen=True)
class HubOpenness:
    """What is publicly known about a harness implementation's source.

    Openness describes the harness's own licensing, not SuperQode's route to
    it and not the model behind it. An agent stays open whether it is reached
    over ACP, as an optional runtime, or not at all yet.
    """

    openness: str
    license: str = ""
    repository: str = ""


_PROJECT_OPENNESS = HubOpenness("open", "Apache-2.0", PROJECT_REPOSITORY)

# Verified against each project's published license metadata. Anything absent
# here resolves through the fallbacks in ``_resolve_openness`` and, failing
# those, stays unknown. A harness is never reported as open on a guess.
#
# Deliberately absent: Charm's Crush ships under the Functional Source License,
# which is source-available rather than OSI open source, so it must not appear
# under an open-source filter.
_LANGCHAIN_DEEPAGENTS = HubOpenness("open", "MIT", "https://github.com/langchain-ai/deepagents")
_OPENNESS_BY_ID: dict[str, HubOpenness] = {
    "deepagents": _LANGCHAIN_DEEPAGENTS,
    "deepagents-code": _LANGCHAIN_DEEPAGENTS,
    "acp:deepagents": _LANGCHAIN_DEEPAGENTS,
    "acp:deepagents-code": _LANGCHAIN_DEEPAGENTS,
    "tau": HubOpenness("open", "MIT", "https://github.com/huggingface/tau"),
    "uhp": HubOpenness("open", "Apache-2.0", "https://github.com/HarnessRouter/harnessrouter"),
    "deepseek-harness": HubOpenness(
        "open", "MIT", "https://github.com/deepseek-ai/deepseek-harness"
    ),
    "droid": HubOpenness("closed"),
    "grok": HubOpenness("open", "Apache-2.0", "https://github.com/xai-org/grok-build"),
    "muse": HubOpenness("closed"),
    "junie": HubOpenness("closed"),
    "codex": HubOpenness("open", "Apache-2.0", "https://github.com/openai/codex"),
    "acp:codex": HubOpenness("open", "Apache-2.0", "https://github.com/openai/codex"),
    "acp:gemini": HubOpenness("open", "Apache-2.0", "https://github.com/google-gemini/gemini-cli"),
    "acp:goose": HubOpenness("open", "Apache-2.0", "https://github.com/aaif-goose/goose"),
    "acp:cline": HubOpenness("open", "Apache-2.0", "https://github.com/cline/cline"),
    "acp:opencode": HubOpenness("open", "MIT", "https://github.com/opencode-ai/opencode"),
    "acp:openhands": HubOpenness("open", "MIT", "https://github.com/OpenHands/OpenHands"),
    # Drawn on the Open and Closed connect lists, so the Hub has to agree with
    # what those rows already state about the same harness.
    "acp:fast-agent": HubOpenness("open", "Apache-2.0", "https://github.com/evalstate/fast-agent"),
    "acp:pi": HubOpenness("open", "MIT", "https://github.com/earendil-works/pi"),
    "acp:mistral-vibe": HubOpenness(
        "open", "Apache-2.0", "https://github.com/mistralai/mistral-vibe"
    ),
    "acp:hermes": HubOpenness("open", "MIT", "https://github.com/nousresearch/hermes-agent"),
    "acp:qoder": HubOpenness("closed"),
    "acp:poolside": HubOpenness("closed"),
    "qwen-code": HubOpenness("open", "Apache-2.0", "https://github.com/QwenLM/qwen-code"),
    "acp:qwen": HubOpenness("open", "Apache-2.0", "https://github.com/QwenLM/qwen-code"),
    "kimi-code": HubOpenness("open", "MIT", "https://github.com/MoonshotAI/kimi-code"),
    "acp:kimi": HubOpenness("open", "MIT", "https://github.com/MoonshotAI/kimi-code"),
    "fx": HubOpenness("open", "Apache-2.0", "https://github.com/vercel-labs/fx"),
    "acp:fx": HubOpenness("open", "Apache-2.0", "https://github.com/vercel-labs/fx"),
    "prime-agent": HubOpenness("open", "MIT", "https://github.com/PrimeIntellect-ai/prime-agent"),
    "acp:prime-agent": HubOpenness(
        "open", "MIT", "https://github.com/PrimeIntellect-ai/prime-agent"
    ),
    "ecosystem:aider": HubOpenness("open", "Apache-2.0", "https://github.com/Aider-AI/aider"),
    "ecosystem:plandex": HubOpenness("open", "MIT", "https://github.com/plandex-ai/plandex"),
    "ecosystem:roo-code": HubOpenness(
        "open", "Apache-2.0", "https://github.com/RooCodeInc/Roo-Code"
    ),
    "ecosystem:jcode": HubOpenness("open", "MIT", "https://github.com/1jehuang/jcode"),
    "ecosystem:letta": HubOpenness("open", "Apache-2.0", "https://github.com/letta-ai/letta-code"),
    "ecosystem:warp": HubOpenness("open", "AGPL-3.0", "https://github.com/warpdotdev/warp"),
    "ecosystem:qm": HubOpenness("open", "MIT", "https://github.com/yc-software/qm"),
    "ecosystem:headlong": HubOpenness(
        "open", "Apache-2.0", "https://github.com/laude-institute/headlong"
    ),
    "ecosystem:better-harness": HubOpenness(
        "open", "MIT", "https://github.com/QoderAI/better-harness"
    ),
    # A download-only desktop application with no published source.
    "ecosystem:zcode": HubOpenness("closed"),
}


@dataclass(frozen=True)
class HubSetupStep:
    """One human-readable installation or authentication step."""

    title: str
    command: str = ""
    description: str = ""


_SETUP_STEPS_BY_ID = {
    "codex": (
        HubSetupStep(
            "Install the SuperQode Codex integration",
            'uv tool install "superqode[codex-sdk]"',
        ),
        HubSetupStep("Authenticate with your OpenAI account", "codex login"),
    ),
    "cursor": (
        HubSetupStep("Install Cursor Agent", "curl https://cursor.com/install -fsS | bash"),
        HubSetupStep("Authenticate with your Cursor account", "cursor-agent login"),
    ),
    "amp": (
        HubSetupStep("Install Amp and authenticate", "amp login"),
        HubSetupStep("Install the SuperQode ACP adapter", "uv tool install acp-amp"),
    ),
    "antigravity": (
        HubSetupStep(
            "Install or update Antigravity CLI",
            description=(
                "Follow the official CLI installation guide. SuperQode requires agy 1.1.1 or "
                "newer: https://antigravity.google/docs/cli-install"
            ),
        ),
        HubSetupStep("Complete Google Sign-In", "agy"),
    ),
    "muse": (
        HubSetupStep(
            "Install Muse Code on macOS or Linux",
            "curl -fsSL https://dev.meta.ai/install.sh | bash",
        ),
        HubSetupStep("Authenticate with your Meta account", "muse login"),
    ),
    "prime-agent": (
        HubSetupStep(
            "Install Prime Agent",
            "curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh",
        ),
        HubSetupStep(
            "Authenticate inside Prime Agent",
            "prime-agent",
            "When Prime Agent opens, enter /login and follow the provider sign-in flow.",
        ),
    ),
    "grok": (
        HubSetupStep(
            "Install the official Grok CLI",
            description="Use the installation instructions at https://x.ai/cli.",
        ),
        HubSetupStep(
            "Authenticate your account",
            "grok login",
            "Device authentication is also available with grok login --device-auth.",
        ),
    ),
    "copilot": (
        HubSetupStep(
            "Recommended: install the SuperQode Copilot SDK integration",
            'uv tool install "superqode[copilot-sdk]"',
        ),
        HubSetupStep(
            "Alternative: install the official GitHub Copilot CLI",
            "npm install -g @github/copilot",
        ),
        HubSetupStep("Authenticate with GitHub Copilot", "copilot login"),
    ),
    "devin": (
        HubSetupStep("Install Devin CLI", "curl -fsSL https://cli.devin.ai/install.sh | bash"),
        HubSetupStep("Authenticate with your Devin account", "devin auth login"),
    ),
    "junie": (
        HubSetupStep("Install Junie CLI", "npm install -g @jetbrains/junie"),
        HubSetupStep(
            "Authenticate with your JetBrains account",
            description="Sign in with Junie CLI using your JetBrains AI / Junie plan.",
        ),
    ),
    "droid": (
        HubSetupStep(
            "Install Factory Droid",
            description="Follow the official installation instructions at https://factory.ai/.",
        ),
        HubSetupStep(
            "Authenticate the Droid CLI",
            description="Complete Factory's CLI sign-in flow before connecting from SuperQode.",
        ),
    ),
    "kiro": (
        HubSetupStep(
            "Install Kiro CLI",
            description="Follow the official guide at https://kiro.dev/docs/cli/.",
        ),
        HubSetupStep(
            "Authenticate your account",
            description="Sign in with your Kiro or Amazon Q Developer account.",
        ),
    ),
    "glm-cli": (
        HubSetupStep("Install the GLM ACP agent", "npm install -g glm-acp-agent"),
        HubSetupStep(
            "Configure authentication",
            description="Provide the Z.AI API key used by the GLM agent.",
        ),
    ),
    "qwen-code": (
        HubSetupStep("Install Qwen Code", "npm install -g @qwen-code/qwen-code"),
        HubSetupStep("Authenticate your Qwen account", "qwen auth"),
    ),
    "kimi-code": (
        HubSetupStep(
            "Install Kimi Code", "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash"
        ),
        HubSetupStep(
            "Authenticate inside Kimi Code",
            "kimi",
            "When Kimi opens, enter /login and complete the account flow.",
        ),
    ),
    "deepagents-code": (
        HubSetupStep("Install Deep Agents Code", "curl -LsSf https://langch.in/dcode | bash"),
        HubSetupStep(
            "Connect a model provider",
            "dcode",
            "When Deep Agents Code opens, enter /auth and connect any provider it supports.",
        ),
    ),
    "fx": (
        HubSetupStep("Install fx", "curl -fsSL https://fx.sh/setup.sh | bash"),
        HubSetupStep(
            "Sign in with Vercel",
            "fx login",
            "On a headless machine, set FX_NO_OPEN_BROWSER=1 so the authorization URL is printed.",
        ),
    ),
}

_POPULARITY_RANK = {
    "codex": 10,
    "claude": 20,
    "cursor": 30,
    "copilot": 40,
    "antigravity": 50,
    "acp:gemini": 55,
    "acp:opencode": 60,
    "amp": 70,
    "grok": 80,
    "kimi-code": 90,
    "qwen-code": 100,
    "devin": 110,
    "droid": 120,
    "acp:cline": 130,
    "acp:goose": 140,
    "acp:openhands": 150,
    "kiro": 160,
    "prime-agent": 170,
    "acp:qoder": 180,
    "deepagents-code": 185,
    "fx": 188,
    "core": 220,
    "workbench": 230,
    "pipy": 240,
    "rlm": 250,
    "deepagents": 255,
    "no-tool": 260,
}


def _spec_lifecycle_commands(reference: str) -> dict[str, tuple[str, ...]]:
    """Return the measure-then-improve commands for a HarnessSpec entry.

    Every command here takes a spec file, so a built-in with no file on disk
    points at the conventional ``harness.yaml`` rather than at an identifier
    the CLI would reject.
    """
    spec = reference if reference.endswith((".yaml", ".yml")) else "harness.yaml"
    return {
        "eval_commands": (
            f"superqode harness test --spec {spec}",
            f"superqode harness eval --spec {spec} --tasks eval-tasks.yaml",
            "superqode harness bench --manifest harnessbench.yaml",
        ),
        "optimize_commands": (
            f"superqode harness optimize-omni --spec {spec} --tasks eval-tasks.yaml",
            f"superqode harness optimize --spec {spec} --tasks eval-tasks.yaml",
            "superqode harness promote stage",
        ),
    }


_ECOSYSTEM_DETAILS: dict[str, dict[str, Any]] = {
    "ecosystem:zcode": {
        "interface": "Desktop application",
        "support_note": (
            "Direct SuperQode integration is pending. ZCode currently runs as an independent "
            "desktop harness and does not document an ACP server, headless CLI, or external "
            "agent SDK."
        ),
        "docs_url": "https://zcode.z.ai/en/docs/welcome",
        "install_command": (
            "Download the official application for macOS, Windows, or Linux from zcode.z.ai."
        ),
        "tools": (
            "workspace files",
            "terminal commands",
            "browser automation",
            "MCP servers",
            "Git review",
        ),
        "policies": (
            "ZCode owns its agent loop, permissions, tools, and task history",
            "ZCode authentication and Coding Plan quota remain with Z.AI",
            "No commands are executed by SuperQode until an official connector exists",
        ),
        "capabilities": (
            "Official GLM-5.3 harness",
            "Long-horizon tasks",
            "Multi-agent workflows",
            "Browser automation",
            "Remote control",
        ),
        "based_on": "Z.AI ZCode Agent",
        "popularity_rank": 65,
        "setup_steps": (
            HubSetupStep(
                "Install ZCode independently",
                description=(
                    "Download the official desktop application for macOS, Windows, or Linux. "
                    "It currently runs outside SuperQode."
                ),
            ),
            HubSetupStep(
                "Connect a Z.AI account or model provider",
                description="Complete authentication inside ZCode's onboarding flow.",
            ),
        ),
    },
    "ecosystem:jcode": {
        "interface": "Terminal harness",
        # Unlike ZCode, jcode publishes programmatic entry points. Saying so is
        # the difference between "cannot be integrated" and "not yet built".
        "support_note": (
            "Not yet runnable from SuperQode, but unlike a desktop-only harness jcode documents "
            "a headless `jcode run`, a TypeScript SDK, and a versioned harness API, so a "
            "SuperQode route is buildable once it is implemented and tested."
        ),
        "docs_url": "https://jcode.sh/docs",
        "repository": "https://github.com/1jehuang/jcode",
        "install_command": "curl -fsSL https://jcode.sh/install | bash",
        "tools": ("workspace files", "terminal commands", "MCP servers", "semantic memory"),
        "policies": (
            "jcode owns its agent loop, tools, and session state",
            "Model provider credentials remain with jcode's own configuration",
            "No commands are executed by SuperQode until a connector is built and tested",
        ),
        "capabilities": (
            "Terminal coding harness",
            "Headless runs",
            "Parallel agent swarms",
            "TypeScript SDK",
            "MCP tools",
        ),
        "based_on": "jcode (Rust, MIT)",
        "popularity_rank": 68,
        "setup_steps": (
            HubSetupStep(
                "Install jcode independently",
                command="curl -fsSL https://jcode.sh/install | bash",
                description="Binaries are published for macOS, Linux, and Windows.",
            ),
            HubSetupStep(
                "Configure a model provider",
                description="jcode connects to Anthropic, OpenAI, or OpenRouter with its own keys.",
            ),
        ),
    },
    "ecosystem:letta": {
        "interface": "Terminal harness",
        "support_note": (
            "Not yet launched from SuperQode. Letta Code is a published CLI "
            "(`npm install -g @letta-ai/letta-code`, then `letta`). Configure "
            "a provider with /connect or Letta Cloud with /login. SuperQode "
            "does not speak Letta ACP from this row yet."
        ),
        "docs_url": "https://docs.letta.com/letta-code/cli",
        "repository": "https://github.com/letta-ai/letta-code",
        "install_command": "npm install -g @letta-ai/letta-code",
        "tools": ("workspace files", "terminal commands", "skills", "memory", "subagents"),
        "policies": (
            "Letta Code owns its agent loop, memory, and session state",
            "Provider keys and Letta Cloud credentials stay in Letta's own config",
            "No commands are executed by SuperQode until an ACP or CLI attach ships",
        ),
        "capabilities": (
            "Memory-first coding harness",
            "Interactive CLI",
            "Letta Cloud sync",
            "Skills and subagents",
            "Model-agnostic /connect",
        ),
        "based_on": "Letta Code (Apache-2.0)",
        "popularity_rank": 72,
        "setup_steps": (
            HubSetupStep(
                "Install Letta Code",
                command="npm install -g @letta-ai/letta-code",
            ),
            HubSetupStep(
                "Connect a model",
                command="letta",
                description="Inside Letta, run /connect for a provider key or /login for Letta Cloud.",
            ),
        ),
    },
    "ecosystem:warp": {
        "interface": "Terminal harness",
        "support_note": (
            "Ecosystem watch: SuperQode does not attach Warp. Warp Agent's loop runs "
            "server-side and the open client is AGPL-3.0, so there is nothing to embed "
            "and no protocol to speak. Warp has said it plans to support ACP "
            "(warpdotdev/warp#9233). SuperQode will revisit an attach when an ACP "
            "surface or licence terms make one clean. Run Warp directly meanwhile."
        ),
        "docs_url": "https://docs.warp.dev/agents/cli/",
        "repository": "https://github.com/warpdotdev/warp",
        "install_command": "curl -fsSL https://app.warp.dev/download/agent-cli | bash",
        "tools": ("workspace files", "terminal commands", "codebase index", "model routing"),
        "policies": (
            "Warp Agent owns its loop, permissions, and model routing",
            "Warp account or WARP_API_KEY remains with Warp",
            "No commands are executed by SuperQode: no attach is built",
            "Warp's client is AGPL-3.0 and SuperQode is Apache-2.0, so no code is shared",
        ),
        "capabilities": (
            "Standalone Agent CLI",
            "Warp Terminal harness",
            "Model routing",
            "Cloud handoff (Oz)",
        ),
        "based_on": "Warp Agent (AGPL-3.0)",
        "popularity_rank": 70,
        "setup_steps": (
            HubSetupStep(
                "Install Warp Agent CLI",
                command="curl -fsSL https://app.warp.dev/download/agent-cli | bash",
            ),
            HubSetupStep(
                "Authenticate",
                command="warp",
                description="Sign in with your Warp account, or export WARP_API_KEY.",
            ),
        ),
    },
    "ecosystem:headlong": {
        "interface": "Named identity CLI",
        "support_note": (
            "Not runnable from SuperQode, and a different case from jcode's: Headlong has no "
            "ACP server, MCP server, SDK, or task-runner API. `<agent> hello` is a one-shot "
            "observation sent into a standing mind that may choose not to reply, not a task "
            "call with a result contract. It has a Unix surface to attach to (start/stop the "
            "identity, tail its trajectory) but no run contract to speak of yet. See "
            "RLM Routes Compared for how its persistent inner-monologue loop differs from "
            "SuperQode's own RLM routes."
        ),
        "docs_url": "https://github.com/laude-institute/headlong#readme",
        "repository": "https://github.com/laude-institute/headlong",
        "install_command": "curl -fsSL https://headlong.ai/install.sh | bash",
        "tools": (
            "thinkers (idle-loop dispatcher)",
            "shellm (Bash RLM core)",
            "traj (jsonl DAG, fork/merge)",
            "context (tiered-rollup projection)",
            "mem / skills",
            "recap (logarithmic memory pyramid)",
        ),
        "policies": (
            "Headlong owns its agent loop, trajectory, and identity store",
            "Model provider keys (Anthropic, OpenAI, Gemini, OpenRouter) stay in Headlong's own config",
            "No commands are executed by SuperQode until a connector is built and tested",
        ),
        "capabilities": (
            "Persistent inner-monologue loop, never idle",
            "Bash-native RLM core, no tool schema",
            "One shared trajectory across a whole team",
            "Self-modifies by forking Headlong, testing changes, then merging them",
            "Docker-sandboxed generated code by default",
        ),
        "based_on": "Headlong (Bash, Apache-2.0)",
        "popularity_rank": 76,
        "setup_steps": (
            HubSetupStep(
                "Install Headlong independently",
                command="curl -fsSL https://headlong.ai/install.sh | bash",
                description="Interviews you for an agent name and personality, then installs it as a command.",
            ),
            HubSetupStep(
                "Configure a model provider",
                description="Headlong's `llm` CLI takes an Anthropic, OpenAI, Gemini, or OpenRouter key.",
            ),
        ),
    },
}


@dataclass(frozen=True)
class HubRecord:
    """A stable public record shared by terminal, CLI, docs, and web clients."""

    id: str
    name: str
    description: str
    category: str
    kind: str
    runtime: str
    source: str
    readiness: str
    integration_level: str
    continuity: str
    provider: str = ""
    model: str = ""
    setup: str = ""
    warning: str = ""
    project_path: str = ""
    homepage: str = ""
    repository: str = ""
    interface: str = ""
    support_note: str = ""
    last_verified: str = ""
    aliases: tuple[str, ...] = ()
    docs_url: str = ""
    install_command: str = ""
    tui_commands: tuple[str, ...] = ()
    cli_commands: tuple[str, ...] = ()
    eval_commands: tuple[str, ...] = ()
    optimize_commands: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    policies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    based_on: str = ""
    popularity_rank: int = 500
    setup_steps: tuple[HubSetupStep, ...] = ()
    openness: str = ""
    license: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _readiness(item: HarnessPickerItem) -> str:
    if item.kind == "acp-browser":
        return "discover"
    return "ready" if item.available else "setup-required"


def _openness_from_acp_tags(item: HarnessPickerItem) -> HubOpenness | None:
    """Read the registry's own ``open-source`` tag for an ACP agent.

    The ACP catalog already records this per agent, so an agent SuperQode has
    not license-checked by hand is still reported honestly: open, with the
    license left blank rather than invented.
    """
    if item.kind != "acp" or not isinstance(item.target, dict):
        return None
    tags = item.target.get("tags")
    if not isinstance(tags, (list, tuple)):
        return None
    if "open-source" not in {str(tag).strip().casefold() for tag in tags}:
        return None
    url = str(item.target.get("publisher_url") or item.target.get("url") or "")
    return HubOpenness("open", "", url if "github.com" in url else "")


def _resolve_openness(item: HarnessPickerItem, integration_level: str) -> HubOpenness:
    """Resolve openness from the most specific source that actually knows.

    Order: a verified entry, then the ACP registry's own tag, then the vendor
    connection profile that already curates this, then SuperQode's own code.
    A repository HarnessSpec is left unknown on purpose: SuperQode has no way
    to know how a user licenses their own project.
    """
    verified = _OPENNESS_BY_ID.get(item.id)
    if verified is not None:
        return verified
    tagged = _openness_from_acp_tags(item)
    if tagged is not None:
        return tagged
    declared = str(getattr(item.target, "harness_openness", "") or "")
    if declared:
        return HubOpenness(declared)
    if integration_level in {"native", "preset"}:
        return _PROJECT_OPENNESS
    return HubOpenness("")


def is_open_source(item: HarnessPickerItem) -> bool:
    """Whether this entry's harness implementation is known to be open source.

    Exposed for the terminal filter, which must not build a full record for
    every row on every keystroke.
    """
    return _resolve_openness(item, _integration_level(item)).openness == "open"


def _integration_level(item: HarnessPickerItem) -> str:
    if item.group == "Project harnesses":
        return "custom"
    if item.kind == "connection":
        return "managed"
    if item.kind in {"acp", "acp-browser"}:
        return "protocol"
    if item.group == "Optional integrations":
        return "optional"
    if item.group == "Model and task presets":
        return "preset"
    return "native"


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _native_details(item: HarnessPickerItem) -> dict[str, Any]:
    target = item.target
    spec = getattr(target, "spec", None)
    if spec is None:
        return {}

    tools = tuple(
        dict.fromkeys(
            str(tool)
            for agent in getattr(spec, "agents", ())
            for tool in getattr(agent, "tools", ())
        )
    )
    execution = getattr(spec, "execution_policy", None)
    checks = getattr(spec, "checks", None)
    workflow = getattr(spec, "workflow", None)
    recursion = getattr(spec, "recursion", None)
    model_policy = getattr(spec, "model_policy", None)
    policies = tuple(
        value
        for value in (
            f"Sandbox: {_enum_value(getattr(execution, 'sandbox', 'not declared'))}",
            f"Approvals: {_enum_value(getattr(execution, 'approval_profile', 'not declared'))}",
            f"Shell: {'allowed' if getattr(execution, 'allow_shell', False) else 'blocked'}",
            f"Network: {'allowed' if getattr(execution, 'allow_network', False) else 'blocked'}",
            f"Checks: {'enabled' if getattr(checks, 'enabled', False) else 'not required'}",
        )
        if value
    )
    model_config = getattr(model_policy, "config", {}) or {}
    capabilities = [f"{_enum_value(getattr(workflow, 'mode', 'single'))} workflow"]
    if model_config.get("parallel_tools"):
        capabilities.append("Parallel tool calls")
    if getattr(recursion, "enabled", False) or item.runtime == "rlm":
        capabilities.append("Recursive child agents")
    if getattr(getattr(spec, "observability", None), "events", False):
        capabilities.append("Structured run events")
    metadata = getattr(spec, "metadata", {}) or {}
    inherited = getattr(spec, "inherits", None)
    template = metadata.get("template")
    based_on = str(inherited or template or "Repository HarnessSpec")
    item_reference = str(item.path) if item.path is not None else item.id
    return {
        "tools": tools,
        "policies": policies,
        "capabilities": tuple(capabilities),
        "based_on": based_on,
        "tui_commands": (
            f":harness switch {item_reference}",
            f":harness show {item_reference}",
            ":harness status",
        ),
        "cli_commands": (
            f'superqode harness run {item_reference} "Describe your task"',
            f"superqode harness show {item_reference}",
        ),
        **_spec_lifecycle_commands(item_reference),
    }


def _connection_details(item: HarnessPickerItem) -> dict[str, Any]:
    target = item.target
    if item.kind == "acp" and isinstance(target, dict):
        short_name = str(target.get("short_name") or item.id.removeprefix("acp:"))
        install = str(target.get("actions", {}).get("*", {}).get("install", {}).get("command", ""))
        homepage = str(target.get("url") or "")
        publisher = str(target.get("publisher_url") or "")
        setup_step = (
            HubSetupStep(f"Install {target.get('name') or short_name}", command=install)
            if install
            else HubSetupStep(
                f"Set up {target.get('name') or short_name}",
                description=item.issue,
            )
        )
        return {
            "homepage": homepage,
            "repository": publisher if "github.com" in publisher else "",
            "docs_url": homepage or f"{DOCS_BASE}providers/acp/",
            "install_command": install or item.issue,
            "setup_steps": (setup_step,),
            "tui_commands": (
                f":connect acp {short_name}",
                f":harness switch acp:{short_name}",
                ":harness status",
            ),
            "cli_commands": (f'superqode harness run acp:{short_name} "Describe your task"',),
            "policies": (
                "External agent owns its tool loop and tool inventory",
                "SuperQode provides ACP connection, session handoff, and context replay",
            ),
            "capabilities": ("Agent Client Protocol", "Context replay"),
            "based_on": f"{target.get('name') or short_name} agent",
        }

    commands = _COMMANDS_BY_ID.get(
        item.id,
        (f":connect {item.id}", f":harness switch {item.id}", ":harness status"),
    )
    badges = tuple(getattr(target, "badges", ()) or ())
    capabilities = tuple(dict.fromkeys((*badges, "Managed connection from SuperQode")))
    return {
        "homepage": _HOMEPAGE_BY_ID.get(item.id, ""),
        "docs_url": _DOCS_BY_ID.get(item.id, f"{DOCS_BASE}concepts/modes/"),
        "install_command": item.issue,
        "setup_steps": _SETUP_STEPS_BY_ID.get(
            item.id,
            (HubSetupStep("Complete the required setup", description=item.issue),)
            if item.issue
            else (),
        ),
        "tui_commands": commands,
        "cli_commands": (f'superqode harness run {item.id} "Describe your task"',),
        "policies": (
            "The connected coding agent owns its tool loop",
            "Authentication remains with the vendor CLI or account",
            "SuperQode provides discovery, launch, and session continuity",
            "Evaluation and optimization apply to SuperQode HarnessSpecs, not to this agent's "
            "internal loop",
        ),
        "capabilities": capabilities,
        # Vendor labels are the product name on its own, so the display name is
        # already what this route is based on.
        "based_on": item.display_name,
    }


def hub_record(item: HarnessPickerItem, *, include_local_paths: bool = False) -> HubRecord:
    """Convert an internal picker item without exposing its executable target."""
    if item.kind in REFERENCE_ONLY_KINDS and isinstance(item.target, HubRecord):
        return item.target
    details = (
        _connection_details(item) if item.kind in {"connection", "acp"} else _native_details(item)
    )
    integration_level = _integration_level(item)
    openness = _resolve_openness(item, integration_level)
    return HubRecord(
        id=item.id,
        name=item.display_name,
        description=item.description,
        category=item.group,
        kind=item.kind,
        runtime=item.runtime,
        source=item.source,
        readiness=_readiness(item),
        integration_level=integration_level,
        continuity=item.continuity,
        provider=item.provider,
        model=item.model,
        setup=item.issue,
        warning=item.warning,
        project_path=(str(item.path) if include_local_paths and item.path is not None else ""),
        homepage=str(details.get("homepage") or ""),
        repository=str(details.get("repository") or openness.repository or ""),
        docs_url=str(details.get("docs_url") or _DOCS_BY_ID.get(item.id, "")),
        install_command=str(details.get("install_command") or item.issue),
        tui_commands=tuple(details.get("tui_commands") or ()),
        cli_commands=tuple(details.get("cli_commands") or ()),
        eval_commands=tuple(details.get("eval_commands") or ()),
        optimize_commands=tuple(details.get("optimize_commands") or ()),
        tools=tuple(details.get("tools") or ()),
        policies=tuple(details.get("policies") or ()),
        capabilities=tuple(details.get("capabilities") or ()),
        based_on=str(details.get("based_on") or ""),
        popularity_rank=_POPULARITY_RANK.get(item.id, 500),
        setup_steps=tuple(details.get("setup_steps") or ()),
        openness=openness.openness,
        license=openness.license,
    )


def _supplemental_records() -> list[HubRecord]:
    """A deliberately small watchlist of harnesses SuperQode cannot yet run.

    The Hub catalogs harnesses. Model routes, inference servers, memory
    providers and sandboxes are documented under docs/integrations/ instead, so
    that someone browsing for a harness is only ever shown harnesses.
    """

    ecosystem = (
        (
            "ecosystem:zcode",
            "ZCode",
            "Z.AI's official desktop coding harness for GLM-5.3, with its own agent loop, tools, review flow, browser automation, and long-horizon task experience.",
            "https://zcode.z.ai/en",
            ("Z Code", "Z.AI ZCode", "official GLM-5.3 harness"),
        ),
        (
            "ecosystem:headlong",
            "Headlong",
            "Laude Institute's Apache-2.0 agent microharness (<10K lines of Bash) built around shellm, a recursive-language-model (RLM) core, for persistent agents that keep thinking between messages.",
            "https://headlong.ai",
            (
                "headlong",
                "shellm",
                "laude institute",
                "recursive language model",
                "persistent agent",
            ),
        ),
        (
            "ecosystem:qm",
            "QM",
            "Y Combinator's open-source multiplayer agent harness for company work, with interchangeable Pi, OpenCode, Codex, and Claude Code loops.",
            "https://github.com/yc-software/qm",
            ("Y Combinator QM", "multiplayer agent harness"),
        ),
        (
            "ecosystem:harness-new",
            "harness.new",
            "Tensorlake's durable-sandbox playground for launching several coding-agent harnesses.",
            "https://www.harness.new/",
            ("Tensorlake Harness", "instant agent sandboxes"),
        ),
        (
            "ecosystem:replicas",
            "Replicas",
            "A cloud background-agent platform that runs Codex or Claude Code in isolated environments and returns pull requests.",
            "https://www.ycombinator.com/companies/replicas",
            ("background coding agents",),
        ),
        (
            "ecosystem:synth",
            "Synth",
            "A harness and context optimization platform for evaluating coding-agent loops across models and task datasets.",
            "https://www.ycombinator.com/companies/synth-3",
            ("coding harness optimization",),
        ),
        (
            "ecosystem:better-harness",
            "Better Harness",
            "Qoder's cross-agent project for evaluating and improving coding workflows across Claude Code, Codex, Cursor, and other agents.",
            "https://github.com/QoderAI/better-harness",
            ("Qoder Better Harness",),
        ),
        (
            "ecosystem:jcode",
            "jcode",
            "An MIT-licensed terminal coding harness written in Rust, focused on low memory use, fast start, and parallel agent swarms.",
            "https://jcode.sh",
            ("jcode.sh", "Rust coding agent", "RAM efficient harness"),
        ),
        (
            "ecosystem:letta",
            "Letta Code",
            "Letta's Apache-2.0 memory-first coding harness. Agents keep identity and learn across sessions through the `letta` CLI, desktop app, or Letta Cloud.",
            "https://www.letta.com/",
            ("letta", "letta-code", "MemGPT coding agent"),
        ),
        (
            "ecosystem:warp",
            "Warp Agent",
            "Warp's AGPL-3.0 Agent CLI — the same harness as Warp Terminal, runnable in any terminal with a Warp account or WARP_API_KEY.",
            "https://www.warp.dev/agent-cli",
            ("warp", "warp agent cli", "warp terminal agent"),
        ),
        (
            "ecosystem:aider",
            "Aider",
            "Long-running Apache-2.0 terminal harness for AI pair programming, built around Git as the unit of change.",
            "https://github.com/Aider-AI/aider",
            ("aider", "AI pair programming", "git-native coding agent"),
        ),
        (
            "ecosystem:crush",
            "Crush",
            "Charm's terminal coding harness with multi-provider model switching, LSP context, MCP servers and reusable agent skills.",
            "https://github.com/charmbracelet/crush",
            ("charm crush", "glamourous agentic coding"),
        ),
        (
            "ecosystem:plandex",
            "Plandex",
            "MIT-licensed terminal harness aimed at large multi-file tasks, with a durable plan the agent works through.",
            "https://github.com/plandex-ai/plandex",
            ("plandex", "large project coding agent"),
        ),
        (
            "ecosystem:roo-code",
            "Roo Code",
            "Apache-2.0 editor-based harness offering a team of specialised agent modes inside the IDE.",
            "https://github.com/RooCodeInc/Roo-Code",
            ("roo code", "roocode", "agent modes"),
        ),
    )

    records: list[HubRecord] = []
    records.extend(
        HubRecord(
            id=item_id,
            name=name,
            description=description,
            category="Ecosystem watch",
            kind="ecosystem",
            runtime="external",
            source="industry watch",
            readiness="not-supported",
            integration_level="ecosystem",
            continuity="external",
            homepage=homepage,
            interface=_ECOSYSTEM_DETAILS.get(item_id, {}).get("interface", "External project"),
            support_note=_ECOSYSTEM_DETAILS.get(item_id, {}).get(
                "support_note",
                "Not currently supported in SuperQode; tracked for future integration.",
            ),
            last_verified="2026-08-14",
            aliases=aliases,
            docs_url=_ECOSYSTEM_DETAILS.get(item_id, {}).get("docs_url", homepage),
            repository=_ECOSYSTEM_DETAILS.get(item_id, {}).get(
                "repository", _OPENNESS_BY_ID.get(item_id, HubOpenness("")).repository
            ),
            openness=_OPENNESS_BY_ID.get(item_id, HubOpenness("")).openness,
            license=_OPENNESS_BY_ID.get(item_id, HubOpenness("")).license,
            install_command=_ECOSYSTEM_DETAILS.get(item_id, {}).get("install_command", ""),
            tools=_ECOSYSTEM_DETAILS.get(item_id, {}).get("tools", ()),
            policies=_ECOSYSTEM_DETAILS.get(item_id, {}).get("policies", ()),
            capabilities=_ECOSYSTEM_DETAILS.get(item_id, {}).get(
                "capabilities", ("External ecosystem project",)
            ),
            based_on=_ECOSYSTEM_DETAILS.get(item_id, {}).get("based_on", "Independent project"),
            popularity_rank=_ECOSYSTEM_DETAILS.get(item_id, {}).get("popularity_rank", 700),
            setup_steps=_ECOSYSTEM_DETAILS.get(item_id, {}).get("setup_steps", ()),
        )
        for item_id, name, description, homepage, aliases in ecosystem
    )
    return records


def hub_ecosystem_picker_items() -> list[HarnessPickerItem]:
    """Adapt reference-only records for read-only browsing in the TUI.

    These entries are real catalog content but are not switchable harnesses:
    an ecosystem project SuperQode cannot run, or a measurement and
    optimization route you invoke against a harness rather than select as one.
    """
    return [
        HarnessPickerItem(
            id=record.id,
            display_name=record.name,
            description=record.description,
            runtime=record.runtime,
            source=record.source,
            group=record.category,
            available=record.readiness == "supported",
            issue=record.setup,
            continuity=record.continuity,
            kind=record.kind,
            target=record,
        )
        for record in _supplemental_records()
        if record.kind in REFERENCE_ONLY_KINDS
    ]


def build_hub_index(
    root: str | Path = ".",
    *,
    include_all: bool = True,
    items: Iterable[HarnessPickerItem] | None = None,
    public: bool = False,
    include_local_paths: bool = False,
) -> dict[str, Any]:
    """Build the complete serializable Hub index for a project context."""
    inventory = (
        list(items)
        if items is not None
        else harness_picker_items(
            root,
            include_all=include_all,
            expand_protocol_catalog=include_all,
        )
    )
    if public:
        inventory = [item for item in inventory if item.group != "Project harnesses"]
    records = [
        hub_record(item, include_local_paths=include_local_paths and not public).to_dict()
        for item in inventory
    ]
    if items is None and include_all:
        records.extend(record.to_dict() for record in _supplemental_records())
    if public:
        for record in records:
            record["readiness"] = _publication_readiness(record)
    return {
        "schema_version": HUB_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(records),
        "categories": list(dict.fromkeys(record["category"] for record in records)),
        "items": records,
    }


def _publication_readiness(record: dict[str, Any]) -> str:
    """Return readiness that does not depend on the exporting machine.

    ``ready`` and ``setup-required`` come from live probes of the current
    machine: whether ``codex`` is on PATH, whether an optional package is
    importable.  That answer is useful in the TUI and meaningless -- actively
    misleading -- in a snapshot published to the website, where it would report
    the maintainer's laptop as product truth.  Publication therefore states the
    structural answer instead: harnesses SuperQode ships are ready for
    everyone, and routes that wrap an external CLI, account, or optional
    package need setup for everyone.

    States that were never machine-derived (``supported`` for model and
    inference routes, ``not-supported`` for ecosystem entries) pass through.
    """
    readiness = str(record.get("readiness", ""))
    if readiness not in {"ready", "setup-required", "discover"}:
        return readiness
    return "ready" if record.get("integration_level") in {"native", "preset"} else "setup-required"


def filter_hub_records(
    records: Iterable[dict[str, Any]],
    *,
    query: str = "",
    readiness: str | None = "",
    category: str = "",
    openness: str | None = "",
) -> list[dict[str, Any]]:
    """Filter serialized records with the same broad discovery vocabulary as the TUI."""
    needle = query.strip().casefold()
    wanted_readiness = (readiness or "").strip().casefold()
    wanted_category = category.strip().casefold()
    wanted_openness = (openness or "").strip().casefold()
    matched: list[dict[str, Any]] = []
    for record in records:
        if wanted_readiness and str(record.get("readiness", "")).casefold() != wanted_readiness:
            continue
        if wanted_category and str(record.get("category", "")).casefold() != wanted_category:
            continue
        if wanted_openness and str(record.get("openness", "")).casefold() != wanted_openness:
            continue
        if needle:
            haystack = " ".join(
                str(record.get(field, ""))
                for field in (
                    "id",
                    "name",
                    "description",
                    "category",
                    "kind",
                    "runtime",
                    "source",
                    "provider",
                    "model",
                    "interface",
                    "support_note",
                    "aliases",
                    "install_command",
                    "tui_commands",
                    "cli_commands",
                    "tools",
                    "policies",
                    "capabilities",
                    "based_on",
                    "openness",
                    "license",
                    "repository",
                )
            ).casefold()
            if needle not in haystack:
                continue
        matched.append(record)
    return matched


__all__ = [
    "HUB_SCHEMA_VERSION",
    "OPENNESS_LABELS",
    "OPENNESS_VALUES",
    "READINESS_LABELS",
    "READINESS_VALUES",
    "PROJECT_REPOSITORY",
    "HubOpenness",
    "HubRecord",
    "build_hub_index",
    "filter_hub_records",
    "hub_record",
    "is_open_source",
    "openness_label",
    "readiness_label",
]
