"""Cheap local readiness probe for the Google Antigravity CLI."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

MINIMUM_ANTIGRAVITY_CLI_VERSION = (1, 1, 1)


def version_tuple(text: str) -> tuple[int, int, int] | None:
    """Extract a semantic version triple from ``agy --version`` output."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(map(int, match.groups())) if match else None


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


def probe_antigravity_cli(*, timeout: float = 3.0) -> AntigravityCLIStatus:
    """Report installation and compatibility without accessing credentials/network."""
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
    "probe_antigravity_cli",
    "version_tuple",
]
