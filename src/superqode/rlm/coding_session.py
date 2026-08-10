"""A one-tool recursive-language-model coding session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
from superqode.pipy.harness import AgentHarness, HarnessResources, TurnState
from superqode.pipy.prompt_templates import load_prompt_templates
from superqode.pipy.resources import load_context_files
from superqode.pipy.session import Session, SessionRepository
from superqode.pipy.skills import load_skills

from .config import sessions_root
from .kernel import create_python_tool, kernel_for
from .kernel_backend import create_backend_python_tool
from .policy import GateResult, RLMPolicy, RLMPolicyStore, _bounded
from .sandbox import RLMSandboxConfig
from .supervisor import AgentRecord, AgentSupervisor

_SUPERVISORS: dict[str, AgentSupervisor] = {}
_BACKENDS: dict[str, Any] = {}


@dataclass(slots=True)
class RLMCodingSessionOptions(CodingSessionOptions):
    """RLM-only runtime ownership layered over PiPy's portable options."""

    supervisor: AgentSupervisor | None = None
    agent_id: str = "root"
    max_depth: int = 3
    max_children: int = 8
    max_parallel: int = 4
    goal: str = ""
    autonomous: bool = False
    gates: tuple[str, ...] = ()
    autonomous_max_rounds: int = 3
    gate_timeout: float = 120.0
    durable_children: bool = True
    sandbox: RLMSandboxConfig | None = None
    #: The root session that owns the boundary. Children inherit it so they get
    #: their own kernel inside the root's sandbox rather than one each.
    sandbox_session: str = ""


class RLMCodingSession(PiPyCodingSession):
    """PiPy's proven session/loop substrate configured as a true RLM."""

    policy_store: RLMPolicyStore

    @classmethod
    def _wire(
        cls,
        session: Session,
        path: Path,
        options: CodingSessionOptions,
        repository: SessionRepository,
    ) -> "RLMCodingSession":
        cwd = Path(options.cwd).expanduser().resolve()
        context_files = load_context_files(cwd)
        skills = load_skills(cwd=cwd).skills
        templates = load_prompt_templates(cwd=cwd).templates
        session_key = str(path.resolve())
        # A child names the session that owns the boundary; a root names itself.
        owner = str(getattr(options, "sandbox_session", "") or "") or path.stem
        supervisor = getattr(options, "supervisor", None) or _SUPERVISORS.get(session_key)
        if supervisor is None:
            supervisor = AgentSupervisor(
                asyncio.get_running_loop(),
                max_depth=int(getattr(options, "max_depth", 3)),
                max_children=int(getattr(options, "max_children", 8)),
                max_parallel=int(getattr(options, "max_parallel", 4)),
                journal_path=path.with_suffix(".agents.jsonl"),
            )
            supervisor.set_runner(cls._child_runner(options, supervisor, owner))
        _SUPERVISORS[session_key] = supervisor
        agent_id = str(getattr(options, "agent_id", "root") or "root")
        # Refuse rather than downgrade: a requested boundary this build cannot
        # provide would otherwise run model-written Python on the host.
        sandbox = (getattr(options, "sandbox", None) or RLMSandboxConfig()).require_available()
        if sandbox.isolated:
            # Only the isolated profile goes through a backend. The host path is
            # left exactly as released: rerouting it would risk a regression in
            # a shipped runtime for no behaviour it does not already have.
            tool = create_backend_python_tool(
                _backend_for(session_key, path, cwd, sandbox, supervisor, agent_id, owner),
                agent_id,
                drain_events=_supervisor_drain(supervisor),
                cwd=cwd,
            )
        else:
            tool = create_python_tool(
                kernel_for(
                    session_key,
                    cwd,
                    supervisor=supervisor,
                    agent_id=agent_id,
                    checkpoint_path=path.with_suffix(".kernel.pkl"),
                    sandbox=sandbox,
                )
            )
        instance = cls(
            harness=None,  # type: ignore[arg-type]
            session_path=path,
            options=options,
            repository=repository,
            context_files=context_files,
            skills=skills,
            templates=templates,
        )
        instance.policy_store = RLMPolicyStore(
            path.with_suffix(".policy.json"),
            defaults=RLMPolicy(
                goal=str(getattr(options, "goal", "") or "").strip(),
                autonomous=bool(getattr(options, "autonomous", False)),
                gates=tuple(str(item) for item in getattr(options, "gates", ()) or ()),
                max_rounds=int(getattr(options, "autonomous_max_rounds", 3)),
                gate_timeout=float(getattr(options, "gate_timeout", 120.0)),
            ),
        )
        instance.harness = AgentHarness(
            session=session,
            model=options.model or _default_model(),
            stream_fn=options.stream_fn or _default_stream_fn(),
            tools=[tool],
            system_prompt=instance._build_prompt,
            thinking_level=options.thinking_level,
            steering_mode=options.steering_mode,
            follow_up_mode=options.follow_up_mode,
            resources=HarnessResources(skills=tuple(skills), prompt_templates=tuple(templates)),
            compaction_settings=options.compaction_settings,
        )
        return instance

    @staticmethod
    def _child_runner(options: CodingSessionOptions, supervisor: AgentSupervisor, owner: str = ""):
        async def run(record: AgentRecord) -> str:
            if bool(getattr(options, "durable_children", True)) and options.stream_fn is None:
                from .worker_process import run_durable_child

                return await run_durable_child(record, options=options, supervisor=supervisor)
            model = options.model
            if record.model:
                from superqode.pipy.ai.models import resolve_model

                provider, separator, model_id = record.model.partition("/")
                model = resolve_model(
                    model_id if separator else record.model,
                    provider=provider if separator else "",
                )
            child_options = RLMCodingSessionOptions(
                cwd=options.cwd,
                model=model,
                stream_fn=options.stream_fn,
                thinking_level=options.thinking_level,
                session_root=options.session_root,
                custom_prompt=options.custom_prompt,
                append_system_prompt=options.append_system_prompt,
                self_docs=options.self_docs,
                steering_mode=options.steering_mode,
                follow_up_mode=options.follow_up_mode,
                compaction_settings=options.compaction_settings,
                supervisor=supervisor,
                agent_id=record.id,
                max_depth=supervisor.max_depth,
                max_children=supervisor.max_children,
                max_parallel=supervisor.max_parallel,
                durable_children=False,
                sandbox=getattr(options, "sandbox", None),
                # The root's boundary, so an isolated child gets its own kernel
                # inside it instead of starting a container of its own.
                sandbox_session=owner,
            )
            child = await RLMCodingSession.create(child_options)
            await supervisor.attach_session(record.id, child)
            result = await child.prompt(record.prompt)
            record.usage = _usage_dict(getattr(result, "usage", None))
            return result.text

        return run

    @classmethod
    async def create(cls, options: CodingSessionOptions | None = None) -> "RLMCodingSession":
        resolved = options or CodingSessionOptions()
        if resolved.session_root is None:
            resolved.session_root = sessions_root()
        return await super().create(resolved)  # type: ignore[return-value]

    @classmethod
    async def resume(
        cls,
        options: CodingSessionOptions | None = None,
        *,
        session_path: Path | str | None = None,
    ) -> "RLMCodingSession":
        resolved = options or CodingSessionOptions()
        if resolved.session_root is None:
            resolved.session_root = sessions_root()
        return await super().resume(resolved, session_path=session_path)  # type: ignore[return-value]

    def _build_prompt(self, state: TurnState) -> str:
        policy = self.policy
        context = "\n\n".join(
            f'<project_instructions path="{item.path}">\n{item.content}\n</project_instructions>'
            for item in self._context_files
        )
        suffix = f"\n\n<project_context>\n{context}\n</project_context>" if context else ""
        custom = (
            f"\n\n{self.options.append_system_prompt}" if self.options.append_system_prompt else ""
        )
        policy_text = ""
        if policy.goal:
            policy_text += f"\n\nPersistent goal:\n{policy.goal}"
        if policy.autonomous:
            policy_text += (
                "\n\nAutonomous mode is enabled. Work without asking avoidable questions, "
                "use repository evidence, and do not declare completion until the goal and "
                "configured host completion gates are satisfied."
            )
        if self.options.custom_prompt:
            return (
                self.options.custom_prompt
                + custom
                + policy_text
                + suffix
                + f"\n\nWorking directory: {self.cwd}"
            )
        return (
            "You are an expert coding agent operating inside SuperQode's native RLM harness.\n\n"
            "You have exactly one executable tool: python. It is a persistent Python "
            "environment, so variables and imports survive across tool calls. Build the "
            "context you need by writing Python rather than asking for separate file, search, "
            "shell, or editing tools.\n\n"
            "The namespace provides:\n"
            "- workspace.read(path), write(path, content), edit(path, old, new), "
            "search(pattern, path='.'), and glob(pattern)\n"
            "- shell.run(command) for commands and tests\n"
            "- rlm.run(prompt) or rlm.run_batch(prompts) for live child agents\n"
            "- child handles provide status(), send(), steer(), wait(), and cancel()\n"
            "- rlm.agents() lists children and rlm.wait_all(handles) collects results\n\n"
            "Inspect the repository before editing, make focused changes, run relevant "
            "verification, and give a concise final answer. Never claim a command passed "
            "unless its returned result shows success."
            + custom
            + policy_text
            + suffix
            + f"\n\nWorking directory: {self.cwd}"
        )

    @property
    def sandbox_backend(self) -> Any | None:
        """The isolated backend owning this session's Python, if there is one."""
        return _BACKENDS.get(str(Path(self.session_path).resolve()))

    @property
    def gate_runner(self) -> Any | None:
        """Run completion gates wherever this session's Python runs.

        Returns nothing under the host profile, where gates already execute in
        the same place as the kernel.
        """
        backend = self.sandbox_backend
        if backend is None:
            return None

        async def run(command: str, timeout: float) -> GateResult:
            await backend.start()
            result = await backend.shell(command, timeout=timeout)
            return GateResult(
                command=command,
                returncode=result.returncode,
                stdout=_bounded(result.stdout, 12_000),
                stderr=_bounded(result.stderr, 12_000),
            )

        return run

    @property
    def policy(self) -> RLMPolicy:
        return self.policy_store.load()

    def update_policy(self, **changes) -> RLMPolicy:
        return self.policy_store.update(**changes)


def _default_model():
    from superqode.pipy.ai.models import resolve_model

    return resolve_model("claude-opus-5", provider="anthropic")


def _default_stream_fn():
    from superqode.pipy.ai.gateway import create_gateway_stream

    return create_gateway_stream()


def _usage_dict(usage) -> dict[str, int | float]:
    if usage is None:
        return {}
    cost = getattr(usage, "cost", None)
    return {
        "input_tokens": int(getattr(usage, "input", 0) or 0),
        "output_tokens": int(getattr(usage, "output", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read", 0) or 0),
        "cache_write_tokens": int(getattr(usage, "cache_write", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cost_usd": float(getattr(cost, "total", 0.0) or 0.0),
    }


def _supervisor_drain(supervisor: AgentSupervisor):
    """Child lifecycle events come from the host supervisor, not the sandbox."""
    cursor = {"value": 0}

    def drain() -> list[dict[str, Any]]:
        events, cursor["value"] = supervisor.events_since(cursor["value"])
        return events

    return drain


def _agent_value(supervisor: AgentSupervisor, agent_id: str) -> dict[str, Any]:
    """Describe a child in a form the sandbox can rebuild as a handle."""
    return {"__rlm__": "agent", "id": agent_id, "status": supervisor.snapshot(agent_id)}


def _host_call_bridge(supervisor: AgentSupervisor, agent_id: str):
    """Serve `rlm.*` for a kernel that runs inside a boundary.

    Recursion stays on the host because it needs the supervisor and the provider
    credentials, and because a limit the sandbox could reach is not a limit. The
    depth, child-count and parallelism checks are the supervisor's either way.
    """

    async def call(name: str, payload: dict[str, Any]) -> Any:
        target = str(payload.get("agent") or "")
        if name in {"rlm.run", "rlm.spawn"}:
            handle = supervisor.spawn(
                str(payload.get("prompt") or ""),
                parent_id=agent_id,
                model=payload.get("model"),
            )
            return _agent_value(supervisor, handle.id)
        if name in {"rlm.run_batch", "rlm.spawn_batch"}:
            handles = supervisor.spawn_batch(
                [str(item) for item in payload.get("prompts") or ()],
                parent_id=agent_id,
                model=payload.get("model"),
            )
            return [_agent_value(supervisor, handle.id) for handle in handles]
        if name == "rlm.agents":
            parent = None if payload.get("all_agents") else agent_id
            return supervisor.snapshots(parent_id=parent)
        if name == "rlm.status":
            return supervisor.snapshot(target)
        if name == "rlm.wait":
            return await supervisor.wait(target)
        if name == "rlm.wait_all":
            return await supervisor.wait_all([str(item) for item in payload.get("agents") or ()])
        if name == "rlm.send":
            await supervisor.send(target, str(payload.get("message") or ""))
            return None
        if name == "rlm.steer":
            await supervisor.steer(target, str(payload.get("instruction") or ""))
            return None
        if name == "rlm.cancel":
            await supervisor.cancel(target)
            return None
        if name == "rlm.delete":
            supervisor.delete(target)
            return None
        raise RuntimeError(f"Unsupported sandbox host call: {name}")

    return call


def _backend_for(
    session_key: str,
    path: Path,
    cwd: Path,
    sandbox: RLMSandboxConfig,
    supervisor: AgentSupervisor,
    agent_id: str,
    owner: str,
) -> Any:
    from .kernel_docker import DockerKernelBackend

    existing = _BACKENDS.get(session_key)
    if existing is not None:
        return existing
    backend = DockerKernelBackend(
        cwd,
        config=sandbox,
        session_id=owner,
        state_dir=path.with_suffix(".sandbox"),
        host_call=_host_call_bridge(supervisor, agent_id),
    )
    _BACKENDS[session_key] = backend
    return backend


def supervisor_for_session(session_path: str | Path) -> AgentSupervisor | None:
    return _SUPERVISORS.get(str(Path(session_path).expanduser().resolve()))


__all__ = ["RLMCodingSession", "RLMCodingSessionOptions", "supervisor_for_session"]
