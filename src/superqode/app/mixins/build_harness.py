"""Build-your-own-harness screens for the ``:connect`` ladder.

The third rung of ``:connect`` is authoring a repository-owned HarnessSpec.
Importing whatever agent config the repository already has comes first, because
it produces a working harness out of work the user has already done. Presets,
the wizard, and a blank spec follow for people who want to start clean.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rich.text import Text

from superqode.app.constants import THEME
from superqode.app.widgets import ConversationLog

#: Repository files that describe how an agent should behave here. Each entry is
#: (path, label, how the content is used). Markdown instruction files become the
#: harness system prompt; agent YAML compiles straight to a HarnessSpec.
IMPORT_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("AGENTS.md", "AGENTS.md", "prompt"),
    ("CLAUDE.md", "CLAUDE.md", "prompt"),
    (".claude/CLAUDE.md", "Claude Code project instructions", "prompt"),
    (".cursor/rules", "Cursor rules", "prompt-tree"),
    (".github/copilot-instructions.md", "Copilot instructions", "prompt"),
    ("agent.yaml", "SuperQode agent spec", "agent-yaml"),
    ("agent.yml", "SuperQode agent spec", "agent-yaml"),
)

#: Where a generated harness lands. Repository-owned and version-controllable.
HARNESS_OUTPUT_DIR = Path(".superqode") / "harnesses"


def _append_next_steps(text: Text, steps: tuple[tuple[str, str], ...]) -> None:
    """Append an aligned command/description block.

    Harness names vary in length, so the description column has to be measured
    rather than hard-coded or the two rows visibly disagree.
    """
    width = max(len(command) for command, _ in steps)
    for command, description in steps:
        text.append(f"      {command:<{width}}  ", style=f"bold {THEME['cyan']}")
        text.append(f"{description}\n", style=THEME["muted"])


def discover_importable(repo_root: Path | None = None) -> list[tuple[Path, str, str]]:
    """Return the agent-config files present in this repository."""
    root = repo_root or Path.cwd()
    found: list[tuple[Path, str, str]] = []
    for relative, label, kind in IMPORT_CANDIDATES:
        candidate = root / relative
        try:
            if candidate.is_dir():
                has_content = any(
                    child.is_file()
                    and child.suffix.lower() in {".md", ".mdc", ".txt"}
                    and child.stat().st_size > 0
                    for child in candidate.rglob("*")
                )
            else:
                has_content = candidate.exists() and candidate.stat().st_size > 0
            if has_content:
                found.append((candidate, label, kind))
        except OSError:
            continue
    return found


class BuildHarnessMixin:
    """Import, preset, and blank-spec entry points for harness authoring."""

    # --- import ---------------------------------------------------------------

    def _harness_import_picker(self, log: ConversationLog) -> None:
        """Offer to turn existing repository agent config into a HarnessSpec."""
        found = discover_importable()
        if not found:
            t = Text()
            t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append("Nothing to import yet\n", style=f"bold {THEME['text']}")
            t.append(
                "  Looked for AGENTS.md, CLAUDE.md, .claude/, .cursor/rules, "
                "Copilot instructions and agent.yaml.\n\n",
                style=THEME["muted"],
            )
            t.append("  Start from a preset instead: ", style=THEME["muted"])
            t.append(":connect build-preset", style=THEME["cyan"])
            t.append("\n  Or answer a few questions:  ", style=THEME["muted"])
            t.append(":harness wizard", style=THEME["cyan"])
            t.append("\n", style="")
            log.write(t)
            return

        self._harness_import_list = found
        self._awaiting_harness_import = True
        self._harness_import_index = 0
        self._render_harness_import_picker(log)

    def _render_harness_import_picker(
        self, log: ConversationLog, *, clear_log: bool = True
    ) -> None:
        found = getattr(self, "_harness_import_list", [])
        highlighted = getattr(self, "_harness_import_index", 0)

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Import what's already here\n", style=f"bold {THEME['text']}")
        t.append(
            "  Your existing agent config becomes a portable HarnessSpec you own.\n\n",
            style=THEME["muted"],
        )
        for index, (path, label, kind) in enumerate(found):
            num = index + 1
            if index == highlighted:
                t.append("  ▶ ", style=f"bold {THEME['success']}")
                t.append(f"[{num}] ", style=f"bold {THEME['success']}")
                t.append(label, style=f"bold {THEME['success']}")
                t.append("\n", style="")
            else:
                t.append(f"    [{num}] ", style=THEME["dim"])
                t.append(label, style=f"bold {THEME['text']}")
                t.append("\n", style="")
            if index == highlighted:
                detail = (
                    "compiles directly to a HarnessSpec"
                    if kind == "agent-yaml"
                    else "becomes the harness system prompt"
                )
                t.append(f"        {path}  ·  {detail}\n\n", style=THEME["muted"])

        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" import  ", style=THEME["dim"])
        t.append("Esc", style=THEME["purple"])
        t.append(" back\n", style=THEME["dim"])

        if clear_log:
            log.clear()
        log.write(t)

    def _import_harness_selection(self, index: int, log: ConversationLog) -> None:
        """Import the chosen config file and write a repository harness."""
        found = getattr(self, "_harness_import_list", [])
        if not (0 <= index < len(found)):
            return
        path, label, kind = found[index]
        self._awaiting_harness_import = False

        try:
            spec, note = self._build_spec_from_import(path, kind)
            output = HARNESS_OUTPUT_DIR / f"{spec.name}.yaml"
            from superqode.harness.loader import save_harness_spec

            if output.exists():
                log.add_error(
                    f"Refusing to overwrite existing harness: {output}. "
                    "Rename it or choose a different harness name first."
                )
                return
            written = save_harness_spec(spec, output)
        except Exception as exc:  # noqa: BLE001 - surface import failures in the TUI
            log.add_error(f"Could not import {label}: {exc}")
            return

        t = Text()
        t.append("\n  ✓ ", style=f"bold {THEME['success']}")
        t.append(f"Imported {label}\n\n", style=f"bold {THEME['text']}")
        t.append("    Harness   ", style=THEME["dim"])
        t.append(f"{spec.name}\n", style=THEME["text"])
        t.append("    Written   ", style=THEME["dim"])
        t.append(f"{written}\n", style=THEME["text"])
        t.append("    Source    ", style=THEME["dim"])
        t.append(f"{note}\n\n", style=THEME["muted"])
        t.append("    Next\n", style=f"bold {THEME['text']}")
        _append_next_steps(
            t,
            (
                (f":harness use {spec.name}", "make it the active harness"),
                (":harness doctor", "validate the spec"),
            ),
        )
        log.write(t)
        self._record_milestone("built_harness")

    def _build_spec_from_import(self, path: Path, kind: str):
        """Return (spec, human note) for one importable config file."""
        if kind == "agent-yaml":
            from superqode.harness.agent_importer import import_agent_yaml

            spec = import_agent_yaml(path)
            return spec, f"compiled from {path.name}"

        from superqode.harness.templates import get_harness_template

        if kind == "prompt-tree":
            parts = []
            for child in sorted(path.rglob("*")):
                if not child.is_file() or child.suffix.lower() not in {".md", ".mdc", ".txt"}:
                    continue
                content = child.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"## {child.relative_to(path)}\n\n{content}")
            instructions = "\n\n".join(parts)
        else:
            instructions = path.read_text(encoding="utf-8").strip()
        name = f"{Path.cwd().name or 'project'}-imported".lower().replace(" ", "-")
        spec = replace(get_harness_template("coding"), name=name)
        base = spec.agents[0] if spec.agents else None
        if base is not None:
            merged = "\n\n".join(part for part in (base.system_prompt, instructions) if part)
            spec = replace(spec, agents=(replace(base, system_prompt=merged), *spec.agents[1:]))
        # Root AGENTS.md and CLAUDE.md are loaded by the coding template by
        # default. Once their contents are embedded above, remove that source
        # from the context list so the model does not receive it twice.
        try:
            relative_source = str(path.relative_to(Path.cwd()))
        except ValueError:
            relative_source = str(path)
        if relative_source in spec.context.instruction_files:
            spec = replace(
                spec,
                context=replace(
                    spec.context,
                    instruction_files=tuple(
                        item for item in spec.context.instruction_files if item != relative_source
                    ),
                ),
            )
        metadata = dict(spec.metadata)
        metadata["imported_from"] = str(path)
        metadata["built_with"] = "connect import"
        return replace(spec, metadata=metadata), f"{len(instructions)} chars from {path.name}"

    # --- presets --------------------------------------------------------------

    def _show_harness_preset_picker(self, log: ConversationLog) -> None:
        """List built-in harness templates and clone the chosen one into the repo."""
        from superqode.harness.wizard import WIZARD_STARTERS

        self._harness_preset_list = list(WIZARD_STARTERS)
        self._awaiting_harness_preset = True
        self._harness_preset_index = 0
        self._render_harness_preset_picker(log)

    def _render_harness_preset_picker(
        self, log: ConversationLog, *, clear_log: bool = True
    ) -> None:
        presets = getattr(self, "_harness_preset_list", [])
        highlighted = getattr(self, "_harness_preset_index", 0)

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Start from a SuperQode preset\n", style=f"bold {THEME['text']}")
        t.append(
            "  Each preset is a tuned HarnessSpec. The copy lands in your repo, "
            "so you can read and change every policy in it.\n\n",
            style=THEME["muted"],
        )
        for index, (template_id, description) in enumerate(presets):
            num = index + 1
            if index == highlighted:
                t.append("  ▶ ", style=f"bold {THEME['success']}")
                t.append(f"[{num}] ", style=f"bold {THEME['success']}")
                t.append(template_id, style=f"bold {THEME['success']}")
                t.append("\n", style="")
            else:
                t.append(f"    [{num}] ", style=THEME["dim"])
                t.append(template_id, style=f"bold {THEME['text']}")
                t.append("\n", style="")
            if index == highlighted:
                t.append(f"        {description}\n\n", style=THEME["muted"])

        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" clone into repo  ", style=THEME["dim"])
        t.append("Esc", style=THEME["purple"])
        t.append(" back\n", style=THEME["dim"])

        if clear_log:
            log.clear()
        log.write(t)

    def _clone_harness_preset(self, index: int, log: ConversationLog) -> None:
        presets = getattr(self, "_harness_preset_list", [])
        if not (0 <= index < len(presets)):
            return
        template_id = presets[index][0]
        self._awaiting_harness_preset = False

        try:
            from superqode.harness.loader import save_harness_spec
            from superqode.harness.templates import get_harness_template

            spec = replace(get_harness_template(template_id), name=template_id)
            metadata = dict(spec.metadata)
            metadata["built_with"] = "connect preset"
            spec = replace(spec, metadata=metadata)
            output = HARNESS_OUTPUT_DIR / f"{template_id}.yaml"
            if output.exists():
                log.add_error(
                    f"Refusing to overwrite existing harness: {output}. "
                    "Rename it or remove it explicitly before cloning again."
                )
                return
            written = save_harness_spec(spec, output)
        except Exception as exc:  # noqa: BLE001 - surface template failures in the TUI
            log.add_error(f"Could not clone preset {template_id}: {exc}")
            return

        t = Text()
        t.append("\n  ✓ ", style=f"bold {THEME['success']}")
        t.append(f"Cloned {template_id}\n\n", style=f"bold {THEME['text']}")
        t.append("    Written   ", style=THEME["dim"])
        t.append(f"{written}\n", style=THEME["text"])
        t.append("    Tools     ", style=THEME["dim"])
        tool_count = sum(len(agent.tools) for agent in spec.agents)
        if tool_count:
            t.append(f"{tool_count}\n\n", style=THEME["text"])
        else:
            # A zero here is a deliberate choice for review and reasoning work,
            # and a surprise to anyone who picked it expecting to build.
            t.append("none\n", style=THEME["warning"])
            t.append(
                "              this harness can discuss code, not change it\n\n",
                style=THEME["muted"],
            )
        t.append("    Next\n", style=f"bold {THEME['text']}")
        _append_next_steps(
            t,
            (
                (f":harness use {template_id}", "make it the active harness"),
                (":harness doctor", "validate the spec"),
            ),
        )
        log.write(t)
        self._record_milestone("built_harness")

    # --- blank ----------------------------------------------------------------

    def _scaffold_blank_harness(self, log: ConversationLog) -> None:
        """Write the minimum valid spec for someone who knows the schema."""
        target = Path.cwd() / "harness.yaml"
        if target.exists():
            log.add_info(f"{target} already exists. Open it with :edit harness.yaml")
            return
        try:
            from superqode.harness.loader import save_harness_spec
            from superqode.harness.templates import get_harness_template

            spec = replace(get_harness_template("core"), name=Path.cwd().name or "harness")
            written = save_harness_spec(spec, target)
        except Exception as exc:  # noqa: BLE001 - surface scaffold failures in the TUI
            log.add_error(f"Could not write harness.yaml: {exc}")
            return

        t = Text()
        t.append("\n  ✓ ", style=f"bold {THEME['success']}")
        t.append("Wrote a starting harness\n\n", style=f"bold {THEME['text']}")
        t.append("    ", style="")
        t.append(str(written), style=THEME["text"])
        t.append("\n\n    Reference: ", style=THEME["dim"])
        t.append(":harness explain", style=f"bold {THEME['cyan']}")
        t.append("  every field and what it controls\n", style=THEME["muted"])
        log.write(t)
        self._record_milestone("built_harness")

    # --- navigation -----------------------------------------------------------

    def _move_build_index(self, attr: str, list_attr: str, delta: int, renderer) -> None:
        items = getattr(self, list_attr, [])
        current = getattr(self, attr, 0)
        target = max(0, min(len(items) - 1, current + delta))
        if target != current:
            setattr(self, attr, target)
            renderer(self.query_one("#log", ConversationLog), clear_log=True)

    def action_navigate_harness_import_up(self) -> None:
        if getattr(self, "_awaiting_harness_import", False):
            self._move_build_index(
                "_harness_import_index",
                "_harness_import_list",
                -1,
                self._render_harness_import_picker,
            )

    def action_navigate_harness_import_down(self) -> None:
        if getattr(self, "_awaiting_harness_import", False):
            self._move_build_index(
                "_harness_import_index",
                "_harness_import_list",
                1,
                self._render_harness_import_picker,
            )

    def action_select_harness_import(self) -> None:
        if not getattr(self, "_awaiting_harness_import", False):
            return
        log = self.query_one("#log", ConversationLog)
        log.clear()
        self._import_harness_selection(getattr(self, "_harness_import_index", 0), log)

    def action_navigate_harness_preset_up(self) -> None:
        if getattr(self, "_awaiting_harness_preset", False):
            self._move_build_index(
                "_harness_preset_index",
                "_harness_preset_list",
                -1,
                self._render_harness_preset_picker,
            )

    def action_navigate_harness_preset_down(self) -> None:
        if getattr(self, "_awaiting_harness_preset", False):
            self._move_build_index(
                "_harness_preset_index",
                "_harness_preset_list",
                1,
                self._render_harness_preset_picker,
            )

    def action_select_harness_preset(self) -> None:
        if not getattr(self, "_awaiting_harness_preset", False):
            return
        log = self.query_one("#log", ConversationLog)
        log.clear()
        self._clone_harness_preset(getattr(self, "_harness_preset_index", 0), log)


__all__ = [
    "HARNESS_OUTPUT_DIR",
    "IMPORT_CANDIDATES",
    "BuildHarnessMixin",
    "discover_importable",
]
