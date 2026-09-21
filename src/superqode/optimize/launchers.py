"""Managed local launchers for Jev Tool Routing.

The launcher layer owns only files bearing its marker.  It never edits a
harness binary or the harness's own configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping, Sequence

from .profiles import get_profile, profiles

CONFIG_VERSION = 1
CONFIG_NAME = "jev-routing.json"
LAUNCHER_MARKER = "Managed by SuperQode Jev Tool Routing"
SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic", "google", "xai"})
_HARNESS_PROVIDERS = {
    "codex": frozenset({"openai"}),
    "claude": frozenset({"anthropic"}),
    "opencode": SUPPORTED_PROVIDERS,
    "grok": frozenset({"xai"}),
    "pi": SUPPORTED_PROVIDERS,
    "superqode": SUPPORTED_PROVIDERS,
}


@dataclass(frozen=True)
class LauncherEntry:
    harness: str
    launcher: str
    provider: str
    model: str
    mode: str
    threshold: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "launcher": self.launcher,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "threshold": self.threshold,
        }


def config_root(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    if value := str(source.get("SUPERQODE_HOME", "") or "").strip():
        return Path(value).expanduser()
    if value := str(source.get("XDG_CONFIG_HOME", "") or "").strip():
        return Path(value).expanduser() / "superqode"
    return Path.home() / ".superqode"


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    return config_root(environ) / CONFIG_NAME


def default_bin_dir(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    if value := str(source.get("SUPERQODE_BIN_DIR", "") or "").strip():
        return Path(value).expanduser()
    if value := str(source.get("XDG_BIN_HOME", "") or "").strip():
        return Path(value).expanduser()
    return Path.home() / ".local" / "bin"


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"version": CONFIG_VERSION, "harnesses": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("harnesses", {}), dict):
        return {"version": CONFIG_VERSION, "harnesses": {}}
    return raw


def save_config(data: Mapping[str, Any], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    payload = dict(data)
    payload["version"] = CONFIG_VERSION
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.chmod(0o600)
    os.replace(temporary, target)
    target.chmod(0o600)
    return target


def launcher_name(harness: str, *, windows: bool | None = None) -> str:
    is_windows = os.name == "nt" if windows is None else windows
    suffix = ".cmd" if is_windows else ""
    return f"{harness}-jev{suffix}"


def launcher_text(harness: str, *, windows: bool | None = None) -> str:
    # Harness names come only from the fixed profile registry, never raw shell
    # input.  Keeping the shim constant leaves all mutable settings in JSON.
    get_profile(harness)
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        return (
            f"@echo off\r\nREM {LAUNCHER_MARKER}\r\nsuperqode optimize launch {harness} -- %*\r\n"
        )
    return f'#!/bin/sh\n# {LAUNCHER_MARKER}\nexec superqode optimize launch {harness} -- "$@"\n'


def is_managed_launcher(path: Path, harness: str | None = None) -> bool:
    if path.is_symlink():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if LAUNCHER_MARKER not in text:
        return False
    return harness is None or f"optimize launch {harness} --" in text


def install_launcher(harness: str, bin_dir: Path) -> Path:
    target = bin_dir / launcher_name(harness)
    if (target.exists() or target.is_symlink()) and not is_managed_launcher(target, harness):
        raise FileExistsError(f"refusing to overwrite unmanaged launcher: {target}")
    bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=bin_dir,
        prefix=f".{target.name}.",
        delete=False,
        newline="",
    ) as handle:
        temporary = Path(handle.name)
        handle.write(launcher_text(harness))
    if os.name != "nt":
        temporary.chmod(0o755)
    os.replace(temporary, target)
    return target


def remove_launcher(path: Path, harness: str) -> bool:
    if not path.exists():
        return True
    if not is_managed_launcher(path, harness):
        return False
    path.unlink()
    return True


def default_harnesses() -> tuple[str, ...]:
    return tuple(
        profile.id
        for profile in profiles()
        if profile.executable() is not None and profile.support in {"gateway", "native"}
    )


def enable_launchers(
    harnesses: Sequence[str],
    *,
    provider: str | None = None,
    model: str = "",
    mode: str = "shadow",
    threshold: float = 0.30,
    bin_dir: Path | None = None,
    path: Path | None = None,
) -> tuple[list[LauncherEntry], list[dict[str, str]]]:
    if provider is not None and provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    if mode not in {"shadow", "enforce"}:
        raise ValueError("mode must be shadow or enforce")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    target_config = path or config_path()
    data = load_config(target_config)
    configured = dict(data.get("harnesses", {}))
    destination = bin_dir or default_bin_dir()
    enabled: list[LauncherEntry] = []
    skipped: list[dict[str, str]] = []

    for harness in dict.fromkeys(harnesses):
        profile = get_profile(harness)
        if profile.support == "detect-only":
            skipped.append({"harness": harness, "reason": profile.note or "detect-only"})
            continue
        chosen_provider = provider or str(
            configured.get(harness, {}).get("provider") or profile.default_provider
        )
        chosen_model = model or str(configured.get(harness, {}).get("model") or "")
        if chosen_provider not in _HARNESS_PROVIDERS[harness]:
            skipped.append(
                {
                    "harness": harness,
                    "reason": f"{profile.label} does not support the {chosen_provider} wire protocol",
                }
            )
            continue
        if harness == "pi" and not chosen_model:
            skipped.append({"harness": harness, "reason": "Pi requires --model"})
            continue
        if harness == "opencode" and chosen_provider == "google" and not chosen_model:
            skipped.append({"harness": harness, "reason": "OpenCode with Google requires --model"})
            continue
        try:
            launcher = install_launcher(harness, destination)
        except FileExistsError as exc:
            skipped.append({"harness": harness, "reason": str(exc)})
            continue
        entry = LauncherEntry(
            harness=harness,
            launcher=str(launcher),
            provider=chosen_provider,
            model=chosen_model,
            mode=mode,
            threshold=threshold,
        )
        configured[harness] = entry.as_dict()
        enabled.append(entry)

    data["harnesses"] = configured
    data["bin_dir"] = str(destination)
    if enabled or target_config.exists():
        save_config(data, target_config)
    return enabled, skipped


def disable_launchers(
    harnesses: Sequence[str] = (),
    *,
    path: Path | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    target_config = path or config_path()
    data = load_config(target_config)
    configured = dict(data.get("harnesses", {}))
    selected = tuple(dict.fromkeys(harnesses)) or tuple(configured)
    removed: list[str] = []
    retained: list[dict[str, str]] = []
    for harness in selected:
        raw = configured.get(harness)
        if not isinstance(raw, dict):
            retained.append({"harness": harness, "reason": "not enabled"})
            continue
        launcher = Path(str(raw.get("launcher", "")))
        if launcher and remove_launcher(launcher, harness):
            configured.pop(harness, None)
            removed.append(harness)
        else:
            retained.append(
                {"harness": harness, "reason": f"launcher is no longer managed: {launcher}"}
            )
    data["harnesses"] = configured
    if configured:
        save_config(data, target_config)
    elif target_config.exists():
        target_config.unlink()
    return removed, retained


def launcher_rows(path: Path | None = None) -> list[dict[str, Any]]:
    target_config = path or config_path()
    data = load_config(target_config)
    rows: list[dict[str, Any]] = []
    for harness, raw in sorted(data.get("harnesses", {}).items()):
        if not isinstance(raw, dict):
            continue
        launcher = Path(str(raw.get("launcher", "")))
        rows.append(
            {
                "harness": harness,
                "launcher": str(launcher),
                "launcher_exists": launcher.is_file(),
                "launcher_managed": is_managed_launcher(launcher, harness),
                "provider": str(raw.get("provider", "")),
                "model": str(raw.get("model", "")),
                "mode": str(raw.get("mode", "shadow")),
                "threshold": float(raw.get("threshold", 0.30)),
                "executable": shutil.which(harness) or "",
            }
        )
    return rows


def launch_arguments(
    harness: str, harness_args: Sequence[str], path: Path | None = None
) -> list[str]:
    data = load_config(path or config_path())
    raw = data.get("harnesses", {}).get(harness)
    if not isinstance(raw, dict):
        raise ValueError(f"{harness}-jev is not enabled; run superqode optimize enable {harness}")
    command = ["optimize", "run", harness]
    if provider := str(raw.get("provider", "") or ""):
        command.extend(["--provider", provider])
    if model := str(raw.get("model", "") or ""):
        command.extend(["--model", model])
    command.extend(
        [
            "--mode",
            str(raw.get("mode", "shadow")),
            "--threshold",
            str(float(raw.get("threshold", 0.30))),
            "--",
            *harness_args,
        ]
    )
    return command


__all__ = [
    "CONFIG_NAME",
    "CONFIG_VERSION",
    "LAUNCHER_MARKER",
    "LauncherEntry",
    "config_path",
    "default_bin_dir",
    "default_harnesses",
    "disable_launchers",
    "enable_launchers",
    "install_launcher",
    "is_managed_launcher",
    "launch_arguments",
    "launcher_rows",
    "load_config",
    "remove_launcher",
    "save_config",
]
