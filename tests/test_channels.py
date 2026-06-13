"""Tests for the channel daemon stack: config, service, and transports.

All platform APIs and agent runs are faked; nothing touches the network or
a real model.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from superqode.channels.config import ChannelsConfig, TelegramConfig, load_channels_config
from superqode.channels.service import ChannelService, InboundMessage
from superqode.channels.telegram import chunk_text


# ------------------------------------------------------------------ config


def test_load_channels_config_env_tokens(monkeypatch, tmp_path):
    config_file = tmp_path / "channels.yaml"
    config_file.write_text(
        "defaults:\n"
        "  provider: ollama\n"
        "  model: qwen3-coder:30b-a3b\n"
        "telegram:\n"
        "  allowed_chat_ids: [123, '456']\n"
        "slack:\n"
        "  allowed_channel_ids: [C0AB]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERQODE_TELEGRAM_BOT_TOKEN", "tg-token")
    monkeypatch.delenv("SUPERQODE_SLACK_APP_TOKEN", raising=False)
    monkeypatch.delenv("SUPERQODE_SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SUPERQODE_DISCORD_BOT_TOKEN", raising=False)

    config = load_channels_config(config_file)
    assert config.defaults.provider == "ollama"
    assert config.telegram.bot_token == "tg-token"
    assert config.telegram.allowed_chat_ids == ["123", "456"]
    assert config.telegram.configured
    assert not config.slack.configured  # tokens missing
    assert not config.discord.configured
    assert config.any_configured


def test_load_channels_config_missing_file(monkeypatch, tmp_path):
    for name in (
        "SUPERQODE_TELEGRAM_BOT_TOKEN",
        "SUPERQODE_SLACK_APP_TOKEN",
        "SUPERQODE_SLACK_BOT_TOKEN",
        "SUPERQODE_DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    config = load_channels_config(tmp_path / "missing.yaml")
    assert not config.any_configured


# ---------------------------------------------------------------- chunking


def test_chunk_text_respects_limit():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    chunks = chunk_text(text, limit=500)
    assert all(len(c) <= 500 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks).startswith("line 0")


def test_chunk_text_hard_splits_long_lines():
    chunks = chunk_text("y" * 1200, limit=500)
    assert [len(c) for c in chunks] == [500, 500, 200]


def test_chunk_text_empty():
    assert chunk_text("   ") == []


# ----------------------------------------------------------------- service


class FakeReplier:
    def __init__(self):
        self.sent: List[tuple] = []
        self.approvals: List[tuple] = []
        self.threads: List[str] = []

    def send(self, chat_id, text, thread_id=""):
        self.sent.append((chat_id, text))
        self.threads.append(thread_id)

    def send_approval(self, chat_id, text, thread_id=""):
        self.approvals.append((chat_id, text))


@dataclass
class FakeResponse:
    content: str = "done"
    stopped_reason: str = "complete"
    error: Optional[str] = None


class FakePure:
    """Stands in for PureMode: scripted responses and approval state."""

    def __init__(self):
        self.session = type("S", (), {"provider": "ollama", "model": "m", "harness_name": ""})()
        self.responses: List[FakeResponse] = []
        self.pending: List[Dict[str, Any]] = []
        self.prompts: List[str] = []
        self.steered: List[str] = []
        self.cancelled = False
        self.run_active = False

    def connect(self, provider, model, working_directory=None, **kw):
        self.session.provider = provider
        self.session.model = model
        return True

    async def run(self, prompt):
        self.prompts.append(prompt)
        return self.responses.pop(0) if self.responses else FakeResponse()

    def steer(self, message):
        if not self.run_active:
            return False
        self.steered.append(message)
        return True

    def cancel(self):
        self.cancelled = True

    def get_pending_approvals(self):
        return list(self.pending)

    async def approve_and_resume(self, index=0, always=False):
        self.pending = []
        return FakeResponse(content="tool ran")

    async def reject_and_resume(self, index=0, message=None, always=False):
        self.pending = []
        return FakeResponse(content="tool rejected")

    def get_status(self):
        return {
            "provider": self.session.provider,
            "model": self.session.model,
            "working_directory": "/tmp",
            "stats": {"total_requests": 1, "total_tool_calls": 2},
            "harness": {"enabled": False},
        }


def _service_with_fake_session(allowed=("100",)) -> tuple:
    config = ChannelsConfig(telegram=TelegramConfig(bot_token="t", allowed_chat_ids=list(allowed)))
    service = ChannelService(config)
    fake = FakePure()
    session = None

    def get_session(platform, chat_id):
        nonlocal session
        from superqode.channels.service import ChatSession

        key = (platform, chat_id)
        if key not in service._sessions:
            service._sessions[key] = ChatSession(platform=platform, chat_id=chat_id, pure=fake)
        return service._sessions[key]

    service._get_session = get_session  # type: ignore[method-assign]
    return service, fake


def _run(service, message, replier):
    asyncio.run(service._handle(message, replier))


def test_unauthorized_chat_gets_pairing_only():
    service, fake = _service_with_fake_session(allowed=("100",))
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="999", text="rm -rf /"), replier)
    assert len(replier.sent) == 1
    assert "not authorized" in replier.sent[0][1]
    assert "999" in replier.sent[0][1]
    assert fake.prompts == []  # the agent never ran


def test_plain_text_runs_prompt_and_replies():
    service, fake = _service_with_fake_session()
    fake.responses = [FakeResponse(content="answer text")]
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="fix the bug"), replier)
    assert fake.prompts == ["fix the bug"]
    assert any("answer text" in text for _, text in replier.sent)


def test_needs_approval_sends_approval_request():
    service, fake = _service_with_fake_session()
    fake.responses = [FakeResponse(content="", stopped_reason="needs_approval")]
    fake.pending = [{"tool_name": "bash", "arguments": {"command": "pytest"}}]
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="run tests"), replier)
    assert replier.approvals, "approval request should use send_approval"
    assert "bash" in replier.approvals[0][1]


def test_approve_command_resumes():
    service, fake = _service_with_fake_session()
    fake.pending = [{"tool_name": "bash", "arguments": {}}]
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/approve"), replier)
    assert fake.pending == []
    assert any("Approved" in text for _, text in replier.sent)
    assert any("tool ran" in text for _, text in replier.sent)


def test_deny_command_with_reason():
    service, fake = _service_with_fake_session()
    fake.pending = [{"tool_name": "bash", "arguments": {}}]
    replier = FakeReplier()
    _run(
        service,
        InboundMessage(platform="telegram", chat_id="100", text="/deny too risky"),
        replier,
    )
    assert any("Denied: too risky" in text for _, text in replier.sent)


def test_approve_without_pending():
    service, fake = _service_with_fake_session()
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/approve"), replier)
    assert any("No pending approval" in text for _, text in replier.sent)


def test_steering_when_busy():
    service, fake = _service_with_fake_session()
    replier = FakeReplier()
    # Prime the session, then mark it busy with an active run.
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/status"), replier)
    session = service._sessions[("telegram", "100")]
    session.busy = True
    fake.run_active = True
    _run(
        service,
        InboundMessage(platform="telegram", chat_id="100", text="also update the docs"),
        replier,
    )
    assert fake.steered == ["also update the docs"]
    assert any("Steering" in text for _, text in replier.sent)


def test_stop_cancels_active_run():
    service, fake = _service_with_fake_session()
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/status"), replier)
    service._sessions[("telegram", "100")].busy = True
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/stop"), replier)
    assert fake.cancelled


def test_status_command():
    service, fake = _service_with_fake_session()
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/status"), replier)
    text = replier.sent[-1][1]
    assert "ollama/m" in text
    assert "Run active: no" in text


def test_model_command_switches():
    service, fake = _service_with_fake_session()
    replier = FakeReplier()
    _run(
        service,
        InboundMessage(platform="telegram", chat_id="100", text="/model mlx/some-model"),
        replier,
    )
    assert fake.session.provider == "mlx"
    assert fake.session.model == "some-model"


def test_new_command_resets_session():
    service, fake = _service_with_fake_session()
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/status"), replier)
    assert ("telegram", "100") in service._sessions
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="/new"), replier)
    assert ("telegram", "100") not in service._sessions


def test_progress_reporter_edits_tracked_message():
    from superqode.channels.service import ProgressReporter

    class TrackedReplier(FakeReplier):
        def __init__(self):
            super().__init__()
            self.edits: List[tuple] = []

        def send_tracked(self, chat_id, text, thread_id=""):
            self.sent.append((chat_id, text))
            return "msg-1"

        def edit(self, chat_id, handle, text, thread_id=""):
            self.edits.append((handle, text))

    replier = TrackedReplier()
    reporter = ProgressReporter(replier, "100", "", min_interval=0.0)
    reporter.start("🤖 Working on it.")
    assert replier.sent == [("100", "🤖 Working on it.")]

    reporter.on_tool_call("bash", {"command": "pytest -q"})
    deadline = time.time() + 2
    while time.time() < deadline and not replier.edits:
        time.sleep(0.02)
    assert replier.edits, "tool call should edit the tracked message"
    handle, text = replier.edits[0]
    assert handle == "msg-1"
    assert "bash" in text and "pytest -q" in text

    reporter.finish("🤖 Finished working.")
    assert replier.edits[-1] == ("msg-1", "🤖 Finished working.")


def test_progress_reporter_degrades_without_tracking():
    from superqode.channels.service import ProgressReporter

    replier = FakeReplier()  # no send_tracked / edit
    reporter = ProgressReporter(replier, "100", "")
    reporter.start("working")
    assert replier.sent == [("100", "working")]
    reporter.on_tool_call("bash", {"command": "x"})  # must not raise
    reporter.finish("done")  # must not raise


def test_done_message_has_runtime_footer():
    service, fake = _service_with_fake_session()
    fake.responses = [FakeResponse(content="answer text")]
    replier = FakeReplier()
    _run(service, InboundMessage(platform="telegram", chat_id="100", text="task"), replier)
    final = replier.sent[-1][1]
    assert "✅ Done" in final
    assert "🧠 ollama/m" in final


def test_callback_data_treated_as_command():
    service, fake = _service_with_fake_session()
    fake.pending = [{"tool_name": "bash", "arguments": {}}]
    replier = FakeReplier()
    _run(
        service,
        InboundMessage(platform="telegram", chat_id="100", callback_data="/approve always"),
        replier,
    )
    assert any("Approved (always)" in text for _, text in replier.sent)


def test_submit_marshals_from_threads():
    service, fake = _service_with_fake_session()
    fake.responses = [FakeResponse(content="threaded ok")]
    replier = FakeReplier()

    runner = threading.Thread(target=service.run_forever, daemon=True)
    runner.start()
    assert service.wait_ready(5)
    service.submit(InboundMessage(platform="telegram", chat_id="100", text="go"), replier)
    deadline = time.time() + 5
    while time.time() < deadline and not any("threaded ok" in t for _, t in replier.sent):
        time.sleep(0.05)
    service.stop()
    assert any("threaded ok" in t for _, t in replier.sent)


# -------------------------------------------------------------- transports


def test_telegram_to_inbound_message_and_callback(monkeypatch, tmp_path):
    from superqode.channels.telegram import TelegramRunner

    config = TelegramConfig(bot_token="t", allowed_chat_ids=["1"])
    runner = TelegramRunner(config, ChannelService(ChannelsConfig()), state_dir=tmp_path)

    message = runner._to_inbound(
        {"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "hello"}}
    )
    assert message is not None
    assert (message.chat_id, message.user_id, message.text) == ("42", "7", "hello")

    acked = []
    monkeypatch.setattr(
        "superqode.channels.telegram.telegram_api_call",
        lambda token, method, payload=None, timeout=35.0: acked.append(method) or {"ok": True},
    )
    callback = runner._to_inbound(
        {
            "callback_query": {
                "id": "cb1",
                "data": "/approve",
                "from": {"id": 7},
                "message": {"chat": {"id": 42}},
            }
        }
    )
    assert callback is not None and callback.callback_data == "/approve"
    assert "answerCallbackQuery" in acked


def test_telegram_offset_persistence(tmp_path):
    from superqode.channels.telegram import TelegramRunner

    runner = TelegramRunner(
        TelegramConfig(bot_token="t"), ChannelService(ChannelsConfig()), state_dir=tmp_path
    )
    assert runner._load_offset() is None
    runner._store_offset(1234)
    assert runner._load_offset() == 1234


def test_slack_to_inbound_filters_bots():
    from superqode.channels.slack import SlackRunner
    from superqode.channels.config import SlackConfig

    runner = SlackRunner(
        SlackConfig(app_token="a", bot_token="b"), ChannelService(ChannelsConfig())
    )
    assert (
        runner._to_inbound(
            {"type": "message", "bot_id": "B1", "user": "U", "channel": "C", "text": "x"}
        )
        is None
    )
    assert (
        runner._to_inbound(
            {"type": "message", "subtype": "edited", "user": "U", "channel": "C", "text": "x"}
        )
        is None
    )
    message = runner._to_inbound(
        {"type": "message", "user": "U1", "channel": "C1", "text": "hello"}
    )
    assert message is not None and message.chat_id == "C1"


def test_slack_app_mention_strips_token():
    from superqode.channels.slack import SlackRunner
    from superqode.channels.config import SlackConfig

    runner = SlackRunner(
        SlackConfig(app_token="a", bot_token="b"), ChannelService(ChannelsConfig())
    )
    message = runner._to_inbound(
        {"type": "app_mention", "user": "U1", "channel": "C1", "text": "<@UBOT> run tests"}
    )
    assert message is not None and message.text == "run tests"


def test_slack_message_event_also_strips_mention():
    """A channel mention arrives as a message event too; both must yield /status."""
    from superqode.channels.slack import SlackRunner
    from superqode.channels.config import SlackConfig

    runner = SlackRunner(
        SlackConfig(app_token="a", bot_token="b"), ChannelService(ChannelsConfig())
    )
    message = runner._to_inbound(
        {"type": "message", "user": "U1", "channel": "C1", "ts": "1.1", "text": "<@UBOT> /status"}
    )
    assert message is not None and message.text == "/status"


def test_slack_same_message_processed_once_across_event_types():
    """app_mention and message events for one user message share channel:ts."""
    from superqode.channels.slack import SlackRunner
    from superqode.channels.config import SlackConfig

    runner = SlackRunner(
        SlackConfig(app_token="a", bot_token="b"), ChannelService(ChannelsConfig())
    )
    first = runner._to_inbound(
        {"type": "app_mention", "user": "U1", "channel": "C1", "ts": "9.9", "text": "<@UBOT> hi"}
    )
    duplicate = runner._to_inbound(
        {"type": "message", "user": "U1", "channel": "C1", "ts": "9.9", "text": "<@UBOT> hi"}
    )
    assert first is not None
    assert duplicate is None


def test_slack_threads_replies_under_trigger_message():
    from superqode.channels.slack import SlackRunner
    from superqode.channels.config import SlackConfig

    runner = SlackRunner(
        SlackConfig(app_token="a", bot_token="b"), ChannelService(ChannelsConfig())
    )
    message = runner._to_inbound(
        {"type": "message", "user": "U1", "channel": "C1", "ts": "5.5", "text": "hello"}
    )
    assert message is not None and message.thread_id == "5.5"
    reply = runner._to_inbound(
        {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "ts": "6.6",
            "thread_ts": "5.5",
            "text": "in thread",
        }
    )
    assert reply is not None and reply.thread_id == "5.5"


def test_slack_replier_threads_every_outbound_message(monkeypatch):
    """All reply kinds must carry thread_ts so channel replies stay threaded."""
    from superqode.channels.slack import SlackReplier

    calls = []
    monkeypatch.setattr(
        "superqode.channels.slack.slack_api_call",
        lambda token, method, payload=None, timeout=15.0: calls.append(payload) or {"ok": True},
    )
    replier = SlackReplier("xoxb-test")
    replier.send("C1", "working", thread_id="1.23")
    replier.send_done("C1", "done", thread_id="1.23")
    replier.send_approval("C1", "approve?", thread_id="1.23")
    assert calls and all(p.get("thread_ts") == "1.23" for p in calls)


def test_slack_interactive_button_press_becomes_command():
    from superqode.channels.slack import SlackRunner
    from superqode.channels.config import SlackConfig

    captured = []

    class CaptureService:
        def submit(self, message, replier):
            captured.append(message)

    runner = SlackRunner(SlackConfig(app_token="a", bot_token="b"), CaptureService())  # type: ignore[arg-type]
    runner._handle_interactive(
        {
            "type": "block_actions",
            "user": {"id": "U1"},
            "channel": {"id": "C1"},
            "container": {"thread_ts": "5.5"},
            "actions": [
                {"action_id": "superqode_approve", "action_ts": "7.7", "value": "/approve"}
            ],
        }
    )
    assert len(captured) == 1
    assert captured[0].callback_data == "/approve"
    assert captured[0].chat_id == "C1"
    assert captured[0].thread_id == "5.5"
    # Same action_ts again is a duplicate.
    runner._handle_interactive(
        {
            "type": "block_actions",
            "user": {"id": "U1"},
            "channel": {"id": "C1"},
            "actions": [
                {"action_id": "superqode_approve", "action_ts": "7.7", "value": "/approve"}
            ],
        }
    )
    assert len(captured) == 1


def test_discord_button_interaction_becomes_command(monkeypatch):
    from superqode.channels.discord import DiscordRunner
    from superqode.channels.config import DiscordConfig

    captured = []
    acked = []

    class CaptureService:
        def submit(self, message, replier):
            captured.append(message)

    monkeypatch.setattr(
        "superqode.channels.discord.discord_api_call",
        lambda token, method, path, payload=None, timeout=15.0: acked.append(path) or {},
    )
    runner = DiscordRunner(DiscordConfig(bot_token="d"), CaptureService())  # type: ignore[arg-type]
    runner._handle_dispatch(
        "INTERACTION_CREATE",
        {
            "type": 3,
            "id": "INT1",
            "token": "tok",
            "channel_id": "C9",
            "member": {"user": {"id": "U2"}},
            "data": {"custom_id": "/approve"},
        },
    )
    assert len(captured) == 1
    assert captured[0].callback_data == "/approve"
    assert any("/interactions/INT1/tok/callback" in path for path in acked)


def test_slack_rich_text_extraction():
    from superqode.channels.slack import extract_message_text

    event = {
        "text": "",
        "blocks": [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "fix "},
                            {"type": "link", "url": "https://x.test"},
                        ],
                    }
                ],
            }
        ],
    }
    assert extract_message_text(event) == "fix https://x.test"


def test_discord_dispatch_filters_self_and_bots():
    from superqode.channels.discord import DiscordRunner
    from superqode.channels.config import DiscordConfig

    captured = []

    class CaptureService:
        def submit(self, message, replier):
            captured.append(message)

    runner = DiscordRunner(DiscordConfig(bot_token="d"), CaptureService())  # type: ignore[arg-type]
    runner._bot_user_id = "BOT"

    runner._handle_dispatch(
        "MESSAGE_CREATE",
        {"id": "1", "author": {"id": "BOT"}, "channel_id": "C", "content": "self echo"},
    )
    runner._handle_dispatch(
        "MESSAGE_CREATE",
        {"id": "2", "author": {"id": "U", "bot": True}, "channel_id": "C", "content": "bot"},
    )
    runner._handle_dispatch(
        "MESSAGE_CREATE",
        {"id": "3", "author": {"id": "U2"}, "channel_id": "C9", "content": "hello"},
    )
    # Duplicate id is dropped.
    runner._handle_dispatch(
        "MESSAGE_CREATE",
        {"id": "3", "author": {"id": "U2"}, "channel_id": "C9", "content": "hello"},
    )
    assert [m.chat_id for m in captured] == ["C9"]
    assert captured[0].text == "hello"


# ------------------------------------------------------------------ daemon


def test_daemon_check_requires_config(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from superqode.commands.daemon import daemon

    for name in (
        "SUPERQODE_TELEGRAM_BOT_TOKEN",
        "SUPERQODE_SLACK_APP_TOKEN",
        "SUPERQODE_SLACK_BOT_TOKEN",
        "SUPERQODE_DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    # Run from an empty cwd: the daemon loads ./.env, and the developer's
    # repo may have real tokens there.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(daemon, ["--check", "--config", str(tmp_path / "none.yaml")])
    assert result.exit_code != 0
    assert "No channels configured" in result.output


def test_daemon_check_validates_telegram(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from superqode.commands.daemon import daemon

    monkeypatch.setenv("SUPERQODE_TELEGRAM_BOT_TOKEN", "tg")
    for name in (
        "SUPERQODE_SLACK_APP_TOKEN",
        "SUPERQODE_SLACK_BOT_TOKEN",
        "SUPERQODE_DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    config_file = tmp_path / "channels.yaml"
    config_file.write_text("telegram:\n  allowed_chat_ids: ['1']\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "superqode.channels.telegram.telegram_api_call",
        lambda token, method, payload=None, timeout=35.0: {"ok": True, "result": {}},
    )
    result = CliRunner().invoke(daemon, ["--check", "--config", str(config_file)])
    assert result.exit_code == 0, result.output
    assert "telegram: configured and reachable" in result.output
    assert "Configuration OK" in result.output


def test_daemon_naming_a_channel_selects_only_it(monkeypatch, tmp_path):
    """`--slack` must start Slack alone even when other tokens are configured."""
    from click.testing import CliRunner

    from superqode.commands.daemon import daemon

    monkeypatch.setenv("SUPERQODE_TELEGRAM_BOT_TOKEN", "tg")
    monkeypatch.setenv("SUPERQODE_SLACK_APP_TOKEN", "xapp")
    monkeypatch.setenv("SUPERQODE_SLACK_BOT_TOKEN", "xoxb")
    monkeypatch.setenv("SUPERQODE_DISCORD_BOT_TOKEN", "dc")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        "superqode.channels.slack.slack_api_call",
        lambda token, method, payload=None, timeout=15.0: {"ok": True},
    )
    result = CliRunner().invoke(
        daemon, ["--check", "--config", str(tmp_path / "none.yaml"), "--slack"]
    )
    assert result.exit_code == 0, result.output
    assert "slack: configured and reachable" in result.output
    assert "telegram:" not in result.output
    assert "discord:" not in result.output
