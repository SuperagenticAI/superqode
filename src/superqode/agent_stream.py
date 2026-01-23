"""
SuperQode Agent Streaming - Real-time Agent Communication

Implements ACP (Agent Client Protocol) for streaming agent output in real-time.
Supports OpenCode and other ACP-compatible agents.

Features:
- Real-time message streaming (agent responses, thoughts, tool calls)
- Interactive permission requests
- Plan tracking with live updates
- Colorful SuperQode styling
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Literal
from time import monotonic

# ============================================================================
# THEME & COLORS (SuperQode style)
# ============================================================================

STREAM_COLORS = {
    "message": "#a855f7",  # Purple - agent messages
    "thought": "#ec4899",  # Pink - thinking
    "tool": "#f97316",  # Orange - tool calls
    "plan": "#06b6d4",  # Cyan - plan updates
    "success": "#22c55e",  # Green - completed
    "error": "#ef4444",  # Red - errors
    "warning": "#f59e0b",  # Amber - warnings
    "pending": "#71717a",  # Gray - pending
    "progress": "#3b82f6",  # Blue - in progress
}

STREAM_ICONS = {
    "message": "💬",
    "thought": "💭",
    "tool_read": "📖",
    "tool_edit": "✏️",
    "tool_delete": "🗑️",
    "tool_execute": "⚡",
    "tool_search": "🔍",
    "tool_think": "🧠",
    "tool_fetch": "🌐",
    "tool_other": "🔧",
    "plan": "📋",
    "permission": "🔐",
    "success": "✅",
    "error": "❌",
    "pending": "⏳",
    "progress": "🔄",
}


# ============================================================================
# MESSAGE TYPES
# ============================================================================


class StreamEventType(Enum):
    """Types of streaming events from agents."""

    MESSAGE_CHUNK = "message_chunk"  # Agent text response
    THOUGHT_CHUNK = "thought_chunk"  # Agent thinking
    TOOL_CALL = "tool_call"  # Tool invocation started
    TOOL_UPDATE = "tool_update"  # Tool status update
    PLAN = "plan"  # Plan with tasks
    PERMISSION = "permission"  # Permission request
    MODE_UPDATE = "mode_update"  # Mode change
    STATUS = "status"  # Status line update
    ERROR = "error"  # Error occurred
    COMPLETE = "complete"  # Agent finished


class ToolKind(Enum):
    """Types of tool operations."""

    READ = "read"
    EDIT = "edit"
    DELETE = "delete"
    MOVE = "move"
    SEARCH = "search"
    EXECUTE = "execute"
    THINK = "think"
    FETCH = "fetch"
    SWITCH_MODE = "switch_mode"
    OTHER = "other"


class ToolStatus(Enum):
    """Status of a tool call."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(Enum):
    """Status of a plan task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TaskPriority(Enum):
    """Priority of a plan task."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class StreamMessage:
    """A chunk of agent message text."""

    text: str
    is_complete: bool = False


@dataclass
class StreamThought:
    """Agent's thinking/reasoning."""

    text: str


@dataclass
class ToolCallContent:
    """Content within a tool call (diff, terminal, etc.)."""

    type: str  # "content", "diff", "terminal"
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamToolCall:
    """A tool call from the agent."""

    tool_id: str
    title: str
    kind: ToolKind = ToolKind.OTHER
    status: ToolStatus = ToolStatus.PENDING
    content: List[ToolCallContent] = field(default_factory=list)
    locations: List[Dict[str, Any]] = field(default_factory=list)
    raw_input: Dict[str, Any] = field(default_factory=dict)
    raw_output: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanTask:
    """A task in the agent's plan."""

    content: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM


@dataclass
class StreamPlan:
    """Agent's plan with tasks."""

    tasks: List[PlanTask] = field(default_factory=list)


@dataclass
class PermissionOption:
    """An option for permission request."""

    option_id: str
    name: str
    kind: str  # allow_once, allow_always, reject_once, reject_always


@dataclass
class StreamPermission:
    """Permission request from agent."""

    tool_call: StreamToolCall
    options: List[PermissionOption] = field(default_factory=list)
    result_future: Optional[asyncio.Future] = None


@dataclass
class StreamEvent:
    """A streaming event from the agent."""

    event_type: StreamEventType
    data: Any  # StreamMessage, StreamThought, StreamToolCall, etc.
    timestamp: float = field(default_factory=monotonic)


# ============================================================================
# JSON-RPC HELPERS
# ============================================================================


class JSONRPCError(Exception):
    """JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code}: {message}")


def make_request(method: str, params: Dict[str, Any], request_id: int) -> bytes:
    """Create a JSON-RPC request."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    return json.dumps(request).encode("utf-8") + b"\n"


def make_response(request_id: int, result: Any) -> bytes:
    """Create a JSON-RPC response."""
    response = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
    return json.dumps(response).encode("utf-8") + b"\n"


def parse_message(line: bytes) -> Optional[Dict[str, Any]]:
    """Parse a JSON-RPC message from a line."""
    try:
        text = line.decode("utf-8").strip()
        if not text:
            return None
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# ============================================================================
# AGENT STREAM CLIENT
# ============================================================================


class AgentStreamClient:
    """
    Real-time streaming client for ACP-compatible agents.

    Spawns agent subprocess and streams JSON-RPC messages for live updates.
    """

    PROTOCOL_VERSION = 1

    def __init__(
        self,
        project_root: Path,
        agent_command: str,
        on_event: Optional[Callable[[StreamEvent], None]] = None,
    ):
        self.project_root = project_root
        self.agent_command = agent_command
        self.on_event = on_event

        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._session_id: str = ""
        self._tool_calls: Dict[str, StreamToolCall] = {}
        self._current_message: str = ""
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _emit(self, event_type: StreamEventType, data: Any):
        """Emit a streaming event."""
        event = StreamEvent(event_type=event_type, data=data)
        if self.on_event:
            self.on_event(event)

    async def start(self) -> bool:
        """Start the agent subprocess."""
        if self._process is not None:
            return True

        env = os.environ.copy()
        env["SUPERQODE_CWD"] = str(self.project_root.absolute())

        try:
            self._process = await asyncio.create_subprocess_shell(
                self.agent_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(self.project_root),
                limit=10 * 1024 * 1024,  # 10MB buffer
            )
            self._running = True

            # Start reading stdout in background
            asyncio.create_task(self._read_loop())

            # Initialize ACP
            await self._initialize()
            await self._new_session()

            return True

        except Exception as e:
            self._emit(StreamEventType.ERROR, str(e))
            return False

    async def stop(self):
        """Stop the agent subprocess."""
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

    async def _send(self, method: str, params: Dict[str, Any]) -> asyncio.Future:
        """Send a JSON-RPC request and return a future for the response."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Agent not started")

        request_id = self._next_request_id()
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future

        request = make_request(method, params, request_id)
        self._process.stdin.write(request)
        await self._process.stdin.drain()

        return future

    async def _respond(self, request_id: int, result: Any):
        """Send a JSON-RPC response."""
        if not self._process or not self._process.stdin:
            return

        response = make_response(request_id, result)
        self._process.stdin.write(response)
        await self._process.stdin.drain()

    async def _read_loop(self):
        """Read and process messages from agent stdout."""
        if not self._process or not self._process.stdout:
            return

        while self._running:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                msg = parse_message(line)
                if msg:
                    await self._handle_message(msg)

            except Exception as e:
                self._emit(StreamEventType.ERROR, f"Read error: {e}")
                break

        self._running = False
        self._emit(StreamEventType.COMPLETE, None)

    async def _handle_message(self, msg: Dict[str, Any]):
        """Handle an incoming JSON-RPC message."""
        # Check if it's a response to a pending request
        if "result" in msg or "error" in msg:
            request_id = msg.get("id")
            if request_id and request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if "error" in msg:
                    err = msg["error"]
                    future.set_exception(
                        JSONRPCError(
                            err.get("code", -1),
                            err.get("message", "Unknown error"),
                            err.get("data"),
                        )
                    )
                else:
                    future.set_result(msg.get("result"))
            return

        # It's a notification or request from the agent
        method = msg.get("method", "")
        params = msg.get("params", {})
        request_id = msg.get("id")

        if method == "session/update":
            await self._handle_session_update(params, request_id)
        elif method == "session/request_permission":
            await self._handle_permission_request(params, request_id)
        elif method == "fs/read_text_file":
            await self._handle_read_file(params, request_id)
        elif method == "fs/write_text_file":
            await self._handle_write_file(params, request_id)
        elif method == "terminal/create":
            await self._handle_terminal_create(params, request_id)
        elif method == "terminal/output":
            await self._handle_terminal_output(params, request_id)
        elif method == "terminal/kill":
            await self._handle_terminal_kill(params, request_id)

    async def _handle_session_update(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle session/update notifications."""
        update = params.get("update", {})
        update_type = update.get("sessionUpdate", "")

        if update_type == "agent_message_chunk":
            content = update.get("content", {})
            text = content.get("text", "")
            self._current_message += text
            self._emit(StreamEventType.MESSAGE_CHUNK, StreamMessage(text=text))

        elif update_type == "agent_thought_chunk":
            content = update.get("content", {})
            text = content.get("text", "")
            self._emit(StreamEventType.THOUGHT_CHUNK, StreamThought(text=text))

        elif update_type == "tool_call":
            tool_call = self._parse_tool_call(update)
            self._tool_calls[tool_call.tool_id] = tool_call
            self._emit(StreamEventType.TOOL_CALL, tool_call)

        elif update_type == "tool_call_update":
            tool_id = update.get("toolCallId", "")
            if tool_id in self._tool_calls:
                tool_call = self._tool_calls[tool_id]
                self._update_tool_call(tool_call, update)
                self._emit(StreamEventType.TOOL_UPDATE, tool_call)
            else:
                # Create new tool call from update
                tool_call = self._parse_tool_call(update)
                self._tool_calls[tool_id] = tool_call
                self._emit(StreamEventType.TOOL_CALL, tool_call)

        elif update_type == "plan":
            entries = update.get("entries", [])
            plan = StreamPlan(
                tasks=[
                    PlanTask(
                        content=e.get("content", ""),
                        status=TaskStatus(e.get("status", "pending")),
                        priority=TaskPriority(e.get("priority", "medium")),
                    )
                    for e in entries
                ]
            )
            self._emit(StreamEventType.PLAN, plan)

    def _parse_tool_call(self, data: Dict[str, Any]) -> StreamToolCall:
        """Parse a tool call from JSON data."""
        kind_str = data.get("kind", "other")
        try:
            kind = ToolKind(kind_str)
        except ValueError:
            kind = ToolKind.OTHER

        status_str = data.get("status", "pending")
        try:
            status = ToolStatus(status_str)
        except ValueError:
            status = ToolStatus.PENDING

        content = []
        for c in data.get("content", []):
            content.append(ToolCallContent(type=c.get("type", "content"), data=c))

        return StreamToolCall(
            tool_id=data.get("toolCallId", ""),
            title=data.get("title", "Tool Call"),
            kind=kind,
            status=status,
            content=content,
            locations=data.get("locations", []),
            raw_input=data.get("rawInput", {}),
            raw_output=data.get("rawOutput", {}),
        )

    def _update_tool_call(self, tool_call: StreamToolCall, update: Dict[str, Any]):
        """Update a tool call with new data."""
        if "title" in update and update["title"]:
            tool_call.title = update["title"]
        if "kind" in update and update["kind"]:
            try:
                tool_call.kind = ToolKind(update["kind"])
            except ValueError:
                pass
        if "status" in update and update["status"]:
            try:
                tool_call.status = ToolStatus(update["status"])
            except ValueError:
                pass
        if "content" in update and update["content"]:
            tool_call.content = [
                ToolCallContent(type=c.get("type", "content"), data=c) for c in update["content"]
            ]
        if "locations" in update:
            tool_call.locations = update["locations"]
        if "rawInput" in update:
            tool_call.raw_input = update["rawInput"]
        if "rawOutput" in update:
            tool_call.raw_output = update["rawOutput"]

    async def _handle_permission_request(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle permission request from agent."""
        options_data = params.get("options", [])
        tool_call_data = params.get("toolCall", {})

        options = [
            PermissionOption(
                option_id=o.get("optionId", ""),
                name=o.get("name", ""),
                kind=o.get("kind", "allow_once"),
            )
            for o in options_data
        ]

        tool_call = self._parse_tool_call(tool_call_data)

        # Create future for response
        result_future: asyncio.Future = asyncio.Future()

        permission = StreamPermission(
            tool_call=tool_call,
            options=options,
            result_future=result_future,
        )

        self._emit(StreamEventType.PERMISSION, permission)

        # Wait for user response
        try:
            selected_option_id = await asyncio.wait_for(result_future, timeout=300)

            if request_id is not None:
                await self._respond(
                    request_id,
                    {
                        "outcome": {
                            "outcome": "selected",
                            "optionId": selected_option_id,
                        }
                    },
                )
        except asyncio.TimeoutError:
            if request_id is not None:
                await self._respond(request_id, {"outcome": {"outcome": "cancelled"}})

    async def _handle_read_file(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle file read request from agent."""
        path = params.get("path", "")
        line = params.get("line")
        limit = params.get("limit")

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
        except IOError:
            text = ""

        if request_id is not None:
            await self._respond(request_id, {"content": text})

    async def _handle_write_file(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle file write request from agent."""
        path = params.get("path", "")
        content = params.get("content", "")

        write_path = self.project_root / path
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(content, encoding="utf-8")

        if request_id is not None:
            await self._respond(request_id, {})

    async def _handle_terminal_create(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle terminal create request."""
        # For now, just acknowledge - full terminal support can be added later
        terminal_id = f"terminal-{self._next_request_id()}"
        if request_id is not None:
            await self._respond(request_id, {"terminalId": terminal_id})

    async def _handle_terminal_output(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle terminal output request."""
        if request_id is not None:
            await self._respond(
                request_id,
                {
                    "output": "",
                    "truncated": False,
                },
            )

    async def _handle_terminal_kill(self, params: Dict[str, Any], request_id: Optional[int]):
        """Handle terminal kill request."""
        if request_id is not None:
            await self._respond(request_id, {})

    async def _initialize(self):
        """Initialize ACP protocol."""
        future = await self._send(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
                "clientInfo": {
                    "name": "SuperQode",
                    "title": "SuperQode - Multi-Agent Coding Team",
                    "version": "1.0.0",
                },
            },
        )

        try:
            result = await asyncio.wait_for(future, timeout=30)
            return result
        except asyncio.TimeoutError:
            raise RuntimeError("Agent initialization timed out")

    async def _new_session(self):
        """Create a new ACP session."""
        future = await self._send(
            "session/new",
            {
                "projectRoot": str(self.project_root),
                "mcpServers": [],
            },
        )

        try:
            result = await asyncio.wait_for(future, timeout=30)
            self._session_id = result.get("sessionId", "")
            return result
        except asyncio.TimeoutError:
            raise RuntimeError("Session creation timed out")

    async def send_prompt(self, prompt: str) -> Optional[str]:
        """Send a prompt to the agent and stream the response."""
        self._current_message = ""

        future = await self._send(
            "session/prompt",
            {
                "sessionId": self._session_id,
                "content": [{"type": "text", "text": prompt}],
            },
        )

        try:
            result = await future
            # Mark message as complete
            self._emit(StreamEventType.MESSAGE_CHUNK, StreamMessage(text="", is_complete=True))
            return result.get("stopReason")
        except JSONRPCError as e:
            self._emit(StreamEventType.ERROR, str(e))
            return None

    async def cancel(self) -> bool:
        """Cancel the current operation."""
        try:
            future = await self._send(
                "session/cancel",
                {
                    "sessionId": self._session_id,
                    "options": {},
                },
            )
            await asyncio.wait_for(future, timeout=5)
            return True
        except Exception:
            return False

    async def reset_session(self) -> bool:
        """
        Reset the session (e.g., after model change).

        Creates a new session without restarting the agent process.

        Returns:
            True if reset was successful, False otherwise.
        """
        try:
            # Cancel any pending operations
            await self.cancel()

            # Clear internal state
            self._tool_calls.clear()
            self._current_message = ""
            self._pending_requests.clear()

            # Create new session
            await self._new_session()

            return True
        except Exception as e:
            self._emit(StreamEventType.ERROR, f"Session reset failed: {e}")
            return False

    async def switch_agent(self, new_command: str) -> bool:
        """
        Switch to a different agent command.

        Stops the current agent and starts a new one with the given command.

        Args:
            new_command: The new agent command to run.

        Returns:
            True if switch was successful, False otherwise.
        """
        try:
            # Stop current agent
            await self.stop()

            # Update command
            self.agent_command = new_command

            # Clear state
            self._tool_calls.clear()
            self._current_message = ""
            self._pending_requests.clear()
            self._session_id = ""
            self._request_id = 0

            # Start fresh
            return await self.start()

        except Exception as e:
            self._emit(StreamEventType.ERROR, f"Agent switch failed: {e}")
            return False

    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id


# ============================================================================
# SIMPLE STREAMING CLIENT (for non-ACP agents like basic OpenCode)
# ============================================================================


class SimpleStreamClient:
    """
    Simple streaming client for agents that output plain text.

    Reads stdout line by line and emits message events.
    """

    def __init__(
        self,
        project_root: Path,
        command: List[str],
        on_event: Optional[Callable[[StreamEvent], None]] = None,
    ):
        self.project_root = project_root
        self.command = command
        self.on_event = on_event

        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None

    def _emit(self, event_type: StreamEventType, data: Any):
        """Emit a streaming event."""
        event = StreamEvent(event_type=event_type, data=data)
        if self.on_event:
            self.on_event(event)

    async def start(self) -> bool:
        """Start the subprocess."""
        if self._process is not None:
            return True

        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.project_root),
            )
            self._running = True
            return True
        except Exception as e:
            self._emit(StreamEventType.ERROR, str(e))
            return False

    async def stop(self):
        """Stop the subprocess."""
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

    async def run_and_stream(self) -> int:
        """Run the command and stream output."""
        if not self._process or not self._process.stdout:
            return -1

        buffer = ""
        while self._running:
            try:
                chunk = await self._process.stdout.read(256)
                if not chunk:
                    break

                text = chunk.decode("utf-8", errors="replace")
                buffer += text

                # Emit line by line for cleaner output
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._emit(StreamEventType.MESSAGE_CHUNK, StreamMessage(text=line + "\n"))

            except Exception as e:
                self._emit(StreamEventType.ERROR, str(e))
                break

        # Emit remaining buffer
        if buffer:
            self._emit(StreamEventType.MESSAGE_CHUNK, StreamMessage(text=buffer))

        # Wait for process to complete
        if self._process:
            await self._process.wait()
            return_code = self._process.returncode or 0
        else:
            return_code = -1

        self._emit(StreamEventType.MESSAGE_CHUNK, StreamMessage(text="", is_complete=True))
        self._emit(StreamEventType.COMPLETE, return_code)

        return return_code


# ============================================================================
# RENDERING HELPERS (SuperQode colorful style)
# ============================================================================


def get_tool_icon(kind: ToolKind) -> str:
    """Get icon for tool kind."""
    icons = {
        ToolKind.READ: "📖",
        ToolKind.EDIT: "✏️",
        ToolKind.DELETE: "🗑️",
        ToolKind.MOVE: "📦",
        ToolKind.SEARCH: "🔍",
        ToolKind.EXECUTE: "⚡",
        ToolKind.THINK: "🧠",
        ToolKind.FETCH: "🌐",
        ToolKind.SWITCH_MODE: "🔄",
        ToolKind.OTHER: "🔧",
    }
    return icons.get(kind, "🔧")


def get_status_icon(status: ToolStatus) -> str:
    """Get icon for tool status."""
    icons = {
        ToolStatus.PENDING: "⏳",
        ToolStatus.IN_PROGRESS: "🔄",
        ToolStatus.COMPLETED: "✅",
        ToolStatus.FAILED: "❌",
    }
    return icons.get(status, "○")


def get_status_color(status: ToolStatus) -> str:
    """Get color for tool status."""
    colors = {
        ToolStatus.PENDING: STREAM_COLORS["pending"],
        ToolStatus.IN_PROGRESS: STREAM_COLORS["progress"],
        ToolStatus.COMPLETED: STREAM_COLORS["success"],
        ToolStatus.FAILED: STREAM_COLORS["error"],
    }
    return colors.get(status, STREAM_COLORS["pending"])


def get_task_icon(status: TaskStatus) -> str:
    """Get icon for task status."""
    icons = {
        TaskStatus.PENDING: "○",
        TaskStatus.IN_PROGRESS: "●",
        TaskStatus.COMPLETED: "✓",
    }
    return icons.get(status, "○")


def get_task_color(status: TaskStatus) -> str:
    """Get color for task status."""
    colors = {
        TaskStatus.PENDING: STREAM_COLORS["pending"],
        TaskStatus.IN_PROGRESS: STREAM_COLORS["progress"],
        TaskStatus.COMPLETED: STREAM_COLORS["success"],
    }
    return colors.get(status, STREAM_COLORS["pending"])


def format_tool_call_title(tool_call: StreamToolCall) -> str:
    """Format tool call title with icon."""
    icon = get_tool_icon(tool_call.kind)
    status_icon = get_status_icon(tool_call.status)
    return f"{status_icon} {icon} {tool_call.title}"


def format_plan_task(task: PlanTask, index: int) -> str:
    """Format a plan task."""
    icon = get_task_icon(task.status)
    return f"  {icon} {index}. {task.content}"
