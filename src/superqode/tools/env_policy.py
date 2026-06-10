"""Shell environment policy: keep secrets out of spawned commands.

Filtering the environment passed to model-initiated commands means a
prompt-injected ``env`` or ``printenv`` can't exfiltrate API keys.
Opt-in, to preserve existing workflows:

- ``SUPERQODE_SHELL_ENV_POLICY`` unset/``inherit`` — full environment
  (today's behavior).
- ``SUPERQODE_SHELL_ENV_POLICY=filter-secrets`` — drop variables whose
  names look secret-bearing (``*KEY*``, ``*TOKEN*``, ``*SECRET*``,
  ``*PASSWORD*``, ``*CREDENTIAL*``, ``*AUTH*``...), except a small set the
  agent legitimately needs and anything listed in
  ``SUPERQODE_SHELL_ENV_ALLOW`` (comma-separated names).
"""

from __future__ import annotations

import os
import re
from typing import Dict, Optional

POLICY_ENV = "SUPERQODE_SHELL_ENV_POLICY"
ALLOW_ENV = "SUPERQODE_SHELL_ENV_ALLOW"

_SECRET_NAME_RE = re.compile(
    r"(API_?KEY|ACCESS_?KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_?KEY|AUTH)",
    re.IGNORECASE,
)

# Never filtered: these aren't credentials even though they match patterns
# loosely, or the toolchain breaks without them.
_ALWAYS_KEEP = {
    "SSH_AUTH_SOCK",  # agent socket path, not a secret value
}


def env_policy() -> str:
    return os.environ.get(POLICY_ENV, "").strip().lower() or "inherit"


def _allowlist() -> set:
    raw = os.environ.get(ALLOW_ENV, "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def build_shell_env(base: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """Environment for model-spawned shell commands.

    Returns None under the default inherit policy (callers pass env=None so
    the child inherits, preserving exact current behavior), or a filtered
    copy under ``filter-secrets``.
    """
    policy = env_policy()
    if policy in ("inherit", "off", "none", ""):
        return None if base is None else dict(base)
    source = dict(base) if base is not None else dict(os.environ)
    if policy != "filter-secrets":
        return source
    allow = _allowlist() | _ALWAYS_KEEP
    return {
        name: value
        for name, value in source.items()
        if name in allow or not _SECRET_NAME_RE.search(name)
    }


__all__ = ["ALLOW_ENV", "POLICY_ENV", "build_shell_env", "env_policy"]
