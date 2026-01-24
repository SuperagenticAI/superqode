"""
ACP Client for SuperQode.

Handles communication with ACP-compatible coding agents like OpenCode.
This is the primary interface for all ACP agent communication.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional, Dict, List
from dataclasses import dataclass, field
from time import monotonic

from superqode.acp.types import (
    PermissionOption,
    ToolCall,
    ToolCallUpdate,
    ContentBlock,
    InitializeResponse,
    NewSessionResponse,
    SessionPromptResponse,
    CreateTerminalResponse,
    TerminalOutputResponse,
    WaitForTerminalExitResponse,
    AvailableMode,
    AvailableModel,
    ModesResponse,
    ModelsResponse,
    SlashCommand,
    AvailableCommandsResponse,
)


PROTOCOL_VERSION = 1
CLIENT_NAME = "SuperQode"
CLIENT_VERSION = "0.1.0"


@dataclass
class ACPMessage:
    """A message received from the agent."""

    type: str
    data: dict[str, Any]


@dataclass
class ACPStats:
    """Statistics from an ACP session."""

    tool_count: int = 0
    files_modified: List[str] = field(default_factory=list)
    files_read: List[str] = field(default_factory=list)
    duration: float = 0.0
    stop_reason: str = ""


@dataclass
class ACPClient:
    """
    ACP (Agent Client Protocol) client for communicating with coding agents.

    This client manages the subprocess communication with an ACP-compatible agent
    and handles the JSON-RPC protocol.
    """

    project_root: Path
    command: str  # e.g., "opencode acp"
    model: Optional[str] = None

    # Callbacks for handling agent events
    on_message: Optional[Callable[[str], Awaitable[None]]] = None
    on_thinking: Optional[Callable[[str], Awaitable[None]]] = None
    on_tool_call: Optional[Callable[[ToolCall], Awaitable[None]]] = None
    on_tool_update: Optional[Callable[[ToolCallUpdate], Awaitable[None]]] = None
    on_permission_request: Optional[
        Callable[[List[PermissionOption], ToolCall], Awaitable[str]]
    ] = None
    on_plan: Optional[Callable[[List[dict]], Awaitable[None]]] = None

    # Internal state
    _process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    _request_id: int = field(default=0, repr=False)
    _pending_requests: Dict[int, asyncio.Future] = field(default_factory=dict, repr=False)
    _session_id: str = field(default="", repr=False)
    _tool_calls: Dict[str, ToolCall] = field(default_factory=dict, repr=False)
    _read_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _terminal_count: int = field(default=0, repr=False)
    _terminals: Dict[str, dict] = field(default_factory=dict, repr=False)

    # Tracking stats
    _files_modified: List[str] = field(default_factory=list, repr=False)
    _files_read: List[str] = field(default_factory=list, repr=False)
    _tool_actions: List[dict] = field(default_factory=list, repr=False)
    _start_time: float = field(default=0.0, repr=False)
    _message_buffer: str = field(default="", repr=False)

    def reset_stats(self) -> None:
        """Reset tracking stats for a new prompt."""
        self._files_modified = []
        self._files_read = []
        self._tool_actions = []
        self._start_time = monotonic()
        self._message_buffer = ""

    def get_stats(self) -> ACPStats:
        """Get current session stats."""
        return ACPStats(
            tool_count=len(self._tool_actions),
            files_modified=self._files_modified.copy(),
            files_read=self._files_read.copy(),
            duration=monotonic() - self._start_time if self._start_time else 0.0,
        )

    def get_message_buffer(self) -> str:
        """Get accumulated message text."""
        return self._message_buffer

    async def start(self) -> bool:
        """Start the ACP agent subprocess."""
        try:
            # Use command as-is - model selection is handled via ACP protocol
            # Don't add -m flag as not all agents support it (e.g., opencode acp)
            cmd = self.command

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            # Add --print-logs for debugging if needed
            if "opencode" in cmd:
                cmd = f"{cmd} --print-logs"

            self._process = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=str(self.project_root),
                env=env,
                limit=10 * 1024 * 1024,  # 10MB buffer
            )

            # Start reading output
            self._read_task = asyncio.create_task(self._read_loop())

            # Initialize the protocol
            await self._initialize()

            # Create a new session
            await self._new_session()

            return True

        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[startup error] {e}")
            return False

    async def stop(self) -> None:
        """Stop the ACP agent subprocess."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

    async def send_prompt(self, prompt: str) -> Optional[str]:
        """
        Send a prompt to the agent and wait for completion.

        Returns the stop reason.
        """
        # Reset stats for this prompt
        self.reset_stats()

        content_blocks: List[ContentBlock] = [{"type": "text", "text": prompt}]

        response = await self._call_method(
            "session/prompt",
            prompt=content_blocks,
            sessionId=self._session_id,
        )

        stop_reason = response.get("stopReason") if response else None
        return stop_reason

    async def cancel(self) -> bool:
        """Cancel the current operation."""
        try:
            await self._send_notification(
                "session/cancel",
                sessionId=self._session_id,
                _meta={},
            )
            return True
        except Exception:
            return False

    async def switch_model(self, new_model: str) -> bool:
        """
        Switch to a new model, creating a new session.

        When the user changes the model, we need to:
        1. Stop the current session cleanly
        2. Update the model configuration
        3. Start fresh with a new session

        Args:
            new_model: The new model identifier to switch to.

        Returns:
            True if switch was successful, False otherwise.
        """
        try:
            # Cancel any pending operations
            await self.cancel()

            # Stop the current agent process
            await self.stop()

            # Update model
            self.model = new_model

            # Reset internal state
            self._session_id = ""
            self._tool_calls.clear()
            self._terminals.clear()
            self._terminal_count = 0
            self.reset_stats()

            # Start fresh with new session
            return await self.start()

        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[model switch error] {e}")
            return False

    async def reset_session(self) -> bool:
        """
        Reset the current session without changing the model.

        Creates a new session with the same configuration.

        Returns:
            True if reset was successful, False otherwise.
        """
        try:
            # Cancel any pending operations
            await self.cancel()

            # Reset internal state
            self._tool_calls.clear()
            self._terminals.clear()
            self._terminal_count = 0
            self.reset_stats()

            # Create new session
            await self._new_session()

            return True

        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[session reset error] {e}")
            return False

    def get_current_model(self) -> Optional[str]:
        """Get the currently configured model."""
        return self.model

    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id

    # ========================================================================
    # Internal Methods
    # ========================================================================

    async def _initialize(self) -> InitializeResponse:
        """Initialize the ACP protocol."""
        response = await self._call_method(
            "initialize",
            protocolVersion=PROTOCOL_VERSION,
            clientCapabilities={
                "fs": {
                    "readTextFile": True,
                    "writeTextFile": True,
                },
                "terminal": True,
            },
            clientInfo={
                "name": CLIENT_NAME,
                "title": "SuperQode - Multi-Agent Coding Team",
                "version": CLIENT_VERSION,
            },
        )
        return response

    async def _new_session(self) -> NewSessionResponse:
        """Create a new session."""
        response = await self._call_method(
            "session/new",
            cwd=str(self.project_root),
            mcpServers=[],
        )
        self._session_id = response.get("sessionId", "")
        return response

    async def _call_method(self, method: str, **params) -> Dict[str, Any]:
        """Call a JSON-RPC method and wait for response."""
        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        # Send request
        await self._send_json(request)

        # Wait for response
        try:
            response = await asyncio.wait_for(future, timeout=300.0)  # 5 min timeout
            return response
        except asyncio.TimeoutError:
            del self._pending_requests[request_id]
            raise

    async def _send_notification(self, method: str, **params) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._send_json(notification)

    async def _send_json(self, data: dict) -> None:
        """Send JSON data to the agent."""
        if self._process and self._process.stdin:
            json_bytes = json.dumps(data).encode("utf-8") + b"\n"
            self._process.stdin.write(json_bytes)
            await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """Read and process output from the agent."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    # Not JSON - might be debug output, log it
                    if self.on_thinking and line_str:
                        await self.on_thinking(f"[agent] {line_str}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.on_thinking:
                    await self.on_thinking(f"[error] {e}")
                break

    async def _handle_message(self, data: dict) -> None:
        """Handle an incoming JSON-RPC message."""
        # Check if it's a response to a pending request
        if "result" in data or "error" in data:
            request_id = data.get("id")
            if request_id and request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if "error" in data:
                    future.set_exception(Exception(data["error"].get("message", "Unknown error")))
                else:
                    future.set_result(data.get("result", {}))
            return

        # It's a request from the agent - handle it
        method = data.get("method", "")
        params = data.get("params", {})
        request_id = data.get("id")

        try:
            result = await self._handle_agent_request(method, params)

            # Send response if this was a request (not notification)
            if request_id is not None:
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id,
                }
                await self._send_json(response)

        except Exception as e:
            if request_id is not None:
                error_response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": str(e),
                    },
                    "id": request_id,
                }
                await self._send_json(error_response)

    async def _handle_agent_request(self, method: str, params: dict) -> Any:
        """Handle a request from the agent."""

        if method == "session/update":
            await self._handle_session_update(params)
            return {}

        elif method == "session/request_permission":
            return await self._handle_permission_request(params)

        elif method == "fs/read_text_file":
            return self._handle_read_file(params)

        elif method == "fs/write_text_file":
            return self._handle_write_file(params)

        elif method == "terminal/create":
            return await self._handle_terminal_create(params)

        elif method == "terminal/output":
            return await self._handle_terminal_output(params)

        elif method == "terminal/kill":
            return self._handle_terminal_kill(params)

        elif method == "terminal/release":
            return self._handle_terminal_release(params)

        elif method == "terminal/wait_for_exit":
            return await self._handle_terminal_wait_for_exit(params)

        else:
            raise Exception(f"Unknown method: {method}")

    async def _handle_session_update(self, params: dict) -> None:
        """Handle session update notifications."""
        # The params dict IS the update - sessionUpdate is a direct key
        update = params
        update_type = update.get("sessionUpdate", "")

        # Also check if update is nested (some implementations do this)
        if not update_type and "update" in params:
            update = params.get("update", {})
            update_type = update.get("sessionUpdate", "")

        if update_type == "agent_message_chunk":
            content = update.get("content", {})
            text = self._content_to_text(content)
            if text:
                self._message_buffer += text
                if self.on_message:
                    await self.on_message(text)

        elif update_type == "agent_thought_chunk":
            content = update.get("content", {})
            text = self._content_to_text(content)
            if text and self.on_thinking:
                await self.on_thinking(text)

        elif update_type == "tool_call":
            tool_call_id = update.get("toolCallId", "")
            self._tool_calls[tool_call_id] = update

            # Track tool action
            kind = update.get("kind", "other")
            title = update.get("title", "")
            raw_input = update.get("rawInput", {})
            self._tool_actions.append(
                {
                    "tool": title,
                    "kind": kind,
                    "input": raw_input,
                }
            )

            # Track file operations from tool call
            locations = update.get("locations", [])
            for loc in locations:
                path = loc.get("path", "")
                if path:
                    if kind in ("edit", "write", "delete"):
                        if path not in self._files_modified:
                            self._files_modified.append(path)
                    elif kind == "read":
                        if path not in self._files_read:
                            self._files_read.append(path)

            if self.on_tool_call:
                await self.on_tool_call(update)

        elif update_type == "tool_call_update":
            tool_call_id = update.get("toolCallId", "")
            if tool_call_id in self._tool_calls:
                # Merge update into existing tool call
                for key, value in update.items():
                    if value is not None:
                        self._tool_calls[tool_call_id][key] = value
            if self.on_tool_update:
                await self.on_tool_update(update)

        elif update_type == "plan":
            entries = update.get("entries", [])
            if self.on_plan:
                await self.on_plan(entries)

    def _content_to_text(self, content: Any) -> str:
        """Convert ACP content blocks into a displayable text string."""
        if content is None:
            return ""
        if isinstance(content, list):
            parts = [self._content_to_text(item) for item in content]
            return "".join([p for p in parts if p])
        if not isinstance(content, dict):
            return str(content)

        content_type = content.get("type")
        if content_type == "text":
            return content.get("text", "")
        if content_type == "image":
            mime = content.get("mimeType", "image")
            data = content.get("data", "")
            size = len(data) if isinstance(data, str) else 0
            return f"[image:{mime} {size} bytes]"
        if content_type == "audio":
            mime = content.get("mimeType", "audio")
            return f"[audio:{mime}]"
        if content_type in ("resource", "embedded_resource", "embeddedResource"):
            name = content.get("name") or content.get("uri") or "resource"
            return f"[resource:{name}]"
        if content_type in ("resource_link", "link"):
            name = content.get("title") or content.get("uri") or "link"
            return f"[link:{name}]"

        text = content.get("text")
        if text:
            return text
        return ""

    async def _handle_permission_request(self, params: dict) -> dict:
        """Handle permission request from agent."""
        options = params.get("options", [])
        tool_call = params.get("toolCall", {})

        # Store tool call if not already stored
        tool_call_id = tool_call.get("toolCallId", "")
        if tool_call_id and tool_call_id not in self._tool_calls:
            self._tool_calls[tool_call_id] = tool_call

        # Call the permission callback if set
        if self.on_permission_request:
            option_id = await self.on_permission_request(options, tool_call)
            return {
                "outcome": {
                    "outcome": "selected",
                    "optionId": option_id,
                }
            }

        # Default: allow once
        for opt in options:
            if opt.get("kind") == "allow_once":
                return {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": opt.get("optionId", ""),
                    }
                }

        # Fallback to first option
        if options:
            return {
                "outcome": {
                    "outcome": "selected",
                    "optionId": options[0].get("optionId", ""),
                }
            }

        return {"outcome": {"outcome": "cancelled"}}

    def _handle_read_file(self, params: dict) -> dict:
        """Handle file read request."""
        path = params.get("path", "")
        line = params.get("line")
        limit = params.get("limit")

        # Track file read
        if path and path not in self._files_read:
            self._files_read.append(path)

        read_path = self.project_root / path
        try:
            text = read_path.read_text(encoding="utf-8", errors="ignore")

            if line is not None:
                line = max(0, line - 1)
                lines = text.splitlines()
                if limit is None:
                    text = "\n".join(lines[line:])
                else:
                    text = "\n".join(lines[line : line + limit])

            return {"content": text}
        except IOError:
            return {"content": ""}

    def _handle_write_file(self, params: dict) -> dict:
        """Handle file write request."""
        path = params.get("path", "")
        content = params.get("content", "")

        # Track file modification
        if path and path not in self._files_modified:
            self._files_modified.append(path)

        write_path = self.project_root / path
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(content, encoding="utf-8")
        return {}

    # ========================================================================
    # Mode and Model Management (ACP Protocol Completeness)
    # ========================================================================

    async def get_available_modes(self) -> List[AvailableMode]:
        """Get list of available modes from the agent."""
        try:
            response = await self._call_method(
                "session/modes",
                sessionId=self._session_id,
            )
            return response.get("modes", [])
        except Exception:
            return []

    async def get_available_models(self) -> List[AvailableModel]:
        """Get list of available models from the agent."""
        try:
            response = await self._call_method(
                "session/models",
                sessionId=self._session_id,
            )
            return response.get("models", [])
        except Exception:
            return []

    async def set_mode(self, mode_slug: str) -> bool:
        """Set the current mode for the session."""
        try:
            await self._call_method(
                "session/set_mode",
                sessionId=self._session_id,
                modeSlug=mode_slug,
            )
            return True
        except Exception:
            return False

    async def set_model(self, model_id: str) -> bool:
        """Set the current model for the session."""
        try:
            await self._call_method(
                "session/set_model",
                sessionId=self._session_id,
                modelId=model_id,
            )
            return True
        except Exception:
            return False

    async def get_current_mode(self) -> Optional[str]:
        """Get the current mode."""
        try:
            response = await self._call_method(
                "session/modes",
                sessionId=self._session_id,
            )
            return response.get("currentMode")
        except Exception:
            return None

    async def get_current_model(self) -> Optional[str]:
        """Get the current model."""
        try:
            response = await self._call_method(
                "session/models",
                sessionId=self._session_id,
            )
            return response.get("currentModel")
        except Exception:
            return None

    # ========================================================================
    # Slash Commands (ACP Protocol Completeness)
    # ========================================================================

    async def get_available_commands(self) -> List[SlashCommand]:
        """Get list of available slash commands from the agent."""
        try:
            response = await self._call_method(
                "session/commands",
                sessionId=self._session_id,
            )
            return response.get("commands", [])
        except Exception:
            return []

    async def execute_command(
        self, command_name: str, args: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Execute a slash command."""
        try:
            response = await self._call_method(
                "session/execute_command",
                sessionId=self._session_id,
                command=command_name,
                args=args or {},
            )
            return response.get("result")
        except Exception as e:
            return None

    # ========================================================================
    # Batch Operations (ACP Protocol Completeness)
    # ========================================================================

    async def batch_request(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute multiple requests in a batch."""
        try:
            response = await self._call_method(
                "batch",
                requests=requests,
            )
            return response.get("responses", [])
        except Exception:
            return []

    # ========================================================================
    # Terminal Handling
    # ========================================================================

    async def _handle_terminal_create(self, params: dict) -> CreateTerminalResponse:
        """Handle terminal create request."""
        command = params.get("command", "")
        args = params.get("args", [])
        cwd = params.get("cwd")
        env_vars = params.get("env", [])

        self._terminal_count += 1
        terminal_id = f"terminal-{self._terminal_count}"

        # Build environment
        env = os.environ.copy()
        for var in env_vars:
            env[var["name"]] = var["value"]

        # Build full command
        if args:
            full_command = f"{command} {' '.join(args)}"
        else:
            full_command = command

        # Start the process
        try:
            process = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE,
                cwd=cwd or str(self.project_root),
                env=env,
            )

            self._terminals[terminal_id] = {
                "process": process,
                "output": "",
                "truncated": False,
                "exit_code": None,
                "signal": None,
            }

            # Start reading output in background
            asyncio.create_task(self._read_terminal_output(terminal_id))

            return {"terminalId": terminal_id}

        except Exception as e:
            raise Exception(f"Failed to create terminal: {e}")

    async def _read_terminal_output(self, terminal_id: str) -> None:
        """Read output from a terminal process."""
        terminal = self._terminals.get(terminal_id)
        if not terminal:
            return

        process = terminal["process"]
        output_limit = 100 * 1024  # 100KB limit

        try:
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break

                text = chunk.decode("utf-8", errors="replace")

                if len(terminal["output"]) + len(text) > output_limit:
                    terminal["truncated"] = True
                    remaining = output_limit - len(terminal["output"])
                    terminal["output"] += text[:remaining]
                    break
                else:
                    terminal["output"] += text

            # Process finished
            await process.wait()
            terminal["exit_code"] = process.returncode

        except Exception:
            pass

    async def _handle_terminal_output(self, params: dict) -> TerminalOutputResponse:
        """Handle terminal output request."""
        terminal_id = params.get("terminalId", "")
        terminal = self._terminals.get(terminal_id)

        if not terminal:
            return {
                "output": "",
                "truncated": False,
            }

        result: TerminalOutputResponse = {
            "output": terminal["output"],
            "truncated": terminal["truncated"],
        }

        if terminal["exit_code"] is not None:
            result["exitStatus"] = {"exitCode": terminal["exit_code"]}

        return result

    def _handle_terminal_kill(self, params: dict) -> dict:
        """Handle terminal kill request."""
        terminal_id = params.get("terminalId", "")
        terminal = self._terminals.get(terminal_id)

        if terminal and terminal["process"]:
            terminal["process"].terminate()

        return {}

    def _handle_terminal_release(self, params: dict) -> dict:
        """Handle terminal release request."""
        terminal_id = params.get("terminalId", "")
        if terminal_id in self._terminals:
            del self._terminals[terminal_id]
        return {}

    async def _handle_terminal_wait_for_exit(self, params: dict) -> WaitForTerminalExitResponse:
        """Handle terminal wait for exit request."""
        terminal_id = params.get("terminalId", "")
        terminal = self._terminals.get(terminal_id)

        if not terminal:
            return {"exitCode": -1, "signal": None}

        process = terminal["process"]

        # Wait for process to complete
        await process.wait()
        terminal["exit_code"] = process.returncode

        return {
            "exitCode": terminal["exit_code"],
            "signal": terminal["signal"],
        }
