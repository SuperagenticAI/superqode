"""Network destination allowlist for shell commands.

Pairs with the command-safety classifier: when a command reaches the network,
this decides whether its destinations are *trusted* (known package registries /
source hosts → safe to auto-run), *untrusted* (a host not on the allowlist →
flag/deny), or *unknown* (no host could be determined → ask).

This is the network policy layer. It does not itself enforce at the OS level —
the local sandbox does that — but it lets trusted installs (`pip install`,
`npm install`, `git clone github…`) run without prompts while still gating
arbitrary egress like `curl evil.com`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Trusted by default: package registries, language toolchains, source forges.
DEFAULT_ALLOWED_DOMAINS = {
    # Python
    "pypi.org",
    "pypi.python.org",
    "files.pythonhosted.org",
    # JS
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    # Rust / Go / Ruby
    "crates.io",
    "static.crates.io",
    "index.crates.io",
    "proxy.golang.org",
    "sum.golang.org",
    "goproxy.io",
    "rubygems.org",
    # Source forges
    "github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "gitlab.com",
    "bitbucket.org",
    # Containers / models
    "ghcr.io",
    "registry-1.docker.io",
    "auth.docker.io",
    "huggingface.co",
    # OS package mirrors
    "deb.debian.org",
    "archive.ubuntu.com",
    "security.ubuntu.com",
}

# Commands whose implicit destination is a known registry even without a URL.
_IMPLICIT_REGISTRY = {
    "pip": "files.pythonhosted.org",
    "pip3": "files.pythonhosted.org",
    "uv": "files.pythonhosted.org",
    "poetry": "files.pythonhosted.org",
    "npm": "registry.npmjs.org",
    "pnpm": "registry.npmjs.org",
    "yarn": "registry.yarnpkg.com",
    "cargo": "crates.io",
    "gem": "rubygems.org",
    "bundle": "rubygems.org",
}

_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s'\"]+)", re.IGNORECASE)
_SCP_RE = re.compile(r"\b[\w.-]+@([\w.-]+):", re.IGNORECASE)  # git@github.com:owner/repo


@dataclass
class NetworkVerdict:
    """Result of evaluating a network command against the allowlist."""

    status: str  # "trusted" | "untrusted" | "unknown" | "none"
    hosts: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


def load_allowlist() -> set[str]:
    """Default allowlist plus any domains from ``SUPERQODE_NET_ALLOW`` (CSV)."""
    extra = os.environ.get("SUPERQODE_NET_ALLOW", "")
    domains = set(DEFAULT_ALLOWED_DOMAINS)
    try:
        from superqode.governance import active_governance

        bundle = active_governance()
        if bundle is not None:
            domains.update(item.lower() for item in bundle.allowed_hosts)
    except Exception:
        pass
    for item in extra.split(","):
        item = item.strip().lower()
        if item:
            domains.add(item)
    return domains


def _host_allowed(host: str, allowlist: set[str]) -> bool:
    host = host.lower().split(":")[0]  # drop any port
    return any(host == d or host.endswith("." + d) for d in allowlist)


def extract_hosts(command: str) -> list[str]:
    """Pull destination hosts out of a network command (URLs, scp/git targets)."""
    hosts: list[str] = []
    for match in _URL_RE.finditer(command):
        netloc = match.group(1)
        if "@" in netloc:  # strip creds: user:pass@host
            netloc = netloc.split("@", 1)[1]
        hosts.append(netloc.split(":")[0])
    for match in _SCP_RE.finditer(command):
        hosts.append(match.group(1))

    if not hosts:
        # No explicit URL: infer the implicit registry for package managers.
        for token in command.split():
            base = token.split("/")[-1]
            if base in _IMPLICIT_REGISTRY:
                hosts.append(_IMPLICIT_REGISTRY[base])
                break
    # De-dupe, preserve order.
    seen: set[str] = set()
    ordered = []
    for h in hosts:
        if h and h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered


def check_network(command: str, allowlist: set[str] | None = None) -> NetworkVerdict:
    """Classify a network command's destinations against the allowlist."""
    allowlist = allowlist if allowlist is not None else load_allowlist()
    hosts = extract_hosts(command)
    if not hosts:
        return NetworkVerdict(status="unknown", hosts=[])
    blocked = [h for h in hosts if not _host_allowed(h, allowlist)]
    if blocked:
        return NetworkVerdict(status="untrusted", hosts=hosts, blocked=blocked)
    return NetworkVerdict(status="trusted", hosts=hosts)


def strict_mode() -> bool:
    """When set, untrusted network destinations are denied rather than prompted."""
    try:
        from superqode.governance import active_governance

        bundle = active_governance()
        if bundle is not None and bundle.network_strict:
            return True
    except Exception:
        pass
    return os.environ.get("SUPERQODE_NET_STRICT", "").strip().lower() in ("1", "true", "yes")
