"""ACP client implementation for SuperQode."""

import asyncio
import logging
import os
import sys
import pathlib
from pathlib import Path
from typing import Any

# Ensure CWD exists before importing acp (which imports logfire that resolves CWD)
# This prevents FileNotFoundError when CWD doesn't exist
try:
    cwd = os.getcwd()
    if not pathlib.Path(cwd).exists():
        # Change to home directory if CWD doesn't exist
        os.chdir(os.path.expanduser("~"))
except (OSError, FileNotFoundError):
    # If getcwd() fails, change to home directory
    try:
        os.chdir(os.path.expanduser("~"))
    except Exception:
        pass  # Last resort - let it fail naturally

# Now safe to import acp
from acp import (
    PROTOCOL_VERSION,
    Client,
    RequestError,
    connect_to_agent,
    text_block,
)
from acp.core import ClientSideConnection
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AudioContentBlock,
    AvailableCommandsUpdate,
    ClientCapabilities,
    CreateTerminalResponse,
    CurrentModeUpdate,
    EmbeddedResourceContentBlock,
    EnvVariable,
    ImageContentBlock,
    Implementation,
    KillTerminalCommandResponse,
    PermissionOption,
    ReadTextFileResponse,
    ReleaseTerminalResponse,
    RequestPermissionResponse,
    ResourceContentBlock,
    TerminalOutputResponse,
    ToolCall,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
    WaitForTerminalExitResponse,
    WriteTextFileResponse,
)


class SuperQodeACPClient(Client):
    """ACP client implementation for SuperQode."""

    def __init__(self):
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.current_session_id: str | None = None

    async def request_permission(
        self, options: list[PermissionOption], session_id: str, tool_call: ToolCall, **kwargs: Any
    ) -> RequestPermissionResponse:
        """Handle permission requests from agent."""
        # For now, auto-approve all permissions
        # In the future, this could show a UI for user approval
        return RequestPermissionResponse(
            permission="approved", message="Auto-approved by SuperQode"
        )

    async def write_text_file(
        self, content: str, path: str, session_id: str, **kwargs: Any
    ) -> WriteTextFileResponse:
        """Handle file write requests."""
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return WriteTextFileResponse(success=True)
        except Exception as e:
            return WriteTextFileResponse(success=False, message=str(e))

    async def read_text_file(
        self,
        path: str,
        session_id: str,
        limit: int | None = None,
        line: int | None = None,
        **kwargs: Any,
    ) -> ReadTextFileResponse:
        """Handle file read requests."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return ReadTextFileResponse(success=True, content=content)
        except Exception as e:
            return ReadTextFileResponse(success=False, message=str(e))

    async def create_terminal(
        self,
        command: str,
        session_id: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: list[EnvVariable] | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> CreateTerminalResponse:
        """Handle terminal creation requests."""
        raise RequestError.method_not_found("terminal/create")

    async def kill_terminal(
        self, session_id: str, signal: int | None = None, **kwargs: Any
    ) -> KillTerminalCommandResponse:
        """Handle terminal kill requests."""
        raise RequestError.method_not_found("terminal/kill")

    async def release_terminal(self, session_id: str, **kwargs: Any) -> ReleaseTerminalResponse:
        """Handle terminal release requests."""
        raise RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(
        self, session_id: str, **kwargs: Any
    ) -> WaitForTerminalExitResponse:
        """Handle terminal wait requests."""
        raise RequestError.method_not_found("terminal/wait")

    async def on_connect(self, conn: Any) -> None:
        """Handle agent connection."""
        logging.info(f"Connected to agent: {conn}")
        self.current_session_id = getattr(conn, "session_id", None)

    async def on_disconnect(self, conn: Any) -> None:
        """Handle agent disconnection."""
        logging.info(f"Disconnected from agent: {conn}")
        self.current_session_id = None


class ACPAgentManager:
    """Manages ACP agent connections."""

    def __init__(self):
        self.client: SuperQodeACPClient | None = None
        self.connection: ClientSideConnection | None = None
        self._response_queue: asyncio.Queue = asyncio.Queue()

    async def connect_to_agent(self, command: str, cwd: str | None = None) -> bool:
        """Connect to an ACP agent.

        Args:
            command: The command to run the agent
            cwd: Working directory for the connection

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Parse command
            import shlex

            cmd_parts = shlex.split(command)
            program = cmd_parts[0]
            args = cmd_parts[1:] if len(cmd_parts) > 1 else []

            # Check if the program exists
            program_path = Path(program)
            if program_path.exists():
                # If it's a Python script, run it with python
                if program_path.suffix == ".py":
                    program = sys.executable
                    args = [str(program_path)] + args
                else:
                    program = program
                    args = args

            # Create subprocess
            proc = await asyncio.create_subprocess_exec(
                program,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                cwd=cwd or os.getcwd(),
            )

            if proc.stdin is None or proc.stdout is None:
                logging.error("Agent process does not expose stdio pipes")
                return False

            # Connect to the agent
            self.connection = connect_to_agent(self.client, proc.stdin, proc.stdout)

            # Initialize the connection
            await self.connection.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(
                    name="SuperQode", title="SuperQode ACP Client", version="0.1.0"
                ),
            )

            return True

        except Exception as e:
            logging.error(f"Failed to connect to agent: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the current agent."""
        if self.connection:
            await self.connection.close()
            self.connection = None
        if self.client:
            del self.client
            self.client = None

    async def send_message(self, message: str) -> None:
        """Send a message to the agent."""
        if not self.connection:
            raise RuntimeError("Not connected to an agent")

        # Create text block
        text_content = text_block(text=message)
        chunk = UserMessageChunk(role="user", content=[text_content])

        await self.connection.send(chunk)

    async def receive_messages(self) -> list:
        """Receive all pending messages from the agent."""
        messages = []
        while not self.client.message_queue.empty():
            try:
                msg = self.client.message_queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break
        return messages

    async def is_connected(self) -> bool:
        """Check if currently connected to an agent."""
        return self.connection is not None
