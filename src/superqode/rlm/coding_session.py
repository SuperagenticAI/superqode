"""A one-tool recursive-language-model coding session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
from superqode.pipy.harness import AgentHarness, HarnessResources, TurnState
from superqode.pipy.prompt_templates import load_prompt_templates
from superqode.pipy.resources import load_context_files
from superqode.pipy.session import Session, SessionRepository
from superqode.pipy.skills import load_skills

from .config import sessions_root
from .kernel import create_python_tool, kernel_for
from .policy import RLMPolicy, RLMPolicyStore
from .supervisor import AgentRecord, AgentSupervisor

_SUPERVISORS: dict[str, AgentSupervisor] = {}


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
        supervisor = getattr(options, "supervisor", None) or _SUPERVISORS.get(session_key)
        if supervisor is None:
            supervisor = AgentSupervisor(
                asyncio.get_running_loop(),
                max_depth=int(getattr(options, "max_depth", 3)),
                max_children=int(getattr(options, "max_children", 8)),
                max_parallel=int(getattr(options, "max_parallel", 4)),
                journal_path=path.with_suffix(".agents.jsonl"),
            )
            supervisor.set_runner(cls._child_runner(options, supervisor))
        _SUPERVISORS[session_key] = supervisor
        agent_id = str(getattr(options, "agent_id", "root") or "root")
        tool = create_python_tool(
            kernel_for(
                session_key,
                cwd,
                supervisor=supervisor,
                agent_id=agent_id,
                checkpoint_path=path.with_suffix(".kernel.pkl"),
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
    def _child_runner(options: CodingSessionOptions, supervisor: AgentSupervisor):
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


def supervisor_for_session(session_path: str | Path) -> AgentSupervisor | None:
    return _SUPERVISORS.get(str(Path(session_path).expanduser().resolve()))


__all__ = ["RLMCodingSession", "RLMCodingSessionOptions", "supervisor_for_session"]
