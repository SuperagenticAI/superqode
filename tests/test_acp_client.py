"""
Tests for SuperQode ACP (Agent Client Protocol) Client.

Tests the communication layer for ACP-compatible coding agents.
"""

import pytest
import asyncio
import shlex
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import json

from superqode.acp.client import (
    ACPClient,
    ACPMessage,
    ACPStats,
    PROTOCOL_VERSION,
    CLIENT_NAME,
    CLIENT_VERSION,
    default_acp_traffic_log_dir,
)
from superqode.acp.types import (
    PermissionOption,
    ToolCall,
    ToolCallUpdate,
)


class TestACPMessage:
    """Tests for ACPMessage dataclass."""

    def test_create_message(self):
        """Test creating an ACP message."""
        msg = ACPMessage(type="text", data={"content": "hello"})

        assert msg.type == "text"
        assert msg.data == {"content": "hello"}

    def test_message_with_empty_data(self):
        """Test message with empty data."""
        msg = ACPMessage(type="status", data={})

        assert msg.type == "status"
        assert msg.data == {}


class TestACPStats:
    """Tests for ACPStats dataclass."""

    def test_default_stats(self):
        """Test default statistics values."""
        stats = ACPStats()

        assert stats.tool_count == 0
        assert stats.files_modified == []
        assert stats.files_read == []
        assert stats.duration == 0.0
        assert stats.stop_reason == ""

    def test_stats_with_data(self):
        """Test statistics with provided data."""
        stats = ACPStats(
            tool_count=5,
            files_modified=["file1.py", "file2.py"],
            files_read=["file3.py"],
            duration=10.5,
            stop_reason="completed",
        )

        assert stats.tool_count == 5
        assert len(stats.files_modified) == 2
        assert stats.duration == 10.5


class TestACPClient:
    """Tests for ACPClient."""

    def test_client_initialization(self, tmp_path):
        """Test client initialization with required parameters."""
        client = ACPClient(project_root=tmp_path, command="opencode acp", model="test-model")

        assert client.project_root == tmp_path
        assert client.command == "opencode acp"
        assert client.model == "test-model"
        assert client.startup_timeout == 30.0
        assert client.prompt_timeout == 180.0
        assert client.request_timeout == 30.0

    def test_client_without_model(self, tmp_path):
        """Test client initialization without model."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")

        assert client.model is None
        assert client.is_running() is False

    def test_client_callbacks_default_none(self, tmp_path):
        """Test that callbacks default to None."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")

        assert client.on_message is None
        assert client.on_thinking is None
        assert client.on_tool_call is None
        assert client.on_tool_update is None
        assert client.on_permission_request is None
        assert client.on_plan is None

    @pytest.mark.asyncio
    async def test_client_with_callbacks(self, tmp_path):
        """Test client with custom callbacks."""
        on_message = AsyncMock()
        on_thinking = AsyncMock()

        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            on_message=on_message,
            on_thinking=on_thinking,
        )

        assert client.on_message is on_message
        assert client.on_thinking is on_thinking

    @pytest.mark.asyncio
    async def test_new_session_sends_model_when_configured(self, tmp_path, monkeypatch):
        """Test model is sent during session creation."""
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            model="opencode/minimax-m2.5-free",
        )
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append((method, params))
            return {"sessionId": "session-1"}

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        response = await client._new_session()

        assert response["sessionId"] == "session-1"
        assert client.get_session_id() == "session-1"
        assert calls == [
            (
                "session/new",
                {
                    "cwd": str(tmp_path),
                    "mcpServers": [],
                    "model": "opencode/minimax-m2.5-free",
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_new_session_passes_configured_mcp_servers(self, tmp_path, monkeypatch):
        """ACP agents should receive enabled MCP servers, including fetch servers."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")
        mcp_servers = [
            {
                "name": "fetch",
                "transport": "stdio",
                "command": "uvx",
                "args": ["mcp-server-fetch"],
            }
        ]
        calls = []

        monkeypatch.setattr("superqode.mcp.config.get_acp_mcp_servers", lambda: mcp_servers)

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append((method, params))
            return {"sessionId": "session-1"}

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        assert calls == [
            (
                "session/new",
                {
                    "cwd": str(tmp_path),
                    "mcpServers": mcp_servers,
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_session_update_accepts_nested_and_non_chunk_message(self, tmp_path):
        """Some ACP agents send nested updates or agent_message instead of chunk names."""
        on_message = AsyncMock()
        client = ACPClient(
            project_root=tmp_path,
            command="uvx --from fast-agent-mcp@latest fast-agent-acp",
            on_message=on_message,
        )

        await client._handle_session_update(
            {
                "sessionUpdate": {
                    "type": "agent_message",
                    "content": {"type": "text", "text": "hello"},
                }
            }
        )

        on_message.assert_awaited_once_with("hello")
        assert client.get_message_buffer() == "hello"

    @pytest.mark.asyncio
    async def test_stop_tolerates_already_exited_process(self, tmp_path):
        """Live doctor should not crash when an ACP subprocess exits before cleanup."""

        class ExitedProcess:
            returncode = 2

            def terminate(self):
                raise ProcessLookupError()

            async def wait(self):
                return self.returncode

            def kill(self):
                raise ProcessLookupError()

        client = ACPClient(project_root=tmp_path, command="bad-agent --acp")
        client._process = ExitedProcess()

        await client.stop()

        assert client._process is None

    @pytest.mark.asyncio
    async def test_session_update_handles_commands_mode_and_usage(self, tmp_path):
        """ACP state updates should be cached and surfaced to callbacks."""
        on_commands = AsyncMock()
        on_mode = AsyncMock()
        on_usage = AsyncMock()
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            on_available_commands=on_commands,
            on_mode_update=on_mode,
            on_usage_update=on_usage,
        )

        commands = [{"name": "review", "description": "Review changes"}]
        await client._handle_session_update(
            {
                "sessionUpdate": "available_commands_update",
                "availableCommands": commands,
            }
        )
        await client._handle_session_update(
            {"sessionUpdate": "current_mode_update", "currentModeId": "plan"}
        )
        await client._handle_session_update(
            {
                "sessionUpdate": "usage_update",
                "used": 1000,
                "size": 4000,
                "cost": {"amount": 0.02, "currency": "USD"},
            }
        )

        on_commands.assert_awaited_once_with(commands)
        on_mode.assert_awaited_once_with("plan")
        on_usage.assert_awaited_once()
        assert client.get_available_commands_cached() == commands
        assert await client.get_current_mode() == "plan"
        assert client.get_usage()["used"] == 1000
        assert client.get_stats().cost == 0.02

    @pytest.mark.asyncio
    async def test_new_session_captures_modes_and_models(self, tmp_path, monkeypatch):
        """Modes and models returned by session/new should be available without extra RPCs."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")

        async def fake_call_method(method, *, timeout=None, **params):
            return {
                "sessionId": "session-1",
                "modes": {
                    "currentModeId": "write",
                    "availableModes": [{"id": "write", "name": "Write"}],
                },
                "models": {
                    "currentModelId": "model-1",
                    "availableModels": [{"id": "model-1", "name": "Model 1"}],
                },
            }

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        assert await client.get_current_mode() == "write"
        assert await client.get_current_model() == "model-1"
        assert await client.get_available_modes() == [{"id": "write", "name": "Write"}]
        assert await client.get_available_models() == [{"id": "model-1", "name": "Model 1"}]

    @pytest.mark.asyncio
    async def test_new_session_switches_to_requested_model(self, tmp_path, monkeypatch):
        """Agents like opencode ignore session/new's model field and start on
        their default, so the client must follow up with session/set_model."""
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            model="opencode/mimo-v2.5-free",
        )
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append((method, params))
            return {
                "sessionId": "session-1",
                "models": {
                    "currentModelId": "opencode/big-pickle",
                    "availableModels": [
                        {"modelId": "opencode/big-pickle", "name": "Big Pickle"},
                        {"modelId": "opencode/mimo-v2.5-free", "name": "MiMo"},
                    ],
                },
            }

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        methods = [m for m, _ in calls]
        assert methods == ["session/new", "session/set_model"]
        assert calls[1] == (
            "session/set_model",
            {"sessionId": "session-1", "modelId": "opencode/mimo-v2.5-free"},
        )
        assert client._current_model_id == "opencode/mimo-v2.5-free"

    @pytest.mark.asyncio
    async def test_new_session_switches_opencode_config_option_model(self, tmp_path, monkeypatch):
        """OpenCode now exposes model selection through configOptions.

        Regression: when only configOptions were present, SuperQode skipped
        model switching and OpenCode stayed on its default big-pickle model.
        """
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            model="deepseek/deepseek-v4-pro",
        )
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append((method, params))
            if method == "session/new":
                return {
                    "sessionId": "session-1",
                    "configOptions": [
                        {
                            "id": "model",
                            "name": "Model",
                            "category": "model",
                            "type": "select",
                            "currentValue": "opencode/big-pickle",
                            "options": [
                                {
                                    "value": "opencode/big-pickle",
                                    "name": "OpenCode/Big Pickle",
                                },
                                {
                                    "value": "deepseek/deepseek-v4-pro",
                                    "name": "DeepSeek/DeepSeek V4 Pro",
                                },
                            ],
                        }
                    ],
                }
            if method == "session/set_config_option":
                return {
                    "configOptions": [
                        {
                            "id": "model",
                            "category": "model",
                            "type": "select",
                            "currentValue": params["value"],
                            "options": [
                                {
                                    "value": "opencode/big-pickle",
                                    "name": "OpenCode/Big Pickle",
                                },
                                {
                                    "value": "deepseek/deepseek-v4-pro",
                                    "name": "DeepSeek/DeepSeek V4 Pro",
                                },
                            ],
                        }
                    ]
                }
            return {}

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        assert calls[1] == (
            "session/set_config_option",
            {
                "sessionId": "session-1",
                "configId": "model",
                "value": "deepseek/deepseek-v4-pro",
            },
        )
        assert client._current_model_id == "deepseek/deepseek-v4-pro"
        assert await client.get_current_model() == "deepseek/deepseek-v4-pro"
        assert await client.get_available_models() == [
            {
                "id": "opencode/big-pickle",
                "modelId": "opencode/big-pickle",
                "name": "OpenCode/Big Pickle",
            },
            {
                "id": "deepseek/deepseek-v4-pro",
                "modelId": "deepseek/deepseek-v4-pro",
                "name": "DeepSeek/DeepSeek V4 Pro",
            },
        ]

    @pytest.mark.asyncio
    async def test_new_session_switches_legacy_id_model_shape(self, tmp_path, monkeypatch):
        """Some ACP agents advertise availableModels with id rather than modelId."""
        client = ACPClient(
            project_root=tmp_path,
            command="some-agent --acp",
            model="deepseek/deepseek-v4-pro",
        )
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append((method, params))
            return {
                "sessionId": "session-1",
                "models": {
                    "currentModelId": "opencode/big-pickle",
                    "availableModels": [
                        {"id": "opencode/big-pickle", "name": "Big Pickle"},
                        {"id": "deepseek/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
                    ],
                },
            }

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        assert calls[1] == (
            "session/set_model",
            {"sessionId": "session-1", "modelId": "deepseek/deepseek-v4-pro"},
        )
        assert client._current_model_id == "deepseek/deepseek-v4-pro"

    @pytest.mark.asyncio
    async def test_new_session_skips_set_model_when_already_current(self, tmp_path, monkeypatch):
        """No redundant set_model when the session already starts on our model."""
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            model="opencode/big-pickle",
        )
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append(method)
            return {
                "sessionId": "session-1",
                "models": {
                    "currentModelId": "opencode/big-pickle",
                    "availableModels": [{"modelId": "opencode/big-pickle", "name": "Big Pickle"}],
                },
            }

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        assert calls == ["session/new"]

    @pytest.mark.asyncio
    async def test_new_session_skips_set_model_for_unadvertised_model(self, tmp_path, monkeypatch):
        """Don't send a model id the agent never advertised (and no models => skip)."""
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            model="opencode/not-a-real-model",
        )
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append(method)
            return {
                "sessionId": "session-1",
                "models": {
                    "currentModelId": "opencode/big-pickle",
                    "availableModels": [{"modelId": "opencode/big-pickle", "name": "Big Pickle"}],
                },
            }

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        await client._new_session()

        assert calls == ["session/new"]

    @pytest.mark.asyncio
    async def test_set_mode_uses_acp_mode_id_parameter(self, tmp_path, monkeypatch):
        """ACP session/set_mode expects modeId, not SuperQode's older modeSlug alias."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")
        client._session_id = "session-1"
        calls = []

        async def fake_call_method(method, *, timeout=None, **params):
            calls.append((method, params))
            return {}

        monkeypatch.setattr(client, "_call_method", fake_call_method)

        assert await client.set_mode("plan") is True
        assert calls == [
            (
                "session/set_mode",
                {
                    "sessionId": "session-1",
                    "modeId": "plan",
                },
            )
        ]
        assert await client.get_current_mode() == "plan"

    @pytest.mark.asyncio
    async def test_terminal_requests_delegate_to_service(self, tmp_path):
        """TUI callers can own ACP terminal lifecycle through terminal_service."""

        class FakeTerminalService:
            def __init__(self):
                self.calls = []

            async def create(self, params):
                self.calls.append(("create", params))
                return {"terminalId": "ui-terminal-1"}

            async def output(self, params):
                self.calls.append(("output", params))
                return {"output": "hello", "truncated": False}

            async def kill(self, params):
                self.calls.append(("kill", params))
                return {}

            async def release(self, params):
                self.calls.append(("release", params))
                return {}

            async def wait_for_exit(self, params):
                self.calls.append(("wait_for_exit", params))
                return {"exitCode": 0, "signal": None}

        service = FakeTerminalService()
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            terminal_service=service,
        )

        assert await client._handle_agent_request(
            "terminal/create", {"command": "echo", "args": ["hello"]}
        ) == {"terminalId": "ui-terminal-1"}
        assert await client._handle_agent_request(
            "terminal/output", {"terminalId": "ui-terminal-1"}
        ) == {"output": "hello", "truncated": False}
        assert await client._handle_agent_request(
            "terminal/wait_for_exit", {"terminalId": "ui-terminal-1"}
        ) == {"exitCode": 0, "signal": None}
        assert (
            await client._handle_agent_request("terminal/kill", {"terminalId": "ui-terminal-1"})
            == {}
        )
        assert (
            await client._handle_agent_request("terminal/release", {"terminalId": "ui-terminal-1"})
            == {}
        )

        assert [name for name, _params in service.calls] == [
            "create",
            "output",
            "wait_for_exit",
            "kill",
            "release",
        ]
        assert client._terminals == {}

    @pytest.mark.asyncio
    async def test_terminal_release_fallback_remains_available(self, tmp_path):
        """Headless callers without terminal_service still use client-owned terminals."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")
        client._terminals["terminal-1"] = {"process": None}

        assert (
            await client._handle_agent_request("terminal/release", {"terminalId": "terminal-1"})
            == {}
        )
        assert "terminal-1" not in client._terminals

    @pytest.mark.asyncio
    async def test_read_loop_does_not_block_responses_behind_permission_request(
        self, tmp_path, monkeypatch
    ):
        """Blocking inbound RPC handlers must not stall unrelated responses.

        ACP agents can ask for permission while also sending responses to
        earlier client requests. If the read loop awaits the permission handler
        inline, the pending response is not processed until the user answers.
        """

        class FakeStdout:
            def __init__(self, lines):
                self._lines = [line.encode("utf-8") + b"\n" for line in lines]
                self.eof = asyncio.Event()

            async def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                await self.eof.wait()
                return b""

        class FakeProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        permission_can_finish = asyncio.Event()

        async def on_permission_request(options, tool_call):
            await permission_can_finish.wait()
            return options[0]["optionId"]

        permission_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/request_permission",
            "params": {
                "options": [
                    {
                        "optionId": "allow-1",
                        "name": "Allow",
                        "kind": "allow_once",
                    }
                ],
                "toolCall": {
                    "toolCallId": "tool-1",
                    "title": "Run command",
                },
            },
        }
        unrelated_response = {
            "jsonrpc": "2.0",
            "id": 99,
            "result": {"ok": True},
        }

        stdout = FakeStdout([json.dumps(permission_request), json.dumps(unrelated_response)])
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            on_permission_request=on_permission_request,
        )
        client._process = FakeProcess(stdout)
        pending = asyncio.get_running_loop().create_future()
        client._pending_requests[99] = pending
        sent = []

        async def fake_send_json(data):
            sent.append(data)

        monkeypatch.setattr(client, "_send_json", fake_send_json)

        read_task = asyncio.create_task(client._read_loop())
        assert await asyncio.wait_for(pending, timeout=1.0) == {"ok": True}

        permission_can_finish.set()
        stdout.eof.set()
        await asyncio.wait_for(read_task, timeout=1.0)

        assert sent == [
            {
                "jsonrpc": "2.0",
                "result": {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": "allow-1",
                    }
                },
                "id": 1,
            }
        ]

    @pytest.mark.asyncio
    async def test_read_loop_preserves_notification_order_before_prompt_response(self, tmp_path):
        """Prompt completion must not overtake queued message callbacks.

        OpenCode sends the final agent_message_chunk immediately before the
        session/prompt response. Processing every inbound message in a detached
        task allowed the response future to resolve first, causing the TUI to
        report that no response was received even though text was on the wire.
        """

        class FakeStdout:
            def __init__(self, lines):
                self._lines = [line.encode("utf-8") + b"\n" for line in lines]
                self.eof = asyncio.Event()

            async def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                await self.eof.wait()
                return b""

        class FakeProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        message_can_finish = asyncio.Event()
        messages = []

        async def on_message(text):
            await message_can_finish.wait()
            messages.append(text)

        update = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "session-1",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "model reply"},
                },
            },
        }
        prompt_response = {
            "jsonrpc": "2.0",
            "id": 99,
            "result": {"stopReason": "end_turn"},
        }

        stdout = FakeStdout([json.dumps(update), json.dumps(prompt_response)])
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            on_message=on_message,
        )
        client._process = FakeProcess(stdout)
        pending = asyncio.get_running_loop().create_future()
        client._pending_requests[99] = pending

        read_task = asyncio.create_task(client._read_loop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert pending.done() is False

        message_can_finish.set()
        assert await asyncio.wait_for(pending, timeout=1.0) == {"stopReason": "end_turn"}
        stdout.eof.set()
        await asyncio.wait_for(read_task, timeout=1.0)

        assert messages == ["model reply"]
        assert client.get_message_buffer() == "model reply"

    @pytest.mark.asyncio
    async def test_traffic_logging_to_explicit_path(self, tmp_path):
        """ACP traffic logs raw client/agent JSON when an explicit path is configured."""

        class FakeStdin:
            def __init__(self):
                self.writes = []

            def write(self, data):
                self.writes.append(data)

            async def drain(self):
                return None

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = None

        log_path = tmp_path / "traffic.jsonl"
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            traffic_log_path=log_path,
        )
        client._process = FakeProcess()

        await client._initialize_traffic_log()
        await client._send_json({"jsonrpc": "2.0", "method": "initialize", "id": 1})
        await client._log_traffic("agent->client", {"jsonrpc": "2.0", "result": {}, "id": 1})

        records = [json.loads(line) for line in log_path.read_text().splitlines()]
        assert records[0]["direction"] == "meta"
        assert records[0]["event"] == "start"
        assert records[1]["direction"] == "client->agent"
        assert records[1]["payload"]["method"] == "initialize"
        assert records[2]["direction"] == "agent->client"
        assert records[2]["payload"]["id"] == 1
        assert client.get_traffic_log_path() == log_path

    @pytest.mark.asyncio
    async def test_traffic_logging_env_uses_per_agent_default_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
        monkeypatch.setenv("SUPERQODE_ACP_TRAFFIC_LOG", "1")

        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            agent_identity="opencode.ai",
        )
        await client._initialize_traffic_log()

        log_path = client.get_traffic_log_path()
        assert log_path is not None
        assert log_path.parent == default_acp_traffic_log_dir()
        assert log_path.name.startswith("opencode.ai-")
        assert log_path.suffix == ".jsonl"

    @pytest.mark.asyncio
    async def test_traffic_logging_write_failure_is_non_fatal(self, tmp_path, monkeypatch):
        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            traffic_log_path=tmp_path / "traffic.jsonl",
        )
        client._traffic_log_resolved_path = tmp_path / "traffic.jsonl"

        def fail_open(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "open", fail_open)

        await client._log_traffic("client->agent", {"ok": True})

    @pytest.mark.asyncio
    async def test_real_subprocess_agent_exercises_terminal_service_path(self, tmp_path):
        """Run a tiny ACP subprocess that calls terminal/* during a prompt turn.

        This covers the real ``ACPClient.start()`` + read loop + outbound
        request correlation path, not just direct method calls.
        """

        server_path = tmp_path / "fake_acp_terminal_server.py"
        server_path.write_text(
            textwrap.dedent(
                """
                import json
                import sys


                def send(payload):
                    print(json.dumps(payload), flush=True)


                def recv():
                    line = sys.stdin.readline()
                    if not line:
                        raise SystemExit(0)
                    return json.loads(line)


                session_id = "fake-session-1"
                while True:
                    request = recv()
                    method = request.get("method")
                    request_id = request.get("id")
                    if method == "initialize":
                        send({
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": 1,
                                "agentCapabilities": {
                                    "loadSession": False,
                                    "promptCapabilities": {},
                                },
                            },
                        })
                    elif method == "session/new":
                        send({
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"sessionId": session_id},
                        })
                    elif method == "session/prompt":
                        send({
                            "jsonrpc": "2.0",
                            "id": 101,
                            "method": "terminal/create",
                            "params": {
                                "sessionId": session_id,
                                "command": "echo",
                                "args": ["fake_terminal_service_smoke"],
                            },
                        })
                        create_response = recv()
                        terminal_id = create_response["result"]["terminalId"]
                        send({
                            "jsonrpc": "2.0",
                            "id": 102,
                            "method": "terminal/output",
                            "params": {
                                "sessionId": session_id,
                                "terminalId": terminal_id,
                            },
                        })
                        recv()
                        send({
                            "jsonrpc": "2.0",
                            "id": 103,
                            "method": "terminal/wait_for_exit",
                            "params": {
                                "sessionId": session_id,
                                "terminalId": terminal_id,
                            },
                        })
                        recv()
                        send({
                            "jsonrpc": "2.0",
                            "method": "session/update",
                            "params": {
                                "sessionId": session_id,
                                "update": {
                                    "sessionUpdate": "agent_message_chunk",
                                    "content": {
                                        "type": "text",
                                        "text": "terminal done",
                                    },
                                },
                            },
                        })
                        send({
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"stopReason": "end_turn"},
                        })
                    else:
                        send({
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": f"unknown {method}"},
                        })
                """
            ),
            encoding="utf-8",
        )

        class FakeTerminalService:
            def __init__(self):
                self.calls = []

            async def create(self, params):
                self.calls.append(("create", params))
                return {"terminalId": "host-terminal-1"}

            async def output(self, params):
                self.calls.append(("output", params))
                return {"output": "fake_terminal_service_smoke", "truncated": False}

            async def kill(self, params):
                self.calls.append(("kill", params))
                return {}

            async def release(self, params):
                self.calls.append(("release", params))
                return {}

            async def wait_for_exit(self, params):
                self.calls.append(("wait_for_exit", params))
                return {"exitCode": 0, "signal": None}

        service = FakeTerminalService()
        messages = []

        async def on_message(text):
            messages.append(text)

        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(server_path))}"
        client = ACPClient(
            project_root=tmp_path,
            command=command,
            terminal_service=service,
            on_message=on_message,
            startup_timeout=5,
            request_timeout=5,
            prompt_timeout=5,
        )

        try:
            assert await client.start() is True
            assert await client.send_prompt("run terminal smoke") == "end_turn"
        finally:
            await client.stop()

        assert messages == ["terminal done"]
        assert [name for name, _params in service.calls] == [
            "create",
            "output",
            "wait_for_exit",
        ]
        assert service.calls[0][1]["command"] == "echo"
        assert service.calls[1][1]["terminalId"] == "host-terminal-1"
        assert service.calls[2][1]["terminalId"] == "host-terminal-1"


class TestProtocolConstants:
    """Tests for protocol constants."""

    def test_protocol_version(self):
        """Test protocol version is defined."""
        assert PROTOCOL_VERSION == 1

    def test_client_name(self):
        """Test client name."""
        assert CLIENT_NAME == "SuperQode"

    def test_client_version(self):
        """Test client version format."""
        assert CLIENT_VERSION == "0.1.20"


class TestToolCall:
    """Tests for ToolCall type."""

    def test_create_tool_call(self):
        """Test creating a tool call."""
        tool_call = ToolCall(
            toolCallId="tool-123",
            title="read_file",
            rawInput={"path": "/test/file.py"},
        )

        assert tool_call["toolCallId"] == "tool-123"
        assert tool_call["title"] == "read_file"
        assert tool_call["rawInput"]["path"] == "/test/file.py"


class TestToolCallUpdate:
    """Tests for ToolCallUpdate type."""

    def test_create_tool_call_update(self):
        """Test creating a tool call update."""
        update = ToolCallUpdate(
            toolCallId="tool-123",
            status="completed",
            rawOutput={"content": "File contents..."},
        )

        assert update["toolCallId"] == "tool-123"
        assert update["status"] == "completed"


class TestPermissionOption:
    """Tests for PermissionOption type."""

    def test_create_permission_option(self):
        """Test creating a permission option."""
        option = PermissionOption(
            optionId="allow",
            name="Allow",
            kind="allow_once",
        )

        assert option["optionId"] == "allow"
        assert option["name"] == "Allow"


# Integration tests (marked to skip unless in full test mode)
@pytest.mark.integration
class TestACPClientIntegration:
    """Integration tests for ACP client.

    These tests require an actual ACP agent to be installed and available.
    Run with: pytest -m integration
    """

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires ACP agent to be installed")
    async def test_start_stop_client(self, tmp_path):
        """Test starting and stopping the client."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")

        await client.start()
        assert client._process is not None

        await client.stop()
        assert client._process is None


class TestToolUpdateMerging:
    """Sparse tool_call_update payloads must reach consumers merged."""

    @pytest.mark.asyncio
    async def test_on_tool_update_receives_merged_record(self, tmp_path):
        from superqode.acp.client import ACPClient

        seen_updates = []
        seen_calls = []

        async def on_tool_update(update):
            seen_updates.append(update)

        async def on_tool_call(call):
            seen_calls.append(call)

        client = ACPClient(
            project_root=tmp_path,
            command="opencode acp",
            on_tool_call=on_tool_call,
            on_tool_update=on_tool_update,
        )

        await client._handle_session_update(
            {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "title": "Run tests",
                    "kind": "execute",
                    "status": "in_progress",
                    "rawInput": {"command": "pytest -q"},
                }
            }
        )
        # Follow-up carries only id + status, as several agents send it.
        await client._handle_session_update(
            {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": "completed",
                }
            }
        )

        assert len(seen_updates) == 1
        merged = seen_updates[0]
        assert merged["status"] == "completed"
        assert merged["title"] == "Run tests"  # from the original call
        assert merged["rawInput"] == {"command": "pytest -q"}
