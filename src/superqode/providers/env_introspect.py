"""Work out which environment SuperQode is running from and produce the correct
uv command for installing an optional extra into *that same* environment.

SuperQode is distributed as a uv tool (``uv tool install superqode``). Optional
runtimes (codex-sdk, claude-agent-sdk, ...) must be installed into the same
environment SuperQode runs from, otherwise they are not importable and the app
reports them as "not installed" even though the user installed them somewhere.
That mismatch is the root cause of "I installed it but it is not detected": the
extra landed in a different interpreter than the one SuperQode runs under.

The functions here name a uv command that targets SuperQode's own environment,
so following the hint always makes detection succeed.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "EnvironmentInfo",
    "environment_info",
    "running_context",
    "install_command",
    "python_package_install_command",
    "missing_extra_hint",
]


@dataclass(frozen=True)
class EnvironmentInfo:
    """User-facing description of the Python environment running SuperQode."""

    context: str
    label: str
    python: str
    prefix: str
    project_root: str | None = None

    @property
    def target(self) -> str:
        if self.context == "uv-tool":
            return f"the uv tool environment at {self.prefix}"
        if self.context == "dev-checkout":
            return f"the SuperQode checkout at {self.project_root or Path.cwd()}"
        if self.context == "project":
            return f"the current project environment at {self.project_root or Path.cwd()}"
        if self.context == "venv":
            return f"the active virtual environment at {self.prefix}"
        return f"the Python environment at {self.prefix}"


def _running_in_uv_tool() -> bool:
    """True when SuperQode runs from a ``uv tool install`` environment.

    uv tool environments live under ``<data>/uv/tools/<name>/`` (for example
    ``~/.local/share/uv/tools/superqode`` on Linux or
    ``~/Library/Application Support/uv/tools/superqode`` on macOS).
    """
    try:
        prefix = Path(sys.prefix).resolve().as_posix()
    except OSError:
        prefix = sys.prefix.replace(os.sep, "/")
    return "/uv/tools/" in prefix


def _running_in_venv() -> bool:
    """True when SuperQode runs from a virtual environment (project or checkout)."""
    if os.environ.get("VIRTUAL_ENV"):
        return True
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _has_pyproject() -> bool:
    try:
        return (Path.cwd() / "pyproject.toml").is_file()
    except OSError:
        return False


def _cwd_project_name() -> str | None:
    try:
        with (Path.cwd() / "pyproject.toml").open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    name = project.get("name")
    return name if isinstance(name, str) else None


def _running_from_superqode_checkout() -> bool:
    try:
        cwd = Path.cwd()
    except OSError:
        return False
    return _cwd_project_name() == "superqode" and (cwd / "src" / "superqode").is_dir()


def running_context() -> str:
    """Classify the active environment.

    Returns one of ``"uv-tool"``, ``"dev-checkout"``, ``"project"``,
    ``"venv"`` or ``"system"``.
    """
    if _running_in_uv_tool():
        return "uv-tool"
    if _running_in_venv():
        if _running_from_superqode_checkout():
            return "dev-checkout"
        return "project" if _has_pyproject() else "venv"
    return "system"


def environment_info() -> EnvironmentInfo:
    """Describe where SuperQode is running from."""
    context = running_context()
    labels = {
        "uv-tool": "uv tool install",
        "dev-checkout": "SuperQode dev checkout",
        "project": "project virtual environment",
        "venv": "virtual environment",
        "system": "system Python",
    }
    project_root = str(Path.cwd()) if context in {"dev-checkout", "project"} else None
    return EnvironmentInfo(
        context=context,
        label=labels.get(context, context),
        python=sys.executable,
        prefix=sys.prefix,
        project_root=project_root,
    )


def install_command(extra: str) -> str:
    """uv command that installs ``superqode[extra]`` into SuperQode's own env.

    The recommended distribution is a global uv tool, so the default and the
    fallback both use ``uv tool install``. When SuperQode is run from a project
    or checkout virtualenv (e.g. during development) the command targets that
    venv instead, so the extra lands where the running interpreter can import it.
    """
    spec = f'"superqode[{extra}]"'
    context = running_context()
    if context == "dev-checkout":
        return f'uv pip install -e ".[{extra}]"'
    if context == "project":
        return f"uv add {spec}"
    if context == "venv":
        return f"uv pip install {spec}"
    # uv-tool (recommended) or system: install/refresh the global tool with the
    # extra so it lands in the same environment SuperQode runs from.
    return f"uv tool install {spec}"


def python_package_install_command(requirement: str, *, python: str | None = None) -> str:
    """Exact command for installing a package into the running Python env."""
    python = python or sys.executable
    req = shlex.quote(requirement)
    py = shlex.quote(python)
    if shutil.which("uv"):
        return f"uv pip install --python {py} {req}"
    return f"{py} -m pip install {req}"


def missing_extra_hint(extra: str, *, suffix: str = "") -> str:
    """A full "how to enable" hint: the uv command plus any extra steps.

    ``suffix`` is appended for runtimes that need more than the package, e.g.
    ``"then run `codex login`"``.
    """
    hint = install_command(extra)
    if suffix:
        return f"{hint}, {suffix}"
    return hint
