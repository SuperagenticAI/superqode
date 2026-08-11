"""Internal resident worker for one native-RLM root session."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from superqode.harness.protocol import HarnessMessage, HarnessSessionRef
from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter

from .root_runtime import (
    ROOT_RUNTIME_PROTOCOL,
    _atomic_json,
    _read_json,
    _read_jsonl_since,
    append_runtime_event,
    complete_runtime_command,
)


class ResidentRootWorker:
    def __init__(
        self,
        manifest_path: Path,
        generation: str,
        *,
        adapter: Any | None = None,
    ) -> None:
        self.manifest_path = manifest_path
        self.directory = manifest_path.parent
        self.generation = generation
        self.manifest = self._manifest()
        self.commands_path = self.directory / "commands.jsonl"
        self.controls_path = self.directory / "controls.jsonl"
        self.events_path = self.directory / "events.jsonl"
        self.state_path = self.directory / "state.json"
        self._command_offset = 0
        self._control_offset = 0
        self._active_command = ""
        self._adapter = adapter or RLMHarnessProtocolAdapter(resident=False)
        self._ref: HarnessSessionRef | None = None
        self._stopping = False

    def _manifest(self) -> dict[str, Any]:
        value = _read_json(self.manifest_path)
        if value is None:
            raise RuntimeError(f"Invalid RLM root manifest: {self.manifest_path}")
        if value.get("protocol") != ROOT_RUNTIME_PROTOCOL:
            raise RuntimeError(
                f"Unsupported RLM root protocol {value.get('protocol')!r}; "
                f"expected {ROOT_RUNTIME_PROTOCOL}"
            )
        return value

    async def run(self) -> int:
        heartbeat: asyncio.Task[None] | None = None
        controls: asyncio.Task[None] | None = None
        try:
            await self._open()
            self._write_state("ready")
            heartbeat = asyncio.create_task(self._heartbeat())
            controls = asyncio.create_task(self._watch_controls())
            while not self._stopping:
                commands, self._command_offset = _read_jsonl_since(
                    self.commands_path, self._command_offset
                )
                for command in commands:
                    if command.get("generation") != self.generation:
                        continue
                    await self._execute(command)
                    if self._stopping:
                        break
                await asyncio.sleep(0.05)
            self._write_state("stopped")
            return 0
        except BaseException as error:  # noqa: BLE001 - worker must publish every failure
            self._write_state("failed", error=f"{type(error).__name__}: {error}")
            return 1
        finally:
            tasks = [task for task in (heartbeat, controls) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _open(self) -> None:
        metadata = dict(self.manifest.get("metadata") or {})
        limits = dict(metadata.get("rlm_config") or {})
        # The resident root owns every descendant.  Separate per-child workers
        # would create separate supervisors and make tree-wide limits advisory.
        limits["durable_children"] = False
        metadata["rlm_config"] = limits
        metadata.update(
            {
                "provider": str(self.manifest.get("provider") or ""),
                "model": str(self.manifest.get("model") or ""),
                "working_directory": str(self.manifest.get("working_directory") or Path.cwd()),
            }
        )
        self._ref = await self._adapter.resume(
            HarnessSessionRef(
                session_id=str(self.manifest["session_id"]),
                harness_id="rlm",
                external_session_id=str(self.manifest.get("external_session_id") or "") or None,
                metadata=metadata,
            )
        )

    async def _execute(self, command: Mapping[str, Any]) -> None:
        command_id = str(command.get("id") or "")
        operation = str(command.get("operation") or "")
        payload = command.get("payload")
        body = dict(payload) if isinstance(payload, dict) else {}
        if not command_id:
            return
        self._active_command = command_id
        self._write_state("running")
        try:
            if operation == "send":
                assert self._ref is not None
                message = HarnessMessage(
                    "user",
                    str(body.get("content") or ""),
                    message_id=str(body.get("message_id") or command_id),
                )
                async for event in self._adapter.send(self._ref, message):
                    append_runtime_event(self.events_path, command_id, event)
            elif operation == "checkpoint":
                assert self._ref is not None
                checkpoint = await self._adapter.checkpoint(self._ref)
                from superqode.harness.events import HarnessEvent

                append_runtime_event(
                    self.events_path,
                    command_id,
                    HarnessEvent(type="checkpoint.created", data=checkpoint.to_dict()),
                )
            elif operation == "admin":
                from superqode.harness.events import HarnessEvent

                result = await self._admin(
                    str(body.get("command") or "status"),
                    str(body.get("argument") or ""),
                )
                append_runtime_event(
                    self.events_path,
                    command_id,
                    HarnessEvent(type="runtime.result", data=result),
                )
            elif operation == "stop":
                self._stopping = True
            else:
                raise ValueError(f"Unknown resident RLM operation: {operation!r}")
        except asyncio.CancelledError:
            complete_runtime_command(self.events_path, command_id, status="cancelled")
            raise
        except Exception as error:  # noqa: BLE001 - error crosses the process boundary
            complete_runtime_command(
                self.events_path,
                command_id,
                status="failed",
                error=f"{type(error).__name__}: {error}",
            )
        else:
            complete_runtime_command(self.events_path, command_id)
        finally:
            self._active_command = ""
            if not self._stopping:
                self._write_state("ready")

    def _session(self) -> Any:
        ref = self._ref
        if ref is None:
            raise RuntimeError("Resident RLM session is not open")
        return self._adapter._sessions[ref.session_id]

    async def _admin(self, command: str, argument: str) -> dict[str, Any]:
        """Execute an operational command where authoritative state lives."""
        from superqode.rlm.coding_session import supervisor_for_session

        session = self._session()
        supervisor = supervisor_for_session(session.session_path)
        lines: list[dict[str, str]] = []

        def emit(text: str, level: str = "info") -> None:
            lines.append({"level": level, "text": text})

        if command in {"session", "status"}:
            info = await session.info()
            sandbox = session.options.sandbox
            emit("state    resident")
            emit(f"worker   {os.getpid()} generation={self.generation[:12]}")
            emit(f"id       {info.id}")
            emit(f"path     {session.session_path}")
            emit(f"messages {info.message_count}")
            emit("tools    python (serializable state checkpointed)")
            emit("tree     one resident root worker owns every descendant")
            emit(f"sandbox  {getattr(sandbox, 'backend', 'host')}")
        elif command == "policy":
            policy = session.policy
            emit(f"goal       {policy.goal or 'off'}")
            emit(f"autonomous {'on' if policy.autonomous else 'off'}")
            emit(f"rounds     {policy.max_rounds}")
            if policy.gates:
                for index, gate in enumerate(policy.gates, 1):
                    emit(f"gate {index:<2}    {gate}")
            else:
                emit("gates      none")
        elif command == "goal":
            raw = argument.strip()
            if not raw:
                emit(f"RLM goal: {session.policy.goal or 'off'}")
            else:
                goal = "" if raw.lower() in {"off", "clear", "none"} else raw.strip("\"'")
                session.update_policy(goal=goal)
                emit(f"RLM goal set: {goal}" if goal else "RLM goal cleared.", "success")
        elif command == "autonomous":
            raw = argument.strip()
            policy = session.policy
            if not raw:
                emit(
                    f"RLM autonomous: {'on' if policy.autonomous else 'off'} "
                    f"({len(policy.gates)} gate(s))"
                )
            elif raw.lower() in {"off", "clear", "none"}:
                session.update_policy(autonomous=False, gates=())
                emit("RLM autonomous mode and gates cleared.", "success")
            elif raw.lower() == "on":
                session.update_policy(autonomous=True)
                emit("RLM autonomous mode enabled.", "success")
            else:
                gates = (*policy.gates, raw.strip("\"'"))
                session.update_policy(autonomous=True, gates=gates)
                emit(f"RLM autonomous gate added: {gates[-1]}", "success")
        elif command == "agents":
            records = supervisor.snapshots() if supervisor is not None else []
            if not records:
                emit("No recursive child agents in this session.")
            for record in records:
                emit(
                    f"{record['id']}  {record['status']:<9} "
                    f"parent={record['parent_id']}  {record['prompt']}"
                )
        elif command in {"send", "steer"}:
            agent_id, separator, message = argument.partition(" ")
            if not separator or not message.strip():
                raise ValueError(f":rlm {command} needs <agent-id> <message>")
            if supervisor is None:
                raise RuntimeError("No active RLM supervisor")
            operation = supervisor.send if command == "send" else supervisor.steer
            await operation(agent_id, message.strip())
            emit(f"{command.title()} delivered to {agent_id}.", "success")
        elif command == "cancel":
            if not argument.strip():
                raise ValueError(":rlm cancel needs an agent id")
            if supervisor is None:
                raise RuntimeError("No active RLM supervisor")
            await supervisor.cancel(argument.strip())
            emit(f"Cancelled {argument.strip()}.", "success")
        elif command == "compact":
            result = await session.compact(argument or None)
            emit("Nothing old enough to compact." if result is None else "Context compacted.")
        elif command == "tree":
            leaf = await session.navigate_tree(argument or None)
            emit(
                f"Moved to {leaf}" if leaf else "Already at the requested point.",
                "success",
            )
        elif command == "fork":
            forked = await session.fork(up_to_entry_id=argument or None)
            emit(f"Forked into {forked.session_path}", "success")
        elif command == "export":
            target = Path(session.session_path).with_suffix(".md")
            target.write_text(await session.export_markdown(), encoding="utf-8")
            emit(f"Exported to {target}", "success")
        elif command == "usage":
            subcalls = session.subcall_usage
            if subcalls:
                usage = subcalls["usage"]
                limit = subcalls["policy"]["max_calls"]
                emit(
                    f"subcalls   {usage['calls']} of {limit} calls, "
                    f"{usage['total_tokens']} tokens, ${usage['cost_usd']:.4f}"
                    + (f", {usage['failures']} failed" if usage["failures"] else "")
                )
            else:
                emit("subcalls   none yet")
            records = supervisor.snapshots() if supervisor is not None else []
            tokens = sum(int((item.get("usage") or {}).get("total_tokens", 0)) for item in records)
            cost = sum(float((item.get("usage") or {}).get("cost_usd", 0.0)) for item in records)
            emit(
                f"children   {len(records)}, {tokens} tokens, ${cost:.4f}"
                if records
                else "children   none"
            )
            from superqode.rlm.context import RLMContext

            stats = RLMContext(session.cwd, policy=session.options.context_policy).stats()
            emit(f"context    {stats['files']} files, {stats['bytes']} bytes in scope")
            emit("Root conversation usage is reported by the harness, not here.")
        elif command == "sandbox":
            from superqode.rlm.sandbox import RLMSandboxConfig, docker_available

            config = session.options.sandbox or RLMSandboxConfig()
            raw = argument.strip().lower()
            if raw in {"", "status"}:
                for line in config.describe():
                    emit(line)
            elif raw == "doctor":
                emit(f"active      {config.backend}")
                available, detail = docker_available()
                emit(
                    f"docker      {detail}" if available else f"docker      unavailable: {detail}",
                    "success" if available else "info",
                )
                emit("profiles    host, docker, monty")
                emit("Docker networking is disabled unless allow_network is enabled.")
            else:
                raise ValueError(
                    "The sandbox profile is selected by the active HarnessSpec; reconnect "
                    "after changing runtime.config.sandbox."
                )
        else:
            raise ValueError(f"Unknown resident RLM command: {command!r}")
        return {"command": command, "lines": lines}

    async def _watch_controls(self) -> None:
        while not self._stopping:
            controls, self._control_offset = _read_jsonl_since(
                self.controls_path, self._control_offset
            )
            for control in controls:
                if control.get("generation") != self.generation:
                    continue
                operation = str(control.get("operation") or "")
                payload = control.get("payload")
                body = dict(payload) if isinstance(payload, dict) else {}
                ref = self._ref
                if ref is None:
                    continue
                if operation == "steer":
                    await self._adapter.steer(
                        ref, HarnessMessage("user", str(body.get("content") or ""))
                    )
                elif operation == "cancel":
                    await self._adapter.cancel(ref)
                elif operation == "stop":
                    await self._adapter.cancel(ref)
                    self._stopping = True
            await asyncio.sleep(0.05)

    async def _heartbeat(self) -> None:
        while not self._stopping:
            self._write_state("running" if self._active_command else "ready")
            await asyncio.sleep(1)

    def _write_state(self, state: str, *, error: str = "") -> None:
        ref = self._ref
        session_path = ""
        external = ""
        if ref is not None:
            external = str(ref.external_session_id or "")
            session = self._adapter._sessions.get(ref.session_id)
            session_path = str(getattr(session, "session_path", "") or "")
        _atomic_json(
            self.state_path,
            {
                "protocol": ROOT_RUNTIME_PROTOCOL,
                "session_id": str(self.manifest.get("session_id") or ""),
                "generation": self.generation,
                "pid": os.getpid(),
                "state": state,
                "active_command": self._active_command,
                "session_path": session_path,
                "external_session_id": external,
                "heartbeat": time.time(),
                "error": error,
            },
        )


async def run_worker(manifest: str | Path, generation: str) -> int:
    return await ResidentRootWorker(Path(manifest), generation).run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal native RLM resident root worker")
    parser.add_argument("manifest")
    parser.add_argument("--generation", required=True)
    arguments = parser.parse_args()
    return asyncio.run(run_worker(arguments.manifest, arguments.generation))


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())


__all__ = ["ResidentRootWorker", "main", "run_worker"]
