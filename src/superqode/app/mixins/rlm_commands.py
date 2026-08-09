"""TUI command surface for the native RLM harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from superqode.app.constants import THEME

_COMMANDS = (
    ("session", "Show the native RLM session and Python continuity"),
    ("policy", "Show the persistent goal and autonomous completion policy"),
    ("goal", "Set a persistent goal: goal <text>|off"),
    ("autonomous", "Enable completion gates: autonomous [gate]|off"),
    ("agents", "List live recursive child agents"),
    ("send", "Queue a follow-up for a child: send <id> <message>"),
    ("steer", "Steer a running child: steer <id> <instruction>"),
    ("cancel", "Cancel a running child: cancel <id>"),
    ("compact", "Compact older conversation context"),
    ("tree", "Move to another session-tree entry"),
    ("fork", "Fork the current session branch"),
    ("export", "Export the current session branch as Markdown"),
)


class RLMCommandMixin:
    """Implement ``:rlm`` without introducing a second runtime connection."""

    def _rlm_cmd(self, args: str, log) -> None:
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "help"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub in {"help", "?"}:
            self._show_rlm_help(log)
            return
        if sub not in {name for name, _ in _COMMANDS}:
            log.add_error(f"Unknown RLM command: {sub}")
            log.add_info("Use :rlm help to see the native RLM command catalog.")
            return
        if not self._rlm_is_active():
            log.add_error("RLM is not the active harness.")
            log.add_info("Use :harness switch rlm, then try again.")
            return
        getattr(self, "run_worker")(self._rlm_run(sub, rest, log), exclusive=False)

    def _show_rlm_help(self, log) -> None:
        from rich.text import Text

        text = Text()
        text.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        text.append("RLM\n", style=f"bold {THEME['text']}")
        text.append(
            "  Native recursive coding with one persistent Python tool.\n\n",
            style=THEME["muted"],
        )
        width = max(len(name) for name, _ in _COMMANDS)
        for name, summary in _COMMANDS:
            text.append(f"    :rlm {name:<{width}}  ", style=THEME["cyan"])
            text.append(f"{summary}\n", style=THEME["muted"])
        text.append(
            "\n  The initial Python kernel has the permissions of the SuperQode process.\n",
            style=THEME["dim"],
        )
        log.write(text)

    def _rlm_is_active(self) -> bool:
        pure = getattr(self, "_pure_mode", None)
        spec = getattr(pure, "_harness_spec", None)
        backend = getattr(getattr(spec, "runtime", None), "backend", "")
        return str(backend or "").strip().lower() == "rlm"

    async def _rlm_open_session(self) -> tuple[Any, Any]:
        from superqode.harness.protocol import HarnessSessionRef
        from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter

        pure = getattr(self, "_pure_mode", None)
        session_id = str(getattr(pure, "_harness_session_id", "") or "") or "rlm-session"
        working_directory = Path(
            str(getattr(getattr(pure, "session", None), "working_directory", "") or Path.cwd())
        )
        adapter = RLMHarnessProtocolAdapter()
        ref = await adapter.resume(
            HarnessSessionRef(
                session_id=session_id,
                harness_id="rlm",
                external_session_id=session_id,
                metadata={"working_directory": str(working_directory)},
            )
        )
        return adapter, ref

    async def _rlm_run(self, sub: str, rest: str, log) -> None:
        try:
            adapter, ref = await self._rlm_open_session()
            session = adapter._sessions[ref.session_id]
            await self._rlm_dispatch(session, sub, rest, log)
        except Exception as error:  # noqa: BLE001 - user-visible TUI command failure
            log.add_error(f":rlm {sub} failed: {error}")

    async def _rlm_dispatch(self, session: Any, sub: str, rest: str, log) -> None:
        from superqode.rlm.coding_session import supervisor_for_session

        supervisor = supervisor_for_session(session.session_path)
        if sub == "session":
            info = await session.info()
            log.add_info(f"id       {info.id}")
            log.add_info(f"path     {session.session_path}")
            log.add_info(f"messages {info.message_count}")
            log.add_info("tools    python (serializable state checkpointed)")
            log.add_info("workers  detached Python processes with journal reattachment")
            return
        if sub == "policy":
            policy = session.policy
            log.add_info(f"goal       {policy.goal or 'off'}")
            log.add_info(f"autonomous {'on' if policy.autonomous else 'off'}")
            log.add_info(f"rounds     {policy.max_rounds}")
            if policy.gates:
                for index, gate in enumerate(policy.gates, 1):
                    log.add_info(f"gate {index:<2}    {gate}")
            else:
                log.add_info("gates      none")
            return
        if sub == "goal":
            raw = rest.strip()
            if not raw:
                log.add_info(f"RLM goal: {session.policy.goal or 'off'}")
                return
            goal = "" if raw.lower() in {"off", "clear", "none"} else raw.strip("\"'")
            session.update_policy(goal=goal)
            if goal:
                log.add_success(f"RLM goal set: {goal}")
            else:
                log.add_success("RLM goal cleared.")
            return
        if sub == "autonomous":
            raw = rest.strip()
            policy = session.policy
            if not raw:
                state = "on" if policy.autonomous else "off"
                log.add_info(f"RLM autonomous: {state} ({len(policy.gates)} gate(s))")
                return
            if raw.lower() in {"off", "clear", "none"}:
                session.update_policy(autonomous=False, gates=())
                log.add_success("RLM autonomous mode and gates cleared.")
                return
            if raw.lower() == "on":
                session.update_policy(autonomous=True)
                log.add_success("RLM autonomous mode enabled.")
                return
            gates = (*policy.gates, raw.strip("\"'"))
            session.update_policy(autonomous=True, gates=gates)
            log.add_success(f"RLM autonomous gate added: {gates[-1]}")
            return
        if sub == "agents":
            records = supervisor.snapshots() if supervisor is not None else []
            if not records:
                log.add_info("No recursive child agents in this session.")
                return
            for record in records:
                worker = f" worker={record['worker_pid']}" if record.get("worker_pid") else ""
                log.add_info(
                    f"{record['id']}  {record['status']:<9} parent={record['parent_id']}  "
                    f"{record['prompt']}{worker}"
                )
            return
        if sub in {"send", "steer"}:
            agent_id, separator, message = rest.partition(" ")
            if not separator or not message.strip():
                raise ValueError(f":rlm {sub} needs <agent-id> <message>")
            if supervisor is None:
                raise RuntimeError("No active RLM supervisor")
            operation = supervisor.send if sub == "send" else supervisor.steer
            await operation(agent_id, message.strip())
            log.add_success(f"{sub.title()} delivered to {agent_id}.")
            return
        if sub == "cancel":
            if not rest:
                raise ValueError(":rlm cancel needs an agent id")
            if supervisor is None:
                raise RuntimeError("No active RLM supervisor")
            await supervisor.cancel(rest)
            log.add_success(f"Cancelled {rest}.")
            return
        if sub == "compact":
            result = await session.compact(rest or None)
            log.add_info(
                "Nothing old enough to compact." if result is None else "Context compacted."
            )
            return
        if sub == "tree":
            leaf = await session.navigate_tree(rest or None)
            log.add_success(f"Moved to {leaf}" if leaf else "Already at the requested point.")
            return
        if sub == "fork":
            forked = await session.fork(up_to_entry_id=rest or None)
            log.add_success(f"Forked into {forked.session_path}")
            return
        if sub == "export":
            target = Path(session.session_path).with_suffix(".md")
            target.write_text(await session.export_markdown(), encoding="utf-8")
            log.add_success(f"Exported to {target}")


__all__ = ["RLMCommandMixin"]
