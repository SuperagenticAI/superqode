"""Classify ACP agent install commands and decide what SuperQode may run.

Agent install commands come from the registry and are written by third parties.
They fall into two very different groups:

* Package-manager installs (``npm install -g <pkg>``, ``cargo install <pkg>``,
  ``uv tool install <pkg>``). The artifact is named, so a user consenting to
  "install this agent" knows what is being fetched.
* Pipe-to-shell installs (``curl ... | bash``). These execute a remote script
  that the user cannot review and whose contents can change after SuperQode
  shipped. Consenting to install an agent is not informed consent to run
  arbitrary remote code, so SuperQode never runs these itself.

SuperQode deliberately does not repair the user's toolchain. If ``npm`` fails
because their Node is too old, the failure is reported verbatim and the flow
stops rather than escalating to sudo or editing PATH.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, replace
from typing import Any, Mapping

__all__ = [
    "InstallCommand",
    "classify_install_command",
    "managed_agent_install",
    "managed_agent_install_rejection_reason",
    "managed_harness_install",
]

#: Leading tokens of commands whose artifact is explicitly named.
_RUNNABLE_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("npm", "install"),
    ("npm", "i"),
    ("pnpm", "add"),
    ("yarn", "global"),
    ("bun", "install"),
    ("cargo", "install"),
    ("go", "install"),
    ("uv", "tool"),
    ("uvx",),
    ("pipx", "install"),
    ("brew", "install"),
)

_SHELL_PIPE_TOKENS = ("|", "&&", ";", ">", "<", "`", "$(")


@dataclass(frozen=True)
class InstallCommand:
    """A registry install command and what SuperQode is willing to do with it."""

    raw: str
    #: Command SuperQode would actually run; normalised where needed.
    command: str
    kind: str  # "npm" | "cargo" | "go" | "python" | "brew" | "pipe-to-shell" | "other" | "none"
    runnable: bool
    #: Why the command is not runnable, shown to the user.
    reason: str = ""
    #: True only for a recipe reviewed and shipped by SuperQode. Registry
    #: metadata alone can never opt a command into automatic execution.
    managed: bool = False
    repository: str = ""
    license: str = ""
    executable: str = ""

    @property
    def argv(self) -> list[str]:
        """Argument vector for a runnable command, empty when not runnable."""
        if not self.runnable:
            return []
        try:
            return shlex.split(self.command)
        except ValueError:
            return []


def _is_pipe_to_shell(command: str) -> bool:
    lowered = command.lower()
    if "|" not in lowered:
        return False
    return any(shell in lowered for shell in ("sh", "bash", "zsh", "iex", "powershell"))


def classify_install_command(raw: str) -> InstallCommand:
    """Decide whether SuperQode may run ``raw`` on the user's behalf."""
    command = (raw or "").strip()
    if not command:
        return InstallCommand(raw="", command="", kind="none", runnable=False)

    if _is_pipe_to_shell(command):
        return InstallCommand(
            raw=command,
            command=command,
            kind="pipe-to-shell",
            runnable=False,
            reason=(
                "SuperQode does not run those for you. Remote scripts piped into "
                "a shell can change without notice; review the vendor's command "
                "before running it yourself."
            ),
        )

    # Anything else carrying shell metacharacters needs a shell to mean what it
    # says, and running it through one has the same reviewability problem.
    if any(token in command for token in _SHELL_PIPE_TOKENS):
        return InstallCommand(
            raw=command,
            command=command,
            kind="other",
            runnable=False,
            reason="This installer needs a shell to run, so SuperQode leaves it to you.",
        )

    try:
        tokens = shlex.split(command)
    except ValueError:
        return InstallCommand(
            raw=command,
            command=command,
            kind="other",
            runnable=False,
            reason="This install command could not be parsed safely.",
        )
    if not tokens:
        return InstallCommand(raw=command, command="", kind="none", runnable=False)

    # A bare `pip install` targets whichever pip is first on PATH, which is
    # rarely the environment the user expects. SuperQode does not silently
    # rewrite the registry's command into something else, so this is reported
    # rather than run, with the uv equivalent named for anyone who wants it.
    if tokens[0] in {"pip", "pip3"} and len(tokens) >= 3 and tokens[1] == "install":
        packages = [token for token in tokens[2:] if not token.startswith("-")]
        suggestion = " ".join(shlex.quote(package) for package in packages)
        return InstallCommand(
            raw=command,
            command=command,
            kind="python",
            runnable=False,
            reason=(
                "SuperQode does not run bare 'pip install', which targets whichever "
                "pip is first on PATH. To install it into a known environment, use "
                + (f"'uv pip install {suggestion}'" if suggestion else "'uv pip install'")
                + " yourself."
            ),
        )

    for prefix in _RUNNABLE_PREFIXES:
        if tuple(tokens[: len(prefix)]) == prefix:
            kind = {
                "npm": "npm",
                "pnpm": "npm",
                "yarn": "npm",
                "bun": "npm",
                "cargo": "cargo",
                "go": "go",
                "uv": "python",
                "uvx": "python",
                "pipx": "python",
                "brew": "brew",
            }.get(tokens[0], "other")
            return InstallCommand(raw=command, command=command, kind=kind, runnable=True)

    return InstallCommand(
        raw=command,
        command=command,
        kind="other",
        runnable=False,
        reason="SuperQode only runs recognised package-manager installs.",
    )


# Automatic external installs are deliberately opt-in. A remote registry can
# describe and display a command, but cannot grant itself execution rights by
# claiming an ``open-source`` tag. Each recipe below is reviewed and released
# with SuperQode; its exact command is re-derived here at click time.
_MANAGED_AGENT_INSTALLS: dict[str, tuple[str, str, str, str]] = {
    "opencode": (
        "npm install -g opencode-ai",
        "https://github.com/anomalyco/opencode",
        "MIT",
        "opencode",
    ),
    "qwen": (
        "npm install -g @qwen-code/qwen-code",
        "https://github.com/QwenLM/qwen-code",
        "Apache-2.0",
        "qwen",
    ),
    "fast-agent": (
        "uv tool install -U fast-agent-mcp",
        "https://github.com/evalstate/fast-agent",
        "Apache-2.0",
        "fast-agent-acp",
    ),
    "pi": (
        "npm install -g @earendil-works/pi-coding-agent pi-acp",
        "https://github.com/earendil-works/pi",
        "MIT",
        "pi-acp",
    ),
    "omp": (
        "bun install -g @oh-my-pi/pi-coding-agent",
        "https://github.com/can1357/oh-my-pi",
        "MIT",
        "omp",
    ),
    "cline": (
        "npm install -g @cline/cli",
        "https://github.com/cline/cline",
        "Apache-2.0",
        "cline",
    ),
    "mistral-vibe": (
        "uv tool install mistral-vibe",
        "https://github.com/mistralai/mistral-vibe",
        "Apache-2.0",
        "vibe-acp",
    ),
    "hermes": (
        "uv tool install 'hermes-agent[acp]'",
        "https://github.com/nousresearch/hermes-agent",
        "MIT",
        "hermes",
    ),
    "deepagents-code": (
        "uv tool install deepagents-code",
        "https://github.com/langchain-ai/deepagents",
        "MIT",
        "dcode",
    ),
    # Subscription authentication remains vendor-owned. SuperQode only
    # installs the named CLI package, then hands off to Junie's own login.
    "junie": (
        "npm install -g @jetbrains/junie",
        "https://www.jetbrains.com/junie/",
        "Proprietary",
        "junie",
    ),
}

_MANAGED_AGENT_IDENTITIES = {
    "opencode": "opencode.ai",
    "qwen": "qwenlm.github.io",
    "fast-agent": "fastagent.ai",
    "pi": "pi.dev",
    "omp": "omp.sh",
    "cline": "cline.bot",
    "mistral-vibe": "mistral-vibe.mistral.ai",
    "hermes": "hermes-agent.nousresearch.com",
    "deepagents-code": "deepagents-code.langchain.com",
    "junie": "junie.jetbrains.com",
}

_MANAGED_HARNESS_INSTALLS: dict[str, tuple[str, str, str, str]] = {
    "letta": (
        "npm install -g @letta-ai/letta-code",
        "https://github.com/letta-ai/letta-code",
        "Apache-2.0",
        "letta",
    ),
}


def _managed_install(
    integration_id: str, recipes: Mapping[str, tuple[str, str, str, str]]
) -> InstallCommand | None:
    recipe = recipes.get((integration_id or "").strip())
    if recipe is None:
        return None
    command, repository, license_name, executable = recipe
    classified = classify_install_command(command)
    if not classified.runnable:
        return None
    return replace(
        classified,
        managed=True,
        repository=repository,
        license=license_name,
        executable=executable,
    )


def managed_agent_install(agent: Mapping[str, Any]) -> InstallCommand | None:
    """Return a reviewed install recipe for a bundled agent."""
    short_name = str(agent.get("short_name") or "").strip()
    identity = str(agent.get("identity") or "").strip()
    if identity != _MANAGED_AGENT_IDENTITIES.get(short_name):
        return None
    return _managed_install(short_name, _MANAGED_AGENT_INSTALLS)


def managed_agent_install_rejection_reason(agent: Mapping[str, Any]) -> str:
    """Explain why a known recipe did not pass its fail-closed identity check."""
    short_name = str(agent.get("short_name") or "").strip()
    identity = str(agent.get("identity") or "").strip()
    expected = _MANAGED_AGENT_IDENTITIES.get(short_name)
    if expected and identity != expected:
        actual = identity or "<missing>"
        return (
            f"Managed install blocked: registry identity mismatch for {short_name!r}; "
            f"expected {expected!r}, received {actual!r}."
        )
    return ""


def managed_harness_install(harness_id: str) -> InstallCommand | None:
    """Return a reviewed recipe for an open harness without an agent route."""
    return _managed_install(harness_id, _MANAGED_HARNESS_INSTALLS)
