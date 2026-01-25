#!/usr/bin/env python3
"""
Test app for SuperQode enhanced output display.

Run with: python test_unified_output.py

This demonstrates the enhanced ConversationLog with:
- Consistent thinking display for BYOK/ACP/Local
- Copy to clipboard support (Ctrl+Shift+C)
- Tool call display
- Session stats
"""

import asyncio
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Static, Footer, Button, Header

from superqode.app.widgets import ConversationLog


class TestOutputApp(App):
    """Test app for enhanced ConversationLog."""

    TITLE = "SuperQode - Output Display Test"
    CSS = """
    Screen {
        background: #0a0a0a;
    }

    #main-container {
        height: 100%;
        padding: 1;
    }

    #controls {
        height: 3;
        margin-bottom: 1;
    }

    #controls Button {
        margin-right: 1;
    }

    #log-container {
        height: 1fr;
        border: round #27272a;
    }

    ConversationLog {
        height: 100%;
    }

    #status {
        height: 2;
        margin-top: 1;
        padding: 0 1;
        background: #111111;
    }
    """

    BINDINGS = [
        Binding("1", "test_acp", "Test ACP"),
        Binding("2", "test_byok", "Test BYOK"),
        Binding("3", "test_local", "Test Local"),
        Binding("4", "test_error", "Test Error"),
        Binding("ctrl+shift+c", "copy_response", "Copy Response", show=True),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self._log: ConversationLog | None = None
        self._status: Static | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            with Horizontal(id="controls"):
                yield Button("1. ACP Mode", id="btn-acp", variant="success")
                yield Button("2. BYOK Mode", id="btn-byok", variant="primary")
                yield Button("3. Local Mode", id="btn-local", variant="warning")
                yield Button("4. Error Test", id="btn-error", variant="error")
            with Container(id="log-container"):
                self._log = ConversationLog(id="conversation-log")
                yield self._log
            self._status = Static(
                "Press 1-4 to test different modes | Ctrl+Shift+C to copy response", id="status"
            )
            yield self._status
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-acp":
            self.action_test_acp()
        elif event.button.id == "btn-byok":
            self.action_test_byok()
        elif event.button.id == "btn-local":
            self.action_test_local()
        elif event.button.id == "btn-error":
            self.action_test_error()

    def action_copy_response(self) -> None:
        """Copy last response to clipboard."""
        if self._log:
            success = self._log.copy_to_clipboard()
            if self._status:
                if success:
                    self._status.update("[green]Copied to clipboard![/green]")
                else:
                    self._status.update("[yellow]Nothing to copy or clipboard unavailable[/yellow]")

    def action_test_acp(self) -> None:
        """Test ACP mode output."""
        self.run_worker(self._simulate_acp())

    def action_test_byok(self) -> None:
        """Test BYOK mode output."""
        self.run_worker(self._simulate_byok())

    def action_test_local(self) -> None:
        """Test Local mode output."""
        self.run_worker(self._simulate_local())

    def action_test_error(self) -> None:
        """Test error handling."""
        self.run_worker(self._simulate_error())

    async def _simulate_acp(self) -> None:
        """Simulate ACP mode with thinking and tool calls."""
        if not self._log:
            return

        if self._status:
            self._status.update("Simulating ACP mode...")

        # Start session
        self._log.start_agent_session(
            agent_name="OpenCode",
            model_name="gpt-4o",
            mode="acp",
            approval_mode="ask",
        )

        # Simulate thinking
        thoughts = [
            ("Analyzing your request to understand what needs to be done", "analyzing"),
            ("Searching for relevant files in the codebase", "searching"),
            ("Reading src/main.py to understand the current implementation", "reading"),
            ("Planning the implementation approach", "planning"),
        ]
        for thought, category in thoughts:
            self._log.add_thinking(thought, category)
            await asyncio.sleep(0.5)

        # Simulate tool calls
        self._log.add_tool_call("Read", "running", "src/main.py")
        await asyncio.sleep(0.3)
        self._log.add_tool_call("Read", "success", "src/main.py", output="File read successfully")

        self._log.add_tool_call("Edit", "running", "src/utils.py")
        await asyncio.sleep(0.5)
        self._log.add_tool_call("Edit", "success", "src/utils.py", output="+15 -3 lines")

        self._log.add_tool_call("Bash", "running", command="pytest tests/")
        await asyncio.sleep(0.8)
        self._log.add_tool_call("Bash", "success", command="pytest tests/", output="5 passed")

        # More thinking
        self._log.add_thinking("Verifying the changes work correctly", "verifying")
        await asyncio.sleep(0.3)

        # End session
        self._log.end_agent_session(
            success=True,
            response_text="I've made the requested changes:\n\n1. Added input validation\n2. Updated the error handling\n3. All tests passing",
            prompt_tokens=250,
            completion_tokens=180,
            thinking_tokens=120,
            cost=0.0045,
        )

        # Show final response
        self._log.add_agent(
            "I've made the requested changes:\n\n"
            "1. **Added input validation** to `process_data()`\n"
            "2. **Updated error handling** in `utils.py`\n"
            "3. All tests passing (5/5)\n\n"
            "```python\ndef process_data(data: list) -> dict:\n    if not data:\n        return {}\n    return {item: process(item) for item in data}\n```",
            agent="OpenCode",
        )

        if self._status:
            self._status.update("ACP simulation complete! Press Ctrl+Shift+C to copy response.")

    async def _simulate_byok(self) -> None:
        """Simulate BYOK mode with streaming."""
        if not self._log:
            return

        if self._status:
            self._status.update("Simulating BYOK mode...")

        # Start session
        self._log.start_agent_session(
            agent_name="Claude",
            model_name="claude-sonnet-4-20250514",
            mode="byok",
            approval_mode="auto",
        )

        # Simulate thinking (streaming style)
        thinking_chunks = [
            "Let me analyze this code...",
            "I see the function handles user input...",
            "I'll need to check for edge cases...",
        ]
        for thought in thinking_chunks:
            self._log.add_thinking(thought)
            await asyncio.sleep(0.4)

        # Simulate tool usage
        self._log.add_tool_call("Read", "success", "src/api.py")
        self._log.add_tool_call("Grep", "success", command="grep -r 'TODO'", output="3 matches")

        # End session
        self._log.end_agent_session(
            success=True,
            response_text="Analysis complete",
            prompt_tokens=150,
            completion_tokens=320,
            thinking_tokens=85,
            cost=0.0032,
        )

        # Show response
        self._log.add_agent(
            "## Analysis Complete\n\n"
            "I've analyzed your code and found the following:\n\n"
            "### Key Findings\n"
            "1. Input validation is proper\n"
            "2. Error handling in place\n"
            "3. Performance is O(n)\n\n"
            "The code looks good overall!",
            agent="Claude",
        )

        if self._status:
            self._status.update("BYOK simulation complete! Press Ctrl+Shift+C to copy.")

    async def _simulate_local(self) -> None:
        """Simulate Local mode (Ollama)."""
        if not self._log:
            return

        if self._status:
            self._status.update("Simulating Local mode (Ollama)...")

        # Start session
        self._log.start_agent_session(
            agent_name="Ollama",
            model_name="llama3.2:8b",
            mode="local",
            approval_mode="ask",
        )

        # Simple thinking
        self._log.add_thinking("Processing locally with llama3.2...")
        await asyncio.sleep(0.5)

        # End session
        self._log.end_agent_session(
            success=True,
            response_text="Local processing complete",
            prompt_tokens=50,
            completion_tokens=120,
        )

        # Show response
        self._log.add_agent(
            "Hello! I'm running locally on your machine.\n\n"
            "Local models provide:\n"
            "- **Privacy** - Data stays local\n"
            "- **Speed** - No network latency\n"
            "- **Cost** - No API charges",
            agent="Ollama",
        )

        if self._status:
            self._status.update("Local simulation complete!")

    async def _simulate_error(self) -> None:
        """Simulate an error state."""
        if not self._log:
            return

        if self._status:
            self._status.update("Simulating error state...")

        # Start session
        self._log.start_agent_session(
            agent_name="Claude",
            model_name="claude-opus-4-20250514",
            mode="byok",
            approval_mode="ask",
        )

        # Some thinking before error
        self._log.add_thinking("Connecting to API...")
        await asyncio.sleep(0.5)
        self._log.add_thinking("Sending request...")
        await asyncio.sleep(0.5)

        # End with error
        self._log.end_agent_session(
            success=False,
            response_text="Error: API rate limit exceeded. Please wait and try again.",
        )

        self._log.add_error("API rate limit exceeded (429 Too Many Requests)")

        if self._status:
            self._status.update("Error simulation complete!")


if __name__ == "__main__":
    app = TestOutputApp()
    app.run()
