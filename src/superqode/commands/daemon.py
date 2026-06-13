"""The `superqode daemon` command: channel transports + the channel service.

A long-running process for Local Agentic Coding you supervise from chat:
each configured channel (Telegram, Slack, Discord) runs in a worker thread
and feeds the asyncio channel service, which owns one agent session per
chat. A lock file prevents two daemons sharing state.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, TextIO

import click

LOCK_PATH = Path.home() / ".superqode" / "daemon.lock"


def _load_dotenv(path: Path) -> int:
    """Load KEY=VALUE lines from a .env file into os.environ (no overrides).

    Deliberately minimal: comments and blank lines skipped, optional single
    or double quotes stripped. Lets `superqode daemon` pick up channel
    tokens from ./.env for local testing without a dotenv dependency.
    """
    import os

    if not path.is_file():
        return 0
    loaded = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
    except OSError:
        return 0
    return loaded


def _acquire_lock(lock_path: Path, summary: str) -> Optional[TextIO]:
    import fcntl
    import os

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} channels={summary}\n")
    handle.flush()
    return handle


@click.command("daemon")
@click.option(
    "--telegram/--no-telegram",
    "telegram_flag",
    default=None,
    help="Start only the named channels (combinable); --no-telegram excludes it",
)
@click.option(
    "--slack/--no-slack",
    "slack_flag",
    default=None,
    help="Start only the named channels (combinable); --no-slack excludes it",
)
@click.option(
    "--discord/--no-discord",
    "discord_flag",
    default=None,
    help="Start only the named channels (combinable); --no-discord excludes it",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    metavar="PATH",
    help="Channels config file (default ~/.superqode/channels.yaml)",
)
@click.option("--check", is_flag=True, help="Validate configuration and tokens, then exit")
def daemon(telegram_flag, slack_flag, discord_flag, config_path, check):
    """Run the SuperQode channel daemon (Telegram, Slack, Discord).

    Chats become a remote control for local agent runs: prompts, progress,
    tool-approval relay, mid-run steering, and session commands. Configure
    tokens and chat allowlists in ~/.superqode/channels.yaml; by default
    every channel with a token starts.

    Security: chats not in the allowlist only ever receive pairing
    instructions. The agent never runs for unknown chats.
    """
    from superqode.channels.config import CHANNELS_CONFIG_PATH, load_channels_config
    from superqode.channels.service import ChannelService

    loaded = _load_dotenv(Path.cwd() / ".env")
    if loaded:
        click.echo(f"Loaded {loaded} variable(s) from .env")

    config = load_channels_config(Path(config_path) if config_path else None)

    # Naming any channel selects only the named ones (`--slack` means Slack
    # alone); with no flags, every configured channel starts. `--no-x` always
    # disables x.
    any_selected = True in (telegram_flag, slack_flag, discord_flag)

    def wanted(flag: Optional[bool], configured: bool) -> bool:
        if flag is None:
            return configured and not any_selected
        return flag and configured

    use_telegram = wanted(telegram_flag, config.telegram.configured)
    use_slack = wanted(slack_flag, config.slack.configured)
    use_discord = wanted(discord_flag, config.discord.configured)

    if telegram_flag and not config.telegram.configured:
        raise click.ClickException("Telegram requested but no bot token is configured.")
    if slack_flag and not config.slack.configured:
        raise click.ClickException("Slack requested but app/bot tokens are not configured.")
    if discord_flag and not config.discord.configured:
        raise click.ClickException("Discord requested but no bot token is configured.")
    if not (use_telegram or use_slack or use_discord):
        raise click.ClickException(
            f"No channels configured. Add tokens to {CHANNELS_CONFIG_PATH} or set "
            "SUPERQODE_TELEGRAM_BOT_TOKEN / SUPERQODE_SLACK_APP_TOKEN + "
            "SUPERQODE_SLACK_BOT_TOKEN / SUPERQODE_DISCORD_BOT_TOKEN."
        )

    service = ChannelService(config)
    runners = []
    if use_telegram:
        from superqode.channels.telegram import TelegramRunner

        runners.append(("telegram", TelegramRunner(config.telegram, service)))
    if use_slack:
        from superqode.channels.slack import SlackRunner

        runners.append(("slack", SlackRunner(config.slack, service)))
    if use_discord:
        from superqode.channels.discord import DiscordRunner

        runners.append(("discord", DiscordRunner(config.discord, service)))

    # Validate everything (tokens, deps, connectivity) before going resident.
    for name, runner in runners:
        try:
            runner.validate()
            click.echo(f"{name}: configured and reachable")
        except Exception as exc:
            raise click.ClickException(f"{name}: {exc}") from exc

    names = [name for name, _ in runners]
    if not config.defaults.provider or not config.defaults.model:
        click.echo(
            "Note: defaults.provider/model are not set in channels.yaml; "
            "chats must run /model <provider/model> before prompting."
        )
    for name in names:
        allowed = {
            "telegram": config.telegram.allowed_chat_ids,
            "slack": config.slack.allowed_channel_ids,
            "discord": config.discord.allowed_channel_ids,
        }[name]
        if not allowed:
            click.echo(
                f"Note: {name} has an empty allowlist; it will only reply with "
                "pairing instructions until you add chat ids."
            )

    if check:
        click.echo("Configuration OK.")
        return

    lock = _acquire_lock(LOCK_PATH, ",".join(names))
    if lock is None:
        raise click.ClickException(
            "A SuperQode daemon is already running (lock at "
            f"{LOCK_PATH}). Stop it before starting another."
        )

    click.echo(f"SuperQode daemon starting: {', '.join(names)} (Ctrl+C stops)")
    threads = []
    try:
        for name, runner in runners:
            thread = threading.Thread(
                target=runner.run_forever,
                name=f"superqode-{name}",
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        service.run_forever()  # blocks until Ctrl+C
    except KeyboardInterrupt:
        click.echo("\nSuperQode daemon stopping.")
    finally:
        service.stop()
        for _, runner in runners:
            try:
                runner.stop()
            except Exception:
                pass
        lock.close()


__all__ = ["daemon"]
