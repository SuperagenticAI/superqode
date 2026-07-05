"""
Run SuperQode as an ACP agent (the agent side of the Agent Client Protocol).

Complements the client in ``acp/client.py``: any ACP client — Zed, JetBrains
IDEs, Neovim, Devin Desktop — can drive SuperQode as its coding agent over
stdio JSON-RPC. The agent loop is a HarnessSpec, resolved per session: an
explicit ``--spec``, the session directory's ``superqode.local.yaml`` or
``harness.yaml``, a spec discovered under the conventional harness dirs, or
the built-in coding template.

Run it::

    superqode serve acp                       # stdio, auto-discovered spec
    superqode serve acp --spec harness.yaml   # pin one HarnessSpec

Provider/model resolution order: explicit flags → ``SUPERQODE_ACP_PROVIDER``
/ ``SUPERQODE_ACP_MODEL`` env → the spec's ``model_policy.primary``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)
from acp.exceptions import RequestError
from acp.schema import (
    AgentCapabilities,
    Implementation,
    PermissionOption,
    PromptCapabilities,
    TerminalAuthMethod,
    ToolCallUpdate,
)

# Conventional spec files looked up in the session working directory, in order.
SESSION_SPEC_FILENAMES = ("superqode.local.yaml", "harness.yaml")

# Cap tool output relayed to the client; full output stays in the harness store.
_TOOL_OUTPUT_LIMIT = 2000

_STREAM_DONE = object()


def _tool_kind(name: str) -> str:
    """Map a SuperQode tool name onto an ACP ToolKind."""
    lowered = (name or "").lower()
    exact = {
        "read_file": "read",
        "ls": "read",
        "list_dir": "read",
        "get_context_remaining": "read",
        "edit_file": "edit",
        "write_file": "edit",
        "patch": "edit",
        "grep": "search",
        "glob": "search",
        "repo_search": "search",
        "semantic_search": "search",
        "bash": "execute",
        "shell": "execute",
        "web_fetch": "fetch",
    }
    if lowered in exact:
        return exact[lowered]
    for fragment, kind in (
        ("read", "read"),
        ("edit", "edit"),
        ("write", "edit"),
        ("patch", "edit"),
        ("grep", "search"),
        ("search", "search"),
        ("glob", "search"),
        ("find", "search"),
        ("bash", "execute"),
        ("shell", "execute"),
        ("command", "execute"),
        ("fetch", "fetch"),
    ):
        if fragment in lowered:
            return kind
    return "other"


def _prompt_to_text(blocks: list[Any] | None) -> str:
    """Flatten ACP prompt content blocks into one harness prompt string."""
    parts: list[str] = []
    for block in blocks or []:
        block_type = getattr(block, "type", "")
        if block_type == "text":
            parts.append(getattr(block, "text", "") or "")
        elif block_type == "resource":
            resource = getattr(block, "resource", None)
            text = getattr(resource, "text", None)
            if text:
                uri = getattr(resource, "uri", "") or ""
                parts.append(f'<context uri="{uri}">\n{text}\n</context>')
        elif block_type == "resource_link":
            uri = getattr(block, "uri", "") or ""
            name = getattr(block, "name", "") or ""
            parts.append(f"[resource: {name or uri}]")
    return "\n\n".join(part for part in parts if part).strip()


def _clip(text: Any, limit: int = _TOOL_OUTPUT_LIMIT) -> str:
    rendered = str(text or "")
    if len(rendered) <= limit:
        return rendered
    return rendered[:limit] + f"\n… (truncated, {len(rendered)} chars total)"


class _ToolCallTracker:
    """Assign stable ACP tool_call ids to sequential harness tool events."""

    def __init__(self) -> None:
        self._counter = 0
        self._open: dict[str, list[str]] = {}

    def start(self, name: str) -> str:
        self._counter += 1
        call_id = f"tc-{self._counter}-{name or 'tool'}"
        self._open.setdefault(name, []).append(call_id)
        return call_id

    def finish(self, name: str) -> str | None:
        stack = self._open.get(name)
        if stack:
            return stack.pop(0)
        return None


def discover_session_spec(cwd: Path, harness_dir: Path | None = None) -> Path | None:
    """Find the HarnessSpec that should drive an ACP session rooted at ``cwd``."""
    if harness_dir is not None:
        directory = Path(harness_dir).expanduser()
        if directory.is_dir():
            for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
                return path
    for name in SESSION_SPEC_FILENAMES:
        candidate = cwd / name
        if candidate.is_file():
            return candidate
    from superqode.mcp.harness_server import DEFAULT_HARNESS_DIRS

    for dirname in DEFAULT_HARNESS_DIRS:
        directory = cwd / dirname
        if not directory.is_dir():
            continue
        for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
            return path
    return None


def resolve_provider_model(spec: Any, provider: str = "", model: str = "") -> tuple[str, str]:
    """Resolve provider/model: explicit args → ACP env vars → Harbor requested model
    → model_policy.primary."""
    from superqode.providers.model_specs import (
        normalize_model_for_provider,
        normalize_provider_id,
        split_provider_model_ref,
    )

    provider = provider or os.environ.get("SUPERQODE_ACP_PROVIDER", "").strip()
    model = model or os.environ.get("SUPERQODE_ACP_MODEL", "").strip()
    provider = normalize_provider_id(provider)
    if provider:
        model = normalize_model_for_provider(provider, model)
    elif model:
        parsed_model = split_provider_model_ref(model)
        if parsed_model.provider:
            provider, model = parsed_model.provider, parsed_model.model

    # Harbor's ACP runner exports the benchmark's --model for the agent process;
    # honoring it makes SuperQode work on Terminal-Bench without a wrapper.
    harbor_requested = os.environ.get("HARBOR_ACP_REQUESTED_MODEL", "").strip()
    if (not provider or not model) and harbor_requested:
        parsed_requested = split_provider_model_ref(harbor_requested)
        if parsed_requested.provider:
            provider = provider or parsed_requested.provider
            model = model or parsed_requested.model
        else:
            model = model or harbor_requested

    primary = getattr(getattr(spec, "model_policy", None), "primary", None)
    if (not provider or not model) and primary:
        parsed_primary = split_provider_model_ref(str(primary))
        if parsed_primary.provider:
            provider = provider or parsed_primary.provider
            model = model or parsed_primary.model
        else:
            model = model or str(primary)
    return provider, model


@dataclass
class _AcpSessionState:
    """Live state for one ACP session backed by a HarnessSession."""

    session: Any
    spec: Any
    provider: str
    model: str
    cwd: Path
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class SuperQodeAcpAgent:
    """ACP agent implementation that runs prompts through a HarnessKernel."""

    def __init__(
        self,
        *,
        spec_path: Path | None = None,
        harness_dir: Path | None = None,
        provider: str = "",
        model: str = "",
    ) -> None:
        self._spec_path = spec_path
        self._harness_dir = harness_dir
        self._provider = provider
        self._model = model
        self._conn: Any | None = None
        self._sessions: dict[str, _AcpSessionState] = {}

    # -- connection lifecycle -------------------------------------------------

    def on_connect(self, conn: Any) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        from superqode import __version__

        return InitializeResponse(
            protocol_version=min(int(protocol_version), PROTOCOL_VERSION),
            agent_capabilities=AgentCapabilities(
                load_session=False,
                prompt_capabilities=PromptCapabilities(
                    audio=False, image=False, embedded_context=True
                ),
            ),
            agent_info=Implementation(name="superqode", title="SuperQode", version=__version__),
            auth_methods=[
                TerminalAuthMethod(
                    type="terminal",
                    id="superqode-setup",
                    name="Set up SuperQode",
                    description=(
                        "Detect local hardware, pick a local model, and generate a "
                        "starter harness for this project (superqode local init)."
                    ),
                    args=["local", "init", "--repo", "."],
                )
            ],
        )

    async def authenticate(self, method_id: str, **kwargs: Any) -> None:
        # Terminal auth: the client runs `superqode local init --repo .` itself;
        # nothing to complete on the agent side.
        return None

    # -- sessions ---------------------------------------------------------------

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        from superqode.harness import FileHarnessStore, init_harness

        working_dir = Path(cwd).expanduser() if cwd else Path.cwd()
        spec = self._load_spec(working_dir)
        provider, model = resolve_provider_model(spec, self._provider, self._model)
        if not provider or not model:
            raise RequestError.invalid_params(
                {
                    "reason": (
                        "No provider/model resolved for this session. Set "
                        "`model_policy.primary` in the harness spec, or set "
                        "SUPERQODE_ACP_PROVIDER / SUPERQODE_ACP_MODEL."
                    ),
                    "spec": spec.name,
                }
            )
        storage = Path(spec.context.session_storage)
        if not storage.is_absolute():
            storage = working_dir / storage
        kernel = await init_harness(spec, store=FileHarnessStore(storage))
        session = await kernel.session()
        self._sessions[session.session_id] = _AcpSessionState(
            session=session,
            spec=spec,
            provider=provider,
            model=model,
            cwd=working_dir,
        )
        return NewSessionResponse(session_id=session.session_id)

    async def close_session(self, session_id: str, **kwargs: Any) -> None:
        self._sessions.pop(session_id, None)
        return None

    async def set_session_model(self, model_id: str, session_id: str, **kwargs: Any) -> None:
        """Switch the session's model; accepts `provider/model` or bare model ids.

        Returns None so the handler works across agent-client-protocol versions:
        0.10 accepts None for session/set_model, and 0.11 removed the method from
        the protocol (clients on 0.11 simply never route it here).
        """
        from superqode.providers.model_specs import split_provider_model_ref

        state = self._sessions.get(session_id)
        if state is None:
            raise RequestError.invalid_params({"reason": f"Unknown session: {session_id}"})
        parsed = split_provider_model_ref(str(model_id))
        if parsed.provider:
            state.provider = parsed.provider
            state.model = parsed.model
        else:
            state.model = str(model_id)
        return None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        state = self._sessions.get(session_id)
        if state is not None:
            state.cancel_event.set()

    # -- prompting ---------------------------------------------------------------

    async def prompt(
        self,
        prompt: list[Any],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        state = self._sessions.get(session_id)
        if state is None:
            raise RequestError.invalid_params({"reason": f"Unknown session: {session_id}"})
        text = _prompt_to_text(prompt)
        if not text:
            return PromptResponse(stop_reason="end_turn")
        state.cancel_event = asyncio.Event()
        tracker = _ToolCallTracker()
        try:
            cancelled = await self._stream_turn(state, text, tracker)
            if not cancelled:
                cancelled = await self._resolve_approvals(state, tracker)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_update(
                session_id,
                update_agent_message_text(f"SuperQode harness run failed: {exc}"),
            )
            return PromptResponse(stop_reason="end_turn")
        return PromptResponse(stop_reason="cancelled" if cancelled else "end_turn")

    async def _stream_turn(
        self, state: _AcpSessionState, text: str, tracker: _ToolCallTracker
    ) -> bool:
        """Stream one harness turn to the client. Returns True when cancelled."""
        stream = state.session.stream(
            text,
            provider=state.provider,
            model=state.model,
            working_directory=state.cwd,
            sandbox_backend=state.spec.execution_policy.sandbox,
        )
        iterator = stream.__aiter__()
        try:
            while True:
                next_task = asyncio.ensure_future(anext(iterator, _STREAM_DONE))
                cancel_task = asyncio.ensure_future(state.cancel_event.wait())
                done, _ = await asyncio.wait(
                    {next_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if next_task not in done:
                    next_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await next_task
                    return True
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task
                event = next_task.result()
                if event is _STREAM_DONE:
                    return False
                await self._dispatch_event(state, event, tracker)
        finally:
            with contextlib.suppress(Exception):
                await iterator.aclose()

    async def _dispatch_event(
        self, state: _AcpSessionState, event: Any, tracker: _ToolCallTracker
    ) -> None:
        session_id = state.session.session_id
        data = dict(getattr(event, "data", {}) or {})
        event_type = getattr(event, "type", "")
        if event_type in ("delta", "model_delta"):
            text = data.get("text") or ""
            if text:
                await self._send_update(session_id, update_agent_message_text(text))
        elif event_type == "thinking":
            text = data.get("text") or ""
            if text:
                await self._send_update(session_id, update_agent_thought_text(text))
        elif event_type == "tool_call":
            name = str(data.get("tool_name") or "tool")
            call_id = tracker.start(name)
            await self._send_update(
                session_id,
                start_tool_call(
                    call_id,
                    name,
                    kind=_tool_kind(name),
                    status="in_progress",
                    raw_input=data.get("arguments"),
                ),
            )
        elif event_type == "tool_result":
            name = str(data.get("tool_name") or "tool")
            call_id = tracker.finish(name)
            if call_id is None:
                return
            success = data.get("success", True)
            output = data.get("output") if success else (data.get("error") or data.get("output"))
            content = []
            if output:
                content.append(tool_content(text_block(_clip(output))))
            await self._send_update(
                session_id,
                update_tool_call(
                    call_id,
                    status="completed" if success else "failed",
                    content=content or None,
                    raw_output=output,
                ),
            )

    async def _resolve_approvals(self, state: _AcpSessionState, tracker: _ToolCallTracker) -> bool:
        """Relay pending harness approvals as ACP permission requests."""
        session = state.session
        while True:
            pending = session.pending_approvals()
            if not pending:
                return False
            if state.cancel_event.is_set() or self._conn is None:
                return True
            item = dict(pending[0])
            tool_name = str(item.get("tool_name") or "tool")
            call_id = str(item.get("tool_call_id") or tracker.start(tool_name))
            response = await self._conn.request_permission(
                options=[
                    PermissionOption(option_id="allow_once", name="Allow once", kind="allow_once"),
                    PermissionOption(
                        option_id="allow_always", name="Always allow", kind="allow_always"
                    ),
                    PermissionOption(option_id="reject_once", name="Reject", kind="reject_once"),
                ],
                session_id=session.session_id,
                tool_call=ToolCallUpdate(
                    tool_call_id=call_id,
                    title=tool_name,
                    kind=_tool_kind(tool_name),
                    status="pending",
                    raw_input=item.get("arguments"),
                ),
            )
            outcome = getattr(response, "outcome", None)
            selected = getattr(outcome, "outcome", "") == "selected"
            option_id = getattr(outcome, "option_id", "")
            if selected and option_id in ("allow_once", "allow_always"):
                result = await session.approve_pending(0, always=option_id == "allow_always")
            elif selected:
                result = await session.reject_pending(0)
            else:
                # Client cancelled the permission prompt: reject and stop the turn.
                await session.reject_pending(0, message="Cancelled from the editor")
                return True
            content = getattr(result, "content", "") or ""
            if content:
                await self._send_update(session.session_id, update_agent_message_text(content))

    # -- helpers ---------------------------------------------------------------

    def _load_spec(self, cwd: Path) -> Any:
        from superqode.harness import load_harness_spec
        from superqode.harness.templates import coding_template, get_harness_template

        explicit = str(self._spec_path or os.environ.get("SUPERQODE_ACP_SPEC", "")).strip()
        if explicit:
            # `template:<name>` selects a built-in template — no spec file needed,
            # which is how benchmark containers pin a harness variant per run.
            if explicit.startswith("template:"):
                return get_harness_template(explicit.removeprefix("template:"))
            return load_harness_spec(Path(explicit).expanduser())
        found = discover_session_spec(cwd, self._harness_dir)
        if found is not None:
            return load_harness_spec(found)
        return coding_template()

    async def _send_update(self, session_id: str, update: Any) -> None:
        if self._conn is None:
            return
        await self._conn.session_update(session_id=session_id, update=update)


async def run_acp_server(
    *,
    spec_path: Path | None = None,
    harness_dir: Path | None = None,
    provider: str = "",
    model: str = "",
) -> None:
    """Serve SuperQode as an ACP agent on stdio until the client disconnects."""
    agent = SuperQodeAcpAgent(
        spec_path=spec_path,
        harness_dir=harness_dir,
        provider=provider,
        model=model,
    )
    await run_agent(agent)
