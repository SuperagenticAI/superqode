"""Install optional harness packages into the macOS app, without a separate CLI.

The app already runs SuperQode from its own Python. Optional harnesses such as
DeepSeek Harness are extra packages. This module installs those packages into
the app's private folder and can place a ``superqode`` command on the Mac for
Terminal. It does not ask the user to install uv or SuperQode first.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import urllib.request

# Keep these lists identical to the matching extras in pyproject.toml.
EXTRAS: dict[str, tuple[str, ...]] = {
    "adk": ("google-adk>=2.1.0,<3.0",),
    "openai-agents": (
        "openai-agents>=0.20.0,<0.21",
        "openai-agents[litellm]>=0.20.0,<0.21",
    ),
    "deepagents": (
        "deepagents>=0.7.0,<0.8.0",
        "langchain-ollama>=0.3.0",
        "langchain-openai>=0.3.0",
    ),
    "pydanticai": ("pydantic-ai>=1.98.0,<2.0.0",),
    "rlm-code": ("rlm-code[llm-all]>=0.1.11,<0.2.0",),
    "tau": ("tau-ai>=0.3.3,<0.4.0",),
    "deepseek-harness": (
        "deepseek-harness-sdk>=0.1.0rc6,<0.2.0; "
        "(sys_platform == 'darwin' and platform_machine == 'arm64') or "
        "(sys_platform == 'linux' and platform_machine == 'x86_64') or "
        "(sys_platform == 'linux' and platform_machine == 'aarch64')",
    ),
    "monty": ("pydantic-monty>=1.0.0,<2",),
}

_ACTIVE_EXTRAS = ""
_UV_INSTALLER = "https://astral.sh/uv/install.sh"
# Import names a fresh coding job must load before the harness is usable.
_MODULES = {
    "adk": ("google.adk",),
    "openai-agents": ("agents",),
    "deepagents": ("deepagents",),
    "pydanticai": ("pydantic_ai",),
    "rlm-code": ("rlm_code",),
    "tau": ("tau_coding",),
    "deepseek-harness": ("deepseek_harness", "deepseek_harness_runtime"),
    "monty": ("pydantic_monty",),
}


def engine_pythonpath(state_root: Path) -> str:
    """Source tree plus packages installed from the app.

    Coding jobs replace ``PYTHONPATH``. Without the extras folder, an install
    that succeeded still looks missing inside the job.
    """
    source = str(Path(__file__).resolve().parents[2])
    extras = Path(state_root) / "python-extras"
    if extras.is_dir():
        return os.pathsep.join((source, str(extras.resolve())))
    return source


def activate_bundled_extras(root: Path) -> Path:
    """Make packages installed for this app importable in the running engine."""
    global _ACTIVE_EXTRAS
    path = Path(root) / "python-extras"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = str(path.resolve())
    if _ACTIVE_EXTRAS and _ACTIVE_EXTRAS in sys.path:
        sys.path.remove(_ACTIVE_EXTRAS)
    if text not in sys.path:
        sys.path.append(text)
    _ACTIVE_EXTRAS = text
    importlib.invalidate_caches()
    return path


def packages_for(extra: str) -> list[str]:
    """Requirement strings for one allowlisted extra on this machine."""
    if extra not in EXTRAS:
        raise ValueError("This harness cannot be installed from the app")
    chosen = []
    for raw in EXTRAS[extra]:
        requirement, separator, marker = raw.partition(";")
        if separator and not _marker_matches(marker.strip()):
            continue
        chosen.append(requirement.strip())
    if not chosen:
        raise ValueError("This harness does not ship a build for this Mac.")
    return chosen


def install_extra(root: Path, extra: str) -> None:
    """Install one SuperQode extra into the app's private package folder."""
    packages = packages_for(extra)
    target = activate_bundled_extras(root)
    command = installer_command(Path(root) / "bin") + ["--target", str(target), *packages]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "The install did not finish.").strip()
        raise RuntimeError(detail[-800:])
    verify_extra(root, extra)


def verify_extra(root: Path, extra: str) -> None:
    """Fail the install unless a fresh job process, then this one, can import it."""
    modules = _MODULES.get(extra)
    if not modules:
        raise ValueError("This harness cannot be checked after install")
    _import_in_job_process(root, modules)
    activate_bundled_extras(root)
    importlib.invalidate_caches()
    for name in modules:
        importlib.import_module(name)


def _import_in_job_process(root: Path, modules: tuple[str, ...]) -> None:
    script = "import importlib\n" + "\n".join(
        f"importlib.import_module({name!r})" for name in modules
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = engine_pythonpath(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        detail = (
            result.stderr or result.stdout or "The harness installed, but it does not load."
        ).strip()
        raise RuntimeError(detail[-800:])


def installer_command(bin_dir: Path) -> list[str]:
    """Prefer uv, then a private uv, then the app's own pip."""
    uv = ensure_uv(bin_dir)
    if uv:
        return [uv, "pip", "install", "--python", sys.executable]
    return [sys.executable, "-m", "pip", "install"]


def ensure_uv(bin_dir: Path) -> str:
    """Return a uv binary, downloading one into the app folder when needed.

    An empty string means the caller should use the app Python's pip instead.
    """
    found = shutil.which("uv")
    if found:
        return found
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundled = bin_dir / "uv"
    if bundled.is_file() and os.access(bundled, os.X_OK):
        _prepend_path(bin_dir)
        return str(bundled)
    if _download_uv(bin_dir) and bundled.is_file():
        _prepend_path(bin_dir)
        return str(bundled)
    if _pip_available():
        return ""
    raise RuntimeError("Could not prepare the installer. Check the network and try again.")


def publish_cli(root: Path, *, home: Path | None = None) -> None:
    """Put the bundled SuperQode command where Terminal can find it.

    A command that is already a real file is left alone. Failures are ignored
    so opening the app never depends on writing shell configuration.
    """
    try:
        _publish_cli(root, home or Path.home())
    except OSError:
        return


def _publish_cli(root: Path, home: Path) -> None:
    bin_dir = Path(root) / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    shim = bin_dir / "superqode"
    extras = shlex.quote(str((Path(root) / "python-extras").resolve()))
    pythonpath = shlex.quote(os.environ.get("PYTHONPATH", ""))
    native_helper = os.environ.get("SUPERQODE_APPLE_HELPER")
    native_environment = (
        f"export SUPERQODE_APPLE_HELPER={shlex.quote(native_helper)}\n"
        if native_helper and Path(native_helper).is_file()
        else ""
    )
    shim.write_text(
        "#!/bin/sh\n"
        f"export PYTHONPATH={pythonpath}:{extras}\n"
        + native_environment
        + f"export SUPERQODE_STATE_DIR={shlex.quote(str(Path(root).resolve()))}\n"
        + f'exec {shlex.quote(sys.executable)} -m superqode.main "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    link = local_bin / "superqode"
    # Leave a command the user already has, including a symlink to another install.
    if link.exists() or link.is_symlink():
        return
    link.symlink_to(shim)
    _ensure_shell_path(home)


def _ensure_shell_path(home: Path) -> None:
    _append_once(
        home / ".zshrc",
        'export PATH="$HOME/.local/bin:$PATH"  # Added by SuperQode\n',
    )
    fish = home / ".config" / "fish" / "config.fish"
    if fish.is_file():
        _append_once(fish, 'fish_add_path "$HOME/.local/bin"  # Added by SuperQode\n')


def _append_once(path: Path, line: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if ".local/bin" in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        if existing:
            handle.write("\n")
        handle.write(line)


def _download_uv(bin_dir: Path) -> bool:
    script = bin_dir / "uv-install.sh"
    try:
        urllib.request.urlretrieve(_UV_INSTALLER, script)
        env = os.environ.copy()
        env["UV_INSTALL_DIR"] = str(bin_dir)
        env["UV_NO_MODIFY_PATH"] = "1"
        result = subprocess.run(
            ["/bin/sh", str(script)],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _pip_available() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _prepend_path(bin_dir: Path) -> None:
    current = os.environ.get("PATH", "")
    prefix = str(bin_dir)
    if prefix not in current.split(os.pathsep):
        os.environ["PATH"] = prefix + os.pathsep + current


def _marker_matches(marker: str) -> bool:
    """Evaluate the platform marker used by the DeepSeek Harness extra."""
    import platform

    checks = {
        "sys_platform == 'darwin' and platform_machine == 'arm64'": (
            sys.platform == "darwin" and platform.machine() == "arm64"
        ),
        "sys_platform == 'linux' and platform_machine == 'x86_64'": (
            sys.platform == "linux" and platform.machine() == "x86_64"
        ),
        "sys_platform == 'linux' and platform_machine == 'aarch64'": (
            sys.platform == "linux" and platform.machine() == "aarch64"
        ),
    }
    parts = [part.strip().strip("()") for part in marker.split(" or ")]
    if not parts or any(part not in checks for part in parts):
        return False
    return any(checks[part] for part in parts)
