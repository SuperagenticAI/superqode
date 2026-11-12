"""Readiness and model metadata for the Google Antigravity CLI."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass

MINIMUM_ANTIGRAVITY_CLI_VERSION = (1, 1, 1)

# See devin_status: `list_runtimes()` runs this per vendor picker entry, so an
# uncached probe forked `agy --version` on every completion keystroke.
_CACHE_TTL_SECONDS = 30.0


def version_tuple(text: str) -> tuple[int, int, int] | None:
    """Extract a semantic version triple from ``agy --version`` output."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(map(int, match.groups())) if match else None


def parse_agy_models(output: str) -> list[dict[str, str]]:
    """Read bare model IDs and tab-separated ID and display-name rows."""
    models = []
    seen = set()
    for line in output.splitlines():
        identity, _, name = line.strip().partition("\t")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", identity)
            and identity.lower() not in {"model", "models", "available"}
            and identity not in seen
        ):
            seen.add(identity)
            models.append({"id": identity, "name": name.strip() or identity})
    return models


@dataclass(frozen=True)
class AntigravityCLIStatus:
    binary: str | None
    version_text: str = ""
    version: tuple[int, int, int] | None = None
    issue: str = ""

    @property
    def installed(self) -> bool:
        return self.binary is not None

    @property
    def compatible(self) -> bool:
        return self.installed and self.version is not None and not self.issue


_cached: tuple[float, AntigravityCLIStatus] | None = None


def clear_antigravity_cli_cache() -> None:
    """Drop the memoized probe so the next call re-runs the CLI."""
    global _cached
    _cached = None


def probe_antigravity_cli(*, timeout: float = 3.0, refresh: bool = False) -> AntigravityCLIStatus:
    """Report installation and compatibility without accessing credentials/network.

    The result is memoized for ``_CACHE_TTL_SECONDS``. Pass ``refresh=True`` to
    force a fresh probe after an install or upgrade.
    """
    global _cached

    if not refresh and _cached is not None:
        probed_at, status = _cached
        if time.monotonic() - probed_at < _CACHE_TTL_SECONDS:
            return status
    status = _probe_antigravity_cli(timeout=timeout)
    _cached = (time.monotonic(), status)
    return status


def _probe_antigravity_cli(*, timeout: float) -> AntigravityCLIStatus:
    binary = shutil.which("agy")
    if not binary:
        return AntigravityCLIStatus(
            binary=None,
            issue="install agy from https://antigravity.google/docs/cli-install",
        )
    try:
        process = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return AntigravityCLIStatus(
            binary=binary,
            issue=f"could not run `agy --version`: {exc}",
        )

    text = (process.stdout or process.stderr or "").strip()
    version = version_tuple(text)
    if process.returncode or version is None:
        return AntigravityCLIStatus(
            binary=binary,
            version_text=text,
            version=version,
            issue=f"could not determine Antigravity CLI version: {text or 'no output'}",
        )
    if version < MINIMUM_ANTIGRAVITY_CLI_VERSION:
        return AntigravityCLIStatus(
            binary=binary,
            version_text=text,
            version=version,
            issue=(
                f"Antigravity CLI {text} is incompatible; run `agy update` "
                "(SuperQode requires 1.1.1 or newer)"
            ),
        )
    return AntigravityCLIStatus(binary=binary, version_text=text, version=version)


__all__ = [
    "AntigravityCLIStatus",
    "MINIMUM_ANTIGRAVITY_CLI_VERSION",
    "clear_antigravity_cli_cache",
    "parse_agy_models",
    "probe_antigravity_cli",
    "version_tuple",
]
