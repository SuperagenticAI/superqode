"""Prompt autocompletion panel and candidates."""

from __future__ import annotations
from pathlib import Path
from textual.widgets import Static
from rich.text import Text
from superqode.app.constants import (
    THEME,
    COMMANDS,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput
from superqode.app.recipes import PromptCompletionCandidate


class CompletionMixin:
    """Prompt completion candidates, panel updates, and accept logic."""

    def _complete_prompt_input(self, input_widget: SelectionAwareInput) -> bool:
        """Complete the active prompt command in-place."""
        candidates = self._prompt_completion_candidates_for(input_widget.value)
        if not candidates:
            self._hide_prompt_completion_panel()
            return False
        if len(candidates) > 1 and not self._prompt_completion_visible:
            self._show_prompt_completion_panel(candidates)
            return True
        self._prompt_completion_candidates = candidates
        self._prompt_completion_index = 0
        return self._accept_prompt_completion(input_widget)

    def _suggest_prompt_completion(self, value: str) -> str | None:
        """Return a contextual completion for command-like prompt text."""
        candidates = self._prompt_completion_candidates_for(value)
        return candidates[0].value if candidates else None

    def _mention_completion_candidates(self, value: str) -> list[PromptCompletionCandidate] | None:
        """Return file candidates for an active @mention, or None when not in one.

        The picker reuses the existing prompt-completion panel so the look and
        feel matches slash/colon command completion exactly. Each candidate's
        ``value`` is the full replacement text: everything before the "@" plus
        ``@<path>``, so accepting it leaves a reference that
        ``expand_file_references`` recognises on submit.
        """
        match = self._MENTION_QUERY_RE.search(value)
        if match is None:
            return None
        query = match.group(1)
        at_pos = match.start(1) - 1  # index of the "@" itself
        prefix_text = value[:at_pos]
        candidates: list[PromptCompletionCandidate] = []
        for path, description in self._path_token_candidates(query):
            replacement = f"{prefix_text}@{path}"
            # Skip the no-op match so a fully-typed reference closes the panel
            # instead of lingering on the path the user already selected.
            if replacement == value:
                continue
            candidates.append(
                PromptCompletionCandidate(
                    value=replacement,
                    label=f"@{path}",
                    description=description,
                    kind="dir" if path.endswith("/") else "file",
                )
            )
        return candidates

    def _prompt_completion_candidates_for(self, value: str) -> list[PromptCompletionCandidate]:
        """Return contextual completion candidates for command-like prompt text."""
        mention_candidates = self._mention_completion_candidates(value)
        if mention_candidates is not None:
            return mention_candidates

        if not value.startswith(("/", ":")):
            return []

        lowered = value.lower()
        # Codex has a deeper command tree than the generic static list.  Keep
        # it contextual so every subcommand remains keyboard-reachable and
        # offer values for its model/effort controls without probing the SDK on
        # every input change.
        if lowered == ":codex":
            return [
                PromptCompletionCandidate(
                    value=":codex",
                    label=":codex",
                    description="Connect to the Codex SDK runtime",
                    kind="command",
                ),
                *self._codex_subcommand_completion_candidates(":codex "),
            ]
        if lowered.startswith(":codex effort "):
            return self._codex_effort_completion_candidates(value)
        if lowered.startswith(":codex model "):
            return self._codex_model_completion_candidates(value)
        if lowered.startswith(":codex sandbox "):
            return self._codex_sandbox_completion_candidates(value)
        if lowered.startswith(":codex "):
            return self._codex_subcommand_completion_candidates(value)
        if lowered == ":agy":
            return [
                PromptCompletionCandidate(
                    value=":agy",
                    label=":agy",
                    description="Show the Antigravity CLI command catalog",
                    kind="command",
                ),
                *self._agy_subcommand_completion_candidates(":agy "),
            ]
        if lowered.startswith(":agy plugin "):
            return self._agy_plugin_completion_candidates(value)
        if lowered.startswith(":agy effort "):
            return self._agy_value_completion_candidates(
                value,
                ":agy effort ",
                (
                    ("auto", "Use the Antigravity CLI default"),
                    ("low", "Use low reasoning effort"),
                    ("medium", "Use medium reasoning effort"),
                    ("high", "Use high reasoning effort"),
                ),
            )
        if lowered.startswith(":agy "):
            return self._agy_subcommand_completion_candidates(value)
        if lowered.startswith(":harness use-all "):
            return self._harness_candidates_after_prefix(
                value, ":harness use-all ", include_all=True
            )
        if lowered.startswith(":harness use "):
            return self._harness_candidates_after_prefix(value, ":harness use ", include_all=False)
        if lowered.startswith(":harness switch "):
            return self._harness_candidates_after_prefix(
                value, ":harness switch ", include_all=False
            )
        if lowered.startswith(":harness show "):
            return self._harness_candidates_after_prefix(value, ":harness show ", include_all=True)
        if lowered.startswith(":harness customize "):
            return self._harness_candidates_after_prefix(
                value, ":harness customize ", include_all=True
            )
        if lowered.startswith(":connect acp "):
            return self._acp_candidates_after_prefix(value)
        context_specs = [
            (":mcp connect ", self._mcp_server_completion_candidates),
            (":mcp disconnect ", self._mcp_server_completion_candidates),
            (":mcp reconnect ", self._mcp_server_completion_candidates),
            (":mcp doctor ", self._mcp_server_completion_candidates),
            (":mcp attach ", self._mcp_resource_completion_candidates),
            (":skills info ", self._skill_completion_candidates),
            (":skills search ", self._skill_completion_candidates),
            (":skills optimize ", self._skill_completion_candidates),
            (":skills enable ", self._skill_completion_candidates),
            (":skills disable ", self._all_skill_completion_candidates),
            (":skills remove ", self._all_skill_completion_candidates),
            (":recipe run ", self._recipe_completion_candidates),
            (":recipe info ", self._recipe_completion_candidates),
            (":recipe doctor ", self._recipe_completion_candidates),
            (":recipes run ", self._recipe_completion_candidates),
            (":recipes info ", self._recipe_completion_candidates),
            (":recipes doctor ", self._recipe_completion_candidates),
            (":connect byok ", self._byok_provider_completion_candidates),
            (":connect local ", self._local_provider_completion_candidates),
            (":theme ", self._theme_completion_candidates),
            (":runtime ", self._runtime_completion_candidates),
            (":connect ", self._connect_profile_completion_candidates),
        ]
        for prefix, provider in context_specs:
            if lowered.startswith(prefix):
                return self._candidate_after_prefix(value, prefix, provider())

        if lowered.startswith(":attach "):
            return self._path_candidates_after_prefix(value, ":attach ")
        if lowered.startswith(":prompt "):
            return self._path_candidates_after_prefix(value, ":prompt ", files_only=True)
        if lowered.startswith(":model switch "):
            return self._model_switch_candidates(value, ":model switch ")

        return self._static_command_candidates(value)

    @staticmethod
    def _acp_completion_candidates() -> list[PromptCompletionCandidate]:
        """Return registry controls and bundled ACP agent names."""
        from superqode.agents.acp_registry import get_all_registry_agents
        from superqode.providers.acp_registry import registry_catalog_tier

        candidates = [
            PromptCompletionCandidate(
                value="all",
                label="all",
                description="Open the complete official and SuperQode ACP catalog",
                kind="catalog",
            ),
            PromptCompletionCandidate(
                value="enterprise",
                label="enterprise",
                description="Show enterprise ACP agent runtimes",
                kind="catalog",
            ),
            PromptCompletionCandidate(
                value="refresh",
                label="refresh",
                description="Refresh the cached official ACP Registry",
                kind="command",
            ),
        ]
        seen: set[str] = set()
        for agent in get_all_registry_agents().values():
            short_name = str(agent["short_name"])
            if short_name in seen:
                continue
            seen.add(short_name)
            tier = registry_catalog_tier("", short_name)
            candidates.append(
                PromptCompletionCandidate(
                    value=short_name,
                    label=short_name,
                    description=f"{tier} · {agent['name']}",
                    kind="agent",
                )
            )
        return candidates

    @classmethod
    def _acp_candidates_after_prefix(cls, value: str) -> list[PromptCompletionCandidate]:
        """Complete ACP controls first, followed by catalog agents."""
        prefix = ":connect acp "
        partial = value[len(prefix) :].casefold()
        matches: list[PromptCompletionCandidate] = []
        for candidate in cls._acp_completion_candidates():
            if not candidate.label.casefold().startswith(partial):
                continue
            replacement = prefix + candidate.label
            if replacement == value:
                continue
            matches.append(
                PromptCompletionCandidate(
                    value=replacement,
                    label=candidate.label,
                    description=candidate.description,
                    kind=candidate.kind,
                )
            )
        return matches

    @staticmethod
    def _harness_candidates_after_prefix(
        value: str, prefix: str, *, include_all: bool
    ) -> list[PromptCompletionCandidate]:
        """Complete from the curated or complete catalog without losing group order."""
        try:
            from superqode.harness import list_harnesses, recommended_harnesses

            entries = (
                list_harnesses(Path.cwd()) if include_all else recommended_harnesses(Path.cwd())
            )
        except Exception:
            return []
        partial = value[len(prefix) :].lower()
        candidates: list[PromptCompletionCandidate] = []
        for entry in entries:
            if not entry.available or not entry.id.lower().startswith(partial):
                continue
            replacement = prefix + entry.id
            if replacement == value:
                continue
            route = f"{entry.provider}/{entry.model} · " if entry.provider and entry.model else ""
            source = "project · " if entry.source == "file" else ""
            kind = "project" if entry.source == "file" else entry.category
            candidates.append(
                PromptCompletionCandidate(
                    value=replacement,
                    label=entry.id,
                    description=f"{route}{source}{entry.description}",
                    kind=kind,
                )
            )
        return candidates

    @staticmethod
    def _theme_completion_candidates() -> list[PromptCompletionCandidate]:
        """Theme names for `:theme <name>` completion."""
        from superqode.app.theme_bridge import available_themes

        return [
            PromptCompletionCandidate(
                value=name,
                label=name,
                description=description,
                kind="theme",
            )
            for name, description in available_themes()
        ]

    @staticmethod
    def _should_submit_prompt_without_completion(value: str) -> bool:
        """Return True when Enter should execute the exact command in the prompt."""
        text = value.strip()
        if not text.startswith(("/", ":")):
            return False
        lowered = text.lower()
        if lowered == ":q":
            return False
        if lowered in {
            ":connect acp",
            ":connect byok",
            ":connect local",
            "/connect acp",
            "/connect byok",
            "/connect local",
        }:
            return True
        known = {candidate.lower() for candidate in COMMANDS}
        try:
            from superqode.extensions import load_extension_runtime

            runtime = load_extension_runtime(Path.cwd())
            known.update(f":{name}" for name in runtime.commands)
        except Exception:
            pass
        return lowered in known

    def _selected_prompt_completion_value(self) -> str:
        """Return the currently highlighted completion value, if any."""
        if not self._prompt_completion_candidates:
            return ""
        index = max(
            0,
            min(self._prompt_completion_index, len(self._prompt_completion_candidates) - 1),
        )
        return self._prompt_completion_candidates[index].value

    def _prompt_completion_enter_action(self, value: str) -> str:
        """Choose whether Enter accepts a completion or submits the prompt.

        Exact command rows such as ``:connect`` still submit when they are the
        highlighted row. If the user has moved the highlight to a different row
        such as ``:connect acp``, Enter accepts that completion first.
        """
        selected = self._selected_prompt_completion_value()
        if selected and selected != value:
            return "accept"
        if self._should_submit_prompt_without_completion(value):
            return "submit"
        return "accept"

    def _update_prompt_completion_panel(self, value: str) -> None:
        """Refresh the visible prompt completion panel as the prompt changes."""
        candidates = self._prompt_completion_candidates_for(value)
        if not candidates:
            self._hide_prompt_completion_panel()
            return
        self._show_prompt_completion_panel(candidates)

    def _show_prompt_completion_panel(self, candidates: list[PromptCompletionCandidate]) -> None:
        # Keep every matching candidate so a command group (notably :codex)
        # does not silently lose entries. The renderer below pages eight rows at
        # a time to retain the compact prompt layout on short terminals.
        self._prompt_completion_candidates = list(candidates)
        self._prompt_completion_index = min(
            self._prompt_completion_index,
            max(0, len(self._prompt_completion_candidates) - 1),
        )
        self._prompt_completion_visible = True
        self._render_prompt_completion_panel()

    def _hide_prompt_completion_panel(self) -> None:
        self._prompt_completion_candidates = []
        self._prompt_completion_index = 0
        self._prompt_completion_visible = False
        try:
            panel = self.query_one("#prompt-completions", Static)
            panel.update("")
            panel.remove_class("visible")
        except Exception:
            pass

    def _render_prompt_completion_panel(self) -> None:
        try:
            panel = self.query_one("#prompt-completions", Static)
        except Exception:
            return
        if not self._prompt_completion_candidates:
            self._hide_prompt_completion_panel()
            return
        total = len(self._prompt_completion_candidates)
        page_size = 9
        selected_index = self._prompt_completion_index
        start = max(0, min(selected_index - page_size // 2, total - page_size))
        end = min(total, start + page_size)
        text = Text()
        text.append("  completions", style=f"bold {THEME['cyan']}")
        if total > page_size:
            text.append(f"  {start + 1}–{end} of {total}", style=THEME["muted"])
        text.append("   ↑↓ choose   Tab/Enter accept   Esc close\n", style=THEME["dim"])
        for index in range(start, end):
            candidate = self._prompt_completion_candidates[index]
            selected = index == self._prompt_completion_index
            marker = ">" if selected else " "
            label_style = f"bold {THEME['text']}" if selected else THEME["cyan"]
            desc_style = THEME["text"] if selected else THEME["muted"]
            text.append(f"  {marker} ", style=THEME["success"] if selected else THEME["dim"])
            text.append(f"{candidate.label:<28}", style=label_style)
            if candidate.kind:
                text.append(
                    f"{candidate.kind:<10}", style=THEME["purple"] if selected else THEME["dim"]
                )
            if candidate.description:
                text.append(candidate.description[:80], style=desc_style)
            text.append("\n")
        panel.update(text)
        panel.add_class("visible")

    def _move_prompt_completion(self, delta: int) -> None:
        if not self._prompt_completion_candidates:
            return
        self._prompt_completion_index = (self._prompt_completion_index + delta) % len(
            self._prompt_completion_candidates
        )
        self._render_prompt_completion_panel()

    def _accept_prompt_completion(self, input_widget: SelectionAwareInput) -> bool:
        if not self._prompt_completion_candidates:
            return False
        index = max(
            0,
            min(self._prompt_completion_index, len(self._prompt_completion_candidates) - 1),
        )
        value = self._prompt_completion_candidates[index].value
        if not value or value == input_widget.value:
            return False
        input_widget.value = value
        input_widget.cursor_position = len(value)
        self._hide_prompt_completion_panel()
        return True

    @staticmethod
    def _first_completion(value: str, candidates: list[str] | tuple[str, ...]) -> str | None:
        lowered = value.lower()
        for candidate in sorted(dict.fromkeys(candidates), key=str.lower):
            if candidate.lower().startswith(lowered) and candidate != value:
                return candidate
        return None

    @staticmethod
    def _complete_after_prefix(
        value: str,
        prefix: str,
        candidates: list[str] | tuple[str, ...] | set[str],
    ) -> str | None:
        partial = value[len(prefix) :]
        for candidate in sorted(dict.fromkeys(candidates), key=str.lower):
            if candidate.lower().startswith(partial.lower()):
                completed = prefix + candidate
                return completed if completed != value else None
        return None

    def _complete_path_after_prefix(
        self,
        value: str,
        prefix: str,
        *,
        files_only: bool = False,
    ) -> str | None:
        partial = value[len(prefix) :]
        completed = self._complete_path_token(partial, files_only=files_only)
        if not completed:
            return None
        suggestion = prefix + completed
        return suggestion if suggestion != value else None

    @staticmethod
    def _complete_path_token(partial: str, *, files_only: bool = False) -> str | None:
        from superqode.app_main import SuperQodeApp

        candidates = SuperQodeApp._path_token_candidates(partial, files_only=files_only)
        return candidates[0][0] if candidates else None

    @staticmethod
    def _command_completion_sort_key(lowered_input: str, command: str) -> tuple[int, str]:
        command_lower = command.lower()
        priority: dict[str, dict[str, int]] = {
            ":": {
                ":connect": 0,
                ":connect acp": 1,
                ":connect antigravity": 2,
                ":connect grok": 3,
                ":connect byok": 4,
                ":connect local": 5,
                ":exit": 6,
                ":quit": 7,
            },
            ":c": {
                ":connect": 0,
                ":connect acp": 1,
                ":connect antigravity": 2,
                ":connect grok": 3,
                ":connect byok": 4,
                ":connect local": 5,
                ":clear": 20,
            },
            ":co": {
                ":connect": 0,
                ":connect acp": 1,
                ":connect antigravity": 2,
                ":connect grok": 3,
                ":connect byok": 4,
                ":connect local": 5,
            },
            ":q": {
                ":quit": 0,
            },
            ":e": {
                ":exit": 0,
            },
        }
        for prefix, scores in priority.items():
            if lowered_input.startswith(prefix):
                return (scores.get(command_lower, 10), command_lower)
        return (10, command_lower)

    @staticmethod
    def _skill_completion_candidates() -> list[PromptCompletionCandidate]:
        try:
            from superqode.skills import load_skills

            return [
                PromptCompletionCandidate(
                    value=skill.name,
                    label=skill.name,
                    description=skill.description,
                    kind="skill",
                )
                for skill in load_skills(Path.cwd()).values()
            ]
        except Exception:
            return []

    @staticmethod
    def _all_skill_completion_candidates() -> list[PromptCompletionCandidate]:
        from superqode.app_main import SuperQodeApp

        loaded = {
            candidate.label: candidate for candidate in SuperQodeApp._skill_completion_candidates()
        }
        skills_root = Path.cwd() / ".agents" / "skills"
        if not skills_root.exists():
            return list(loaded.values())
        for path in sorted(skills_root.rglob("*.md")):
            name = path.parent.name if path.name.upper() == "SKILL.MD" else path.stem
            description = ""
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:1000]
            except Exception:
                text = ""
            if text.startswith("---"):
                end = text.find("\n---", 3)
                front = text[:end] if end != -1 else text
                for line in front.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("name:"):
                        name = stripped.split(":", 1)[1].strip().strip('"').strip("'") or name
                    elif stripped.startswith("description:"):
                        description = stripped.split(":", 1)[1].strip()
            loaded.setdefault(
                name,
                PromptCompletionCandidate(
                    value=name,
                    label=name,
                    description=description,
                    kind="skill",
                ),
            )
        return list(loaded.values())

    @staticmethod
    def _provider_completion_candidates(local: bool) -> list[PromptCompletionCandidate]:
        try:
            from superqode.providers.registry import ProviderCategory
            from superqode.providers.dynamic import all_provider_ids, resolve_provider_def
        except Exception:
            return []
        candidates = []
        for provider_id in all_provider_ids():
            provider = resolve_provider_def(provider_id)
            if provider is None:
                continue
            is_local = provider.category == ProviderCategory.LOCAL
            if local != is_local:
                continue
            candidates.append(
                PromptCompletionCandidate(
                    value=provider_id,
                    label=provider_id,
                    description=provider.name,
                    kind="provider",
                )
            )
        return candidates

    def _show_completion_summary(self, name: str, summary: dict, log: ConversationLog):
        """Show completion summary when there's no text response."""
        from superqode.widgets.response_changes import (
            render_file_changes_compact,
            render_file_changes_section,
        )

        duration = summary.get("duration", 0)
        tool_count = summary.get("tool_count", 0)
        files_modified = summary.get("files_modified", [])
        files_read = summary.get("files_read", [])
        file_diffs = summary.get("file_diffs", {})  # NEW: Get diff data

        # Only report files this turn actually changed (no ambient git-tree
        # fallback); see _show_final_outcome for the rationale.

        # Disable auto-scroll
        log.auto_scroll = False

        # Clear and show fresh summary
        log.clear()

        t = Text()
        t.append("\n\n")

        # Celebration header
        celebration = "═" * 50
        gradient = ["#22c55e", "#10b981", "#14b8a6", "#06b6d4"]
        for i, char in enumerate(celebration):
            t.append(char, style=gradient[i % len(gradient)])
        t.append("\n")
        t.append("     🎉 ", style="#fbbf24")
        t.append("DONE!", style="bold #22c55e")
        t.append(" 🎉\n", style="#fbbf24")
        for i, char in enumerate(celebration):
            t.append(char, style=gradient[i % len(gradient)])
        t.append("\n\n")

        # Stats
        t.append(f"  ⏱️ Completed in {duration:.1f}s\n", style="#71717a")

        if tool_count > 0:
            t.append(f"  ⚡ {tool_count} tools executed\n", style="#a855f7")

        # NEW: Show file changes with visual indicators
        if files_modified:
            changes_text = render_file_changes_compact(files_modified, file_diffs)
            t.append_text(changes_text)
        elif files_read:
            t.append(f"  📖 {len(files_read)} files analyzed\n", style="#06b6d4")

        t.append("\n", style="")
        log.write(t)

        # Hidden by default: full file panel + inline diffs only in verbose
        # mode; otherwise a single collapsed line (the compact summary above
        # in ``t`` already names the count).
        change_mode = getattr(log, "tool_output_mode", "normal")
        if files_modified and change_mode == "verbose":
            from rich.console import Console
            from io import StringIO
            from superqode.widgets.response_changes import render_inline_file_diffs

            changes_section = render_file_changes_section(files_modified, file_diffs, max_files=10)
            console = Console(file=StringIO(), width=120, legacy_windows=False)
            console.print(changes_section)
            inline_diffs = render_inline_file_diffs(files_modified, file_diffs, max_files=10)
            console.print(inline_diffs)
            log.write(console.file.getvalue())
        elif files_modified:
            self._write_collapsed_changes_line(log, files_modified, file_diffs)

        # NEW: Trigger sidebar auto-navigation if files were modified
        if files_modified:
            self.set_timer(0.2, lambda: self._navigate_to_sidebar_changes(files_modified))

        # Schedule scroll to top with a small delay to ensure content is rendered
        self.set_timer(0.1, lambda: log.scroll_home())
