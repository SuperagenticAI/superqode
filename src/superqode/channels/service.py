"""The channel service: chat surfaces as remote control for local agent runs.

One agent session per chat (a :class:`superqode.pure_mode.PureMode`), driven
by messages a transport thread hands over. The service owns an asyncio loop;
transports call :meth:`ChannelService.submit` from their threads and the
work is marshalled across with ``run_coroutine_threadsafe``.

The feature set is deliberately the remote-control surface for Local Agentic
Coding: run prompts, watch progress, approve or deny tool calls, steer a live
run, and manage the session. It mirrors the TUI's approval semantics exactly
(pause on approval, approve_and_resume / reject_and_resume).

Outbound traffic goes through a :class:`Replier`. ``thread_id`` carries the
platform's threading handle (Slack ``thread_ts``); transports without
threads ignore it. ``send_approval`` and ``send_done`` let transports attach
native buttons; the plain text always contains the typed-command fallback.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple

from .config import ChannelsConfig

MAX_REPLY_CHARS = 3500  # transports chunk further to their own platform limits

HELP_TEXT = """🤖 SuperQode remote control

Plain text runs the agent; while a run is active, plain text steers it.

/status   session, model, and run state
/approve [always]   approve the pending tool call
/deny [reason]      reject the pending tool call
/stop     cancel the active run
/new      start a fresh session
/model <provider/model>   switch model
/cd <path>                switch working directory
/help     this message"""

PAIRING_TEXT = (
    "🔒 This chat is not authorized for SuperQode.\n"
    "To pair it, add this chat id to ~/.superqode/channels.yaml under "
    "allowed_{kind}_ids and restart the daemon:\n\n  {chat_id}"
)


@dataclass
class InboundMessage:
    platform: str  # telegram | slack | discord
    chat_id: str
    user_id: str = ""
    text: str = ""
    callback_data: str = ""  # button presses (inline keyboards / components)
    thread_id: str = ""  # platform thread handle (slack thread_ts)


class Replier(Protocol):
    """What a transport must provide for outbound traffic. Thread-safe."""

    def send(self, chat_id: str, text: str, thread_id: str = "") -> None: ...

    def send_approval(self, chat_id: str, text: str, thread_id: str = "") -> None:
        """Approval request; transports with buttons attach Approve/Deny."""
        ...

    def send_done(self, chat_id: str, text: str, thread_id: str = "") -> None:
        """Run-completion message; transports may attach Status/New/Stop."""
        ...


@dataclass
class ChatSession:
    platform: str
    chat_id: str
    pure: Any  # superqode.pure_mode.PureMode
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    busy: bool = False
    last_error: str = ""
    thread_id: str = ""  # thread of the message that started the active run


class ProgressReporter:
    """Edits the 'Working on it' message in place as tools execute.

    Hooked to ``PureMode.on_tool_call`` (sync, fired from the agent loop), so
    the platform HTTP call runs on a worker thread and edits are throttled to
    one per ``min_interval`` seconds. Transports without ``send_tracked`` and
    ``edit`` silently degrade to the static working message.
    """

    def __init__(
        self,
        replier: Any,
        chat_id: str,
        thread_id: str,
        min_interval: float = 1.5,
    ) -> None:
        self._replier = replier
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._min_interval = min_interval
        self._handle: Optional[str] = None
        self._steps = 0
        self._last_edit = 0.0
        self._lock = threading.Lock()

    def start(self, text: str) -> None:
        send_tracked = getattr(self._replier, "send_tracked", None)
        if callable(send_tracked):
            self._handle = send_tracked(self._chat_id, text, thread_id=self._thread_id)
        else:
            self._replier.send(self._chat_id, text, thread_id=self._thread_id)

    def on_tool_call(self, name: str, arguments: Any) -> None:
        if self._handle is None:
            return
        with self._lock:
            self._steps += 1
            step = self._steps
        preview = ""
        if isinstance(arguments, dict) and arguments:
            first_value = str(next(iter(arguments.values())))
            preview = f": {first_value[:80]}"
        text = f"🤖 Working ({step} tool calls)\n🛠️ {name}{preview}"
        threading.Thread(target=self._edit_throttled, args=(text,), daemon=True).start()

    def _edit_throttled(self, text: str) -> None:
        import time

        with self._lock:
            now = time.monotonic()
            if now - self._last_edit < self._min_interval:
                return
            self._last_edit = now
        edit = getattr(self._replier, "edit", None)
        if callable(edit):
            try:
                edit(self._chat_id, self._handle, text, thread_id=self._thread_id)
            except Exception:
                pass

    def finish(self, text: str) -> None:
        edit = getattr(self._replier, "edit", None)
        if self._handle is not None and callable(edit) and self._steps:
            try:
                edit(self._chat_id, self._handle, text, thread_id=self._thread_id)
            except Exception:
                pass


class ChannelService:
    """Routes chat messages to per-chat agent sessions."""

    def __init__(self, config: ChannelsConfig) -> None:
        self.config = config
        self._sessions: Dict[Tuple[str, str], ChatSession] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._stopping = False

    # ------------------------------------------------------------ lifecycle

    def run_forever(self) -> None:
        """Run the service event loop in the calling thread (blocks)."""
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._loop_ready.set()
        while not self._stopping:
            await asyncio.sleep(0.5)

    def stop(self) -> None:
        self._stopping = True

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._loop_ready.wait(timeout)

    # ------------------------------------------------------------- ingress

    def submit(self, message: InboundMessage, replier: Replier) -> None:
        """Thread-safe entry point for transports. Returns immediately."""
        loop = self._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._handle(message, replier), loop)

    # ------------------------------------------------------------ allowlist

    def _allowed(self, message: InboundMessage) -> bool:
        if message.platform == "telegram":
            allowed = self.config.telegram.allowed_chat_ids
        elif message.platform == "slack":
            allowed = self.config.slack.allowed_channel_ids
        elif message.platform == "discord":
            allowed = self.config.discord.allowed_channel_ids
        else:
            return False
        return message.chat_id in allowed

    # ------------------------------------------------------------- handling

    async def _handle(self, message: InboundMessage, replier: Replier) -> None:
        try:
            await self._handle_inner(message, replier)
        except Exception as exc:  # never let one message kill the loop
            try:
                replier.send(
                    message.chat_id,
                    f"❌ SuperQode error: {type(exc).__name__}: {exc}",
                    thread_id=message.thread_id,
                )
            except Exception:
                pass

    async def _handle_inner(self, message: InboundMessage, replier: Replier) -> None:
        if not self._allowed(message):
            kind = "chat" if message.platform == "telegram" else "channel"
            replier.send(
                message.chat_id,
                PAIRING_TEXT.format(kind=kind, chat_id=message.chat_id),
                thread_id=message.thread_id,
            )
            return

        text = (message.callback_data or message.text or "").strip()
        if not text:
            return

        session = self._get_session(message.platform, message.chat_id)
        thread_id = message.thread_id

        if text.startswith("/"):
            await self._handle_command(session, text, replier, thread_id)
            return

        if session.busy:
            steered = bool(session.pure.steer(text))
            if steered:
                replier.send(
                    session.chat_id,
                    "↪️ Steering the active run with your message.",
                    thread_id=thread_id or session.thread_id,
                )
            else:
                replier.send(
                    session.chat_id,
                    "⏳ A run is active but could not be steered right now. "
                    "Use /stop to cancel it, or wait for it to finish.",
                    thread_id=thread_id or session.thread_id,
                )
            return

        await self._run_prompt(session, text, replier, thread_id)

    async def _handle_command(
        self, session: ChatSession, text: str, replier: Replier, thread_id: str
    ) -> None:
        parts = text.split(maxsplit=1)
        command = parts[0].lower().split("@", 1)[0]  # strip telegram @botname suffix
        argument = parts[1].strip() if len(parts) > 1 else ""

        if command in ("/start", "/help"):
            replier.send(session.chat_id, HELP_TEXT, thread_id=thread_id)
        elif command == "/status":
            replier.send(session.chat_id, self._status_text(session), thread_id=thread_id)
        elif command == "/new":
            self._sessions.pop((session.platform, session.chat_id), None)
            replier.send(session.chat_id, "✨ Fresh session started.", thread_id=thread_id)
        elif command == "/stop":
            if session.busy:
                session.pure.cancel()
                replier.send(session.chat_id, "🛑 Cancelling the active run.", thread_id=thread_id)
            else:
                replier.send(session.chat_id, "No active run.", thread_id=thread_id)
        elif command == "/approve":
            await self._decide(
                session, replier, thread_id, approve=True, always=argument.lower() == "always"
            )
        elif command == "/deny":
            await self._decide(session, replier, thread_id, approve=False, reason=argument or None)
        elif command == "/model":
            from superqode.providers.model_specs import split_provider_model_ref

            if "/" not in argument and not argument.startswith("hf."):
                replier.send(session.chat_id, "Usage: /model <provider/model>", thread_id=thread_id)
                return
            parsed = split_provider_model_ref(argument)
            provider, model = parsed.provider, parsed.model
            if not provider or not model:
                replier.send(session.chat_id, "Usage: /model <provider/model>", thread_id=thread_id)
                return
            session.pure.connect(provider, model, working_directory=self._cwd())
            replier.send(
                session.chat_id,
                f"🧠 Model set to {provider}/{model}.",
                thread_id=thread_id,
            )
        elif command == "/cd":
            target = Path(argument).expanduser()
            if not target.is_dir():
                replier.send(session.chat_id, f"❌ Not a directory: {target}", thread_id=thread_id)
                return
            session.pure.connect(
                session.pure.session.provider,
                session.pure.session.model,
                working_directory=target,
            )
            replier.send(session.chat_id, f"📁 Working directory: {target}", thread_id=thread_id)
        else:
            replier.send(
                session.chat_id, f"Unknown command {command}. Try /help.", thread_id=thread_id
            )

    # ------------------------------------------------------------ the runs

    async def _run_prompt(
        self, session: ChatSession, prompt: str, replier: Replier, thread_id: str
    ) -> None:
        async with session.lock:
            session.busy = True
            session.thread_id = thread_id
            progress = ProgressReporter(replier, session.chat_id, thread_id)
            progress.start("🤖 Working on it. Plain text now steers the run.")
            session.pure.on_tool_call = progress.on_tool_call
            try:
                response = await session.pure.run(prompt)
            except Exception as exc:
                session.last_error = str(exc)
                replier.send(
                    session.chat_id,
                    f"❌ Run failed: {type(exc).__name__}: {exc}",
                    thread_id=thread_id,
                )
                return
            finally:
                session.busy = False
                session.pure.on_tool_call = None
                progress.finish("🤖 Finished working.")
            self._deliver_response(session, response, replier, thread_id)

    async def _decide(
        self,
        session: ChatSession,
        replier: Replier,
        thread_id: str,
        *,
        approve: bool,
        always: bool = False,
        reason: Optional[str] = None,
    ) -> None:
        thread_id = thread_id or session.thread_id
        pending = session.pure.get_pending_approvals()
        if not pending:
            replier.send(session.chat_id, "No pending approval.", thread_id=thread_id)
            return
        try:
            if approve:
                response = await session.pure.approve_and_resume(index=0, always=always)
                replier.send(
                    session.chat_id,
                    "✅ Approved" + (" (always)" if always else "") + ".",
                    thread_id=thread_id,
                )
            else:
                response = await session.pure.reject_and_resume(index=0, message=reason)
                replier.send(
                    session.chat_id,
                    "🚫 Denied" + (f": {reason}" if reason else "") + ".",
                    thread_id=thread_id,
                )
        except Exception as exc:
            replier.send(
                session.chat_id,
                f"❌ Decision failed: {type(exc).__name__}: {exc}",
                thread_id=thread_id,
            )
            return
        self._deliver_response(session, response, replier, thread_id)

    def _deliver_response(
        self, session: ChatSession, response: Any, replier: Replier, thread_id: str
    ) -> None:
        stopped = getattr(response, "stopped_reason", "")
        if stopped == "needs_approval":
            self._send_approval_request(session, replier, thread_id)
            return
        error = getattr(response, "error", None)
        if error:
            replier.send(session.chat_id, f"❌ Run failed: {error}", thread_id=thread_id)
            return
        content = (getattr(response, "content", "") or "").strip()
        text = "✅ Done\n\n" + (content if content else "(no text output)")
        footer = self._runtime_footer(session)
        if footer:
            text = text[: MAX_REPLY_CHARS * 8] + f"\n\n{footer}"
        send_done = getattr(replier, "send_done", None)
        if callable(send_done):
            send_done(session.chat_id, text[: MAX_REPLY_CHARS * 8 + 200], thread_id=thread_id)
        else:
            replier.send(session.chat_id, text[: MAX_REPLY_CHARS * 8 + 200], thread_id=thread_id)

    def _send_approval_request(
        self, session: ChatSession, replier: Replier, thread_id: str
    ) -> None:
        pending = session.pure.get_pending_approvals()
        if not pending:
            replier.send(
                session.chat_id,
                "Run paused for approval, but nothing is pending.",
                thread_id=thread_id,
            )
            return
        entry = pending[0]
        tool = str(entry.get("tool_name") or "<unknown>")
        args_preview = str(entry.get("arguments") or {})
        if len(args_preview) > 300:
            args_preview = args_preview[:297] + "..."
        text = (
            "🔐 Tool approval needed\n\n"
            f"🛠️ tool: {tool}\n"
            f"📋 args: {args_preview}\n\n"
            "Reply /approve, /approve always, or /deny [reason]."
        )
        send_approval = getattr(replier, "send_approval", None)
        if callable(send_approval):
            send_approval(session.chat_id, text, thread_id=thread_id)
        else:
            replier.send(session.chat_id, text, thread_id=thread_id)

    # ------------------------------------------------------------- sessions

    def _get_session(self, platform: str, chat_id: str) -> ChatSession:
        key = (platform, chat_id)
        existing = self._sessions.get(key)
        if existing is not None:
            return existing

        from superqode.pure_mode import PureMode

        pure = PureMode()
        defaults = self.config.defaults
        if defaults.harness:
            try:
                pure.load_harness(defaults.harness)
            except Exception:
                pass
        provider = defaults.provider or "ollama"
        model = defaults.model or ""
        pure.connect(provider, model, working_directory=self._cwd())
        session = ChatSession(platform=platform, chat_id=chat_id, pure=pure)
        self._sessions[key] = session
        return session

    def _cwd(self) -> Path:
        raw = self.config.defaults.working_directory
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                return candidate
        return Path.cwd()

    def _runtime_footer(self, session: ChatSession) -> str:
        """Compact `model · cwd` line for the final message of a turn."""
        try:
            status = session.pure.get_status()
            model = f"{status.get('provider')}/{status.get('model')}"
            cwd = str(status.get("working_directory") or "")
            home = str(Path.home())
            if cwd.startswith(home):
                cwd = "~" + cwd[len(home) :]
            return f"🧠 {model} · 📁 {cwd}"
        except Exception:
            return ""

    def _status_text(self, session: ChatSession) -> str:
        pure = session.pure
        status = pure.get_status()
        stats = status.get("stats", {})
        lines = [
            "⚙️ SuperQode session",
            f"🧠 Model: {status.get('provider')}/{status.get('model')}",
            f"📁 Home: {status.get('working_directory')}",
            f"{'🏃 Run active: yes' if session.busy else '💤 Run active: no'}",
            f"📊 Requests: {stats.get('total_requests', 0)}, "
            f"tool calls: {stats.get('total_tool_calls', 0)}",
        ]
        harness = status.get("harness", {})
        if isinstance(harness, dict) and harness.get("enabled"):
            lines.append(f"⚓ Harness: {pure.session.harness_name}")
        pending = pure.get_pending_approvals()
        if pending:
            lines.append(f"🔐 Pending approvals: {len(pending)} (reply /approve or /deny)")
        if session.last_error:
            lines.append(f"⚠️ Last error: {session.last_error[:200]}")
        return "\n".join(lines)


__all__ = ["ChannelService", "ChatSession", "InboundMessage", "Replier", "HELP_TEXT"]
