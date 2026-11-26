"""Optional Pydantic Coder ACP integration, isolated from the engine's SDKs."""

from __future__ import annotations

import os
from pathlib import Path
import sys

AGENT_ID = "pydantic-coder"
IDENTITY = "pydantic-coder.superqode.dev"
COMMAND = "superqode-pydantic-coder"
VERSIONS = {
    "pydantic-ai-harness": "0.75.0",
    "pydantic-ai-slim": "2.75.0",
    "agent-client-protocol": "0.11.1",
}
PACKAGES = (
    "pydantic-ai-harness[coder,acp]==0.75.0",
    "pydantic-ai-slim[openai,anthropic,google,mcp]==2.75.0",
    "agent-client-protocol==0.11.1",
)
SETUP_HINT = "Run `superqode pydantic-coder setup`, then `superqode pydantic-coder doctor`."


def state_dir() -> Path:
    return (
        Path(os.environ.get("SUPERQODE_STATE_DIR") or Path.home() / ".superqode")
        .expanduser()
        .absolute()
    )


def runtime_python() -> Path:
    return (
        Path(
            os.environ.get("SUPERQODE_PYDANTIC_CODER_PYTHON")
            or state_dir()
            / "runtimes"
            / AGENT_ID
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        .expanduser()
        .absolute()
    )


def installed() -> bool:
    import json

    target = runtime_python()
    try:
        receipt = json.loads((target.parent.parent / "superqode-pydantic-coder.json").read_text())
        return target.is_file() and os.access(target, os.X_OK) and receipt == VERSIONS
    except (OSError, ValueError):
        return False


def is_bundled_agent(agent) -> bool:
    return (
        agent.get("short_name") == AGENT_ID
        and agent.get("identity") == IDENTITY
        and not agent.get("user_defined")
    )


def launcher_argv() -> list[str]:
    """Use this engine's packaged launcher, including inside the native app."""
    return [sys.executable, "-m", "superqode.pydantic_coder.launcher"]
