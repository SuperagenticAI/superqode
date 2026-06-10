"""User-extensible exec policy: allow/deny/ask rules for shell commands.

Codex ships a Starlark rule engine deciding which commands auto-approve.
This is the superqode equivalent in plain YAML — declarative, shareable
with a team, and layered *with* (not instead of) the built-in safety
checks: a user ``allow`` can skip the approval prompt, but it can never
override a hard manager deny (dangerous-command guards stay supreme), and
a user ``deny``/``ask`` always wins over an auto-allow.

Policy file (first found wins per rule; project rules take precedence):

- ``<project>/.superqode/execpolicy.yaml``
- ``~/.superqode/execpolicy.yaml``
- ``SUPERQODE_EXEC_POLICY=<path>`` prepends an explicit file (tests, CI)

Format:

    rules:
      - pattern: "git status*"        # glob against the full command
        action: allow
      - pattern: "re:^rm\\s+-rf\\s+/"  # 're:' prefix = regex
        action: deny
        reason: "refuse rm -rf on absolute paths"
      - pattern: "npm publish*"
        action: ask

First matching rule decides; no match means no opinion (normal flow).
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

POLICY_PATH_ENV = "SUPERQODE_EXEC_POLICY"
VALID_ACTIONS = ("allow", "deny", "ask")


@dataclass
class ExecRule:
    pattern: str
    action: str
    reason: str = ""
    source: str = ""

    def matches(self, command: str) -> bool:
        command = command.strip()
        if self.pattern.startswith("re:"):
            try:
                return re.search(self.pattern[3:], command) is not None
            except re.error:
                return False
        return fnmatch.fnmatchcase(command, self.pattern)


class ExecPolicy:
    """An ordered rule list; first match decides."""

    def __init__(self, rules: Optional[List[ExecRule]] = None):
        self.rules: List[ExecRule] = rules or []

    def evaluate(self, command: str) -> Optional[ExecRule]:
        command = (command or "").strip()
        if not command:
            return None
        for rule in self.rules:
            if rule.matches(command):
                return rule
        return None

    @staticmethod
    def _load_file(path: Path) -> List[ExecRule]:
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return []
        rules = []
        for item in data.get("rules", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            pattern = str(item.get("pattern", "")).strip()
            action = str(item.get("action", "")).strip().lower()
            if not pattern or action not in VALID_ACTIONS:
                continue
            rules.append(
                ExecRule(
                    pattern=pattern,
                    action=action,
                    reason=str(item.get("reason", "")).strip(),
                    source=str(path),
                )
            )
        return rules

    @classmethod
    def load(cls, working_directory: Path) -> "ExecPolicy":
        rules: List[ExecRule] = []
        candidates: List[Path] = []
        env_path = os.environ.get(POLICY_PATH_ENV, "").strip()
        if env_path:
            candidates.append(Path(os.path.expanduser(env_path)))
        candidates.append(Path(working_directory) / ".superqode" / "execpolicy.yaml")
        candidates.append(Path.home() / ".superqode" / "execpolicy.yaml")
        for candidate in candidates:
            if candidate.is_file():
                rules.extend(cls._load_file(candidate))
        return cls(rules)


__all__ = ["ExecPolicy", "ExecRule", "POLICY_PATH_ENV", "VALID_ACTIONS"]
