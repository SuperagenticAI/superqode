"""Slash-command implementations."""

from __future__ import annotations
import asyncio
import json
import os
import subprocess
import shutil
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.welcome import _harness_display_name
from superqode.app.recipes import PromptCompletionCandidate, LocalRecipe


class CommandImplMixin:
    """Per-command implementations (:claude, :skills, :providers, :vim, …)."""

    @staticmethod
    def _runtime_install_message(runtime_name: str, install_hint: str | None) -> str:
        from superqode.providers.env_introspect import environment_info

        env = environment_info()
        command = install_hint or "uv tool install ..."
        return (
            f"Runtime '{runtime_name}' is not installed.\n"
            f"SuperQode is running from: {env.label} ({env.python})\n"
            f"This command modifies: {env.target}\n"
            f"Run: {command}"
        )

    def _vim_enabled(self) -> bool:
        return bool(getattr(self, "_vim_experience_enabled", False))

    def _vim_cmd(self, args: str, log: ConversationLog) -> None:
        arg = (args or "").strip().lower()
        if arg in {"on", "1", "true", "yes"}:
            self._vim_experience_enabled = True
            log.add_success("Vim mode enabled. Use q: for command history and @: to repeat.")
            return
        if arg in {"off", "0", "false", "no"}:
            self._vim_experience_enabled = False
            log.add_success("Vim mode disabled.")
            return
        if arg in {"", "status"}:
            state = "on" if self._vim_enabled() else "off"
            t = Text()
            t.append("\n  Vim Mode\n\n", style=f"bold {THEME['purple']}")
            t.append("  Status: ", style=THEME["muted"])
            t.append(
                f"{state}\n",
                style=f"bold {THEME['success'] if self._vim_enabled() else THEME['muted']}",
            )
            t.append("  Toggle: ", style=THEME["muted"])
            t.append(":vim on", style=THEME["cyan"])
            t.append(" / ", style=THEME["muted"])
            t.append(":vim off\n", style=THEME["cyan"])
            t.append("  History: ", style=THEME["muted"])
            t.append("q:", style=THEME["cyan"])
            t.append("  Repeat: ", style=THEME["muted"])
            t.append("@:\n", style=THEME["cyan"])
            t.append("  Aliases: ", style=THEME["muted"])
            t.append(":w, :e <file>, :ls, :grep <term>\n", style=THEME["cyan"])
            self._show_command_output(log, t)
            return
        log.add_info("Usage: :vim [on|off|status]")

    def _set_cmd(self, args: str, log: ConversationLog) -> None:
        arg = (args or "").strip().lower()
        if arg in {"vim", "vim on"}:
            self._vim_cmd("on", log)
            return
        if arg in {"novim", "no-vim", "vim off"}:
            self._vim_cmd("off", log)
            return
        if arg in {"", "all"}:
            self._vim_cmd("status", log)
            return
        log.add_info("Usage: :set vim | :set novim")

    def _vim_command_history(self, log: ConversationLog) -> None:
        entries = [
            entry
            for entry in self._history_manager.get_recent(50)
            if str(getattr(entry, "input", "")).startswith(":")
        ][-20:]
        if not entries:
            log.add_info("No Ex command history yet.")
            return

        t = Text()
        t.append("\n  q: Command History\n\n", style=f"bold {THEME['purple']}")
        for index, entry in enumerate(entries, 1):
            t.append(f"  {index:>2}  ", style=THEME["muted"])
            t.append(str(entry.input), style=THEME["text"])
            t.append("\n")
        t.append("\n  Repeat the latest with ", style=THEME["muted"])
        t.append("@:", style=THEME["cyan"])
        t.append(".\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _vim_search(self, log: ConversationLog, query: str, *, reverse: bool = False) -> None:
        query = (query or "").strip()
        if not query:
            self._set_vim_search_highlight(log, "")
            self._vim_search_feedback(log, "Usage: /pattern or ?pattern")
            return

        messages = list(getattr(log, "_messages", []))
        lowered = query.lower()
        matches = [
            index
            for index, (_role, content, _agent) in enumerate(messages)
            if lowered in str(content).lower()
        ]
        self._vim_search_query = query
        self._vim_search_matches = matches
        self._vim_search_reverse = reverse

        if not matches:
            self._vim_search_index = -1
            self._set_vim_search_highlight(log, "")
            self._vim_search_feedback(log, f"No matches for {query!r}")
            return

        self._set_vim_search_highlight(log, query)
        self._vim_search_index = len(matches) - 1 if reverse else 0
        self._scroll_to_vim_search_match(log)

    def _vim_search_next(self, log: ConversationLog, *, reverse: bool = False) -> None:
        matches = getattr(self, "_vim_search_matches", [])
        if not matches:
            self._vim_search_feedback(log, "No previous Vim search. Use /pattern or ?pattern.")
            return

        direction = -1 if reverse else 1
        self._vim_search_index = (self._vim_search_index + direction) % len(matches)
        self._scroll_to_vim_search_match(log)

    def _vim_search_feedback(self, log: ConversationLog, message: str) -> None:
        try:
            self.notify(message, timeout=2)
            return
        except Exception:
            pass
        try:
            log.add_info(message)
        except Exception:
            pass

    async def _compare_cmd(self, args: str, log: ConversationLog) -> None:
        """Fan the last user message across several models concurrently.

        ``:compare <m1> <m2> ...`` — each token is ``provider/model`` or a bare
        ``model`` (using the connected provider). Read-only: a single chat
        completion per target, no tools, so it is safe to run in parallel. This
        leans on SuperQode's multi-runtime reach — comparing across providers in
        one shot is something single-stack harnesses can't do.
        """
        from superqode.agent.parallel_compare import (
            default_compare_runner,
            parse_compare_specs,
            run_parallel_compare,
        )

        prompt = self._last_user_message or log.get_last_message("user")
        if not prompt:
            log.add_info("Send a message first, then :compare <models> to compare answers to it.")
            return

        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :compare arguments: {exc}")
            return
        default_provider = getattr(getattr(self._pure_mode, "session", None), "provider", "") or ""
        specs = parse_compare_specs(tokens, default_provider=default_provider)
        if not specs:
            log.add_info(
                "Usage: :compare <provider/model> <model> …  (e.g. :compare openai/gpt-4o anthropic/claude-3-5-sonnet)"
            )
            return

        labels = ", ".join(spec.label for spec in specs)
        log.add_info(f"⚖ Comparing {len(specs)} models on your last message: {labels}")

        results = await run_parallel_compare(prompt, specs, default_compare_runner)
        self._render_compare_results(results, log)

    def _skills_cmd(self, args: str, log: ConversationLog):
        """Handle local skill inventory and setup commands.

        Covers the most useful day-to-day skill flow:
        users can see the skills currently visible to the agent, inspect one,
        create a template, or import an existing local SKILL.md/markdown skill.
        """
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :skills arguments: {exc}")
            return
        action = tokens[0].lower() if tokens else "list"
        rest = tokens[1:]
        if action in {"ls", "show"}:
            action = "list"

        skills_root = Path.cwd() / ".agents" / "skills"

        if action in {"list", "available", "status"}:
            from superqode.skills import load_skills

            skills = sorted(load_skills(Path.cwd()).values(), key=lambda item: item.name.lower())
            t = Text()
            t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
            t.append("Skills\n\n", style=f"bold {THEME['text']}")
            t.append("  Directory   ", style=THEME["muted"])
            t.append(f"{skills_root}\n", style=THEME["text"])
            t.append("  Loaded      ", style=THEME["muted"])
            t.append(f"{len(skills)}\n\n", style=f"bold {THEME['cyan']}")
            if not skills:
                t.append("  No local skills found.\n", style=THEME["muted"])
                t.append("  Create one with ", style=THEME["muted"])
                t.append(":skills add repo-review", style=THEME["cyan"])
                t.append(" or import an existing SKILL.md.\n", style=THEME["muted"])
            for index, skill in enumerate(skills, 1):
                t.append(f"  [{index}] ", style=THEME["dim"])
                t.append(skill.name, style=f"bold {THEME['cyan']}")
                if skill.description:
                    t.append(f" - {skill.description}", style=THEME["muted"])
                t.append("\n")
                if skill.path:
                    t.append(f"      {skill.path}\n", style=THEME["dim"])
            t.append("\n  Commands: ", style=THEME["muted"])
            t.append(":skills info <name>", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":skills add <name>", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":skills import <path>\n", style=THEME["cyan"])
            t.append("            ", style=THEME["muted"])
            t.append(
                ":skills optimize <name> --harness <path> --tasks <path> --live\n",
                style=THEME["cyan"],
            )
            self._show_command_output(log, t)
            return

        if action in {"info", "read"}:
            if not rest:
                log.add_error("Usage: :skills info <name>")
                return
            from superqode.skills import load_skills

            name = rest[0]
            skills = load_skills(Path.cwd())
            skill = skills.get(name)
            if skill is None:
                lowered = name.lower()
                skill = next(
                    (item for item in skills.values() if item.name.lower() == lowered), None
                )
            if skill is None:
                log.add_error(f"Skill not found: {name}")
                log.add_info("Use :skills to list loaded skills.")
                return
            t = Text()
            t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
            t.append(skill.name, style=f"bold {THEME['text']}")
            t.append("\n\n", style="")
            if skill.description:
                t.append("  Description ", style=THEME["muted"])
                t.append(f"{skill.description}\n", style=THEME["text"])
            if skill.path:
                t.append("  Path        ", style=THEME["muted"])
                t.append(f"{skill.path}\n", style=THEME["dim"])
            t.append("\n", style="")
            preview = skill.instructions.strip()
            if len(preview) > 2400:
                preview = preview[:2400].rstrip() + "\n..."
            t.append(preview or "(empty skill)", style=THEME["text"])
            t.append("\n", style="")
            self._show_command_output(log, t)
            return

        if action in {"search", "find"}:
            if not rest:
                log.add_error("Usage: :skills search <query>")
                return
            from superqode.skills import load_skills

            query = " ".join(rest).lower()
            skills = [
                skill
                for skill in load_skills(Path.cwd()).values()
                if query in skill.name.lower()
                or query in skill.description.lower()
                or query in skill.instructions.lower()
            ]
            t = Text()
            t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
            t.append(f"Skill Search: {query}\n\n", style=f"bold {THEME['text']}")
            if not skills:
                t.append("  No matching skills found.\n", style=THEME["muted"])
            for skill in sorted(skills, key=lambda item: item.name.lower()):
                t.append(f"  {skill.name}", style=f"bold {THEME['cyan']}")
                if skill.description:
                    t.append(f" - {skill.description}", style=THEME["muted"])
                t.append("\n")
                if skill.path:
                    t.append(f"    {skill.path}\n", style=THEME["dim"])
            self._show_command_output(log, t)
            return

        if action in {"doctor", "validate", "check"}:
            self._skills_doctor(skills_root, log)
            return

        if action in {"optimize", "optimise"}:
            if not rest:
                log.add_error(
                    "Usage: :skills optimize <name> --harness harness.yaml --tasks eval-tasks.yaml --live"
                )
                return
            if "--live" not in rest:
                log.add_error(":skills optimize requires --live so eval tasks produce real scores.")
                return
            self.run_worker(self._skills_optimize_cmd(rest, log))
            return

        if action in {"enable", "disable"}:
            if not rest:
                log.add_error(f"Usage: :skills {action} <name>")
                return
            changed = self._set_skill_enabled(skills_root, rest[0], enabled=action == "enable")
            if changed:
                log.add_success(f"Skill {rest[0]} {action}d.")
            else:
                log.add_error(f"Skill not found or could not be updated: {rest[0]}")
            return

        if action in {"add", "create", "new"}:
            if not rest:
                log.add_error("Usage: :skills add <name> [description]")
                return
            name = rest[0].strip().replace("/", "-")
            description = " ".join(rest[1:]).strip() or f"{name} workflow"
            skill_dir = skills_root / name
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                log.add_error(f"Skill already exists: {skill_file}")
                return
            skill_dir.mkdir(parents=True, exist_ok=True)
            content = (
                "---\n"
                f"name: {name}\n"
                f"description: {description}\n"
                "enabled: true\n"
                "---\n\n"
                f"# {name}\n\n"
                "Describe when to use this skill, what context to gather, and the steps the agent should follow.\n"
            )
            skill_file.write_text(content, encoding="utf-8")
            log.add_success(f"Created skill template: {skill_file}")
            log.add_info("Edit the SKILL.md instructions, then run :skills to confirm it loads.")
            return

        if action in {"import", "add-local"}:
            if not rest:
                log.add_error("Usage: :skills import <path-to-SKILL.md-or-directory>")
                return
            source = Path(rest[0]).expanduser()
            if not source.is_absolute():
                source = Path.cwd() / source
            if not source.exists():
                log.add_error(f"Path not found: {source}")
                return
            skills_root.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                name = source.name
                destination = skills_root / name
                if destination.exists():
                    log.add_error(f"Destination already exists: {destination}")
                    return
                shutil.copytree(source, destination)
                log.add_success(f"Imported skill directory: {destination}")
                return
            destination_dir = skills_root / source.stem
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / (
                "SKILL.md" if source.name.upper() == "SKILL.MD" else source.name
            )
            if destination.exists():
                log.add_error(f"Destination already exists: {destination}")
                return
            shutil.copy2(source, destination)
            log.add_success(f"Imported skill file: {destination}")
            return

        if action in {"remove", "rm", "delete", "uninstall"}:
            if not rest:
                log.add_error("Usage: :skills remove <name>")
                return
            target = skills_root / rest[0]
            if not target.exists():
                log.add_error(f"Skill path not found: {target}")
                return
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            log.add_success(f"Removed skill: {target}")
            return

        log.add_info(
            "Usage: :skills [list|info <name>|add <name>|import <path>|optimize <name> --harness <path> --tasks <path> --live|remove <name>]"
        )

    async def _skills_optimize_cmd(self, tokens: list[str], log: ConversationLog) -> None:
        """Run the GEPA skill optimizer from the TUI without blocking input."""
        await self._superqode_cli_cmd(["skills", "optimize", *tokens], log, "Skill optimization")

    def _skillopt_cmd(self, args: str, log: ConversationLog) -> None:
        """Run legacy SkillOpt workspace/check commands from the TUI."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :skillopt arguments: {exc}")
            return
        if not tokens or tokens[0] not in {"export", "check"}:
            log.add_info(
                "Usage: :skillopt export <skill> --tasks <path> --project <dir> | :skillopt check --baseline <path> --candidate <path>"
            )
            return
        self.run_worker(self._superqode_cli_cmd(["skillopt", *tokens], log, "SkillOpt command"))

    async def _superqode_cli_cmd(
        self,
        command_parts: list[str],
        log: ConversationLog,
        label: str,
    ) -> None:
        """Run a SuperQode CLI command from the TUI without blocking input."""
        import sys

        command = [
            sys.executable,
            "-m",
            "superqode.main",
            *command_parts,
        ]
        display_command = " ".join(shlex.quote(part) for part in command)
        log.add_info(f"Starting {label}:\n  {display_command}")

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                cwd=Path.cwd(),
                text=True,
                capture_output=True,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(_run)
        except Exception as exc:
            log.add_error(f"{label} failed to start: {exc}")
            return

        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        if completed.returncode == 0:
            log.add_success(f"{label} completed.")
            if output:
                log.write(Text(output + "\n", style=THEME["text"], overflow="fold"))
        else:
            log.add_error(f"{label} failed with exit code {completed.returncode}.")
            if output:
                log.write(Text(output + "\n", style=THEME["error"], overflow="fold"))

    def _skills_doctor(self, skills_root: Path, log: ConversationLog) -> None:
        """Validate local skill files and show actionable issues."""
        t = Text()
        t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
        t.append("Skills Doctor\n\n", style=f"bold {THEME['text']}")
        t.append("  Directory   ", style=THEME["muted"])
        t.append(f"{skills_root}\n\n", style=THEME["text"])

        if not skills_root.exists():
            t.append("  warning  ", style=THEME["warning"])
            t.append(
                "Skills directory does not exist. Use :skills add <name>.\n", style=THEME["text"]
            )
            self._show_command_output(log, t)
            return

        files = sorted(skills_root.rglob("*.md"))
        names: dict[str, Path] = {}
        issues: list[tuple[str, str]] = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                issues.append((str(path), f"unreadable: {exc}"))
                continue
            name = path.parent.name if path.name.upper() == "SKILL.MD" else path.stem
            description = ""
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    front = text[:end]
                    for line in front.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("name:"):
                            name = stripped.split(":", 1)[1].strip().strip('"').strip("'") or name
                        elif stripped.startswith("description:"):
                            description = stripped.split(":", 1)[1].strip()
            else:
                issues.append((str(path), "missing frontmatter block"))
            if not description:
                issues.append((str(path), "missing description"))
            lowered = name.lower()
            if lowered in names:
                issues.append((str(path), f"duplicate skill name also used by {names[lowered]}"))
            else:
                names[lowered] = path

        t.append("  Files       ", style=THEME["muted"])
        t.append(f"{len(files)}\n", style=THEME["text"])
        t.append("  Names       ", style=THEME["muted"])
        t.append(f"{len(names)}\n", style=THEME["text"])
        t.append("  Issues      ", style=THEME["muted"])
        t.append(f"{len(issues)}\n\n", style=THEME["warning"] if issues else THEME["success"])

        if not issues:
            t.append("  ok  All local skills look valid.\n", style=THEME["success"])
        else:
            for path, issue in issues[:30]:
                t.append("  warning  ", style=THEME["warning"])
                t.append(f"{path}: {issue}\n", style=THEME["text"])
            if len(issues) > 30:
                t.append(f"  ... and {len(issues) - 30} more issue(s)\n", style=THEME["dim"])
        self._show_command_output(log, t)

    async def _recipe_cmd(self, args: str, log: ConversationLog):
        """Handle reusable local workflow recipes."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :recipe arguments: {exc}")
            return
        action = tokens[0].lower() if tokens else "list"
        rest = tokens[1:]
        if action in {"ls", "show"}:
            action = "list"

        if action in {"list", "available", "status"}:
            self._show_recipes(log)
            return

        if action in {"info", "read"}:
            if not rest:
                log.add_error("Usage: :recipe info <name>")
                return
            recipe = self._find_recipe(rest[0])
            if recipe is None:
                log.add_error(f"Recipe not found: {rest[0]}")
                return
            self._show_recipe_info(recipe, log)
            return

        if action in {"doctor", "validate", "check"}:
            if rest:
                recipe = self._find_recipe(rest[0])
                if recipe is None:
                    log.add_error(f"Recipe not found: {rest[0]}")
                    return
                self._show_recipe_doctor(recipe, log)
            else:
                self._show_recipes_doctor(log)
            return

        if action in {"run", "start", "use"}:
            if not rest:
                log.add_error("Usage: :recipe run <name> [extra prompt text]")
                return
            name = rest[0]
            extra = " ".join(rest[1:]).strip()
            recipe = self._find_recipe(name)
            if recipe is None:
                log.add_error(f"Recipe not found: {name}")
                return
            await self._run_recipe(recipe, extra, log)
            return

        log.add_info("Usage: :recipe [list|info <name>|doctor [name]|run <name> [input]]")

    def _recipe_prompt_text(self, recipe: LocalRecipe, extra: str = "") -> str:
        prompt = recipe.prompt
        if recipe.prompt_file and recipe.path:
            path = Path(recipe.prompt_file).expanduser()
            if not path.is_absolute():
                path = recipe.path.parent / path
            if path.exists() and path.is_file():
                prompt = path.read_text(encoding="utf-8").strip()
        if recipe.variables:
            prompt += "\n\nRecipe variables to fill: " + ", ".join(recipe.variables)
        if recipe.skills:
            prompt += "\n\nUse these skills when relevant: " + ", ".join(recipe.skills)
        if extra:
            prompt += "\n\nUser input:\n" + extra
        return prompt.strip()

    def _recipe_issues(self, recipe: LocalRecipe) -> list[str]:
        issues: list[str] = []
        if not recipe.prompt and not recipe.prompt_file:
            issues.append("missing prompt or prompt_file")
        if recipe.prompt_file and recipe.path:
            prompt_path = Path(recipe.prompt_file).expanduser()
            if not prompt_path.is_absolute():
                prompt_path = recipe.path.parent / prompt_path
            if not prompt_path.exists() or not prompt_path.is_file():
                issues.append(f"prompt_file not found: {recipe.prompt_file}")
        if recipe.provider:
            try:
                from superqode.providers.registry import PROVIDERS

                if recipe.provider not in PROVIDERS:
                    issues.append(f"unknown provider: {recipe.provider}")
            except Exception:
                issues.append("provider registry unavailable")
        if recipe.skills:
            loaded = set(self._all_local_skill_names())
            for skill in recipe.skills:
                if skill not in loaded:
                    issues.append(f"missing skill: {skill}")
        if recipe.attachments:
            base = recipe.path.parent if recipe.path else Path.cwd()
            for ref in recipe.attachments:
                if ref.startswith(("http://", "https://", "@")):
                    continue
                path = Path(ref).expanduser()
                if not path.is_absolute():
                    path = base / path
                if not path.exists():
                    issues.append(f"attachment not found: {ref}")
        if recipe.harness and recipe.path:
            harness_path = Path(recipe.harness).expanduser()
            if not harness_path.is_absolute():
                harness_path = recipe.path.parent / harness_path
            if not harness_path.exists():
                issues.append(f"harness spec not found: {recipe.harness}")
        return issues

    @staticmethod
    def _runtime_completion_candidates() -> list[PromptCompletionCandidate]:
        """Runtime names for `:runtime <name>` completion, with install status."""
        from superqode.runtime import list_runtimes

        candidates = [
            PromptCompletionCandidate(
                value="list",
                label="list",
                description="Show all runtimes and their status",
                kind="runtime",
            )
        ]
        for info in list_runtimes():
            if info.usable:
                desc = info.description
            elif info.installed and not info.ready:
                desc = f"not ready — {info.status_detail or 'check setup'}"
            else:
                desc = f"not installed — {info.install_hint or 'optional extra required'}"
            candidates.append(
                PromptCompletionCandidate(
                    value=info.name,
                    label=info.name,
                    description=desc,
                    kind="runtime",
                )
            )
        return candidates

    @staticmethod
    def _recipe_dirs() -> list[Path]:
        return [Path.cwd() / ".superqode" / "recipes", Path.cwd() / ".agents" / "recipes"]

    @staticmethod
    def _recipe_completion_candidates() -> list[PromptCompletionCandidate]:
        from superqode.app_main import SuperQodeApp

        return [
            PromptCompletionCandidate(
                value=recipe.name,
                label=recipe.name,
                description=recipe.description,
                kind="recipe",
            )
            for recipe in SuperQodeApp._load_local_recipes().values()
        ]

    def _attach_cmd(self, args: str, log: ConversationLog):
        """Insert file or URL references into the next prompt."""
        value = args.strip()
        if not value:
            self._show_command_output(log, self._render_attachments())
            return
        try:
            raw_refs = shlex.split(value)
        except ValueError as exc:
            log.add_error(f"Could not parse :attach arguments: {exc}")
            return
        action = raw_refs[0].lower() if raw_refs else ""
        if action in {"list", "ls", "show"}:
            self._show_command_output(log, self._render_attachments())
            return
        if action in {"clear", "reset"}:
            self._attached_refs = []
            self._set_prompt_prefill("")
            log.add_info("Cleared staged prompt references.")
            return
        if action in {"remove", "rm", "delete"}:
            if len(raw_refs) < 2:
                log.add_error("Usage: :attach remove <index|reference>")
                return
            target = raw_refs[1]
            refs = list(getattr(self, "_attached_refs", []))
            removed = None
            if target.isdigit():
                index = int(target) - 1
                if 0 <= index < len(refs):
                    removed = refs.pop(index)
            elif target in refs:
                refs.remove(target)
                removed = target
            if removed is None:
                log.add_error(f"Attachment not found: {target}")
                return
            self._attached_refs = refs
            self._sync_attachment_prefill()
            log.add_info(f"Removed staged reference: {removed}")
            return
        refs: list[str] = []
        for raw in raw_refs:
            if raw.startswith(("http://", "https://")):
                refs.append(raw)
                continue
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.exists():
                log.add_error(f"Cannot attach missing path: {raw}")
                continue
            try:
                refs.append("@" + str(path.relative_to(Path.cwd())))
            except ValueError:
                refs.append("@" + str(path))
        if not refs:
            return
        self._attached_refs.extend(refs)
        self._attached_refs = list(dict.fromkeys(self._attached_refs))
        self._sync_attachment_prefill()
        log.add_info(f"Attached {len(refs)} reference(s) to the next prompt.")

    def _prompt_file_cmd(self, args: str, log: ConversationLog):
        """Load a prompt file into the input buffer."""
        value = args.strip()
        if not value:
            log.add_info("Usage: :prompt <file>")
            return
        try:
            parts = shlex.split(value)
        except ValueError as exc:
            log.add_error(f"Could not parse :prompt arguments: {exc}")
            return
        if not parts:
            log.add_info("Usage: :prompt <file>")
            return
        path = Path(parts[0]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            log.add_error(f"Prompt file not found: {path}")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            log.add_error(f"Could not read prompt file: {exc}")
            return
        self._set_prompt_prefill(content)
        log.add_info(f"Loaded prompt file into input: {path}")

    def _share_dir(self) -> Path:
        return Path(".superqode") / "shares"

    def _share_create(self, tokens: list[str], log: ConversationLog) -> None:
        include_tree = False
        cleaned: list[str] = []
        for token in tokens:
            if token.lower() in {"--tree", "tree"}:
                include_tree = True
            else:
                cleaned.append(token)
        session_arg, path_arg = self._parse_share_session_and_path(cleaned)
        try:
            session_id = self._resolve_share_session_id(session_arg)
            artifact_path = self._write_share_artifact(
                session_id,
                path_arg,
                include_tree=include_tree,
            )
        except Exception as exc:
            log.add_error(f"Could not create share artifact: {exc}")
            return
        label = "share-tree" if include_tree else "share"
        log.add_success(f"Created {label} artifact -> {artifact_path}")
        log.add_info(
            "Send this file to another SuperQode user; they can import it with :share import."
        )

    def _share_export(self, tokens: list[str], log: ConversationLog) -> None:
        from superqode.headless import export_session

        fmt = "markdown"
        cleaned: list[str] = []
        for token in tokens:
            lowered = token.lower()
            if lowered in {"--json", "json"}:
                fmt = "json"
            elif lowered in {"--markdown", "--md", "markdown", "md"}:
                fmt = "markdown"
            else:
                cleaned.append(token)
        session_arg, path_arg = self._parse_share_session_and_path(cleaned)
        try:
            session_id = self._resolve_share_session_id(session_arg)
            content = export_session(session_id, fmt=fmt, storage_dir=".superqode/sessions")
            suffix = ".json" if fmt == "json" else ".md"
            out_path = self._share_output_path(session_id, path_arg, suffix, stem="session")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            log.add_error(f"Could not export share file: {exc}")
            return
        log.add_success(f"Exported {fmt} session -> {out_path}")

    def _share_output_path(
        self,
        session_id: str,
        path_arg: str,
        suffix: str,
        *,
        stem: str,
    ) -> Path:
        if path_arg:
            out_path = Path(path_arg).expanduser()
            if not out_path.name.lower().endswith(suffix.lower()):
                out_path = out_path.with_suffix(suffix)
            return out_path
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id)
        return self._share_dir() / f"{stem}-{safe_id}-{stamp}{suffix}"

    def _share_import(self, tokens: list[str], log: ConversationLog) -> None:
        if not tokens:
            log.add_info("Usage: :share import <artifact.superqode-share.json> [new-session-id]")
            return
        path = Path(tokens[0]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        new_id = tokens[1] if len(tokens) > 1 else ""
        try:
            imported_id = self._import_share_artifact(path, new_id)
        except Exception as exc:
            log.add_error(f"Could not import share artifact: {exc}")
            return
        log.add_success(f"Imported shared session -> {imported_id}")
        log.add_info(f"Resume it with :resume {imported_id[:8]}")

    def _share_list(self, log: ConversationLog) -> None:
        from superqode.session.share_artifacts import list_share_artifacts

        artifacts = list_share_artifacts(self._share_dir())
        t = Text()
        t.append("\n  Local Share Artifacts\n\n", style=f"bold {THEME['purple']}")
        if not artifacts:
            t.append("  No share artifacts found.\n", style=THEME["muted"])
            t.append("  Create one with ", style=THEME["muted"])
            t.append(":share create", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        for index, artifact in enumerate(artifacts, 1):
            t.append(f"  [{index}] ", style=THEME["dim"])
            t.append(artifact.path.name, style=f"bold {THEME['cyan']}")
            if artifact.source_session_id:
                t.append(f"  session {artifact.source_session_id[:8]}", style=THEME["muted"])
            t.append("\n")
        t.append("\n  Import: ", style=THEME["muted"])
        t.append(":share import .superqode/shares/<file>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _share_revoke(self, tokens: list[str], log: ConversationLog) -> None:
        from superqode.session.share_artifacts import revoke_share_artifact

        if not tokens:
            log.add_info("Usage: :share revoke <artifact-name-or-path>")
            return
        try:
            path = revoke_share_artifact(tokens[0], self._share_dir())
        except FileNotFoundError:
            log.add_error(f"Share artifact not found: {tokens[0]}")
            return
        except Exception as exc:
            log.add_error(f"Could not revoke share artifact: {exc}")
            return
        log.add_success(f"Revoked local share artifact -> {path}")

    def _runtime_cmd(self, args: str, log) -> None:
        """Handle :runtime / :runtime list / :runtime <name>.

        With no args: open the RuntimeDialog picker.
        With "list":  print an inline status table.
        With a name:  swap runtime mid-session (env + disconnect; next message reconnects).
        """
        import os as _os
        from superqode.runtime import list_runtimes, resolve_runtime_name

        sub = args.strip().lower()

        if sub.startswith("doctor"):
            self._run_cli_group("runtime", args, log, "Runtime command")
            return

        if sub == "list":
            runtimes = list_runtimes()
            if any(not info.installed and info.install_hint for info in runtimes):
                from superqode.providers.env_introspect import environment_info

                env = environment_info()
                log.add_info(
                    f"SuperQode is running from: {env.label} ({env.python}); "
                    f"install commands target {env.target}."
                )
            for info in runtimes:
                marker = "▸" if info.name == resolve_runtime_name() else " "
                if not info.installed:
                    status = f"missing — {info.install_hint or ''}"
                elif not info.implemented:
                    status = "stub"
                elif not info.ready:
                    status = f"unavailable — {info.status_detail or ''}"
                else:
                    status = "ready"
                log.add_info(f"  {marker} {info.name:18} {status:30} {info.description}")
            return

        if not sub:
            # Bare `:runtime` shows the interactive runtime picker.
            self._show_runtime_picker(log)
            return

        # Direct switch by name.
        info_by_name = {r.name: r for r in list_runtimes()}
        if sub not in info_by_name:
            log.add_error(f"Unknown runtime '{sub}'. Known: {', '.join(sorted(info_by_name))}")
            return
        info = info_by_name[sub]
        if not info.installed:
            log.add_error(self._runtime_install_message(sub, info.install_hint))
            return
        if not info.implemented:
            log.add_error(f"Runtime '{sub}' is a stub and not yet usable.")
            return
        if not info.ready:
            log.add_error(f"Runtime '{sub}' is not ready: {info.status_detail or 'check setup'}")
            return

        # A friendly setup path for the Codex subscription: someone without
        # the product installed should get install steps, not a stack trace
        # from a missing ~/.codex login.
        if sub == "codex-sdk":
            codex_auth = Path.home() / ".codex" / "auth.json"
            has_env_key = bool(
                _os.environ.get("OPENAI_API_KEY") or _os.environ.get("CODEX_API_KEY")
            )
            if not codex_auth.exists() and not has_env_key:
                if shutil.which("codex") is None:
                    log.add_error(
                        "The Codex CLI is not installed, so the Codex "
                        "subscription route is unavailable."
                    )
                    log.add_info("Install it:  npm i -g @openai/codex")
                    log.add_info("Sign in with `codex login`, then re-run :connect codex.")
                    log.add_info("No subscription? Use BYOK instead: :connect byok openai <model>")
                    return
                # Codex is installed but signed out: launch `codex login`
                # (device auth) and auto-resume the connect once it lands.
                started = self._begin_subscription_login(
                    "codex",
                    log,
                    on_success=lambda: self._runtime_cmd("codex-sdk", log),
                    reason="Codex is installed but not signed in (~/.codex/auth.json missing).",
                )
                if started:
                    return
                log.add_error("Codex is installed but not signed in (~/.codex/auth.json missing).")
                log.add_info("Sign in with `codex login`, then re-run :connect codex.")
                log.add_info("No subscription? Use BYOK instead: :connect byok openai <model>")
                return

        current = resolve_runtime_name()
        if sub in self._SELF_CONTAINED_RUNTIMES:
            existing = getattr(self, "_pure_mode", None)
            if (
                existing is not None
                and getattr(existing, "runtime_name", "") == sub
                and getattr(existing.session, "connected", False)
                and Path(getattr(existing.session, "working_directory", Path.cwd())).resolve()
                == Path.cwd().resolve()
                and getattr(existing, "_runtime", None) is not None
            ):
                self._install_pure_permission_bridge(existing, log)
                _os.environ["SUPERQODE_RUNTIME"] = sub
                self._set_status_runtime(sub)
                if sub == "codex-sdk":
                    self.run_worker(self._resolve_codex_active_model(log), exclusive=False)
                    log.add_info("Already connected via codex-sdk; reusing warm Codex app-server.")
                else:
                    log.add_info(f"Already connected via {sub}; reusing the active session.")
                return
        # For self-contained runtimes, ``current`` only reflects the env/runtime
        # name (which --connect/SUPERQODE_RUNTIME may already have set) — not
        # whether a session is actually connected. The connected case is handled
        # above; reaching here means NOT connected, so fall through to
        # auto-connect instead of short-circuiting.
        if sub == current and sub not in self._SELF_CONTAINED_RUNTIMES:
            log.add_info(f"Already on runtime '{sub}'.")
            return

        _os.environ["SUPERQODE_RUNTIME"] = sub
        if hasattr(self, "_pure_mode") and self._pure_mode is not None:
            try:
                self._pure_mode.disconnect()
            except Exception:  # noqa: BLE001 — best-effort
                pass
            self._pure_mode.runtime_name = sub
        # Update the status bar badge if it's mounted.
        # Update the visible status-bar runtime badge. A non-self-contained swap
        # clears any stale model; the self-contained path below sets it.
        self._set_status_runtime(sub)
        if sub not in self._SELF_CONTAINED_RUNTIMES:
            self._set_status_model("")
        # Self-contained runtimes (e.g. codex-sdk) bring their own model + auth
        # (via their local config like ~/.codex) and don't need a BYOK key or an
        # ACP connect. Auto-connect so the user can start chatting immediately;
        # model="" defers entirely to the runtime's local configuration.
        if sub in self._SELF_CONTAINED_RUNTIMES:
            try:
                pure = self._ensure_pure_mode()
                self._install_pure_permission_bridge(pure, log)
                pure.runtime_name = sub
                provider = {
                    "claude-agent-sdk": "anthropic",
                    "antigravity-sdk": "google",
                    "antigravity-cli": "google",
                }.get(sub, "openai")
                pure.connect(provider=provider, model="", working_directory=Path.cwd())
                self._announce_self_contained_connection(sub, log)
            except Exception as exc:  # noqa: BLE001
                log.add_error(f"Switched to {sub} but auto-connect failed: {exc}")
                config_hint = self._codex_config_error_hint_text(exc)
                if config_hint:
                    log.add_info(config_hint)
        else:
            log.add_info(
                f"Runtime swapped: {current} → {sub}. "
                "Next message will reconnect with the new backend."
            )

    # ---- Claude Agent SDK :claude command surface --------------------------
    def _claude_cmd(self, args: str, log) -> None:
        """Handle :claude / :claude <subcommand> (Claude Agent SDK, API key)."""
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "connect"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub in ("connect", "start"):
            self._runtime_cmd("claude-agent-sdk", log)
        elif sub in ("status", "doctor"):
            self._claude_status(log)
        elif sub == "model":
            self._claude_model_cmd(rest, log)
        elif sub in ("permission", "permission-mode", "mode"):
            self._claude_permission_cmd(rest, log)
        elif sub in ("sessions", "threads"):
            self._claude_sessions_cmd(log)
        elif sub == "resume":
            if not rest:
                log.add_info("Usage: :claude resume <session-id>")
            else:
                self._claude_runtime_action(log, "resumed session", lambda r: r.resume_thread(rest))
        elif sub == "rename":
            if not rest:
                log.add_info("Usage: :claude rename <name>")
            else:
                self._claude_runtime_action(log, "renamed session", lambda r: r.rename_thread(rest))
        elif sub == "tag":
            if not rest:
                log.add_info("Usage: :claude tag <tag>")
            else:
                self._claude_runtime_action(log, "tagged session", lambda r: r.tag_thread(rest))
        elif sub == "commands":
            self._claude_commands_cmd(log)
        elif sub == "command":
            if not rest:
                log.add_info("Usage: :claude command <name> [args]")
            else:
                # Claude slash commands are sent as a "/name args" prompt.
                self._handle_message(f"/{rest}", log)
        elif sub == "review":
            self._handle_message(
                "Review the current changes/working tree for correctness and risks; "
                "do not modify files — report findings only.",
                log,
            )
        else:
            log.add_error(f"Unknown claude command: {sub}")
            log.add_info(
                "Usage: :claude [status|model|permission|sessions|resume|rename|tag|commands|command|review]"
            )

    # ---- Google Antigravity CLI :antigravity command surface -----------------
    def _antigravity_cmd(self, args: str, log) -> None:
        """Handle Antigravity CLI handoff/profile commands.

        The current public agy CLI is an interactive terminal UI, not a documented
        ACP server. Keep SuperQode's integration honest: make it discoverable,
        migration-aware, and easy to launch from the current repository without
        pretending we can stream structured tool events yet.
        """
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "connect"
        if sub in ("connect", "start", "cli"):
            self._runtime_cmd("antigravity-cli", log)
        elif sub in ("sdk", "api-key-sdk"):
            self._runtime_cmd("antigravity-sdk", log)
        elif sub in ("superqode", "byok"):
            self._connect_byok_cmd("google", log)
        elif sub in ("launch", "open"):
            self._show_antigravity_connect(log)
        elif sub in ("status", "doctor"):
            self._show_antigravity_status(log)
        elif sub in ("migrate", "migration", "gemini"):
            self._show_antigravity_migration(log)
        elif sub in ("help", "?"):
            self._show_antigravity_help(log)
        else:
            log.add_error(f"Unknown antigravity command: {sub}")
            log.add_info("Usage: :antigravity [cli|sdk|superqode|status|migrate|launch|help]")

    def _antigravity_command_line(self) -> str:
        return f"cd {shlex.quote(str(Path.cwd()))} && agy"

    def _antigravity_version(self) -> str:
        agy = shutil.which("agy")
        if not agy:
            return ""
        for args in (["agy", "--version"], ["agy", "version"]):
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            except Exception:
                continue
            text = (result.stdout or result.stderr or "").strip()
            if result.returncode == 0 and text:
                return text.splitlines()[0].strip()
        return ""

    # ---- xAI Grok Build :grok command surface ------------------------------
    def _grok_cmd(self, args: str, log) -> None:
        """Handle Grok Build ACP and the explicit native-harness opt-in."""
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "connect"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub in ("connect", "start"):
            # Subscription default = Grok Build, xAI's own agent over ACP
            # (matching the Codex and Claude profiles). SuperQode's harness on
            # the same plan is the explicit opt-in `:grok api`.
            self._connect_acp_cmd(("grok " + rest).strip(), log)
        elif sub == "api":
            self._grok_api_cmd(rest, log)
        elif sub in ("models", "ls"):
            self._show_grok_models(log)
        elif sub == "model":
            if rest:
                self._grok_api_cmd(rest, log)
            else:
                self._show_grok_model_picker(log)
        elif sub in ("status", "doctor"):
            self._show_grok_status(log)
        elif sub in ("login", "auth"):
            self._show_grok_login(log)
        elif sub in ("help", "?"):
            self._show_grok_help(log)
        else:
            log.add_error(f"Unknown grok command: {sub}")
            log.add_info(
                "Usage: :grok [connect [model]|model [name]|models|api [model|off]|"
                "status|login|help] (ACP: :connect acp grok)"
            )

    def _grok_api_cmd(self, rest: str, log) -> None:
        """Connect SuperQode harness using the Grok CLI subscription session.

        Imports the local ``grok login`` session token into SuperQode's auth
        store and connects the ``grok-cli`` provider (CLI chat proxy). Grok
        Build is the default ``:connect grok`` / ``:grok connect`` route;
        this native-harness path is always an explicit opt-in.
        """
        from superqode.providers import grok_cli_auth

        arg = (rest or "").strip()
        if arg.lower() in ("off", "remove", "logout"):
            if grok_cli_auth.remove_cli_token():
                log.add_info("Removed the imported Grok CLI token from SuperQode's auth store.")
            else:
                log.add_info("No imported Grok CLI token to remove.")
            return

        model = arg or "grok-build"
        for prefix in ("grok-cli/", "xai/", "grok/"):
            if model.lower().startswith(prefix):
                model = model[len(prefix) :]
                break

        if not self._import_grok_token(log, on_login_success=lambda: self._grok_api_cmd(rest, log)):
            return

        log.add_info(
            "Imported the Grok CLI session token (stored in ~/.superqode/auth.json, 0600)."
        )
        log.add_info(
            f"SuperQode harness on Grok subscription → grok-cli/{model}. "
            "For xAI's own Grok Build agent instead, use :connect grok. "
            "Remove token anytime with :grok api off."
        )
        self._connect_byok_mode("grok-cli", model, log)

    def _claude_runtime_action(self, log, label: str, action) -> None:
        try:
            runtime = self._claude_runtime_or_connect(log)
            action(runtime)
            log.add_success(f"Claude {label}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not {label}: {exc}")

    def _claude_status(self, log) -> None:
        import importlib.util
        import shutil

        text = Text()
        text.append("\n  Claude Agent SDK status\n\n", style=f"bold {THEME['cyan']}")
        sdk_ok = importlib.util.find_spec("claude_agent_sdk") is not None
        text.append("  SDK          ", style=THEME["muted"])
        text.append(
            "installed\n" if sdk_ok else "missing\n",
            style=THEME["success" if sdk_ok else "error"],
        )
        cli_ok = shutil.which("claude") is not None
        text.append("  Claude CLI   ", style=THEME["muted"])
        text.append(
            "found\n" if cli_ok else "not found (install Claude Code)\n",
            style=THEME["success" if cli_ok else "warning"],
        )
        key_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        text.append("  API key      ", style=THEME["muted"])
        text.append(
            "ANTHROPIC_API_KEY set\n" if key_ok else "ANTHROPIC_API_KEY not set\n",
            style=THEME["success" if key_ok else "error"],
        )
        pure = getattr(self, "_pure_mode", None)
        runtime = getattr(pure, "_runtime", None) if pure is not None else None
        connected = runtime is not None and getattr(pure, "runtime_name", "") == "claude-agent-sdk"
        text.append("  Connected    ", style=THEME["muted"])
        text.append(
            "yes\n" if connected else "no (use :claude)\n",
            style=THEME["success" if connected else "warning"],
        )
        if connected:
            model = getattr(runtime, "config", None)
            model_id = getattr(model, "model", "") or "Claude Code default"
            text.append("  Model        ", style=THEME["muted"])
            text.append(f"{model_id}\n", style=THEME["text"])
            text.append("  Permission   ", style=THEME["muted"])
            text.append(
                f"{getattr(runtime, 'permission_mode', None) or 'default'}\n", style=THEME["text"]
            )
            cmds = getattr(runtime, "slash_commands", [])
            text.append("  Slash cmds   ", style=THEME["muted"])
            text.append(f"{len(cmds)} available\n", style=THEME["text"])
        if not (sdk_ok and key_ok):
            text.append("\n  Setup: ", style=THEME["muted"])
            text.append('uv tool install "superqode[claude-agent-sdk]"', style=THEME["cyan"])
            text.append(" + install Claude Code + export ANTHROPIC_API_KEY\n", style=THEME["muted"])
        log.write(text)

    def _claude_permission_cmd(self, mode: str, log) -> None:
        modes = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")
        if not mode:
            log.add_info(
                f"Permission modes: {', '.join(modes)}.  Set with :claude permission <mode>"
            )
            return
        try:
            runtime = self._claude_runtime_or_connect(log)
            runtime.set_permission_mode(mode)
            log.add_success(f"Claude permission mode set to {mode}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not set permission mode: {exc}")

    def _claude_sessions_cmd(self, log) -> None:
        try:
            runtime = self._claude_runtime_or_connect(log)
            sessions = runtime.list_threads(limit=20)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not list Claude sessions: {exc}")
            return
        t = Text()
        t.append("\n  Claude sessions\n\n", style=f"bold {THEME['text']}")
        if not sessions:
            t.append("  (none)\n", style=THEME["muted"])
        for s in list(sessions)[:20]:
            sid = getattr(s, "session_id", getattr(s, "id", "")) or "?"
            title = getattr(s, "title", "") or ""
            t.append("  • ", style=THEME["dim"])
            t.append(f"{sid}", style=THEME["text"])
            if title:
                t.append(f"  {title}", style=THEME["muted"])
            t.append("\n", style="")
        t.append("\n  Resume with ", style=THEME["muted"])
        t.append(":claude resume <session-id>\n", style=THEME["cyan"])
        log.write(t)

    def _claude_commands_cmd(self, log) -> None:
        runtime = getattr(getattr(self, "_pure_mode", None), "_runtime", None)
        cmds = list(getattr(runtime, "slash_commands", []) or []) if runtime else []
        t = Text()
        t.append("\n  Claude slash commands\n\n", style=f"bold {THEME['text']}")
        if not cmds:
            t.append(
                "  (none yet — send a message first so the SDK reports them)\n",
                style=THEME["muted"],
            )
        for name in cmds:
            t.append("  • ", style=THEME["dim"])
            t.append(f"/{name}\n", style=THEME["cyan"])
        t.append("\n  Run with ", style=THEME["muted"])
        t.append(":claude command <name> [args]\n", style=THEME["cyan"])
        log.write(t)

    def _harness_cmd(self, args: str, log) -> None:
        """Handle :harness status/list/templates/off/<path>."""
        import os as _os

        parts = args.split(maxsplit=1)
        sub = parts[0].strip() if parts else "status"
        subargs = parts[1].strip() if len(parts) > 1 else ""
        if not sub:
            sub = "status"

        try:
            from superqode.harness import (
                BUILTIN_TEMPLATES,
                discover_harness_adapters,
                get_harness_template,
                list_harnesses,
                resolve_harness,
            )
        except Exception as exc:
            log.add_error(f"Harness support is unavailable: {exc}")
            return

        if sub in ("status", "current"):
            pure = getattr(self, "_pure_mode", None)
            status = pure.get_status().get("harness", {}) if pure else {}
            if status.get("enabled"):
                log.add_info(
                    f"Harness: {_harness_display_name(status.get('name'))} "
                    f"({status.get('flavor')}, runtime={status.get('runtime')})"
                )
                if status.get("path"):
                    log.add_info(f"Spec: {status.get('path')}")
            else:
                env_path = _os.getenv("SUPERQODE_HARNESS", "").strip()
                if env_path:
                    log.add_info(f"Harness configured for next connection: {env_path}")
                else:
                    log.add_info("No harness is active. Use :harness use core.")
            return

        if sub in ("list", "available"):
            known: set[str] = set()
            for entry in list_harnesses(Path.cwd()):
                known.add(entry.id)
                marker = "*" if entry.default else " "
                status = "ready" if entry.available else (entry.issue or "unavailable")
                log.add_info(
                    f"{marker} {entry.id:18} {entry.source:10} {entry.runtime:14} "
                    f"tools={len(entry.tools):2} {status}"
                )
            for entry in discover_harness_adapters(include_builtins=False):
                if entry.id in known:
                    continue
                status = "ready" if entry.available else (entry.issue or "unavailable")
                log.add_info(f"  {entry.id:18} python     protocol       tools= 0 {status}")
            return

        if sub == "show":
            if not subargs:
                log.add_error("Usage: :harness show <name-or-path>")
                return
            try:
                entry = resolve_harness(subargs, root=Path.cwd())
            except Exception as exc:
                try:
                    from superqode.harness import load_harness_adapter

                    adapter = load_harness_adapter(subargs)
                except Exception:
                    log.add_error(f"Could not resolve harness: {exc}")
                    return
                enabled = [
                    name
                    for name, supported in adapter.descriptor.capabilities.to_dict().items()
                    if supported
                ]
                log.add_info(f"Harness: {adapter.descriptor.name} (Python package)")
                log.add_info(adapter.descriptor.description)
                log.add_info(f"Capabilities: {', '.join(enabled) or 'none'}")
                return
            log.add_info(
                f"Harness: {_harness_display_name(entry.id)} ({entry.source}, "
                f"runtime={entry.runtime}, tools={len(entry.tools)})"
            )
            log.add_info(entry.description)
            log.add_info(f"Tools: {', '.join(entry.tools) or 'none'}")
            log.add_info(f"Digest: {entry.digest}")
            return

        if sub in ("templates", "list-templates"):
            for name in sorted(BUILTIN_TEMPLATES):
                if "_" in name:
                    continue
                spec = get_harness_template(name)
                log.add_info(
                    f"  {name:18} {spec.flavor.value:8} {spec.runtime.backend:14} {spec.description}"
                )
            return

        if sub in ("wizard", "init", "create"):
            self._harness_wizard_cmd(subargs, log)
            return

        if sub in ("inspect", "show", "summary"):
            self._show_harness_inspect(log)
            return

        if sub in ("doctor", "check"):
            self._show_harness_doctor(log)
            return

        if sub in ("graph", "plan"):
            self._show_harness_graph(log, run_id=subargs if sub == "graph" else "")
            return

        if sub in ("runs", "history"):
            self._show_harness_runs(log)
            return

        if sub in ("replay", "replay-plan"):
            if not subargs:
                log.add_error("Usage: :harness replay <run_id>")
                return
            self._show_harness_replay(log, subargs)
            return

        if sub in ("fork", "branch"):
            if not subargs:
                log.add_error("Usage: :harness fork <run_id> [after_index]")
                return
            self._show_harness_fork(log, subargs)
            return

        if sub in ("evidence", "receipt"):
            if not subargs:
                log.add_error("Usage: :harness evidence <run_id>")
                return
            self._show_harness_evidence(log, subargs)
            return

        if sub in ("events", "timeline"):
            if not subargs:
                log.add_error("Usage: :harness events <run_id>")
                return
            self._show_harness_events(log, subargs)
            return

        if sub in ("improve", "optimize", "optimize-inspect", "optimize-ledger"):
            try:
                tokens = shlex.split(subargs or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :harness {sub} arguments: {exc}")
                return
            if sub == "optimize" and not tokens:
                log.add_info(
                    "Usage: :harness optimize --spec <path> --tasks <path> [--export-only]"
                )
                return
            if sub == "improve" and not tokens:
                log.add_info(
                    "Usage: :harness improve --spec <path> --tasks <path> [--from-failures failures.json] [--export-only]"
                )
                return
            if sub in {"optimize-inspect", "optimize-ledger"} and not tokens:
                log.add_info(f"Usage: :harness {sub} <run_dir>")
                return
            label = "Harness self-improvement" if sub == "improve" else "Harness optimization"
            self.run_worker(self._superqode_cli_cmd(["harness", sub, *tokens], log, label))
            return

        cli_backed_harness_subcommands = {
            "audit-candidate",
            "auto-bench",
            "candidates",
            "compile",
            "diff",
            "drain",
            "eval",
            "eval-packs",
            "explain",
            "import-agent",
            "import-omnigent",
            "inbox",
            "list-backends",
            "logbook",
            "mine-failures",
            "registry",
            "run",
            "test",
            "validate",
            "worker",
            "observability",
            "protocol",
        }
        if sub in cli_backed_harness_subcommands:
            try:
                tokens = shlex.split(subargs or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :harness {sub} arguments: {exc}")
                return
            self._run_cli_passthrough(["harness", sub, *tokens], log, "Harness command")
            return

        if sub in ("off", "disable", "none"):
            _os.environ["SUPERQODE_HARNESS"] = "core"
            if hasattr(self, "_pure_mode") and self._pure_mode is not None:
                self._pure_mode.clear_harness()
                if self._pure_mode.session.connected:
                    self._pure_mode.disconnect()
            self._refresh_harness_panel()
            log.add_info(
                "Restored the core harness. Reconnect with :connect byok or :connect local."
            )
            return

        if sub in ("load", "use"):
            reference = subargs
        else:
            reference = args.strip()

        if not reference:
            log.add_info(
                "Usage: :harness <spec.yaml> | :harness wizard [name] --starter <template> --output <path> [--load] | :harness inspect | :harness doctor | :harness graph | :harness replay <run_id> | :harness fork <run_id> | :harness evidence <run_id> | :harness runs | :harness mine-failures --eval-result eval.json | :harness audit-candidate --base <path> --candidate <path> | :harness candidates list | :harness improve --spec <path> --tasks <path> | :harness optimize --spec <path> --tasks <path> | :harness optimize-inspect <run_dir> | :harness optimize-ledger <run_dir> | :harness templates | :harness off"
            )
            return

        try:
            entry = resolve_harness(reference, root=Path.cwd())
        except Exception as exc:
            log.add_error(f"Could not resolve harness: {exc}")
            return

        _os.environ["SUPERQODE_HARNESS"] = str(entry.path or entry.id)
        pure = self._ensure_pure_mode()
        if hasattr(pure, "select_harness"):
            pure.select_harness(str(entry.path or entry.id))
        else:
            pure.set_harness(entry.spec, path=entry.path)
        if pure.session.connected:
            pure.disconnect()
        self._refresh_harness_panel()

        log.add_success(
            f"✓ Harness: {_harness_display_name(entry.id)} loaded "
            f"({entry.spec.flavor.value}, runtime={entry.runtime}, tools={len(entry.tools)})"
        )
        log.add_info(
            "Reconnect with :connect byok or :connect local to run the TUI through this spec."
        )

    def _harness_wizard_cmd(self, args: str, log) -> None:
        """Create a HarnessSpec from wizard answers supplied as TUI flags."""
        try:
            from superqode.harness import (
                APPROVAL_PROFILES,
                TOOL_CALL_FORMATS,
                WIZARD_STARTERS,
                WizardAnswers,
                build_wizard_spec,
                explain_harness,
                render_explanation,
                save_harness_spec,
            )
        except Exception as exc:
            log.add_error(f"Harness wizard is unavailable: {exc}")
            return

        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :harness wizard arguments: {exc}")
            return

        if not tokens:
            self._start_harness_wizard_flow(log)
            return

        starter_keys = {key for key, _label in WIZARD_STARTERS}
        approval_keys = {key for key, _label in APPROVAL_PROFILES}
        tool_format_keys = {key for key, _label in TOOL_CALL_FORMATS}
        workflow_keys = {
            "single",
            "plan-implement-review",
            "fix-and-verify",
            "parallel-review",
            "security-review",
        }
        output = Path("harness.yaml")
        force = False
        load_after_write = False
        answers_kwargs: dict[str, Any] = {
            "name": "my-harness",
            "starter": "qwen-coding",
            "provider": "",
            "model": "",
            "allow_write": True,
            "allow_shell": True,
            "allow_network": False,
            "approval_profile": "balanced",
            "tool_call_format": "auto",
            "workflow_preset": "single",
        }

        def _require_value(index: int, flag: str) -> str:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                raise ValueError(f"{flag} requires a value")
            return tokens[index + 1]

        i = 0
        positional: list[str] = []
        try:
            while i < len(tokens):
                token = tokens[i]
                if token in {"--help", "-h"}:
                    self._show_harness_wizard_help(log)
                    return
                if token in {"--starter", "-t"}:
                    answers_kwargs["starter"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--output", "-o"}:
                    output = Path(_require_value(i, token)).expanduser()
                    i += 2
                    continue
                if token == "--provider":
                    answers_kwargs["provider"] = _require_value(i, token)
                    i += 2
                    continue
                if token == "--model":
                    answers_kwargs["model"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--workflow", "--workflow-preset"}:
                    answers_kwargs["workflow_preset"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--approval", "--approval-profile"}:
                    answers_kwargs["approval_profile"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--tool-format", "--tool-call-format"}:
                    answers_kwargs["tool_call_format"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--read-only", "--no-write"}:
                    answers_kwargs["allow_write"] = False
                    i += 1
                    continue
                if token == "--no-shell":
                    answers_kwargs["allow_shell"] = False
                    i += 1
                    continue
                if token == "--allow-network":
                    answers_kwargs["allow_network"] = True
                    i += 1
                    continue
                if token == "--no-network":
                    answers_kwargs["allow_network"] = False
                    i += 1
                    continue
                if token == "--force":
                    force = True
                    i += 1
                    continue
                if token == "--load":
                    load_after_write = True
                    i += 1
                    continue
                if token.startswith("-"):
                    raise ValueError(f"Unknown option {token}")
                positional.append(token)
                i += 1
        except ValueError as exc:
            log.add_error(str(exc))
            self._show_harness_wizard_help(log)
            return

        if positional:
            answers_kwargs["name"] = positional[0]
        if len(positional) > 1:
            log.add_error(f"Unexpected extra argument: {positional[1]}")
            self._show_harness_wizard_help(log)
            return

        if answers_kwargs["starter"] not in starter_keys:
            log.add_error(
                f"Unknown starter {answers_kwargs['starter']!r}. Try: {', '.join(sorted(starter_keys))}"
            )
            return
        if answers_kwargs["approval_profile"] not in approval_keys:
            log.add_error(
                f"Unknown approval profile {answers_kwargs['approval_profile']!r}. Try: {', '.join(sorted(approval_keys))}"
            )
            return
        if answers_kwargs["tool_call_format"] not in tool_format_keys:
            log.add_error(
                f"Unknown tool-call format {answers_kwargs['tool_call_format']!r}. Try: {', '.join(sorted(tool_format_keys))}"
            )
            return
        if answers_kwargs["workflow_preset"] not in workflow_keys:
            log.add_error(
                f"Unknown workflow {answers_kwargs['workflow_preset']!r}. Try: {', '.join(sorted(workflow_keys))}"
            )
            return

        if output.exists() and not force:
            log.add_error(f"{output} already exists. Add --force to overwrite it.")
            return

        try:
            answers = WizardAnswers(**answers_kwargs)
            spec = build_wizard_spec(answers)
            path = save_harness_spec(spec, output)
            (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
            (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.add_error(f"Could not create harness: {exc}")
            return

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Wizard\n\n", style=f"bold {THEME['text']}")
        t.append("  Wrote       ", style=THEME["muted"])
        t.append(str(path), style=f"bold {THEME['cyan']}")
        t.append("\n  Starter     ", style=THEME["muted"])
        t.append(answers.starter, style=THEME["text"])
        t.append("\n  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        t.append(spec.model_policy.primary or "active connection", style=THEME["text"])
        t.append("\n\n")
        explanation = render_explanation(
            explain_harness(spec, provider=answers.provider, model=answers.model)
        )
        for line in explanation.splitlines()[:18]:
            t.append("  ", style="")
            t.append(line, style=THEME["text"])
            t.append("\n")
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(f":harness {path}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(f":harness doctor", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

        if load_after_write:
            self._harness_cmd(f"load {path}", log)

    @staticmethod
    def _harness_wizard_next(state: dict[str, Any], next_step: str) -> None:
        state.setdefault("history", []).append(state["step"])
        state["step"] = next_step

    @staticmethod
    def _harness_wizard_choice(
        raw: str,
        keys: list[str],
        *,
        default: str | None = None,
    ) -> str | None:
        value = raw.strip().lower()
        if not value and default:
            return default
        if value.isdigit():
            index = int(value) - 1
            return keys[index] if 0 <= index < len(keys) else None
        for key in keys:
            if value == key.lower():
                return key
        matches = [key for key in keys if key.lower().startswith(value)]
        return matches[0] if len(matches) == 1 else None

    def _harness_event_style(self, event_type: str) -> str:
        """Return a theme color for a harness event type."""
        if "failed" in event_type or "error" in event_type:
            return THEME["error"]
        if "completed" in event_type or "result" in event_type:
            return THEME["success"]
        if event_type.startswith("checks."):
            return THEME["gold"]
        if event_type.startswith("workflow."):
            return THEME["cyan"]
        if event_type.startswith("workspace."):
            return THEME["purple"]
        if event_type == "harness.hook.error":
            return THEME["error"]
        if event_type == "harness.permission.check":
            return THEME["warning"]
        if event_type.startswith("harness.compaction."):
            return THEME["gold"]
        if event_type == "harness.stop":
            return THEME["success"]
        if event_type.startswith("harness."):
            return THEME["purple"]
        if event_type.startswith("approval"):
            return THEME["warning"]
        return THEME["text"]

    def _harness_event_preview(self, event) -> str:
        """Build a compact one-line event preview."""
        data = getattr(event, "data", {}) or {}
        fields = []
        for key in (
            "step_id",
            "status",
            "detail",
            "name",
            "command",
            "child_run_id",
            "file_count",
            "returncode",
            "error",
            "content_preview",
            "tool",
            "handler",
            "point",
            "stopped_reason",
            "iterations",
            "tool_calls_made",
        ):
            value = data.get(key)
            if value in (None, "", [], {}):
                continue
            fields.append(f"{key}={value}")
        arguments = data.get("arguments")
        if isinstance(arguments, dict):
            keys = arguments.get("keys")
            if keys:
                fields.append("arg_keys=" + ",".join(str(k) for k in keys[:8]))
            preview = arguments.get("preview")
            if isinstance(preview, dict):
                for key, value in list(preview.items())[:4]:
                    fields.append(f"{key}={value}")
        preview = "  ".join(fields)
        preview = preview.replace("\n", " ")
        return preview[:137] + "..." if len(preview) > 140 else preview

    def _workflow_steps_from_spec(self, spec, prompt: str):
        """Build runnable workflow steps from HarnessSpec agents and a user prompt."""
        from superqode.harness import workflow_steps_from_spec

        return workflow_steps_from_spec(spec, prompt)

    def _workflow_preview_text(self, spec, prompt: str) -> Text:
        """Render a preflight preview for the active HarnessSpec workflow."""
        from superqode.harness import apply_workflow_preset

        spec = apply_workflow_preset(spec)
        provider, model = self._workflow_provider_model(spec)
        steps = self._workflow_steps_from_spec(spec, prompt or "your task")
        policy = spec.execution_policy
        blocked = 0
        warnings = 0

        def status(ok: bool, warn: bool = False) -> tuple[str, str, str]:
            nonlocal blocked, warnings
            if ok:
                return "✓", "ready", THEME["success"]
            if warn:
                warnings += 1
                return "!", "warn", THEME["warning"]
            blocked += 1
            return "!", "blocked", THEME["error"]

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Workflow Preview\n\n", style=f"bold {THEME['text']}")
        t.append("  Harness     ", style=THEME["muted"])
        t.append(spec.name, style=f"bold {THEME['cyan']}")
        t.append(f"  {spec.flavor.value}\n", style=THEME["dim"])
        t.append("  Workflow    ", style=THEME["muted"])
        t.append(spec.workflow.mode.value, style=f"bold {THEME['success']}")
        if spec.workflow.preset:
            t.append(f"  preset={spec.workflow.preset}", style=THEME["dim"])
        t.append(f"  parallelism={spec.workflow.parallelism}\n", style=THEME["dim"])
        t.append("  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        if provider and model:
            t.append(f"{provider}/{model}", style=THEME["text"])
        else:
            t.append("not selected", style=THEME["warning"])
        t.append("\n  Task        ", style=THEME["muted"])
        t.append(
            prompt or "(no task supplied)", style=THEME["text"] if prompt else THEME["warning"]
        )

        t.append("\n\n  Steps\n", style=f"bold {THEME['text']}")
        for index, step in enumerate(steps, 1):
            step_id = step.id or f"step-{index}"
            t.append("  ✓ ", style=THEME["success"])
            t.append(f"{index:02d}. ", style=THEME["dim"])
            t.append(step_id, style=f"bold {THEME['cyan']}")
            role = step.metadata.get("role") if isinstance(step.metadata, dict) else ""
            if role:
                t.append(f"  {role}", style=THEME["muted"])
            t.append("\n")

        t.append("\n  Readiness\n", style=f"bold {THEME['text']}")
        icon, label, style = status(bool(provider and model))
        t.append(f"  {icon} model       {label}", style=style)
        if not provider or not model:
            t.append("  connect BYOK/local or set model_policy.primary", style=THEME["muted"])
        t.append("\n")

        icon, label, style = status(bool(steps))
        t.append(f"  {icon} steps       {label}  {len(steps)} step(s)\n", style=style)

        icon, label, style = status(policy.allow_read, warn=True)
        t.append(f"  {icon} read        {label}\n", style=style)

        write_required = spec.flavor.value == "coding"
        icon, label, style = status(policy.allow_write or not write_required, warn=write_required)
        t.append(f"  {icon} write       {label}", style=style)
        if not policy.allow_write:
            t.append("  read-only harness", style=THEME["muted"])
        t.append("\n")

        icon, label, style = status(policy.allow_shell or not policy.allowed_commands, warn=True)
        t.append(f"  {icon} shell       {label}", style=style)
        if policy.allowed_commands:
            t.append(f"  {', '.join(policy.allowed_commands[:3])}", style=THEME["muted"])
        t.append("\n")

        t.append("  ✓ approvals   ", style=THEME["success"])
        t.append(policy.approval_profile, style=THEME["text"])
        t.append("\n")

        mcp_servers = []
        if isinstance(spec.runtime.config, dict):
            raw_mcp = spec.runtime.config.get("mcp_servers") or spec.runtime.config.get("mcp")
            if isinstance(raw_mcp, dict):
                mcp_servers = list(raw_mcp)
            elif isinstance(raw_mcp, list):
                mcp_servers = [str(item) for item in raw_mcp]
        icon, label, style = status(True, warn=bool(mcp_servers))
        t.append(f"  {icon} MCP         {label}", style=style)
        if mcp_servers:
            t.append(f"  declared: {', '.join(mcp_servers[:4])}", style=THEME["muted"])
        else:
            t.append("  none declared", style=THEME["muted"])
        t.append("\n")

        overall = "blocked" if blocked else "warnings" if warnings else "ready"
        overall_style = (
            THEME["error"] if blocked else THEME["warning"] if warnings else THEME["success"]
        )
        t.append("\n  Result      ", style=THEME["muted"])
        t.append(overall, style=f"bold {overall_style}")
        t.append(f"  ({blocked} blocked, {warnings} warning(s))\n", style=THEME["dim"])
        if not blocked:
            t.append("\n  Run with    ", style=THEME["muted"])
            t.append(
                f':workflow run "{prompt}"\n' if prompt else ":workflow run <task>\n",
                style=THEME["cyan"],
            )
        return t

    def _workflow_timeline_text(
        self,
        *,
        title: str,
        mode: str,
        step_ids: list[str],
        states: dict[str, str],
        details: dict[str, str] | None = None,
    ) -> Text:
        """Render a compact workflow timeline for the TUI log."""
        details = details or {}
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append(title, style=f"bold {THEME['text']}")
        t.append(f"  {mode}\n\n", style=THEME["dim"])
        status_icons = {
            "pending": "○",
            "running": "●",
            "done": "✓",
            "failed": "!",
        }
        status_styles = {
            "pending": THEME["dim"],
            "running": THEME["cyan"],
            "done": THEME["success"],
            "failed": THEME["error"],
        }
        for index, step_id in enumerate(step_ids, 1):
            state = states.get(step_id, "pending")
            style = status_styles.get(state, THEME["text"])
            t.append(f"  {status_icons.get(state, '○')} ", style=f"bold {style}")
            t.append(f"{index:02d}. ", style=THEME["dim"])
            t.append(step_id, style=f"bold {style}" if state != "pending" else style)
            t.append(f"  {state}", style=style)
            if details.get(step_id):
                t.append(f"  {details[step_id]}", style=THEME["muted"])
            t.append("\n")
        return t

    async def _workflow_cmd(self, args: str, log) -> None:
        """Handle HarnessSpec workflow status and explicit workflow runs."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :workflow arguments: {exc}")
            return
        action = tokens[0].lower() if tokens else "status"
        rest = tokens[1:]
        if action in {"presets", "templates"}:
            self._show_workflow_presets(log)
            return
        if action in {"preview", "doctor", "check"}:
            self._show_workflow_preview(log, " ".join(rest).strip())
            return
        if action in {"status", "list", "center", "dashboard", "show"}:
            self._show_workflow_center(log)
            return
        if action not in {"run", "start"}:
            log.add_info(
                "Usage: :workflow status | :workflow preview <task> | :workflow run <task>"
            )
            return

        prompt = " ".join(rest).strip()
        if not prompt:
            log.add_error("Usage: :workflow run <task>")
            return
        spec, path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return

        provider, model = self._workflow_provider_model(spec)
        if not provider or not model:
            log.add_error(
                "Connect a BYOK/local provider or set model_policy.primary before running workflows."
            )
            return

        try:
            from superqode.harness import FileHarnessStore, init_harness, run_workflow
        except Exception as exc:
            log.add_error(f"Workflow support is unavailable: {exc}")
            return

        steps = self._workflow_steps_from_spec(spec, prompt)
        step_ids = [step.id or f"step-{index + 1}" for index, step in enumerate(steps)]
        states = dict.fromkeys(step_ids, "pending")
        details: dict[str, str] = {}
        log.write(
            self._workflow_timeline_text(
                title="Workflow started",
                mode=spec.workflow.mode.value,
                step_ids=step_ids,
                states=states,
                details=details,
            )
        )

        def on_progress(progress) -> None:
            step_id = progress.step_id
            if step_id not in states:
                step_ids.append(step_id)
            states[step_id] = progress.status
            if progress.detail:
                details[step_id] = progress.detail
            log.write(
                self._workflow_timeline_text(
                    title="Workflow timeline",
                    mode=progress.mode.value,
                    step_ids=step_ids,
                    states=states,
                    details=details,
                )
            )

        try:
            pure = getattr(self, "_pure_mode", None)
            kernel = getattr(pure, "_harness_kernel", None) if pure is not None else None
            if kernel is None or not isinstance(getattr(kernel, "store", None), FileHarnessStore):
                kernel = await init_harness(
                    spec,
                    store=FileHarnessStore(Path(spec.context.session_storage)),
                )
                if pure is not None:
                    pure._harness_kernel = kernel
            result = await run_workflow(
                kernel,
                steps,
                provider=provider,
                model=model,
                working_directory=Path.cwd(),
                runtime=spec.runtime.backend,
                sandbox_backend=spec.execution_policy.sandbox,
                session_id=f"workflow-{int(time.time())}",
                progress_callback=on_progress,
            )
        except Exception as exc:
            log.add_error(f"Workflow failed: {exc}")
            return

        self._last_workflow_result = result
        self._refresh_harness_panel()
        done = Text()
        done.append("\n  ✓ ", style=f"bold {THEME['success']}")
        done.append("Workflow complete", style=f"bold {THEME['text']}")
        done.append(
            f"  {result.mode.value}, {len(result.results)} result(s)\n\n", style=THEME["dim"]
        )
        if getattr(result, "run_id", ""):
            done.append("Run graph: ", style=THEME["muted"])
            done.append(f":harness graph {result.run_id}\n\n", style=THEME["cyan"])
        if result.content:
            done.append(result.content, style=THEME["text"])
            done.append("\n", style="")
        log.write(done)

    async def _approval_cmd(self, action: str, args: str, log) -> None:
        """Handle :approve / :reject for the OpenAI Agents HITL flow.

        Usage:
            :approve              # approve pending #0 (the first interruption)
            :approve 1            # approve pending #1
            :approve always       # approve #0 and remember the choice
            :reject               # reject pending #0
            :reject 1 "<msg>"     # reject pending #1 with explicit message
        """
        pure = getattr(self, "_pure_mode", None)
        if pure is None or not hasattr(pure, "get_pending_approvals"):
            log.add_error("No active session supports interactive approvals.")
            return

        pending = pure.get_pending_approvals()
        if not pending:
            log.add_info("No pending approvals.")
            return

        # Parse args: optional integer index, optional "always", optional quoted message
        tokens = args.strip().split(maxsplit=1)
        index = 0
        always = False
        message: Optional[str] = None
        if tokens:
            head = tokens[0].lower()
            tail = tokens[1] if len(tokens) > 1 else ""
            if head.isdigit():
                index = int(head)
                if tail.lower().startswith("always"):
                    always = True
                    rest = tail.split(maxsplit=1)
                    if len(rest) > 1:
                        message = rest[1].strip().strip('"').strip("'")
                elif tail:
                    message = tail.strip().strip('"').strip("'")
            elif head == "always":
                always = True
                if tail:
                    message = tail.strip().strip('"').strip("'")
            else:
                # Treat the whole arg as the rejection message.
                message = args.strip().strip('"').strip("'")

        if index < 0 or index >= len(pending):
            log.add_error(f"Approval index {index} out of range (0..{len(pending) - 1}).")
            return
        choice = pending[index]
        try:
            if action == "approve":
                response = await pure.approve_and_resume(index=index, always=always)
                log.add_info(
                    f"Approved tool '{choice['tool_name']}'" + (" (always)" if always else "") + "."
                )
            else:
                response = await pure.reject_and_resume(index=index, message=message, always=always)
                log.add_info(
                    f"Rejected tool '{choice['tool_name']}'"
                    + (f": {message}" if message else "")
                    + "."
                )
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"{action.capitalize()} failed: {type(exc).__name__}: {exc}")
            return

        # Show resumed run result.
        if getattr(response, "stopped_reason", "") == "needs_approval":
            self._announce_pending_approvals(pure, log)
        elif response.error:
            log.add_error(f"Run failed: {response.error}")
        elif response.content:
            log.add_info(response.content)

    def _hub_cmd(self, args: str, log: ConversationLog):
        """Model-search mode: type a model name to find it (no `:local search`).

        ``:hub`` toggles the mode; ``:hub <name>`` does a one-shot search.
        """
        arg = (args or "").strip()
        low = arg.lower()

        if low in ("off", "stop", "exit"):
            self._hub_mode = False
            log.add_info("Model search OFF. Back to normal input.")
            return
        if low in ("on", "start"):
            self._hub_mode = True
        elif arg:
            # One-shot search; do not change the mode.
            self.run_worker(self._local_search(arg, log))
            return
        else:
            self._hub_mode = not getattr(self, "_hub_mode", False)

        if self._hub_mode:
            t = Text()
            t.append("\n  🔎 Model search ON\n", style=f"bold {THEME['cyan']}")
            t.append(
                "  Just type a model name to find it in the trusted catalog.\n",
                style=THEME["muted"],
            )
            t.append(
                "  Shows size, fit for your hardware, and the get-command.\n", style=THEME["muted"]
            )
            t.append("  Add ", style=THEME["muted"])
            t.append("--hub", style=f"bold {THEME['cyan']}")
            t.append(" on a line for the latest live from Hugging Face.\n", style=THEME["muted"])
            t.append("  Turn off with ", style=THEME["muted"])
            t.append(":hub off", style=f"bold {THEME['cyan']}")
            t.append("\n", style="")
            log.write(t)
        else:
            log.add_info("Model search OFF. Back to normal input.")

    def _chat_cmd(self, args: str, log: ConversationLog):
        """Toggle raw direct-to-model chat mode (no repo context, no tools)."""
        arg = (args or "").strip().lower()
        if arg in ("clear", "reset"):
            self._chat_history = []
            log.add_info("Chat history cleared.")
            return
        if arg in ("off", "stop", "exit", "0", "false"):
            enable = False
        elif arg in ("on", "start", "1", "true"):
            enable = True
        else:
            enable = not getattr(self, "_chat_mode", False)

        if enable:
            chat_ready, chat_message, who = self._direct_chat_status()
            if not chat_ready:
                self._chat_mode = False
                self._refresh_prompt_mode_label()
                log.add_info(chat_message)
                return

        self._chat_mode = enable
        self._refresh_prompt_mode_label()
        if enable:
            self._chat_history = []
            t = Text()
            t.append("\n  💬 Chat mode ON\n", style=f"bold {THEME['cyan']}")
            t.append(
                "  Local/BYOK direct model chat: no repo context, no tools, no harness.\n",
                style=THEME["muted"],
            )
            t.append("  Every reply reports TTFT and decode tok/s.\n", style=THEME["muted"])
            t.append(f"  Model: {who}\n", style=THEME["dim"])
            t.append("  ACP agents use Build/Plan mode, not raw chat.\n", style=THEME["muted"])
            t.append("  Turn off with ", style=THEME["muted"])
            t.append(":chat off", style=f"bold {THEME['cyan']}")
            t.append("\n", style="")
            log.write(t)
        else:
            log.add_info("Chat mode OFF. Back to the full coding harness.")

    def _build_cmd(self, args: str, log: ConversationLog):
        """Return prompts to the repo-aware coding harness."""
        self._chat_mode = False
        self._plan_mode_enabled = False
        self._force_plan_once = False
        self._active_plan_mode_for_current_message = False
        self._refresh_plan_status_badge()
        log.add_success("Build mode ON. Repo context and tools are available for coding tasks.")
        log.add_info("Use :chat on for direct model chat, or :plan on to plan before edits.")

    def _mode_cmd(self, args: str, log: ConversationLog) -> None:
        """Switch or pick Chat, Build, or Plan mode."""
        mode = (args or "").strip().lower()
        aliases = {
            "": "",
            "chat": "chat",
            "c": "chat",
            "build": "build",
            "b": "build",
            "code": "build",
            "plan": "plan",
            "p": "plan",
        }
        if mode in aliases and aliases[mode]:
            self._apply_interaction_mode(aliases[mode], log)
            return
        if mode in {"", "pick", "switch", "toggle"}:
            self._show_mode_picker(log)
            return
        log.add_info("Usage: :mode [chat|build|plan]")

    def _providers_cmd(self, args: str, log: ConversationLog):
        """Show provider setup, labels, and representative models."""
        from superqode.providers.recommendations import provider_doctor_cards
        from superqode.providers.registry import PROVIDERS

        args = args.strip()
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else ""
        subargs = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("doctor", "check"):
            self._doctor_cmd(subargs, log)
            return

        if sub in {
            "list",
            "models",
            "guide",
            "recommend",
            "scan-free",
            "test",
            "monty",
            "ds4",
            "mlx",
        }:
            self._run_cli_group("providers", args, log, "Providers command")
            return

        if sub in ("smoke", "test"):
            self.run_worker(self._providers_smoke_cmd(subargs, log))
            return

        if sub in ("free", "scan-free", "store"):
            self.run_worker(self._providers_free_cmd(subargs, log))
            return

        provider_id = args or None
        if provider_id and provider_id not in PROVIDERS:
            log.add_error(f"Provider not found: {provider_id}")
            log.add_info("Use :providers to list providers or :recommend coding for suggestions.")
            return

        cards = provider_doctor_cards([provider_id] if provider_id else None)
        t = Text()
        t.append("\n  ☁ ", style=f"bold {THEME['cyan']}")
        t.append("Provider Guide\n\n", style=f"bold {THEME['text']}")
        t.append(
            "  Labels show setup readiness, cost/context, and tool support.\n\n",
            style=THEME["muted"],
        )

        for card in cards[:12]:
            status_style = THEME["success"] if card["configured"] else THEME["warning"]
            status = "ready" if card["configured"] else "missing"
            labels = ", ".join(card["labels"]) or "-"
            t.append(f"  {card['provider']:<16}", style=f"bold {THEME['cyan']}")
            t.append(f"{status:<8}", style=status_style)
            t.append(f"{card['name']}  ", style=THEME["text"])
            t.append(f"[{labels}]\n", style=THEME["dim"])
            t.append(f"    setup: {card['setup_hint']}\n", style=THEME["muted"])
            for model in card["models"][:3]:
                t.append(f"    - {model['model']:<28}", style=THEME["text"])
                t.append(f"{model['price']:<13}", style=THEME["gold"])
                t.append(f"{model['context']} ctx  ", style=THEME["cyan"])
                t.append(f"tools={model['tool_support']}\n", style=THEME["muted"])
            t.append("\n")

        t.append("  Commands: ", style=THEME["muted"])
        t.append(":providers <provider>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":providers free --live openrouter", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(
            ":recommend coding|review|testing|budget|speed|large-context|reasoning",
            style=THEME["cyan"],
        )
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    async def _providers_free_cmd(self, args: str, log: ConversationLog):
        """Show free/local inference options from the TUI."""
        from superqode.providers.free_inference import (
            list_free_inference_offers,
            offer_status,
            scan_live_free_candidates,
        )

        tokens = (args or "").split()
        live = "--live" in tokens or "live" in tokens
        configured = "--configured" in tokens
        source_tokens = [
            token for token in tokens if token in {"openrouter", "models-dev", "litellm"}
        ]
        provider_tokens = [
            token
            for token in tokens
            if token
            not in {
                "--live",
                "live",
                "--configured",
                "openrouter",
                "models-dev",
                "litellm",
            }
        ]
        provider_filter = provider_tokens[0] if provider_tokens else None

        if live:
            log.add_info("Scanning live model/pricing catalogs...")
            candidates, errors = await asyncio.to_thread(
                scan_live_free_candidates,
                sources=source_tokens or None,
                limit=50,
            )
            if provider_filter:
                needle = provider_filter.lower()
                candidates = [
                    item
                    for item in candidates
                    if item.provider.lower() == needle
                    or needle in item.model.lower()
                    or needle in item.name.lower()
                ]
            self._show_command_output(
                log,
                self._format_live_free_inference(candidates, errors, source_tokens),
            )
            return

        offers = list_free_inference_offers(
            provider=provider_filter,
            configured_only=configured,
        )
        self._show_command_output(
            log,
            self._format_free_inference_offers(offers, offer_status),
        )

    async def _providers_smoke_cmd(self, args: str, log: ConversationLog):
        """Run a local provider smoke check from the TUI."""
        from superqode.providers.local.smoke import all_local_provider_ids, smoke_local_provider

        tokens = (args or "").split()
        if not tokens:
            log.add_info("Usage: :providers smoke <local-provider> [model] [--run]")
            log.add_info("Example: :providers smoke ollama")
            return

        provider = tokens[0]
        run_prompt = "--run" in tokens
        no_tool_test = "--no-tool-test" in tokens
        model_parts = [token for token in tokens[1:] if token not in ("--run", "--no-tool-test")]
        model = " ".join(model_parts).strip() or None

        if provider not in all_local_provider_ids():
            log.add_error(f"Local provider not found: {provider}")
            log.add_info(f"Available: {', '.join(all_local_provider_ids())}")
            return

        log.add_info(f"Checking {provider}...")
        payload = await smoke_local_provider(
            provider,
            model,
            run_prompt=run_prompt,
            tool_test=not no_tool_test,
        )
        self._show_command_output(log, self._format_local_smoke_result(payload))

    def _recommend_cmd(self, args: str, log: ConversationLog):
        """Recommend providers/models for a task."""
        from superqode.providers.recommendations import normalize_task, recommend_models

        task = normalize_task(args.strip() or "coding")
        recommendations = recommend_models(task, limit=8)
        self._recommendation_list = recommendations
        self._awaiting_recommendation_selection = bool(recommendations)
        t = Text()
        t.append("\n  ◆ ", style=f"bold {THEME['purple']}")
        t.append("Model Recommendations\n\n", style=f"bold {THEME['text']}")
        t.append("  Task: ", style=THEME["muted"])
        t.append(f"{task}\n\n", style=f"bold {THEME['cyan']}")

        if not recommendations:
            self._awaiting_recommendation_selection = False
            t.append("  No recommendations available.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        for index, item in enumerate(recommendations, 1):
            setup_style = THEME["success"] if item.setup.configured else THEME["warning"]
            setup = "ready" if item.setup.configured else item.setup.setup_hint
            labels = ", ".join(item.labels[:6])
            t.append(f"  [{index}] ", style=THEME["dim"])
            t.append(f"{item.provider}/{item.model}\n", style=f"bold {THEME['text']}")
            t.append("      score ", style=THEME["muted"])
            t.append(f"{item.score:<3}", style=THEME["success"])
            t.append(" price ", style=THEME["muted"])
            t.append(f"{item.price:<13}", style=THEME["gold"])
            t.append(" context ", style=THEME["muted"])
            t.append(f"{item.context:<6}", style=THEME["cyan"])
            t.append(" tools ", style=THEME["muted"])
            t.append(
                f"{item.tool_support:<3}",
                style=THEME["success"] if item.tool_support == "yes" else THEME["dim"],
            )
            t.append(" setup ", style=THEME["muted"])
            t.append(f"{setup}\n", style=setup_style)
            t.append(f"      {item.reason}\n", style=THEME["muted"])
            if labels:
                t.append(f"      {labels}\n", style=THEME["dim"])
            t.append("\n")

        t.append("  Type a number to connect, or use ", style=THEME["muted"])
        t.append(":connect <provider>/<model>", style=THEME["cyan"])
        t.append(".\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _sandbox_cmd(self, args: str, log: ConversationLog):
        """Show sandbox provider readiness in the TUI."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :sandbox arguments: {exc}")
            return
        if tokens and tokens[0] in {"doctor", "run"}:
            self._run_cli_passthrough(["sandbox", *tokens], log, "Sandbox command")
            return

        from superqode.sandbox import (
            get_sandbox_capabilities,
            sandbox_provider_status,
            supported_sandbox_backends,
        )

        requested = args.strip()
        backends = [requested] if requested else supported_sandbox_backends(include_cloud=True)
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['cyan']}")
        t.append("Sandbox Backends\n\n", style=f"bold {THEME['text']}")

        for backend in backends:
            status = sandbox_provider_status(backend)
            style = THEME["success"] if status.available else THEME["warning"]
            t.append(f"  {status.backend:<12}", style=f"bold {THEME['cyan']}")
            t.append(("ready" if status.available else "missing").ljust(9), style=style)
            t.append(f"{status.detail}\n", style=THEME["text"])
            try:
                caps = get_sandbox_capabilities(backend)
                t.append(
                    f"    read={caps.can_read} write={caps.can_write} shell={caps.can_shell} network={caps.can_network}\n",
                    style=THEME["muted"],
                )
            except ValueError:
                pass
            if status.required_env:
                t.append(f"    env: {', '.join(status.required_env)}\n", style=THEME["dim"])
            if status.optional_dependency:
                t.append(f"    install: {status.optional_dependency}\n", style=THEME["dim"])

        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":sandbox <backend>", style=THEME["cyan"])
        t.append(", CLI ", style=THEME["muted"])
        t.append("superqode sandbox run docker -- pytest -q", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _plugins_cmd(self, args: str, log: ConversationLog):
        """Manage project plugin manifests."""
        from superqode.plugins import (
            disable_plugin,
            disabled_plugin_ids,
            discover_plugin_manifests,
            enable_plugin,
            install_plugin,
            load_plugin_manifest,
            validate_plugin_manifest,
        )

        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :plugins arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "list"
        subargs = tokens[1:]

        if subcommand in {"show", "list"} and subargs:
            self._run_cli_passthrough(["plugins", *tokens], log, "Plugins command")
            return

        if subcommand in {"add", "install"}:
            if not subargs:
                log.add_info("Usage: :plugins add <local-plugin-dir|plugin.json>")
                return
            if not self._ensure_project_trusted_for(log, "install a plugin"):
                return
            try:
                plugin = install_plugin(subargs[0], Path.cwd())
            except Exception as exc:
                log.add_error(f"Could not install plugin: {exc}")
                return
            pure = getattr(self, "_pure_mode", None)
            if pure is not None:
                self._completion_extension_runtime = pure.reload_extensions()
            log.add_success(f"Installed plugin {plugin.id} -> .superqode/plugins/{plugin.id}")
            return

        if subcommand in {"enable", "disable"}:
            if not subargs:
                log.add_info(f"Usage: :plugins {subcommand} <plugin-id>")
                return
            plugin_id = subargs[0]
            if subcommand == "enable":
                if not self._ensure_project_trusted_for(log, "enable a plugin"):
                    return
                changed = enable_plugin(plugin_id, Path.cwd())
                log.add_success(
                    f"Enabled plugin {plugin_id}"
                    if changed
                    else f"Plugin {plugin_id} was already enabled"
                )
            else:
                changed = disable_plugin(plugin_id, Path.cwd())
                log.add_success(
                    f"Disabled plugin {plugin_id}"
                    if changed
                    else f"Plugin {plugin_id} was already disabled"
                )
            pure = getattr(self, "_pure_mode", None)
            if pure is not None:
                self._completion_extension_runtime = pure.reload_extensions()
            return

        if subcommand in {"doctor", "validate"}:
            runtime_check = "--runtime" in subargs
            subargs = [value for value in subargs if value != "--runtime"]
            paths = discover_plugin_manifests(Path.cwd())
            if subargs:
                target = Path(subargs[0]).expanduser()
                if not target.is_absolute():
                    target = Path.cwd() / target
                if target.is_dir():
                    target = target / "plugin.json"
                paths = [target]
            t = Text()
            t.append("\n  Plugin Doctor\n\n", style=f"bold {THEME['purple']}")
            if not paths and not runtime_check:
                t.append("  No plugin manifests found.\n", style=THEME["muted"])
                t.append("  Install one with ", style=THEME["muted"])
                t.append(":plugins add <path>", style=THEME["cyan"])
                t.append(".\n", style=THEME["muted"])
                self._show_command_output(log, t)
                return
            ok_count = 0
            for path in paths:
                issues = validate_plugin_manifest(path)
                label = str(path)
                try:
                    manifest = load_plugin_manifest(path)
                    label = f"{manifest.id}  ({path})"
                except Exception:
                    pass
                if not issues:
                    ok_count += 1
                    t.append(f"  OK   {label}\n", style=THEME["success"])
                else:
                    t.append(f"  FAIL {label}\n", style=THEME["error"])
                    for issue in issues:
                        t.append(f"       - {issue}\n", style=THEME["warning"])
            t.append(f"\n  {ok_count}/{len(paths)} manifests valid.\n", style=THEME["muted"])
            if runtime_check:
                if not self._ensure_project_trusted_for(log, "execute plugin runtime checks"):
                    return
                from superqode.extensions import load_extension_runtime

                runtime = load_extension_runtime(Path.cwd())
                t.append("\n  Runtime activation\n", style=f"bold {THEME['text']}")
                for extension in runtime.extensions:
                    capabilities = ", ".join(extension.capabilities) or "metadata-only"
                    t.append(f"  ACTIVE {extension.id}", style=THEME["success"])
                    t.append(f"  {capabilities}\n", style=THEME["muted"])
                for skipped in runtime.skipped:
                    t.append(f"  SKIP   {skipped}\n", style=THEME["warning"])
                for error in runtime.errors:
                    t.append(
                        f"  FAIL   {error.extension_id} [{error.capability}] ",
                        style=THEME["error"],
                    )
                    t.append(f"{error.message}\n", style=THEME["warning"])
            self._show_command_output(log, t)
            return

        if subcommand not in {"list", "ls", "status"}:
            log.add_info("Usage: :plugins [list|doctor|add|enable|disable] ...")
            return

        plugins = []
        load_errors: list[tuple[Path, str]] = []
        for path in discover_plugin_manifests(Path.cwd()):
            try:
                plugins.append(load_plugin_manifest(path))
            except Exception as exc:
                load_errors.append((path, str(exc)))
        disabled = disabled_plugin_ids(Path.cwd())
        runtime = self._ensure_pure_mode()._extension_runtime
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append("Plugins\n\n", style=f"bold {THEME['text']}")
        if not plugins and not load_errors and not runtime.extensions and not runtime.errors:
            t.append("  No plugins found.\n", style=THEME["muted"])
            t.append(
                "  Expected manifests under .superqode/plugins/*/plugin.json.\n", style=THEME["dim"]
            )
            t.append("  Install one with ", style=THEME["muted"])
            t.append(":plugins add <path>", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        for plugin in plugins:
            enabled = plugin.id not in disabled
            status = "enabled" if enabled else "disabled"
            status_style = THEME["success"] if enabled else THEME["warning"]
            t.append(f"  {plugin.id:<24}", style=f"bold {THEME['cyan']}")
            t.append(f"{plugin.version:<10}", style=THEME["success"])
            t.append(f"{status:<10}", style=status_style)
            t.append(f"{plugin.name}\n", style=THEME["text"])
            if plugin.description:
                t.append(f"    {plugin.description}\n", style=THEME["muted"])
            if plugin.commands:
                commands = [
                    str(item.get("name") or item.get("command") or item)
                    for item in plugin.commands
                    if isinstance(item, dict)
                ]
                t.append(f"    commands: {', '.join(commands)}\n", style=THEME["dim"])
            if plugin.tools:
                tools = [
                    str(item.get("name") or item.get("tool") or item)
                    for item in plugin.tools
                    if isinstance(item, dict)
                ]
                t.append(f"    tools: {', '.join(tools)}\n", style=THEME["dim"])
            if plugin.path:
                t.append(f"    {plugin.path}\n", style=THEME["dim"])
        for path, error in load_errors:
            t.append(f"  broken manifest  {path}\n", style=THEME["error"])
            t.append(f"    {error}\n", style=THEME["warning"])
        if runtime.extensions:
            t.append("\n  Active runtime extensions\n", style=f"bold {THEME['text']}")
            for extension in runtime.extensions:
                capabilities = ", ".join(extension.capabilities) or "metadata-only"
                t.append(f"  {extension.id:<24}", style=f"bold {THEME['cyan']}")
                t.append(f"{capabilities}\n", style=THEME["muted"])
        for skipped in runtime.skipped:
            t.append(f"  skipped  {skipped}\n", style=THEME["warning"])
        for error in runtime.errors:
            t.append(
                f"  runtime error  {error.extension_id} [{error.capability}]\n",
                style=THEME["error"],
            )
            t.append(f"    {error.message}\n", style=THEME["warning"])
        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":plugins doctor", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":plugins add <path>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":plugins enable|disable <id>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _memory_cmd(self, args: str, log: ConversationLog):
        """Manage SuperQode agent memory from the TUI."""
        from superqode.memory import available_memory_providers, create_memory_provider

        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :memory arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "status"
        rest = tokens[1:]

        if subcommand in {"", "status"}:
            provider_name = rest[0] if rest else "local"
            try:
                status = create_memory_provider(provider_name, project_root=Path.cwd()).status()
            except Exception as exc:
                log.add_error(f"Could not inspect memory provider: {exc}")
                return
            t = Text()
            t.append("\n  Memory\n\n", style=f"bold {THEME['purple']}")
            t.append("  Provider ", style=THEME["muted"])
            t.append(f"{status.provider}\n", style=f"bold {THEME['cyan']}")
            t.append("  Status   ", style=THEME["muted"])
            state = self._memory_status_state(status)
            t.append(
                f"{state}\n",
                style=THEME["success"] if status.available else THEME["warning"],
            )
            t.append("  Records  ", style=THEME["muted"])
            t.append(f"{status.record_count}\n", style=THEME["text"])
            if status.path:
                t.append("  Path     ", style=THEME["muted"])
                t.append(f"{status.path}\n", style=THEME["dim"])
            if status.detail:
                t.append("  Detail   ", style=THEME["muted"])
                t.append(f"{status.detail}\n", style=THEME["text"])
            t.append("\n  Commands: ", style=THEME["muted"])
            t.append(":memory remember", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":memory search", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":memory providers", style=THEME["cyan"])
            t.append("\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        if subcommand in {"providers", "doctor"}:
            statuses = available_memory_providers(Path.cwd())
            t = Text()
            t.append("\n  Memory Providers\n\n", style=f"bold {THEME['purple']}")
            for status in statuses:
                state = self._memory_status_state(status)
                style = THEME["success"] if status.available else THEME["warning"]
                t.append(f"  {status.provider:<12}", style=f"bold {THEME['cyan']}")
                t.append(f"{state:<10}", style=style)
                t.append(f"{status.detail}\n", style=THEME["text"])
                if status.path:
                    t.append(f"    {status.path}\n", style=THEME["dim"])
            self._show_command_output(log, t)
            return

        if subcommand == "remember":
            text = " ".join(rest).strip()
            if not text:
                log.add_info("Usage: :memory remember <text>")
                return
            try:
                record = create_memory_provider("local", project_root=Path.cwd()).remember(text)
            except Exception as exc:
                log.add_error(f"Could not save memory: {exc}")
                return
            log.add_success(f"Remembered {record.id}")
            return

        if subcommand == "search":
            provider_name = "local"
            query_parts = rest
            if len(rest) >= 2 and rest[0] in {"local", "specmem", "mem0", "cognee", "supermemory"}:
                provider_name = rest[0]
                query_parts = rest[1:]
            query = " ".join(query_parts).strip()
            if not query:
                log.add_info("Usage: :memory search [local|specmem] <query>")
                return
            try:
                results = create_memory_provider(provider_name, project_root=Path.cwd()).search(
                    query
                )
            except Exception as exc:
                log.add_error(f"Could not search memory: {exc}")
                return
            t = Text()
            t.append("\n  Memory Search\n\n", style=f"bold {THEME['purple']}")
            if not results:
                t.append("  No memory matches.\n", style=THEME["muted"])
            for result in results:
                record = result.record
                t.append(f"  {record.id:<12}", style=f"bold {THEME['cyan']}")
                t.append(f"{result.provider:<8}", style=THEME["muted"])
                t.append(f"{record.kind:<10}", style=THEME["success"])
                t.append(f"score={result.score:.2f}\n", style=THEME["dim"])
                t.append(f"    {record.content}\n", style=THEME["text"])
            self._show_command_output(log, t)
            return

        if subcommand == "forget":
            if not rest:
                log.add_info("Usage: :memory forget <id>")
                return
            try:
                ok = create_memory_provider("local", project_root=Path.cwd()).forget(rest[0])
            except Exception as exc:
                log.add_error(f"Could not forget memory: {exc}")
                return
            if ok:
                log.add_success(f"Forgot {rest[0]}")
            else:
                log.add_error(f"Memory not found: {rest[0]}")
            return

        if subcommand == "export":
            provider_name = rest[0] if rest else "local"
            try:
                payload = create_memory_provider(provider_name, project_root=Path.cwd()).export()
            except Exception as exc:
                log.add_error(f"Could not export memory: {exc}")
                return
            out_path = Path(".superqode") / "exports" / f"memory-{provider_name}.json"
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            except Exception as exc:
                log.add_error(f"Could not write memory export: {exc}")
                return
            log.add_success(f"Exported memory -> {out_path}")
            return

        log.add_info("Usage: :memory [status|providers|doctor|remember|search|forget|export]")

    def _benchmark_cmd(self, args: str, log: ConversationLog):
        """Show benchmark harness status and optional task-file guidance."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :benchmark arguments: {exc}")
            return
        if tokens and tokens[0] == "run":
            self._run_cli_passthrough(["benchmark", *tokens], log, "Benchmark command")
            return

        from superqode.benchmarks import DEFAULT_TARGETS, is_target_available

        t = Text()
        t.append("\n  ▤ ", style=f"bold {THEME['gold']}")
        t.append("Benchmark Harness\n\n", style=f"bold {THEME['text']}")
        for name, target in DEFAULT_TARGETS.items():
            available = is_target_available(target)
            style = THEME["success"] if available else THEME["warning"]
            t.append(f"  {name:<12}", style=f"bold {THEME['cyan']}")
            t.append(("available" if available else "missing").ljust(11), style=style)
            t.append(f"{' '.join(target.command)}\n", style=THEME["muted"])

        t.append("\n  CLI run:\n", style=THEME["muted"])
        t.append(
            "    superqode benchmark run tasks.json --target superqode --target opencode --target pi --target deepagents\n",
            style=THEME["cyan"],
        )
        if args.strip():
            t.append(
                "\n  TUI note: benchmark execution is CLI-backed for reproducible logs.\n",
                style=THEME["dim"],
            )
        self._show_command_output(log, t)

    def _usage_cmd(self, args: str, log: ConversationLog):
        """Handle :usage command - Show token/cost usage."""
        from superqode.providers.usage import get_usage_tracker

        tracker = get_usage_tracker()
        args = args.strip()

        if args == "reset":
            tracker.reset()
            log.add_success("Usage stats reset")
            return

        summary = tracker.get_summary()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Session Usage\n\n", style=f"bold {THEME['text']}")

        if not summary["connected"]:
            t.append("  Not connected to any provider\n", style=THEME["muted"])
            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(":connect", style=THEME["success"])
            t.append(" to select a provider\n", style=THEME["muted"])
            log.write(t)
            return

        # Provider/Model
        t.append(f"  Provider: ", style=THEME["muted"])
        t.append(f"{summary['provider']}", style=f"bold {THEME['success']}")
        t.append(f" / ", style=THEME["dim"])
        t.append(f"{summary['model']}\n\n", style=THEME["cyan"])

        # Token counts
        t.append(f"  Total Tokens:  ", style=THEME["muted"])
        total = summary["tokens"]
        if total >= 1000:
            t.append(f"{total / 1000:.1f}K", style=f"bold {THEME['text']}")
        else:
            t.append(f"{total}", style=f"bold {THEME['text']}")
        t.append("\n", style="")

        t.append(f"  ├─ Input:      ", style=THEME["dim"])
        input_tokens = summary.get("input_tokens", 0)
        if input_tokens >= 1000:
            t.append(f"{input_tokens / 1000:.1f}K\n", style=THEME["text"])
        else:
            t.append(f"{input_tokens}\n", style=THEME["text"])

        t.append(f"  └─ Output:     ", style=THEME["dim"])
        output_tokens = summary.get("output_tokens", 0)
        if output_tokens >= 1000:
            t.append(f"{output_tokens / 1000:.1f}K\n\n", style=THEME["text"])
        else:
            t.append(f"{output_tokens}\n\n", style=THEME["text"])

        # Cost
        cost = summary["cost"]
        t.append(f"  Estimated Cost: ", style=THEME["muted"])
        if cost > 0:
            t.append(f"${cost:.4f}\n", style=f"bold {THEME['gold']}")
        else:
            t.append("Free\n", style=f"bold {THEME['success']}")

        # Messages
        t.append(f"\n  Messages:      ", style=THEME["muted"])
        t.append(f"{summary['messages']}\n", style=THEME["text"])

        t.append(f"  Tool Calls:    ", style=THEME["muted"])
        t.append(f"{summary['tools']}\n", style=THEME["text"])

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":usage reset", style=THEME["success"])
        t.append(" to reset stats\n", style=THEME["muted"])

        log.write(t)

    def _health_cmd(self, args: str, log: ConversationLog):
        """Handle :health command - Check provider connectivity."""
        self.run_worker(self._check_provider_health(log))

    def _acp_cmd(self, args: str, log: ConversationLog):
        """Handle :acp command with subcommands (list, install, model, doctor).

        Bare agent names are treated as connect targets so ``:acp grok`` works
        the same as ``:connect acp grok`` (Grok Build ACP, not the subscription
        harness path).
        """
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if sub in ("list", ""):
            self._show_agents(log)
        elif sub == "connect":
            # Deprecated: Use :connect acp instead
            log.add_warning(":acp connect is deprecated. Use :connect acp instead.")
            log.add_info("Routing to :connect acp...")
            self._connect_acp_cmd(subargs, log)
        elif sub == "install":
            if subargs:
                self._install_agent(subargs, log)
            else:
                log.add_info("Usage: :acp install <name>")
        elif sub == "model":
            if subargs:
                self._set_model(subargs, log)
            else:
                log.add_info("Usage: :acp model <model_id>")
        elif sub in ("doctor", "check"):
            self.run_worker(self._acp_doctor_cmd(subargs, log))
        else:
            # ":acp grok" / ":acp opencode" → connect that ACP agent by short name
            self._connect_acp_cmd(args.strip(), log)

    def _agents_cmd(self, args: str, log: ConversationLog):
        """Handle :agents as an alias for ACP agent management."""
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if sub in ("list", ""):
            self._show_agents(log)
        elif sub in ("doctor", "check"):
            self.run_worker(self._acp_doctor_cmd(subargs, log))
        elif sub == "install":
            if subargs:
                self._install_agent(subargs, log)
            else:
                log.add_info("Usage: :agents install <name>")
        elif sub == "connect":
            self._connect_acp_cmd(subargs, log)
        else:
            self._run_cli_group("agents", args, log, "Agents command")

    async def _acp_doctor_cmd(self, args: str, log: ConversationLog):
        """Run ACP agent diagnostics from the TUI."""
        from superqode.acp.doctor import acp_doctor

        tokens = (args or "").split()
        live = any(token in ("--live", "live") for token in tokens)
        agent_parts = [token for token in tokens if token not in ("--live", "live")]
        agent = " ".join(agent_parts).strip() or None

        if agent:
            log.add_info(f"Checking ACP agent {agent}...")
        else:
            log.add_info("Checking ACP agents...")

        results = await acp_doctor(agent, live=live)
        if agent and not results:
            log.add_error(f"ACP agent not found: {agent}")
            return

        self._show_command_output(log, self._format_acp_doctor_results(results, live=live))

    async def _a2a_cmd(self, args: str, log: ConversationLog):
        """Handle :a2a commands."""
        parts = args.split(maxsplit=1)
        subcommand = parts[0] if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        # Lazy load A2A commands
        if not hasattr(self, "_a2a_commands"):
            try:
                from .commands.a2a import create_a2a_commands

                self._a2a_commands = create_a2a_commands()
            except ImportError:
                log.add_error("A2A not installed. Run: uv tool install 'superqode[a2a]'")
                return

        await self._a2a_commands.handle_command(subcommand, subargs, log)

    def _doctor_cmd(self, args: str, log: ConversationLog):
        """Show readiness for the current or requested provider."""
        from superqode.providers.recommendations import provider_doctor_cards
        from superqode.providers.registry import PROVIDERS

        tokens = (args or "").split()
        if any(token in ("tui", "dashboard", "all", "harness") for token in tokens):
            self._show_tui_doctor_dashboard(log)
            return
        live = any(token in ("--live", "live", "smoke") for token in tokens)
        provider = " ".join(
            token for token in tokens if token not in ("--live", "live", "smoke")
        ).strip()
        if provider in ("", "current", "."):
            pure = getattr(self, "_pure_mode", None)
            pure_session = getattr(pure, "session", None)
            provider = self.current_provider or getattr(pure_session, "provider", "")

        if not provider:
            log.add_info("No provider selected. Use :connect first or run :doctor <provider>.")
            return

        if provider not in PROVIDERS:
            log.add_error(f"Unknown provider: {provider}")
            return

        if live:
            self.run_worker(self._providers_smoke_cmd(provider, log))
            return

        card = provider_doctor_cards([provider])[0]
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Provider Doctor\n\n", style=f"bold {THEME['text']}")

        configured = "ready" if card["configured"] else "needs setup"
        status_style = THEME["success"] if card["configured"] else THEME["warning"]
        t.append(f"  Provider     ", style=THEME["muted"])
        t.append(f"{card['name']} ({card['provider']})\n", style=f"bold {THEME['cyan']}")
        t.append(f"  Status       ", style=THEME["muted"])
        t.append(f"{configured}\n", style=status_style)
        t.append(f"  Setup        ", style=THEME["muted"])
        t.append(f"{card['setup_hint']}\n", style=THEME["text"])
        labels = ", ".join(card["labels"]) or "-"
        t.append(f"  Labels       ", style=THEME["muted"])
        t.append(f"{labels}\n\n", style=THEME["dim"])

        for model in card["models"][:5]:
            t.append(f"  - {model['model']}", style=THEME["text"])
            t.append(f"  {model['price']}", style=THEME["gold"])
            t.append(f"  {model['context']} ctx", style=THEME["cyan"])
            t.append(f"  tools={model['tool_support']}\n", style=THEME["muted"])

        t.append("\n  Actions: ", style=THEME["muted"])
        t.append(":retry", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":copy error", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":providers ", style=THEME["cyan"])
        t.append(provider, style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _work_cmd(self, args: str, log: ConversationLog):
        """Show the tools, files, and commands from the last completed run."""
        summary = getattr(self, "_last_run_summary", {}) or {}
        if not summary:
            log.add_info("No completed agent work yet.")
            return

        mode = (args or "").strip().lower()
        verbose = mode in ("verbose", "full", "details")
        files_read = summary.get("files_read", []) or []
        files_modified = summary.get("files_modified", []) or []
        tools = summary.get("tools", []) or []
        commands_run = summary.get("commands_run", []) or []
        provider = summary.get("provider") or self.current_provider or "-"
        model = summary.get("model") or self.current_model or "-"

        t = Text()
        t.append("\n  ▤ ", style=f"bold {THEME['purple']}")
        t.append("Last Work Summary\n\n", style=f"bold {THEME['text']}")
        t.append("  Target      ", style=THEME["muted"])
        t.append(f"{provider}/{model}\n", style=f"bold {THEME['cyan']}")
        t.append("  Duration    ", style=THEME["muted"])
        t.append(f"{summary.get('duration', 0):.1f}s\n", style=THEME["text"])
        t.append("  Tools       ", style=THEME["muted"])
        t.append(f"{summary.get('tool_count', len(tools))}\n", style=THEME["text"])

        if files_read:
            t.append("  Files read  ", style=THEME["muted"])
            t.append(f"{len(files_read)}\n", style=THEME["cyan"])
        if files_modified:
            t.append("  Changed     ", style=THEME["muted"])
            t.append(f"{len(files_modified)}\n", style=THEME["success"])
        if commands_run:
            t.append("  Commands    ", style=THEME["muted"])
            t.append(f"{len(commands_run)}\n", style=THEME["orange"])

        def _append_items(title: str, items: list[str], style: str, limit: int = 5):
            if not items:
                return
            visible_items = items if verbose else items[:limit]
            t.append(f"\n  {title}\n", style=f"bold {THEME['text']}")
            for item in visible_items:
                t.append("  - ", style=THEME["dim"])
                t.append(f"{item}\n", style=style)
            hidden = len(items) - len(visible_items)
            if hidden > 0:
                t.append(f"  ... {hidden} more. Use :work verbose.\n", style=THEME["muted"])

        _append_items("Files Read", files_read, THEME["cyan"])
        _append_items("Files Changed", files_modified, THEME["success"])
        _append_items("Commands", commands_run, THEME["orange"])

        if tools:
            visible_tools = tools if verbose else tools[:8]
            t.append("\n  Tools\n", style=f"bold {THEME['text']}")
            for tool in visible_tools:
                name = tool.get("name", "tool")
                detail = tool.get("path") or tool.get("command") or tool.get("query") or ""
                status = tool.get("status", "")
                duration = tool.get("duration", 0.0) or 0.0
                kind = tool.get("kind", "")
                t.append("  - ", style=THEME["dim"])
                t.append(name, style=f"bold {THEME['purple']}")
                if kind:
                    t.append(f" [{kind}]", style=THEME["dim"])
                if status:
                    status_style = THEME["success"] if status == "success" else THEME["error"]
                    if status == "running":
                        status_style = THEME["warning"]
                    t.append(" ", style=THEME["dim"])
                    t.append(status, style=status_style)
                if duration:
                    t.append(f" {duration:.2f}s", style=THEME["muted"])
                if detail:
                    t.append("  ", style=THEME["dim"])
                    t.append(str(detail), style=THEME["muted"])
                t.append("\n")
            hidden = len(tools) - len(visible_tools)
            if hidden > 0:
                t.append(f"  ... {hidden} more. Use :work verbose.\n", style=THEME["muted"])

        t.append("\n  Actions: ", style=THEME["muted"])
        t.append(":diff", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":copy response", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":retry", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _session_cmd(self, args: str, log: ConversationLog):
        """Show the current coding session or recent sessions."""
        sub = (args or "").strip().lower()
        if sub in ("", "current", "."):
            self._show_harness_status(log)
            return

        if sub in ("list", "recent"):
            if not hasattr(self, "_pure_mode"):
                log.add_info("No local/BYOK session manager is active yet.")
                return
            sessions = self._pure_mode.list_sessions()
            t = Text()
            t.append("\n  📂 ", style=f"bold {THEME['orange']}")
            t.append("Recent Sessions\n\n", style=f"bold {THEME['text']}")
            if not sessions:
                t.append("  No sessions found.\n", style=THEME["muted"])
            for item in sessions:
                t.append(f"  {item['display_id']}  ", style=f"bold {THEME['cyan']}")
                t.append(f"{item['provider']}/{item['model']}  ", style=THEME["text"])
                t.append(f"{item['message_count']} messages\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        log.add_info("Usage: :session current or :session list")
