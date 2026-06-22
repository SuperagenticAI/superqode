"""Discord transport over the Gateway websocket.

Requires the optional ``websocket-client`` package (``superqode[channels]``)
and a Discord bot with the Message Content intent enabled. The runner speaks
the Gateway protocol directly: hello, heartbeat thread, identify with the
guild-message + DM + message-content intents, and reconnect on op 7/9 or
socket errors. Outbound replies go through the REST API, chunked to
Discord's 2000-character message limit.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen

from .config import DiscordConfig
from .service import ChannelService, InboundMessage
from .telegram import chunk_text

DISCORD_API = "https://discord.com/api/v10"
DISCORD_MESSAGE_LIMIT = 2000
# GUILDS | GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT
DISCORD_INTENTS = 1 | 512 | 4096 | 32768


class DiscordUnavailableError(RuntimeError):
    """Raised when the Discord transport cannot start."""


def discord_api_call(
    bot_token: str,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    request = Request(
        f"{DISCORD_API}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "SuperQode (https://github.com/SuperagenticAI/superqode)",
        },
        method=method,
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read().decode("utf-8")
    body = json.loads(raw) if raw else {}
    return body if isinstance(body, dict) else {}


def _button_row(buttons: list) -> Dict[str, Any]:
    """A components action row; each button is (label, command, style)."""
    return {
        "type": 1,
        "components": [
            {"type": 2, "style": style, "label": label, "custom_id": command}
            for label, command, style in buttons
        ],
    }


class DiscordReplier:
    """Outbound REST side. Thread-safe.

    Discord threads are separate channels, so ``thread_id`` is ignored;
    replies land in the channel the message came from.
    """

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token

    def _post(self, chat_id: str, content: str, components: Optional[list] = None) -> Optional[str]:
        payload: Dict[str, Any] = {"content": content}
        if components:
            payload["components"] = components
        try:
            body = discord_api_call(
                self._bot_token, "POST", f"/channels/{chat_id}/messages", payload
            )
        except Exception as exc:
            print(f"SuperQode Discord send failed: {exc}", flush=True)
            return None
        return str(body.get("id") or "") or None

    def send(self, chat_id: str, text: str, thread_id: str = "") -> None:
        for chunk in chunk_text(text, limit=DISCORD_MESSAGE_LIMIT):
            self._post(chat_id, chunk)

    def send_tracked(self, chat_id: str, text: str, thread_id: str = "") -> Optional[str]:
        """Send one message and return its id for later PATCH edits."""
        chunks = chunk_text(text, limit=DISCORD_MESSAGE_LIMIT)
        return self._post(chat_id, chunks[0]) if chunks else None

    def edit(self, chat_id: str, handle: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text, limit=DISCORD_MESSAGE_LIMIT)
        if not handle or not chunks:
            return
        try:
            discord_api_call(
                self._bot_token,
                "PATCH",
                f"/channels/{chat_id}/messages/{handle}",
                {"content": chunks[0]},
            )
        except Exception:
            pass

    def send_approval(self, chat_id: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text, limit=DISCORD_MESSAGE_LIMIT)
        # Styles: 3=success(green), 2=secondary(grey), 4=danger(red)
        self._post(
            chat_id,
            chunks[0] if chunks else "Tool approval needed.",
            components=[
                _button_row(
                    [
                        ("Approve", "/approve", 3),
                        ("Always", "/approve always", 2),
                        ("Deny", "/deny", 4),
                    ]
                )
            ],
        )

    def send_done(self, chat_id: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text, limit=DISCORD_MESSAGE_LIMIT)
        if not chunks:
            return
        for chunk in chunks[:-1]:
            self._post(chat_id, chunk)
        self._post(
            chat_id,
            chunks[-1],
            components=[
                _button_row([("Status", "/status", 2), ("New", "/new", 2), ("Stop", "/stop", 4)])
            ],
        )


class DiscordRunner:
    """Gateway loop feeding the channel service. Runs in a thread."""

    def __init__(self, config: DiscordConfig, service: ChannelService) -> None:
        self.config = config
        self.service = service
        self.replier = DiscordReplier(config.bot_token)
        self._seq: Optional[int] = None
        self._bot_user_id: str = ""
        self._heartbeat_stop: Optional[threading.Event] = None
        self._seen_messages: deque = deque(maxlen=500)
        self._stopping = False

    def validate(self) -> None:
        if not self.config.bot_token:
            raise DiscordUnavailableError(
                "Discord needs a bot token (SUPERQODE_DISCORD_BOT_TOKEN or channels.yaml)."
            )
        try:
            import websocket  # noqa: F401
        except ImportError as exc:
            raise DiscordUnavailableError(
                "Discord Gateway requires the websocket-client package: "
                "uv tool install 'superqode[channels]'"
            ) from exc
        discord_api_call(self.config.bot_token, "GET", "/gateway/bot")

    def stop(self) -> None:
        self._stopping = True

    def run_forever(self) -> None:
        self.validate()
        import websocket

        backoff = 2.0
        while not self._stopping:
            ws = None
            heartbeat_thread = None
            try:
                gateway = discord_api_call(self.config.bot_token, "GET", "/gateway/bot")
                url = str(gateway.get("url") or "").strip()
                if not url:
                    raise DiscordUnavailableError("Discord gateway URL missing.")
                ws = websocket.create_connection(f"{url}?v=10&encoding=json", timeout=30)
                hello = json.loads(ws.recv())
                if int(hello.get("op") or 0) != 10:
                    raise DiscordUnavailableError("Discord gateway hello was not received.")
                heartbeat_interval = int((hello.get("d") or {}).get("heartbeat_interval") or 45000)
                # Read timeout comfortably above heartbeat cadence so idle
                # periods do not trigger false reconnect loops.
                ws.settimeout(max(120.0, (heartbeat_interval / 1000.0) * 3.0))
                self._heartbeat_stop = threading.Event()
                heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop,
                    args=(ws, heartbeat_interval / 1000.0),
                    daemon=True,
                )
                heartbeat_thread.start()
                ws.send(
                    json.dumps(
                        {
                            "op": 2,
                            "d": {
                                "token": self.config.bot_token,
                                "intents": DISCORD_INTENTS,
                                "properties": {
                                    "os": "local",
                                    "browser": "superqode",
                                    "device": "superqode",
                                },
                            },
                        }
                    )
                )
                print("SuperQode Discord Gateway connected.", flush=True)
                backoff = 2.0  # healthy connection resets the backoff
                self._receive_loop(ws)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"SuperQode Discord Gateway error: {exc}", flush=True)
                # Exponential backoff; 429s especially must not be hammered.
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            finally:
                if self._heartbeat_stop is not None:
                    self._heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1.0)
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

    # ------------------------------------------------------------ internals

    def _receive_loop(self, ws: Any) -> None:
        while not self._stopping:
            payload = json.loads(ws.recv())
            op = int(payload.get("op") or 0)
            seq = payload.get("s")
            if seq is not None:
                self._seq = int(seq)
            if op == 0:
                self._handle_dispatch(str(payload.get("t") or ""), payload.get("d") or {})
            elif op == 7:  # reconnect requested
                return
            elif op == 9:  # invalid session
                time.sleep(2.0)
                return

    def _handle_dispatch(self, event_type: str, event: Dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        if event_type == "READY":
            user = event.get("user") or {}
            if isinstance(user, dict):
                self._bot_user_id = str(user.get("id") or "")
            return
        if event_type == "INTERACTION_CREATE":
            self._handle_interaction(event)
            return
        if event_type != "MESSAGE_CREATE":
            return
        message_id = str(event.get("id") or "")
        if message_id:
            if message_id in self._seen_messages:
                return
            self._seen_messages.append(message_id)
        author = event.get("author") or {}
        if not isinstance(author, dict) or author.get("bot"):
            return
        author_id = str(author.get("id") or "")
        if self._bot_user_id and author_id == self._bot_user_id:
            return
        channel_id = str(event.get("channel_id") or "").strip()
        text = str(event.get("content") or "").strip()
        if not channel_id or not text:
            return
        self.service.submit(
            InboundMessage(
                platform="discord",
                chat_id=channel_id,
                user_id=author_id,
                text=text,
            ),
            self.replier,
        )

    def _handle_interaction(self, event: Dict[str, Any]) -> None:
        """Button presses: custom_id is the same slash command a user types."""
        if int(event.get("type") or 0) != 3:  # 3 = message component
            return
        interaction_id = str(event.get("id") or "")
        if interaction_id:
            if interaction_id in self._seen_messages:
                return
            self._seen_messages.append(interaction_id)
        data = event.get("data") or {}
        command = str(data.get("custom_id") or "").strip() if isinstance(data, dict) else ""
        channel_id = str(event.get("channel_id") or "").strip()
        member = event.get("member") or {}
        user = member.get("user") if isinstance(member, dict) else None
        if not isinstance(user, dict):
            user = event.get("user") or {}
        user_id = str(user.get("id") or "") if isinstance(user, dict) else ""
        # Ack within 3 seconds (type 6: deferred update, no visible reply)
        # or Discord shows "This interaction failed".
        token = str(event.get("token") or "")
        if interaction_id and token:
            try:
                discord_api_call(
                    self.config.bot_token,
                    "POST",
                    f"/interactions/{interaction_id}/{token}/callback",
                    {"type": 6},
                )
            except Exception:
                pass
        if not command or not channel_id:
            return
        self.service.submit(
            InboundMessage(
                platform="discord",
                chat_id=channel_id,
                user_id=user_id,
                callback_data=command,
            ),
            self.replier,
        )

    def _heartbeat_loop(self, ws: Any, interval_seconds: float) -> None:
        stop = self._heartbeat_stop
        if stop is None:
            return
        while not stop.wait(timeout=interval_seconds):
            try:
                ws.send(json.dumps({"op": 1, "d": self._seq}))
            except Exception:
                return


__all__ = [
    "DiscordReplier",
    "DiscordRunner",
    "DiscordUnavailableError",
    "discord_api_call",
]
