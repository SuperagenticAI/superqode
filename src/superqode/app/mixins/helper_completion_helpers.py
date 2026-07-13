"""Path/command completion candidate helpers."""

from __future__ import annotations
import os
from pathlib import Path
from superqode.app.constants import (
    COMMANDS,
    CONNECT_COMPLETION_COMMANDS,
)
from superqode.app.recipes import PromptCompletionCandidate


class HelperCompletionHelpersMixin:
    """Path/command completion candidate helpers."""

    @staticmethod
    def _candidate_after_prefix(
        value: str,
        prefix: str,
        candidates: list[PromptCompletionCandidate],
    ) -> list[PromptCompletionCandidate]:
        partial = value[len(prefix) :]
        matches: list[PromptCompletionCandidate] = []
        seen: set[str] = set()
        for candidate in sorted(candidates, key=lambda item: item.label.lower()):
            if not candidate.label.lower().startswith(partial.lower()):
                continue
            replacement = prefix + candidate.label
            if replacement == value or replacement in seen:
                continue
            seen.add(replacement)
            matches.append(
                PromptCompletionCandidate(
                    value=replacement,
                    label=candidate.label,
                    description=candidate.description,
                    kind=candidate.kind,
                )
            )
        return matches

    def _path_candidates_after_prefix(
        self,
        value: str,
        prefix: str,
        *,
        files_only: bool = False,
    ) -> list[PromptCompletionCandidate]:
        partial = value[len(prefix) :]
        return [
            PromptCompletionCandidate(
                value=prefix + path,
                label=path,
                description=description,
                kind="path",
            )
            for path, description in self._path_token_candidates(partial, files_only=files_only)
        ]

    @staticmethod
    def _path_token_candidates(partial: str, *, files_only: bool = False) -> list[tuple[str, str]]:
        expanded = partial.replace("\\ ", " ")
        raw_dir, raw_name = os.path.split(expanded)
        base = Path(raw_dir or ".").expanduser()
        if not base.is_absolute():
            base = Path.cwd() / base
        if not base.exists() or not base.is_dir():
            return []
        try:
            entries = sorted(
                base.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            )
        except OSError:
            return []
        candidates: list[tuple[str, str]] = []
        for entry in entries:
            if raw_name and not entry.name.lower().startswith(raw_name.lower()):
                continue
            if entry.name.startswith(".") and not raw_name.startswith("."):
                continue
            if files_only and not entry.is_file():
                continue
            rel = os.path.join(raw_dir, entry.name) if raw_dir else entry.name
            if entry.is_dir():
                candidates.append((rel + "/", "directory"))
            else:
                candidates.append((rel, f"{entry.stat().st_size} bytes"))
            if len(candidates) >= 8:
                break
        return candidates

    def _agent_command_metadata(self) -> dict[str, tuple[str, str]]:
        """Return shortcut -> (name, description) for known ACP agents."""
        metadata: dict[str, tuple[str, str]] = {}

        for agent in getattr(self, "_agents", None) or []:
            short_name = str(getattr(agent, "short_name", "") or "").strip().lower()
            if short_name:
                metadata[short_name] = (
                    str(getattr(agent, "name", "") or short_name),
                    str(getattr(agent, "description", "") or ""),
                )

        for short_name, agent in (getattr(self, "_discovered_acp_agents", {}) or {}).items():
            key = str(short_name or "").strip().lower()
            if key:
                metadata[key] = (
                    str(getattr(agent, "name", "") or key),
                    str(getattr(agent, "description", "") or ""),
                )

        try:
            from superqode.agents.registry import AGENTS

            for short_name, agent in AGENTS.items():
                key = str(short_name or "").strip().lower()
                if key:
                    metadata.setdefault(
                        key,
                        (
                            str(getattr(agent, "name", "") or key),
                            str(getattr(agent, "description", "") or ""),
                        ),
                    )
        except Exception:
            pass

        return metadata

    def _completion_command_values(self) -> tuple[str, ...]:
        """Merge static commands with live agent shortcuts without duplicates."""
        values = list(COMMANDS)
        values.extend(f":{name}" for name in self._agent_command_metadata())
        return tuple(dict.fromkeys(values))

    def _static_command_candidates(self, value: str) -> list[PromptCompletionCandidate]:
        from superqode.app_main import SuperQodeApp

        lowered = value.lower()
        all_commands = self._completion_command_values()
        agent_metadata = self._agent_command_metadata()

        def description(command: str) -> str:
            agent = agent_metadata.get(command.removeprefix(":").lower())
            if agent is not None:
                name, detail = agent
                return detail or f"Connect to {name} through ACP"
            return SuperQodeApp._command_description(command)

        if lowered in {":c", ":co", ":con", ":conn", ":conne", ":connec", ":connect"}:
            priority = list(CONNECT_COMPLETION_COMMANDS)
            commands = [
                *priority,
                *sorted(
                    command
                    for command in all_commands
                    if command.startswith(":connect ") and command not in priority
                ),
            ]
            return [
                PromptCompletionCandidate(
                    value=command,
                    label=command,
                    description=description(command),
                    kind="command",
                )
                for command in commands
                if command != value or lowered == ":connect"
            ]
        matches = [
            PromptCompletionCandidate(
                value=command,
                label=command,
                description=description(command),
                kind="command",
            )
            for command in sorted(
                all_commands,
                key=lambda command: SuperQodeApp._command_completion_sort_key(lowered, command),
            )
            if command.lower().startswith(lowered) and command != value
        ]
        if value in all_commands and matches and lowered != ":q":
            matches.insert(
                0,
                PromptCompletionCandidate(
                    value=value,
                    label=value,
                    description=description(value),
                    kind="command",
                ),
            )
        # The renderer pages eight rows at a time; retain every match here so
        # up/down navigation can reach the full command surface.
        return matches

    @staticmethod
    def _command_description(command: str) -> str:
        descriptions = {
            ":mcp": "manage Model Context Protocol servers",
            ":skills": "manage local project skills",
            ":recipe": "run reusable local workflows",
            ":recipes": "list and run reusable local workflows",
            ":attach": "stage files or URLs for the next prompt",
            ":prompt": "load a prompt file into the input buffer",
            ":model": "inspect or switch active provider/model",
            ":connect": "connect ACP, BYOK, or local runtime",
            ":exit": "exit SuperQode",
            ":quit": "exit SuperQode",
            ":vim": "optional Vim-style command helpers",
            ":set": "set optional TUI modes",
            ":w": "export the current transcript",
            ":e": "view a file",
            ":ls": "list saved sessions",
            ":switchboard": "open durable session graph, handoffs, approvals, and share tree",
            ":sw": "alias for :switchboard",
            ":factory": "switch models, harnesses, and routes without vendor lock-in",
            ":grep": "search the workspace",
            ":status": "show harness status",
            ":tools": "show tool profiles",
        }
        for prefix, description in descriptions.items():
            if command.startswith(prefix):
                return description
        return ""
