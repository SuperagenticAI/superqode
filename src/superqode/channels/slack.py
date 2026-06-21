"""Slack transport over Socket Mode (no public HTTP endpoint needed).

Requires the optional ``websocket-client`` package (``superqode[channels]``)
plus a Slack app with Socket Mode enabled: an app-level token (``xapp-``)
for the connection and a bot token (``xoxb-``) for posting messages.

Behavior:

- Envelopes are acked immediately (Slack retries unacked events).
- The same user message can arrive as both ``app_mention`` and ``message``
  events; both are deduplicated by ``channel:ts`` so it is processed once,
  and a leading ``<@bot>`` mention token is stripped from either shape.
- Replies are threaded under the triggering message, so each task reads as
  one conversation like a code review thread.
- Approval and completion messages carry Block Kit buttons (Approve /
  Always / Deny, Status / New / Stop); presses arrive as ``interactive``
  envelopes whose action value is the same slash command a user could type.
  Buttons need Interactivity enabled on the Slack app; the text fallback
  always works.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from .config import SlackConfig
from .service import ChannelService, InboundMessage
from .telegram import chunk_text

SLACK_MESSAGE_LIMIT = 3500


class SlackUnavailableError(RuntimeError):
    """Raised when the Slack transport cannot start."""


def slack_api_call(
    token: str,
    method: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    request = Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or not body.get("ok"):
        error = body.get("error", "unknown_error") if isinstance(body, dict) else body
        raise RuntimeError(f"Slack {method} failed: {error}")
    return body


def open_socket_mode_url(app_token: str) -> str:
    body = slack_api_call(app_token, "apps.connections.open")
    url = str(body.get("url") or "")
    if not url:
        raise SlackUnavailableError("Slack apps.connections.open returned no websocket URL.")
    return url


def _flatten_rich_text(elements: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        kind = str(element.get("type") or "")
        if kind == "text":
            parts.append(str(element.get("text") or ""))
        elif kind == "link":
            parts.append(str(element.get("url") or ""))
        elif kind == "user":
            user_id = str(element.get("user_id") or "")
            if user_id:
                parts.append(f"<@{user_id}>")
        else:
            nested = element.get("elements")
            if isinstance(nested, list):
                parts.append(_flatten_rich_text(nested))
    return "".join(parts)


def extract_message_text(event: Dict[str, Any]) -> str:
    text = str(event.get("text") or "").strip()
    if text:
        return text
    blocks = event.get("blocks")
    if not isinstance(blocks, list):
        return ""
    parts: List[str] = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("elements"), list):
            flattened = _flatten_rich_text(block["elements"]).strip()
            if flattened:
                parts.append(flattened)
    return "\n".join(parts).strip()


def strip_leading_mention(text: str) -> str:
    """Drop a leading ``<@U...>`` token so mentions become plain commands."""
    stripped = text.strip()
    if stripped.startswith("<@"):
        first, _, rest = stripped.partition(" ")
        if first.endswith(">"):
            return rest.strip()
    return stripped


def _action_buttons(actions: List[tuple]) -> Dict[str, Any]:
    """A Block Kit actions block; each action is (label, command, style|None)."""
    elements = []
    for label, command, style in actions:
        element: Dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": label, "emoji": True},
            "action_id": f"superqode_{command.strip('/').replace(' ', '_')}",
            "value": command,
        }
        if style:
            element["style"] = style
        elements.append(element)
    return {"type": "actions", "elements": elements}


class SlackReplier:
    """Outbound chat.postMessage side. Thread-safe."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token

    def _post(
        self, chat_id: str, text: str, thread_id: str, blocks: Optional[list] = None
    ) -> Optional[str]:
        payload: Dict[str, Any] = {"channel": chat_id, "text": text}
        if thread_id:
            payload["thread_ts"] = thread_id
        if blocks:
            payload["blocks"] = blocks
        try:
            body = slack_api_call(self._bot_token, "chat.postMessage", payload)
        except Exception as exc:
            print(f"SuperQode Slack send failed: {exc}", flush=True)
            return None
        return str(body.get("ts") or "") or None

    def send(self, chat_id: str, text: str, thread_id: str = "") -> None:
        for chunk in chunk_text(text, limit=SLACK_MESSAGE_LIMIT):
            self._post(chat_id, chunk, thread_id)

    def send_tracked(self, chat_id: str, text: str, thread_id: str = "") -> Optional[str]:
        """Send one message and return its ts for later chat.update edits."""
        chunks = chunk_text(text, limit=SLACK_MESSAGE_LIMIT)
        return self._post(chat_id, chunks[0], thread_id) if chunks else None

    def edit(self, chat_id: str, handle: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text, limit=SLACK_MESSAGE_LIMIT)
        if not handle or not chunks:
            return
        try:
            slack_api_call(
                self._bot_token,
                "chat.update",
                {"channel": chat_id, "ts": handle, "text": chunks[0]},
            )
        except Exception:
            pass

    def send_approval(self, chat_id: str, text: str, thread_id: str = "") -> None:
        chunk = chunk_text(text, limit=SLACK_MESSAGE_LIMIT)
        body = chunk[0] if chunk else "Tool approval needed."
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            _action_buttons(
                [
                    ("✅ Approve", "/approve", "primary"),
                    ("♾️ Always", "/approve always", None),
                    ("🚫 Deny", "/deny", "danger"),
                ]
            ),
        ]
        self._post(chat_id, body, thread_id, blocks=blocks)

    def send_done(self, chat_id: str, text: str, thread_id: str = "") -> None:
        chunks = chunk_text(text, limit=SLACK_MESSAGE_LIMIT)
        if not chunks:
            return
        # Body chunks first; buttons ride on the final message.
        for chunk in chunks[:-1]:
            self._post(chat_id, chunk, thread_id)
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": chunks[-1]}},
            _action_buttons(
                [
                    ("📊 Status", "/status", None),
                    ("✨ New", "/new", None),
                    ("🛑 Stop", "/stop", None),
                ]
            ),
        ]
        self._post(chat_id, chunks[-1], thread_id, blocks=blocks)


class SlackRunner:
    """Socket Mode loop feeding the channel service. Runs in a thread."""

    def __init__(self, config: SlackConfig, service: ChannelService) -> None:
        self.config = config
        self.service = service
        self.replier = SlackReplier(config.bot_token)
        self._seen_keys: deque = deque(maxlen=500)
        self._stopping = False

    def validate(self, *, require_socket: bool = True) -> None:
        if not self.config.app_token or not self.config.bot_token:
            raise SlackUnavailableError(
                "Slack needs an app token (xapp-, Socket Mode) and a bot token (xoxb-)."
            )
        if require_socket:
            try:
                import websocket  # noqa: F401
            except ImportError as exc:
                raise SlackUnavailableError(
                    "Slack Socket Mode requires the websocket-client package: "
                    "pip install superqode[channels]"
                ) from exc
        slack_api_call(self.config.bot_token, "auth.test")

    def stop(self) -> None:
        self._stopping = True

    def run_forever(self) -> None:
        self.validate()
        import websocket

        backoff = 1.0
        while not self._stopping:
            try:
                socket_url = open_socket_mode_url(self.config.app_token)
            except Exception as exc:
                print(f"SuperQode Slack connection open failed: {exc}", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 15.0)
                continue

            ws_app = websocket.WebSocketApp(
                socket_url,
                on_message=lambda ws, message: self._on_message(ws, message),
                on_error=lambda ws, error: print(
                    f"SuperQode Slack Socket Mode error: {error}", flush=True
                ),
            )
            try:
                ws_app.run_forever(ping_interval=20, ping_timeout=10)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"SuperQode Slack Socket Mode crashed: {exc}", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 15.0)

    # ------------------------------------------------------------ internals

    def _seen(self, key: str) -> bool:
        if not key:
            return False
        if key in self._seen_keys:
            return True
        self._seen_keys.append(key)
        return False

    def _on_message(self, ws: Any, raw: str) -> None:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(envelope, dict):
            return
        envelope_id = envelope.get("envelope_id")
        if envelope_id:
            # Ack first: Slack retries unacked envelopes aggressively.
            try:
                ws.send(json.dumps({"envelope_id": envelope_id}))
            except Exception:
                pass
        envelope_type = str(envelope.get("type") or "")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return
        if envelope_type == "events_api":
            self._handle_event(payload)
        elif envelope_type == "interactive":
            self._handle_interactive(payload)

    def _handle_event(self, payload: Dict[str, Any]) -> None:
        event = payload.get("event")
        if not isinstance(event, dict):
            return
        message = self._to_inbound(event)
        if message is not None:
            self.service.submit(message, self.replier)

    def _handle_interactive(self, payload: Dict[str, Any]) -> None:
        """Block Kit button presses: the action value is a slash command."""
        if str(payload.get("type") or "") != "block_actions":
            return
        actions = payload.get("actions")
        if not isinstance(actions, list) or not actions:
            return
        first = actions[0] if isinstance(actions[0], dict) else {}
        if self._seen(f"action:{first.get('action_ts', '')}:{first.get('action_id', '')}"):
            return
        command = str(first.get("value") or "").strip()
        channel = payload.get("channel") or {}
        channel_id = str(channel.get("id") or "") if isinstance(channel, dict) else ""
        user = payload.get("user") or {}
        user_id = str(user.get("id") or "") if isinstance(user, dict) else ""
        container = payload.get("container") or {}
        thread_id = ""
        if isinstance(container, dict):
            thread_id = str(container.get("thread_ts") or "")
        message = payload.get("message") or {}
        if not thread_id and isinstance(message, dict):
            thread_id = str(message.get("thread_ts") or message.get("ts") or "")
        if not command or not channel_id:
            return
        self.service.submit(
            InboundMessage(
                platform="slack",
                chat_id=channel_id,
                user_id=user_id,
                callback_data=command,
                thread_id=thread_id,
            ),
            self.replier,
        )

    def _to_inbound(self, event: Dict[str, Any]) -> Optional[InboundMessage]:
        event_type = str(event.get("type") or "")
        if event_type not in ("message", "app_mention"):
            return None
        if event.get("bot_id") or event.get("subtype"):
            return None
        user_id = str(event.get("user") or "").strip()
        channel_id = str(event.get("channel") or "").strip()
        ts = str(event.get("ts") or "").strip()
        # One user message can arrive as both app_mention and message events;
        # channel:ts is identical across both shapes, so process it once.
        if self._seen(f"msg:{channel_id}:{ts}"):
            return None
        text = strip_leading_mention(extract_message_text(event))
        if not user_id or not channel_id or not text:
            return None
        thread_id = str(event.get("thread_ts") or ts or "")
        return InboundMessage(
            platform="slack",
            chat_id=channel_id,
            user_id=user_id,
            text=text,
            thread_id=thread_id,
        )


__all__ = [
    "SlackReplier",
    "SlackRunner",
    "SlackUnavailableError",
    "extract_message_text",
    "open_socket_mode_url",
    "slack_api_call",
    "strip_leading_mention",
]
