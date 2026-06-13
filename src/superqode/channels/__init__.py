"""Chat-channel remote control for Local Agentic Coding.

Long-running local agent runs, supervised from Telegram, Slack, or Discord:
run notifications, tool-approval relay, mid-run steering, and session
control. Started with ``superqode daemon``.

Design:

- Transports (`telegram`, `slack`, `discord`) speak each platform's API and
  run in worker threads. Telegram is stdlib-only; Slack Socket Mode and the
  Discord Gateway need the optional ``websocket-client`` package
  (``pip install superqode[channels]``).
- :class:`superqode.channels.service.ChannelService` owns the asyncio side:
  one agent session per chat, command handling, and the approval relay.
- Security is allowlist-first: chats not explicitly allowed get pairing
  instructions and nothing else. The agent never executes for strangers.
"""

from .config import ChannelsConfig, load_channels_config

__all__ = ["ChannelsConfig", "load_channels_config"]
