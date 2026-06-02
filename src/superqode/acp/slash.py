"""Local slash command dispatcher for the ACP client.

When the user types something like ``/status`` (or ``:status``) in an ACP
session, two routes are possible:

1. Forward the command to the agent (already supported via
   :meth:`ACPClient.execute_slash_command`).
2. Handle it locally — useful for introspection commands that ask about
   *the connection itself* rather than something the agent should do.

This module owns route 2. It mirrors the spirit of fast-agent's
``acp/slash_commands.py`` + ``acp/slash/dispatch.py`` + ``acp/slash/handlers/``
but in a single small file because the surface is much smaller.

Built-in commands:

* ``status`` — connection status, capabilities, session stats
* ``model`` — currently selected model
* ``session`` — current session id + resume support
* ``history`` — prior persisted sessions for this project
* ``commands`` — agent-advertised slash commands (asks the agent)
* ``clear`` — reset the current session
* ``help`` — list every registered local command

The registry is generic, so callers can register their own handlers
without changing this module.
"""

from __future__ import annotations

import inspect
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from superqode.acp.client import ACPClient


# A handler returns either a string (sync) or an awaitable producing a string.
SlashCommandHandlerFn = Callable[["ACPClient", str], Union[str, Awaitable[str]]]


class UnknownSlashCommandError(KeyError):
    """No handler registered for this command name."""


@dataclass(frozen=True)
class SlashCommandSpec:
    """One registered local slash command."""

    name: str
    description: str
    handler: SlashCommandHandlerFn


def parse_slash_input(line: str) -> Optional[Tuple[str, str]]:
    """Parse a ``/cmd [args]`` or ``:cmd [args]`` line.

    Returns ``(command_name, arguments_string)`` or ``None`` if the line
    isn't a slash command. The arguments string is preserved verbatim
    (callers can ``shlex.split`` it themselves if they want tokens).
    """
    if not line:
        return None
    stripped = line.lstrip()
    if not stripped:
        return None
    if stripped[0] not in {"/", ":"}:
        return None
    body = stripped[1:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    name = parts[0].strip().lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return (name, args) if name else None


class SlashRegistry:
    """Insertion-ordered registry of local slash commands."""

    def __init__(self) -> None:
        self._commands: Dict[str, SlashCommandSpec] = {}

    def register(self, spec: SlashCommandSpec) -> None:
        """Add or replace a command. Last registration wins."""
        self._commands[spec.name.lower()] = spec

    def unregister(self, name: str) -> bool:
        return self._commands.pop(name.lower(), None) is not None

    def get(self, name: str) -> Optional[SlashCommandSpec]:
        return self._commands.get(name.lower())

    def list_commands(self) -> List[SlashCommandSpec]:
        return list(self._commands.values())

    def has(self, name: str) -> bool:
        return name.lower() in self._commands

    async def dispatch(self, client: "ACPClient", line: str) -> str:
        """Parse and execute ``line`` against ``client``.

        Raises :class:`UnknownSlashCommandError` if the parsed command
        isn't registered. Raises ``ValueError`` if the line doesn't look
        like a slash command at all (no leading ``/`` or ``:``) - callers
        are expected to gate on :func:`parse_slash_input` first.
        """
        parsed = parse_slash_input(line)
        if parsed is None:
            raise ValueError(f"Not a slash command: {line!r}")
        name, args = parsed
        spec = self._commands.get(name)
        if spec is None:
            raise UnknownSlashCommandError(name)
        result = spec.handler(client, args)
        if inspect.isawaitable(result):
            result = await result
        return str(result)


# ---------------------------------------------------------------------------
# Built-in handlers - introspection only (read ACPClient state).
# ---------------------------------------------------------------------------


def _format_capabilities(caps: Dict[str, object]) -> str:
    if not caps:
        return "  (none reported)"
    lines = []
    for key in sorted(caps):
        value = caps[key]
        if isinstance(value, dict):
            sub = ", ".join(f"{k}={v}" for k, v in sorted(value.items()))
            lines.append(f"  {key}: {sub or '<empty>'}")
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


async def handle_status(client: "ACPClient", _args: str) -> str:
    running = "running" if client.is_running() else "stopped"
    stats = client.get_stats()
    caps = client.get_agent_capabilities()
    duration = f"{stats.duration:.1f}s" if stats.duration else "0.0s"
    return (
        f"ACP session: {running}\n"
        f"  session_id: {client.get_session_id() or '<none>'}\n"
        f"  model: {client.get_current_model() or '<none>'}\n"
        f"  duration: {duration}\n"
        f"  tools called: {stats.tool_count}\n"
        f"  files read: {len(stats.files_read)}\n"
        f"  files modified: {len(stats.files_modified)}\n"
        f"capabilities:\n{_format_capabilities(caps)}"
    )


async def handle_model(client: "ACPClient", _args: str) -> str:
    model = client.get_current_model()
    if model:
        return f"current model: {model}"
    return "no model selected"


async def handle_session(client: "ACPClient", _args: str) -> str:
    sid = client.get_session_id() or "<none>"
    resume = "yes" if client.supports_resume() else "no"
    return f"session_id: {sid}\nagent supports resume: {resume}"


async def handle_history(client: "ACPClient", args: str) -> str:
    cwd_only = True
    limit = 20
    for token in shlex.split(args) if args else []:
        if token == "--all":
            cwd_only = False
        elif token.startswith("--limit="):
            try:
                limit = max(1, int(token.split("=", 1)[1]))
            except ValueError:
                pass
    try:
        sessions = await client.list_persisted_sessions(cwd_only=cwd_only, limit=limit)
    except Exception as exc:  # noqa: BLE001 - report rather than crash dispatcher
        return f"history unavailable: {exc}"
    if not sessions:
        scope = "this project" if cwd_only else "all projects"
        return f"no persisted sessions for {scope}"
    lines = [f"sessions ({len(sessions)}, {'cwd' if cwd_only else 'all'}):"]
    for sess in sessions:
        sess_id = getattr(sess, "session_id", None) or getattr(sess, "id", "<?>")
        label = getattr(sess, "label", None) or getattr(sess, "title", "")
        suffix = f"  {label}" if label else ""
        lines.append(f"  {sess_id}{suffix}")
    return "\n".join(lines)


async def handle_commands(client: "ACPClient", _args: str) -> str:
    """List slash commands advertised by the connected agent (server-side)."""
    try:
        agent_commands = await client.get_available_commands()
    except Exception as exc:  # noqa: BLE001
        return f"could not query agent commands: {exc}"
    if not agent_commands:
        return "agent advertises no slash commands"
    lines = ["agent slash commands:"]
    for cmd in agent_commands:
        name = cmd.get("name", "<?>") if isinstance(cmd, dict) else str(cmd)
        desc = cmd.get("description", "") if isinstance(cmd, dict) else ""
        lines.append(f"  /{name}  {desc}".rstrip())
    return "\n".join(lines)


async def handle_clear(client: "ACPClient", _args: str) -> str:
    try:
        ok = await client.reset_session()
    except Exception as exc:  # noqa: BLE001
        return f"clear failed: {exc}"
    return "session cleared" if ok else "session reset returned no change"


def _build_help_handler(registry: "SlashRegistry") -> SlashCommandHandlerFn:
    async def handle_help(_client: "ACPClient", _args: str) -> str:
        specs = sorted(registry.list_commands(), key=lambda s: s.name)
        if not specs:
            return "no local slash commands registered"
        width = max(len(s.name) for s in specs)
        lines = ["local slash commands:"]
        for spec in specs:
            lines.append(f"  /{spec.name.ljust(width)}  {spec.description}")
        return "\n".join(lines)

    return handle_help


def builtin_registry() -> "SlashRegistry":
    """A registry pre-populated with the standard introspection commands."""
    reg = SlashRegistry()
    reg.register(SlashCommandSpec("status", "Show ACP connection status and stats", handle_status))
    reg.register(SlashCommandSpec("model", "Show currently selected model", handle_model))
    reg.register(SlashCommandSpec("session", "Show session id and resume support", handle_session))
    reg.register(
        SlashCommandSpec(
            "history",
            "List persisted sessions (--all for cross-project, --limit=N)",
            handle_history,
        )
    )
    reg.register(
        SlashCommandSpec(
            "commands",
            "List slash commands the connected agent advertises",
            handle_commands,
        )
    )
    reg.register(SlashCommandSpec("clear", "Reset the current ACP session", handle_clear))
    reg.register(SlashCommandSpec("help", "List local slash commands", _build_help_handler(reg)))
    return reg


__all__ = [
    "SlashCommandHandlerFn",
    "SlashCommandSpec",
    "SlashRegistry",
    "UnknownSlashCommandError",
    "builtin_registry",
    "handle_clear",
    "handle_commands",
    "handle_history",
    "handle_model",
    "handle_session",
    "handle_status",
    "parse_slash_input",
]
