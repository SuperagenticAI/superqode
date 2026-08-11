"""TUI command surface for the native RLM harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from superqode.app.constants import THEME

_COMMANDS = (
    ("status", "Show the resident root worker and active turn"),
    ("attach", "Attach to the active resident RLM turn"),
    ("detach", "Leave the worker running without cancelling it"),
    ("stop", "Stop the resident root worker"),
    ("session", "Show the native RLM session and Python continuity"),
    ("policy", "Show the persistent goal and autonomous completion policy"),
    ("goal", "Set a persistent goal: goal <text>|off"),
    ("autonomous", "Enable completion gates: autonomous [gate]|off"),
    ("sandbox", "Show the execution boundary: sandbox [doctor]"),
    ("usage", "Show subcall, child-agent and context accounting"),
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
            "\n  The Python kernel uses the sandbox profile selected by the active harness spec.\n",
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
        metadata: dict[str, Any] = {"working_directory": str(working_directory)}
        spec = getattr(pure, "_harness_spec", None)
        provider = str(getattr(getattr(pure, "session", None), "provider", "") or "")
        model = str(getattr(getattr(pure, "session", None), "model", "") or "")
        metadata.update({"provider": provider, "model": model})
        if spec is not None:
            from superqode.rlm.sandbox import RLMSandboxConfig

            # Resolved from the active spec so `:rlm sandbox` reports the same
            # boundary the turn path uses, rather than a default of its own.
            metadata["rlm_sandbox"] = RLMSandboxConfig.from_config(
                getattr(getattr(spec, "runtime", None), "config", None) or {},
                execution_policy=getattr(spec, "execution_policy", None),
            ).to_dict()
            metadata["rlm_config"] = dict(
                getattr(getattr(spec, "runtime", None), "config", None) or {}
            )
        adapter = RLMHarnessProtocolAdapter()
        ref = await adapter.resume(
            HarnessSessionRef(
                session_id=session_id,
                harness_id="rlm",
                external_session_id=session_id,
                metadata=metadata,
            )
        )
        return adapter, ref

    async def _rlm_run(self, sub: str, rest: str, log) -> None:
        try:
            adapter, ref = await self._rlm_open_session()
            if getattr(adapter, "_resident", False):
                await self._rlm_resident_dispatch(adapter, ref, sub, rest, log)
                return
            session = adapter._sessions[ref.session_id]
            await self._rlm_dispatch(session, sub, rest, log)
        except Exception as error:  # noqa: BLE001 - user-visible TUI command failure
            log.add_error(f":rlm {sub} failed: {error}")

    async def _rlm_resident_dispatch(self, adapter, ref, sub: str, rest: str, log) -> None:
        client = await adapter._runtime(ref)
        status = client.status()
        if sub == "status":
            log.add_info(f"state    {status.state}")
            log.add_info(
                f"worker   {status.pid or 'not running'}"
                + (f" generation={status.generation[:12]}" if status.generation else "")
            )
            log.add_info(f"active   {status.active_command or 'none'}")
            log.add_info(f"session  {status.external_session_id or ref.session_id}")
            log.add_info(f"path     {status.session_path or 'initialising'}")
            return
        if sub == "detach":
            log.add_success("Detached. The resident RLM worker will continue running.")
            return
        if sub == "stop":
            await client.control("stop")
            log.add_success("Stop requested for the resident RLM worker.")
            return
        if sub == "attach":
            if not status.active_command:
                log.add_info("No active RLM turn to attach to.")
                return
            log.add_info(f"Attached to {status.active_command}.")
            async for event in client.events(status.active_command):
                data = event.data
                if event.type in {"model_delta", "message.delta"}:
                    text = str(data.get("text") or "")
                    if text:
                        log.add_info(text)
                elif event.type in {"tool_call", "tool.requested"}:
                    log.add_info(
                        f"tool     {data.get('tool_name') or data.get('name') or 'python'}"
                    )
                elif event.type in {"error", "run.failed"}:
                    log.add_error(str(data.get("error") or "RLM turn failed"))
            log.add_success("Resident RLM turn completed.")
            return
        events = await client.request("admin", {"command": sub, "argument": rest})
        result = next((event.data for event in events if event.type == "runtime.result"), {})
        for line in result.get("lines") or ():
            level = str(line.get("level") or "info")
            message = str(line.get("text") or "")
            writer = getattr(log, f"add_{level}", log.add_info)
            writer(message)

    async def _rlm_dispatch(self, session: Any, sub: str, rest: str, log) -> None:
        from superqode.rlm.coding_session import supervisor_for_session

        supervisor = supervisor_for_session(session.session_path)
        if sub == "sandbox":
            self._rlm_sandbox(session, rest, log)
            return
        if sub == "usage":
            self._rlm_usage(session, supervisor, log)
            return
        if sub == "session":
            info = await session.info()
            log.add_info(f"id       {info.id}")
            log.add_info(f"path     {session.session_path}")
            log.add_info(f"messages {info.message_count}")
            log.add_info("tools    python (serializable state checkpointed)")
            log.add_info("workers  detached Python processes with journal reattachment")
            log.add_info(f"sandbox  {self._rlm_sandbox_config(session).backend} (:rlm sandbox)")
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

    @staticmethod
    def _rlm_usage(session: Any, supervisor: Any, log) -> None:
        """Report the costs the RLM layer owns.

        Root-turn usage is the harness's to report and is not duplicated here;
        what this adds is the recursive spend, which nothing else accounts for.
        """
        subcalls = getattr(session, "subcall_usage", None)
        if subcalls:
            usage = subcalls["usage"]
            limit = subcalls["policy"]["max_calls"]
            log.add_info(
                f"subcalls   {usage['calls']} of {limit} calls, "
                f"{usage['total_tokens']} tokens, ${usage['cost_usd']:.4f}"
                + (f", {usage['failures']} failed" if usage["failures"] else "")
            )
        else:
            log.add_info("subcalls   none yet")

        snapshots = supervisor.snapshots() if supervisor is not None else []
        if snapshots:
            tokens = sum(
                int((item.get("usage") or {}).get("total_tokens", 0)) for item in snapshots
            )
            cost = sum(float((item.get("usage") or {}).get("cost_usd", 0.0)) for item in snapshots)
            statuses: dict[str, int] = {}
            for item in snapshots:
                statuses[item["status"]] = statuses.get(item["status"], 0) + 1
            summary = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items()))
            log.add_info(f"children   {len(snapshots)} ({summary}), {tokens} tokens, ${cost:.4f}")
        else:
            log.add_info("children   none")

        try:
            from superqode.rlm.context import RLMContext

            context_policy = getattr(getattr(session, "options", None), "context_policy", None)
            stats = RLMContext(session.cwd, policy=context_policy).stats()
            log.add_info(f"context    {stats['files']} files, {stats['bytes']} bytes in scope")
        except Exception as error:  # noqa: BLE001 - accounting must not break the command
            log.add_info(f"context    unavailable: {error}")
        log.add_info("Root conversation usage is reported by the harness, not here.")

    @staticmethod
    def _rlm_sandbox_config(session: Any):
        from superqode.rlm.sandbox import RLMSandboxConfig

        return getattr(getattr(session, "options", None), "sandbox", None) or RLMSandboxConfig()

    def _rlm_sandbox(self, session: Any, rest: str, log) -> None:
        """Report the boundary. The profile itself comes from the harness spec.

        Nothing here changes it; the profile comes from the active harness
        specification and takes effect when the session connects.
        """
        from superqode.rlm.sandbox import docker_available

        config = self._rlm_sandbox_config(session)
        argument = rest.strip().lower()
        if argument in {"", "status"}:
            for line in config.describe():
                log.add_info(line)
            return
        if argument == "doctor":
            log.add_info(f"active      {config.backend}")
            available, detail = docker_available()
            if available:
                log.add_success(f"docker      {detail}")
            else:
                log.add_info(f"docker      unavailable: {detail}")
            log.add_info("profiles    host, docker, monty")
            log.add_info("Docker networking is disabled unless allow_network is enabled.")
            return
        log.add_error(f"The sandbox profile is not set from :rlm sandbox ({argument!r} ignored).")
        log.add_info("Set runtime.config.sandbox in the harness spec, then reconnect.")


__all__ = ["RLMCommandMixin"]
