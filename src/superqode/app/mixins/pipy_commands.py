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
            await self._pipy_resume(session, rest, log)
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

    async def _pipy_resume(self, session: Any, rest: str, log) -> None:
        """List or reopen a prior PiPy session into the live conversation."""
        records = session.list_sessions()
        if not records:
            log.add_info("No previous PiPy sessions for this directory.")
            return

        choice = (rest or "").strip()
        if not choice:
            for index, record in enumerate(records[:20], start=1):
                name = ""
                try:
                    name = str(getattr(record.metadata, "name", "") or "")
                except Exception:
                    name = ""
                label = f"{record.path.name}" + (f"  ({name})" if name else "")
                log.add_info(f"[{index:2}] {label}")
            log.add_info("Reopen with :pipy resume <n> or :pipy resume <path>.")
            log.add_info("Or use :sessions switch after the session is registered.")
            return

        selected = self._resolve_pipy_resume_target(records, choice)
        if selected is None:
            log.add_error(f"PiPy session not found: {choice}")
            log.add_info("Use :pipy resume to list candidates for this directory.")
            return

        pure = getattr(self, "_pure_mode", None)
        if pure is None:
            log.add_error("No active Pure Mode session.")
            return

        session_id = f"pipy-{selected.id}"
        pure._harness_session = None
        pure._harness_kernel = None
        pure._harness_session_id = session_id
        working_directory = Path(
            str(getattr(getattr(pure, "session", None), "working_directory", "") or Path.cwd())
        )
        try:
            from superqode.harness.pipy_adapter import _record_session_path
            from superqode.session.harness_bridge import upsert_harness_session_meta

            _record_session_path(session_id, selected.path)
            title = ""
            try:
                title = str(getattr(selected.metadata, "name", "") or "") or selected.path.name
            except Exception:
                title = selected.path.name
            upsert_harness_session_meta(
                session_id,
                provider=str(getattr(getattr(pure, "session", None), "provider", "") or ""),
                model=str(getattr(getattr(pure, "session", None), "model", "") or ""),
                harness_id="pipy",
                harness_source="pipy",
                harness_display="PiPy",
                title=title,
                backend_session_path=str(selected.path),
                working_directory=working_directory,
            )
        except Exception as error:  # noqa: BLE001
            log.add_error(f"Could not register PiPy session: {error}")
            return

        # Reopen through the adapter so the next prompt continues this file.
        from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter
        from superqode.harness.protocol import HarnessSessionRef

        adapter = PiPyHarnessProtocolAdapter()
        await adapter.resume(
            HarnessSessionRef(
                session_id=session_id,
                harness_id="pipy",
                external_session_id=selected.id,
                metadata={
                    "working_directory": str(working_directory),
                    "session_path": str(selected.path),
                    "provider": str(getattr(getattr(pure, "session", None), "provider", "") or ""),
                    "model": str(getattr(getattr(pure, "session", None), "model", "") or ""),
                },
            )
        )
        from superqode.session.harness_bridge import format_session_label
        from superqode.agent.session_manager import SessionManager

        meta = SessionManager(".superqode/sessions").get_session_info(session_id)
        label = format_session_label(meta) if meta else session_id
        log.add_success(f"Reopened {label}")
        log.add_info(f"id {session_id} · path {selected.path.name}")
        log.add_info("Send a message to continue this transcript. It also appears in :sessions.")

    @staticmethod
    def _resolve_pipy_resume_target(records: list[Any], choice: str) -> Any | None:
        """Resolve :pipy resume <n|path|id> against listed SessionRecords."""
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(records):
                return records[index]
            return None

        lowered = choice.lower()
        path_choice = Path(choice).expanduser()
        matches = []
        for record in records:
            path = Path(record.path)
            if path == path_choice or path.name == choice or str(path) == choice:
                return record
            if record.id.lower() == lowered or path.name.lower().startswith(lowered):
                matches.append(record)
        if len(matches) == 1:
            return matches[0]
        return None


__all__ = ["PiPyCommandMixin"]
