"""Channel configuration: ``~/.superqode/channels.yaml`` plus env overrides.

Example file:

.. code-block:: yaml

    defaults:
      provider: ollama
      model: qwen3-coder:30b-a3b
      working_directory: ~/projects/myrepo
      harness: ~/projects/myrepo/harness.yaml   # optional

    telegram:
      bot_token_env: SUPERQODE_TELEGRAM_BOT_TOKEN
      allowed_chat_ids: ["123456789"]

    slack:
      app_token_env: SUPERQODE_SLACK_APP_TOKEN     # xapp- (Socket Mode)
      bot_token_env: SUPERQODE_SLACK_BOT_TOKEN     # xoxb-
      allowed_channel_ids: ["C0123ABCD"]

    discord:
      bot_token_env: SUPERQODE_DISCORD_BOT_TOKEN
      allowed_channel_ids: ["987654321"]

Tokens are read from the environment by default (never stored in the file);
a literal ``bot_token`` key is accepted but discouraged. A channel with an
empty allowlist replies with pairing instructions and never runs the agent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CHANNELS_CONFIG_PATH = Path.home() / ".superqode" / "channels.yaml"
STATE_DIR = Path.home() / ".superqode" / "channels"


@dataclass
class ChannelDefaults:
    provider: str = ""
    model: str = ""
    working_directory: str = ""
    harness: str = ""


@dataclass
class TelegramConfig:
    bot_token: str = ""
    allowed_chat_ids: List[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.bot_token)


@dataclass
class SlackConfig:
    app_token: str = ""  # xapp-, Socket Mode connection
    bot_token: str = ""  # xoxb-, Web API calls
    allowed_channel_ids: List[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.app_token and self.bot_token)


@dataclass
class DiscordConfig:
    bot_token: str = ""
    allowed_channel_ids: List[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.bot_token)


@dataclass
class ChannelsConfig:
    defaults: ChannelDefaults = field(default_factory=ChannelDefaults)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)

    @property
    def any_configured(self) -> bool:
        return self.telegram.configured or self.slack.configured or self.discord.configured


def _read_token(section: Dict[str, Any], key: str, default_env: str) -> str:
    """A token from env (preferred) or a literal config value."""
    env_name = str(section.get(f"{key}_env") or default_env)
    from_env = os.environ.get(env_name, "").strip()
    if from_env:
        return from_env
    return str(section.get(key) or "").strip()


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def load_channels_config(path: Optional[Path] = None) -> ChannelsConfig:
    """Load and merge the channels file with environment tokens."""
    config_path = path or CHANNELS_CONFIG_PATH
    data: Dict[str, Any] = {}
    if config_path.is_file():
        import yaml

        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    defaults_raw = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    telegram_raw = data.get("telegram") if isinstance(data.get("telegram"), dict) else {}
    slack_raw = data.get("slack") if isinstance(data.get("slack"), dict) else {}
    discord_raw = data.get("discord") if isinstance(data.get("discord"), dict) else {}

    return ChannelsConfig(
        defaults=ChannelDefaults(
            provider=str(defaults_raw.get("provider") or ""),
            model=str(defaults_raw.get("model") or ""),
            working_directory=str(defaults_raw.get("working_directory") or ""),
            harness=str(defaults_raw.get("harness") or ""),
        ),
        telegram=TelegramConfig(
            bot_token=_read_token(telegram_raw, "bot_token", "SUPERQODE_TELEGRAM_BOT_TOKEN"),
            allowed_chat_ids=_str_list(telegram_raw.get("allowed_chat_ids")),
        ),
        slack=SlackConfig(
            app_token=_read_token(slack_raw, "app_token", "SUPERQODE_SLACK_APP_TOKEN"),
            bot_token=_read_token(slack_raw, "bot_token", "SUPERQODE_SLACK_BOT_TOKEN"),
            allowed_channel_ids=_str_list(slack_raw.get("allowed_channel_ids")),
        ),
        discord=DiscordConfig(
            bot_token=_read_token(discord_raw, "bot_token", "SUPERQODE_DISCORD_BOT_TOKEN"),
            allowed_channel_ids=_str_list(discord_raw.get("allowed_channel_ids")),
        ),
    )


__all__ = [
    "CHANNELS_CONFIG_PATH",
    "STATE_DIR",
    "ChannelDefaults",
    "ChannelsConfig",
    "DiscordConfig",
    "SlackConfig",
    "TelegramConfig",
    "load_channels_config",
]
