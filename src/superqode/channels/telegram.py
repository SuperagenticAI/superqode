"""Telegram transport: stdlib-only Bot API client with long polling.

The runner long-polls ``getUpdates`` (25s timeout), persists the update
offset so restarts never replay old messages, and hands each message or
button press to the :class:`~superqode.channels.service.ChannelService`.
Approval requests go out with inline Approve / Always / Deny buttons; the
button press arrives back as a ``callback_query`` whose data is the same
``/approve`` or ``/deny`` command a user could type.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import STATE_DIR, TelegramConfig
from .service import ChannelService, InboundMessage

TELEGRAM_MESSAGE_LIMIT = 4096
POLL_TIMEOUT = 25

BOT_COMMANDS = [
    {"command": "status", "description": "Session, model, and run state"},
    {"command": "approve", "description": "Approve the pending tool call"},
    {"command": "deny", "description": "Reject the pending tool call"},
    {"command": "stop", "description": "Cancel the active run"},
    {"command": "new", "description": "Start a fresh session"},
    {"command": "help", "description": "Show all commands"},
]


class TelegramUnavailableError(RuntimeError):
    """Raised when the Telegram transport cannot start."""


def telegram_api_call(
    bot_token: str,
    method: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 35.0,
) -> Dict[str, Any]:
    request = Request(
        f"https://api.telegram.org/bot{quote(bot_token)}/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description", "unknown_error") if isinstance(body, dict) else body
        raise RuntimeError(f"Telegram {method} failed: {description}")
    return body


def chunk_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """Split a long reply on line boundaries, hard-splitting oversized lines."""
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current)
    return [c.rstrip("\n") for c in chunks if c.strip()]


class TelegramReplier:
    """Outbound side handed to the service. Safe to call from any thread.

    Telegram has no reply threads; ``thread_id`` is accepted and ignored.
    """

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token

    def _post(
        self, chat_id: str, text: str, reply_markup: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        payload: Dict[str, Any] = {
            "chat_id": int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            body = telegram_api_call(self._bot_token, "sendMessage", payload)
        except Exception as exc:
            print(f"SuperQode Telegram send failed: {exc}", flush=True)
            return None
        result = body.get("result") or {}
        return str(result.get("message_id") or "") or None

    def send(self, chat_id: str, text: str, thread_id: str = "") -> None:
        for chunk in chunk_text(text):
            self._post(chat_id, chunk)

    def send_tracked(self, chat_id: str, text: str, thread_id: str = "") -> Optional[str]:
        """Send one message and return a handle for later edits."""
        chunks = chunk_text(text)
        return self._post(chat_id, chunks[0]) if chunks else None

    def edit(self, chat_id: str, handle: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text)
        if not handle or not chunks:
            return
        try:
            telegram_api_call(
                self._bot_token,
                "editMessageText",
                {
                    "chat_id": int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id,
                    "message_id": int(handle),
                    "text": chunks[0],
                },
            )
        except Exception:
            pass  # edit races (same text, deleted message) are not worth noise

    def send_approval(self, chat_id: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text)
        self._post(
            chat_id,
            chunks[0] if chunks else "Tool approval needed.",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve", "callback_data": "/approve"},
                        {"text": "♾️ Always", "callback_data": "/approve always"},
                        {"text": "🚫 Deny", "callback_data": "/deny"},
                    ]
                ]
            },
        )

    def send_done(self, chat_id: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text)
        if not chunks:
            return
        for chunk in chunks[:-1]:
            self._post(chat_id, chunk)
        self._post(
            chat_id,
            chunks[-1],
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "📊 Status", "callback_data": "/status"},
                        {"text": "✨ New", "callback_data": "/new"},
                        {"text": "🛑 Stop", "callback_data": "/stop"},
                    ]
                ]
            },
        )


class TelegramRunner:
    """Long-polling loop feeding the channel service. Runs in a thread."""

    def __init__(
        self,
        config: TelegramConfig,
        service: ChannelService,
        state_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.service = service
        self.replier = TelegramReplier(config.bot_token)
        self._state_dir = state_dir or STATE_DIR
        self._offset_path = self._state_dir / "telegram.offset"
        self._stopping = False

    def validate(self) -> None:
        if not self.config.bot_token:
            raise TelegramUnavailableError(
                "Telegram needs a bot token (SUPERQODE_TELEGRAM_BOT_TOKEN or channels.yaml)."
            )
        telegram_api_call(self.config.bot_token, "getMe")

    def stop(self) -> None:
        self._stopping = True

    def run_forever(self) -> None:
        self.validate()
        try:
            telegram_api_call(self.config.bot_token, "setMyCommands", {"commands": BOT_COMMANDS})
        except Exception as exc:
            print(f"SuperQode Telegram command menu registration failed: {exc}", flush=True)
        offset = self._load_offset()
        while not self._stopping:
            try:
                updates = self._get_updates(offset)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"SuperQode Telegram polling error: {exc}", flush=True)
                time.sleep(2.0)
                continue
            for update in updates:
                offset = int(update.get("update_id") or 0) + 1
                self._store_offset(offset)
                message = self._to_inbound(update)
                if message is not None:
                    self.service.submit(message, self.replier)

    # ------------------------------------------------------------ internals

    def _get_updates(self, offset: Optional[int]) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "timeout": POLL_TIMEOUT,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        body = telegram_api_call(self.config.bot_token, "getUpdates", payload)
        result = body.get("result")
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    def _to_inbound(self, update: Dict[str, Any]) -> Optional[InboundMessage]:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._ack_callback(str(callback.get("id") or ""))
            chat = ((callback.get("message") or {}).get("chat")) or {}
            chat_id = str(chat.get("id") or "").strip()
            data = str(callback.get("data") or "").strip()
            user_id = str((callback.get("from") or {}).get("id") or "")
            if chat_id and data:
                return InboundMessage(
                    platform="telegram",
                    chat_id=chat_id,
                    user_id=user_id,
                    callback_data=data,
                )
            return None
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        text = str(message.get("text") or "").strip()
        user_id = str((message.get("from") or {}).get("id") or "")
        if not chat_id or not text:
            return None
        return InboundMessage(platform="telegram", chat_id=chat_id, user_id=user_id, text=text)

    def _ack_callback(self, callback_id: str) -> None:
        if not callback_id:
            return
        try:
            telegram_api_call(
                self.config.bot_token,
                "answerCallbackQuery",
                {"callback_query_id": callback_id},
            )
        except Exception:
            pass

    def _load_offset(self) -> Optional[int]:
        try:
            return int(self._offset_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _store_offset(self, offset: int) -> None:
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._offset_path.write_text(str(offset), encoding="utf-8")
        except OSError:
            pass


__all__ = [
    "TelegramReplier",
    "TelegramRunner",
    "TelegramUnavailableError",
    "chunk_text",
    "telegram_api_call",
]
