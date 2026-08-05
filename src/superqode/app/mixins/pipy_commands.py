"""The ``:pipy`` command surface, aliased as ``:pi``.

Commands are generated from :data:`superqode.pipy.coding_session.SLASH_COMMANDS`
so the catalogue, help text and completions cannot drift apart. Each command
opens the session through the protocol adapter's ``resume``, the same path a
turn takes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from superqode.app.constants import THEME


class PiPyCommandMixin:
    """``:pipy`` and its subcommands."""

    def _pipy_cmd(self, args: str, log) -> None:
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "help"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub in {"help", "?"}:
            self._show_pipy_help(log)
            return

        from superqode.pipy.coding_session import SLASH_COMMANDS

        known = {command.name: command for command in SLASH_COMMANDS}
        command = known.get(sub)
        if command is None:
            log.add_error(f"Unknown PiPy command: {sub}")
            log.add_info("Use :pipy help to see the complete command catalog.")
            return

        if command.takes_argument is False and rest:
            log.add_error(f":pipy {sub} takes no argument.")
            return

        if not self._pipy_is_active():
            log.add_error("PiPy is not the active harness.")
            log.add_info("Use :harness pipy, or :connect and pick PiPy, then try again.")
            return

        self.run_worker(self._pipy_run(sub, rest, log), exclusive=False)

    def _show_pipy_help(self, log) -> None:
        from rich.text import Text

        from superqode.pipy.coding_session import SLASH_COMMANDS

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("PiPy\n", style=f"bold {THEME['text']}")
        t.append(
            "  Session commands for the PiPy harness. Each acts on the session\n"
            "  this conversation is using. Also available as :pi.\n\n",
            style=THEME["muted"],
        )
        width = max(len(command.name) for command in SLASH_COMMANDS)
        for command in SLASH_COMMANDS:
            t.append(f"    :pipy {command.name:<{width}}  ", style=THEME["cyan"])
            t.append(f"{command.summary}\n", style=THEME["muted"])
        t.append(f"    :pipy {'help':<{width}}  ", style=THEME["cyan"])
        t.append("Show this catalog\n", style=THEME["muted"])
        t.append(
            "\n  PiPy runs tools with the permissions of the process. There is no\n"
            "  approval prompt or sandbox on this harness.\n",
            style=THEME["dim"],
        )
        log.write(t)

    def _pipy_is_active(self) -> bool:
        pure = getattr(self, "_pure_mode", None)
        spec = getattr(pure, "_harness_spec", None)
        backend = getattr(getattr(spec, "runtime", None), "backend", "")
        return str(backend or "").strip().lower() == "pipy"

    async def _pipy_open_session(self) -> Any:
        """Reopen the session this conversation is using."""
        from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter
        from superqode.harness.protocol import HarnessSessionRef

        pure = getattr(self, "_pure_mode", None)
        session_id = str(getattr(pure, "_harness_session_id", "") or "") or "pipy-session"
        working_directory = Path(
            str(getattr(getattr(pure, "session", None), "working_directory", "") or Path.cwd())
        )
        adapter = PiPyHarnessProtocolAdapter()
        ref = await adapter.resume(
            HarnessSessionRef(
                session_id=session_id,
                harness_id="pipy",
                external_session_id=session_id,
                metadata={"working_directory": str(working_directory)},
            )
        )
        return adapter, ref

    async def _pipy_run(self, sub: str, rest: str, log) -> None:
        try:
            adapter, ref = await self._pipy_open_session()
            session = adapter._sessions[ref.session_id]
            await self._pipy_dispatch(session, sub, rest, log)
        except Exception as error:  # noqa: BLE001 - surfaced to the user
            log.add_error(f":pipy {sub} failed: {error}")

    async def _pipy_dispatch(self, session: Any, sub: str, rest: str, log) -> None:
        if sub == "session":
            info = await session.info()
            log.add_info(f"id       {info.id}")
            log.add_info(f"path     {session.session_path}")
            log.add_info(f"messages {getattr(info, 'message_count', '?')}")
            if getattr(info, "name", ""):
                log.add_info(f"name     {info.name}")
            return

        if sub == "compact":
            result = await session.compact(rest or None)
            if result is None:
                log.add_info("Nothing old enough to be worth summarising yet.")
            else:
                log.add_success("Context compacted. The full history stays in the tree.")
            return

        if sub == "tree":
            leaf = await session.navigate_tree(rest or None)
            log.add_success(f"Moved to {leaf}" if leaf else "Already at the requested point.")
            return

        if sub == "fork":
            forked = await session.fork(up_to_entry_id=rest or None)
            log.add_success(f"Forked into {forked.session_path}")
            log.add_info("The source session is untouched.")
            return

        if sub == "new":
            fresh = await session.new()
            log.add_success(f"Started {fresh.session_path}")
            return

        if sub == "resume":
            records = session.list_sessions()
            if not records:
                log.add_info("No previous PiPy sessions for this directory.")
                return
            for index, record in enumerate(records[:20], start=1):
                log.add_info(f"[{index:2}] {record.path.name}")
            log.add_info("Reopen one with :pipy tree, or start fresh with :pipy new.")
            return

        if sub == "name":
            if not rest:
                log.add_error(":pipy name needs a name.")
                return
            await session.rename(rest)
            log.add_success(f"Session named {rest}.")
            return

        if sub == "model":
            if not rest:
                log.add_info(f"Model {session.harness.get_model().id}")
                return
            from superqode.pipy.ai.models import resolve_model

            await session.set_model(resolve_model(rest))
            log.add_success(f"PiPy will use {rest} from the next turn.")
            return

        if sub == "export":
            markdown = await session.export_markdown()
            # Beside the session, never in the working directory.
            target = Path(session.session_path).with_suffix(".md")
            target.write_text(markdown, encoding="utf-8")
            log.add_success(f"Exported to {target}")
            return

        if sub == "skill":
            if not rest:
                names = ", ".join(skill.name for skill in session.skills()) or "none found"
                log.add_info(f"Skills: {names}")
                return
            name, _, extra = rest.partition(" ")
            await session.invoke_skill(name, extra.strip() or None)
            log.add_success(f"Invoked skill {name}.")
            return

        if sub == "prompt":
            if not rest:
                names = (
                    ", ".join(template.name for template in session.prompt_templates())
                    or "none found"
                )
                log.add_info(f"Prompt templates: {names}")
                return
            name, _, extra = rest.partition(" ")
            await session.invoke_prompt_template(name, tuple(extra.split()) if extra else ())
            log.add_success(f"Ran prompt template {name}.")
            return

        log.add_error(f":pipy {sub} is declared but not wired.")


__all__ = ["PiPyCommandMixin"]
