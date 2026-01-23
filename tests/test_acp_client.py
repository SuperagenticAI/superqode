"""
Tests for SuperQode ACP (Agent Client Protocol) Client.

Tests the communication layer for ACP-compatible coding agents.
"""

import pytest
import asyncio
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

    def test_client_without_model(self, tmp_path):
        """Test client initialization without model."""
        client = ACPClient(project_root=tmp_path, command="opencode acp")

        assert client.model is None

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
        assert CLIENT_VERSION == "0.1.0"


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
