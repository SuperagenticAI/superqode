"""The coding session: a harness wired to a working directory.

Ported in shape from ``packages/coding-agent/src/core/agent-session.ts`` of
earendil-works/pi (MIT).

The harness is deliberately ignorant of coding: it knows about turns, queues,
hooks and a session tree. This is the layer that gives it a working directory,
the pi tool set, the project's own instructions and skills, and the commands a
user drives it with.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .compaction import CompactionSettings, CompactResult
from .event_stream import EventStream
from .harness import AgentHarness, HarnessResources, TurnState
from .harness_events import AgentHarnessError
from .messages import AssistantMessage, ImageContent, ToolResultMessage, UserMessage
from .prompt_templates import (
    PromptTemplate,
    format_prompt_template_invocation,
    load_prompt_templates,
)
from .resources import ContextFile, load_context_files
from .session import Session, SessionRecord, SessionRepository
from .skills import Skill, format_skill_invocation, load_skills
from .stream import Model, StreamFn
from .system_prompt import SelfDocs, SystemPromptOptions, build_system_prompt
from .tools.base import AgentTool
from .tools.registry import CODING_TOOL_NAMES, create_tools
from .types import QueueMode, ThinkingLevel


@dataclass(frozen=True, slots=True)
class SlashCommand:
    """A command the UI can offer. Dispatch is a method on the session."""

    name: str
    summary: str
    takes_argument: bool = False


#: The harness-level commands pi exposes. Anything about chrome, themes or
#: authentication belongs to the host, not here.
SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("compact", "Summarise older context and keep working", True),
    SlashCommand("tree", "Move to another point in the session tree", True),
    SlashCommand("fork", "Copy this session into a new one", True),
    SlashCommand("resume", "Reopen a previous session for this directory", True),
    SlashCommand("new", "Start a fresh session in this directory"),
    SlashCommand("name", "Name this session", True),
    SlashCommand("model", "Switch the model for the next turn", True),
    SlashCommand("session", "Show this session's id, path and stats"),
    SlashCommand("export", "Export the current branch as Markdown"),
    SlashCommand("skill", "Invoke a skill by name", True),
    SlashCommand("prompt", "Run a prompt template by name", True),
)


@dataclass(slots=True)
class CodingSessionOptions:
    """Everything needed to open a coding session."""

    cwd: Path | str = "."
    model: Model | None = None
    #: Defaults to the SuperQode gateway bridge, resolved lazily so that
    #: building the options does not import the provider stack.
    stream_fn: StreamFn | None = None
    tool_names: tuple[str, ...] = CODING_TOOL_NAMES
    thinking_level: ThinkingLevel = "off"
    #: Overrides where sessions are stored. Defaults to the PiPy root.
    session_root: Path | None = None
    custom_prompt: str | None = None
    append_system_prompt: str | None = None
    self_docs: SelfDocs = field(default_factory=SelfDocs)
    steering_mode: QueueMode = "one-at-a-time"
    follow_up_mode: QueueMode = "one-at-a-time"
    compaction_settings: CompactionSettings | None = None


@dataclass(slots=True)
class SessionInfo:
    """What ``/session`` reports."""

    id: str
    path: str
    cwd: str
    name: str | None
    entry_count: int
    message_count: int
    model: str
    tools: list[str]
    #: Current leaf of the session tree. This is what a status line shows so a
    #: user can tell which branch they are on after navigating.
    leaf_id: str | None = None


class PiPyCodingSession:
    """A harness bound to a working directory, its resources and its commands."""

    def __init__(
        self,
        *,
        harness: AgentHarness,
        session_path: Path,
        options: CodingSessionOptions,
        repository: SessionRepository,
        context_files: list[ContextFile],
        skills: list[Skill],
        templates: list[PromptTemplate],
    ) -> None:
        self.harness = harness
        self.session_path = session_path
        self.options = options
        self.repository = repository
        self.cwd = Path(options.cwd).expanduser().resolve()
        self._context_files = context_files
        self._skills = skills
        self._templates = templates

    # -- construction ----------------------------------------------------- #

    @classmethod
    async def create(cls, options: CodingSessionOptions | None = None) -> PiPyCodingSession:
        """Open a new session for a working directory."""
        resolved = options or CodingSessionOptions()
        repository = SessionRepository(resolved.session_root)
        session, path = await repository.create(Path(resolved.cwd).expanduser().resolve())
        return cls._wire(session, path, resolved, repository)

    @classmethod
    async def resume(
        cls,
        options: CodingSessionOptions | None = None,
        *,
        session_path: Path | str | None = None,
    ) -> PiPyCodingSession:
        """Reopen a session, the most recent one for this directory by default.

        Falls back to creating one when there is nothing to resume, so callers
        do not have to branch on first use.
        """
        resolved = options or CodingSessionOptions()
        repository = SessionRepository(resolved.session_root)
        cwd = Path(resolved.cwd).expanduser().resolve()

        if session_path is not None:
            path = Path(session_path)
            session = await repository.open(path)
            return cls._wire(session, path, resolved, repository)

        record = repository.latest(cwd)
        if record is None:
            return await cls.create(resolved)
        session = await repository.open(record.path)
        return cls._wire(session, record.path, resolved, repository)

    @classmethod
    def _wire(
        cls,
        session: Session,
        path: Path,
        options: CodingSessionOptions,
        repository: SessionRepository,
    ) -> PiPyCodingSession:
        cwd = Path(options.cwd).expanduser().resolve()
        tools = create_tools(options.tool_names, cwd)
        context_files = load_context_files(cwd)
        skills = load_skills(cwd=cwd).skills
        templates = load_prompt_templates(cwd=cwd).templates

        instance = cls(
            harness=None,  # type: ignore[arg-type]
            session_path=path,
            options=options,
            repository=repository,
            context_files=context_files,
            skills=skills,
            templates=templates,
        )
        instance.harness = AgentHarness(
            session=session,
            model=options.model or _default_model(),
            stream_fn=options.stream_fn or _default_stream_fn(),
            tools=tools,
            # Built per turn, so changing the active tools or reloading the
            # project's instructions takes effect without rebuilding anything.
            system_prompt=instance._build_prompt,
            thinking_level=options.thinking_level,
            steering_mode=options.steering_mode,
            follow_up_mode=options.follow_up_mode,
            resources=HarnessResources(skills=tuple(skills), prompt_templates=tuple(templates)),
            compaction_settings=options.compaction_settings,
        )
        return instance

    def _build_prompt(self, state: TurnState) -> str:
        return build_system_prompt(
            SystemPromptOptions(
                cwd=self.cwd,
                tools=state.active_tools,
                context_files=self._context_files,
                skills=self._skills,
                custom_prompt=self.options.custom_prompt,
                append_system_prompt=self.options.append_system_prompt,
                self_docs=self.options.self_docs,
            )
        )

    # -- resources -------------------------------------------------------- #

    @property
    def session(self) -> Session:
        return self.harness.session

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills)

    @property
    def prompt_templates(self) -> list[PromptTemplate]:
        return list(self._templates)

    @property
    def context_files(self) -> list[ContextFile]:
        return list(self._context_files)

    @property
    def tools(self) -> list[AgentTool]:
        return self.harness.get_tools()

    def reload_resources(self) -> None:
        """Re-read project instructions, skills and templates from disk."""
        self._context_files = load_context_files(self.cwd)
        self._skills = load_skills(cwd=self.cwd).skills
        self._templates = load_prompt_templates(cwd=self.cwd).templates

    # -- running ---------------------------------------------------------- #

    async def prompt(
        self,
        text: str,
        images: Sequence[ImageContent] | None = None,
    ) -> AssistantMessage:
        return await self.harness.prompt(text, images)

    def prompt_events(
        self,
        text: str,
        images: Sequence[ImageContent] | None = None,
    ) -> EventStream:
        return self.harness.prompt_events(text, images)

    async def steer(self, text: str) -> None:
        await self.harness.steer(text)

    async def follow_up(self, text: str) -> None:
        await self.harness.follow_up(text)

    async def next_turn(self, text: str) -> None:
        await self.harness.next_turn(text)

    async def abort(self):
        return await self.harness.abort()

    # -- commands --------------------------------------------------------- #

    async def compact(self, instructions: str | None = None) -> CompactResult | None:
        """``/compact``. Returns None when there is nothing old enough to summarise."""
        return await self.harness.compact(instructions)

    async def navigate_tree(self, entry_id: str | None, *, summarize: bool = True) -> str | None:
        """``/tree``. Move the leaf, summarising the branch left behind."""
        return await self.harness.navigate_tree(entry_id, summarize=summarize)

    async def fork(self, *, up_to_entry_id: str | None = None) -> PiPyCodingSession:
        """``/fork``. Copy this session's branch into a new one and open it.

        The source file is untouched, so an experiment never risks the history
        it came from.
        """
        _, path = await self.repository.fork(self.session_path, up_to_entry_id=up_to_entry_id)
        return await self.resume(self.options, session_path=path)

    async def new(self) -> PiPyCodingSession:
        """``/new``. Start a fresh session in the same directory."""
        return await self.create(self.options)

    def list_sessions(self) -> list[SessionRecord]:
        """``/resume`` candidates for this directory, newest first."""
        return self.repository.list(self.cwd)

    async def rename(self, name: str) -> None:
        """``/name``."""
        await self.session.append_session_name(name)

    async def set_model(self, model: Model) -> None:
        """``/model``."""
        await self.harness.set_model(model)

    async def invoke_skill(self, name: str, additional_instructions: str | None = None):
        """``/skill``. Expand a skill into a prompt and run it."""
        skill = next((item for item in self._skills if item.name == name), None)
        if skill is None:
            available = ", ".join(sorted(item.name for item in self._skills)) or "none"
            raise AgentHarnessError(
                "invalid_argument", f"Unknown skill {name!r}. Available: {available}"
            )
        return await self.prompt(format_skill_invocation(skill, additional_instructions))

    async def invoke_prompt_template(self, name: str, args: Sequence[str] = ()):
        """``/prompt``. Expand a template with its arguments and run it."""
        template = next((item for item in self._templates if item.name == name), None)
        if template is None:
            available = ", ".join(sorted(item.name for item in self._templates)) or "none"
            raise AgentHarnessError(
                "invalid_argument", f"Unknown prompt template {name!r}. Available: {available}"
            )
        return await self.prompt(format_prompt_template_invocation(template, list(args)))

    async def info(self) -> SessionInfo:
        """``/session``."""
        metadata = await self.session.get_metadata()
        stats = await self.session.get_stats()
        return SessionInfo(
            id=metadata.id,
            path=str(self.session_path),
            cwd=metadata.cwd,
            name=await self.session.get_session_name(),
            entry_count=stats.entry_count,
            message_count=stats.message_count,
            model=self.harness.get_model().id,
            tools=[tool.name for tool in self.harness.get_active_tools()],
            leaf_id=await self.session.get_leaf_id(),
        )

    async def export_markdown(self) -> str:
        """``/export``. Render the current branch as Markdown.

        Only the branch, not the whole tree: an export should read like the
        conversation the user actually had.
        """
        context = await self.session.build_context()
        info = await self.info()
        lines = [
            f"# {info.name or 'PiPy session'}",
            "",
            f"- Session: `{info.id}`",
            f"- Directory: `{info.cwd}`",
            f"- Model: `{info.model}`",
            "",
        ]

        for message in context.messages:
            if isinstance(message, UserMessage):
                lines += ["## User", "", message.text, ""]
            elif isinstance(message, AssistantMessage):
                if message.thinking_text:
                    lines += ["## Assistant (thinking)", "", message.thinking_text, ""]
                if message.text:
                    lines += ["## Assistant", "", message.text, ""]
                for call in message.tool_calls:
                    lines += [
                        f"### Tool call: `{call.name}`",
                        "",
                        "```json",
                        _pretty(call.arguments),
                        "```",
                        "",
                    ]
            elif isinstance(message, ToolResultMessage):
                heading = f"### Tool result: `{message.tool_name}`"
                if message.is_error:
                    heading += " (error)"
                lines += [heading, "", "```", message.text, "```", ""]
            else:
                summary = getattr(message, "summary", "")
                if summary:
                    lines += ["## Summary", "", summary, ""]

        return "\n".join(lines).rstrip() + "\n"


def _pretty(value) -> str:
    return json.dumps(value, indent=2, default=str)


def _default_model() -> Model:
    from .ai.models import resolve_model

    return resolve_model("claude-opus-5", provider="anthropic")


def _default_stream_fn() -> StreamFn:
    from .ai.gateway import create_gateway_stream

    return create_gateway_stream()


__all__ = [
    "SLASH_COMMANDS",
    "CodingSessionOptions",
    "PiPyCodingSession",
    "SessionInfo",
    "SlashCommand",
]
