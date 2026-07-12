"""App exit sequence, cleanup, and workspace reset."""

from __future__ import annotations
import asyncio
import os
import shutil
from rich.text import Text
from superqode.app.constants import (
    GRADIENT,
    THEME,
)
from superqode.app.widgets import (
    ModeBadge,
    ConversationLog,
)
from superqode.app.session_state import get_session, set_mode


class HelperExitLifecycleMixin:
    """App exit sequence, cleanup, and workspace reset."""

    def _clear_for_workspace(self, log: ConversationLog, context: str = ""):
        """Clear screen and show minimal workspace header for focused work.

        Args:
            log: The conversation log widget
            context: Optional context string (e.g., "DEV.FULLSTACK", "OPENCODE")
        """
        log.clear()

        # Show minimal ready message
        t = Text()

        # Ensure focus returns to input after clearing
        self.set_timer(0.1, self._ensure_input_focus)
        t.append("\n")
        if context:
            t.append(f"  ✨ ", style=THEME["purple"])
            t.append(f"Ready as ", style=THEME["muted"])
            t.append(context, style=f"bold {THEME['cyan']}")
            t.append(" - What would you like to build?\n", style=THEME["muted"])
        else:
            t.append("  ✨ Ready - What would you like to build?\n", style=THEME["muted"])
        t.append("\n")
        log.write(t)
    def _cleanup_terminals(self, terminals: dict):
        """Clean up any running terminal processes."""
        for tid, term in terminals.items():
            try:
                if term["process"] and term["process"].poll() is None:
                    term["process"].terminate()
                master_fd = term.pop("master_fd", None)
                if master_fd is not None:
                    os.close(master_fd)
            except Exception:
                pass
        terminals.clear()
    def _go_home(self, log: ConversationLog):
        # First, cancel any running agent process
        if self._agent_process is not None:
            self._cancel_requested = True
            try:
                self._agent_process.terminate()
                log.add_info("🛑 Agent process terminated")
            except Exception:
                pass
            self._agent_process = None

        # Stop ACP client if running
        if self._acp_client is not None:
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.stop())
                else:
                    asyncio.create_task(self._acp_client.stop())
            except Exception:
                pass
            self._acp_client = None
            self._acp_client_key = None

        # Stop any animations
        self._stop_thinking()
        self._stop_stream_animation()
        self.is_busy = False

        # Reset session tracking for conversation continuity
        self._is_first_message = True
        self._opencode_session_id = None
        approved_tools = self._ensure_approved_tools()
        approved_tools.clear()  # Clear approved tools for new session
        self._pending_tool_name = None
        self._pending_tool_input = None
        self._tool_id_map = {}  # Clear tool tracking for new session

        session = get_session()

        if session.is_connected_to_agent():
            session.disconnect_agent()

        self.current_mode = "home"
        self.current_role = ""
        self.current_agent = ""
        self.current_model = ""
        self.current_provider = ""
        set_mode("home")
        session.state = "superqode"
        session.execution_mode = "acp"  # Reset execution mode

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.mode = "home"
        badge.role = ""
        badge.agent = ""
        badge.model = ""
        badge.provider = ""
        badge.execution_mode = ""

        # Clear and show homepage
        self.action_clear_screen()
    def _reset_mode_badge_after_role_run(self):
        """Reset mode badge to HOME after a role run completes."""
        try:
            badge = self.query_one("#mode-badge", ModeBadge)
            badge.mode = "home"
            badge.role = ""
            badge.agent = ""
            badge.model = ""
            badge.provider = ""
            badge.execution_mode = ""
        except Exception:
            pass  # Silently fail if badge not found
    def _do_exit(self, log: ConversationLog):
        """Show a beautiful goodbye screen and exit."""
        self._cleanup_on_exit()
        # Run async cleanup safely - wrap in try/except to prevent event loop errors
        try:
            loop = asyncio.get_running_loop()
            if loop and loop.is_running():
                asyncio.ensure_future(self._exit_sequence_async(log))
            else:
                # If no loop running, just exit directly
                self._show_goodbye_sync(log)
                self.exit()
        except RuntimeError:
            # Event loop is closed or not running - exit directly
            self._show_goodbye_sync(log)
            self.exit()
    async def _exit_sequence_async(self, log: ConversationLog):
        """Await ACP/subprocess cleanup, then show goodbye and exit."""
        pure = getattr(self, "_pure_mode", None)
        if pure is not None:
            try:
                await asyncio.wait_for(pure.aclose(), timeout=2.0)
            except Exception:  # noqa: BLE001 - exit cleanup is best-effort
                pass

        # Stop ACP client
        if self._acp_client is not None:
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.stop())
                else:
                    await asyncio.wait_for(self._acp_client.stop(), timeout=2.0)
            except Exception:
                pass
            self._acp_client = None
            self._acp_client_key = None
        if self._acp_loop_runner is not None:
            try:
                self._acp_loop_runner.close()
            except Exception:
                pass
            self._acp_loop_runner = None

        # Cancel all pending workers (this app's own background tasks).
        # NOTE: do NOT cancel asyncio.all_tasks() here — that includes
        # Textual's own message-pump task. Killing it freezes the app so the
        # goodbye timer below never fires and exit() never runs, forcing the
        # user to kill the process. Let self.exit() tear down Textual cleanly.
        try:
            self.workers.cancel_all()
        except Exception:
            pass

        # Show goodbye screen
        log.clear()
        term_width = shutil.get_terminal_size().columns
        t = Text()
        t.append("\n\n\n")
        goodbye_art = """
   ______                ____               __
  / ____/___  ____  ____/ / /_  __  _____  / /
 / / __/ __ \\/ __ \\/ __  / __ \\/ / / / _ \\/ /
/ /_/ / /_/ / /_/ / /_/ / /_/ / /_/ /  __/_/
\\____/\\____/\\____/\\__,_/_.___/\\__, /\\___(_)
                             /____/
"""
        for i, line in enumerate(goodbye_art.strip().split("\n")):
            color = GRADIENT[i % len(GRADIENT)]
            padding = max(0, (term_width - len(line)) // 2)
            t.append(" " * padding)
            t.append(line, style=f"bold {color}")
            t.append("\n")
        t.append("\n\n")
        thanks_text = "Thanks for using SuperQode!"
        padding = max(0, (term_width - len(thanks_text) - 4) // 2)
        t.append(" " * padding)
        t.append("👋 ", style="")
        t.append("Thanks for using ", style="#e4e4e7")
        t.append("Super", style="bold #a855f7")
        t.append("Qode", style="bold #ec4899")
        t.append("! 👋\n\n", style="#e4e4e7")
        fun_text = "Keep building amazing things!"
        padding = max(0, (term_width - len(fun_text) - 4) // 2)
        t.append(" " * padding)
        t.append("🚀 ", style="")
        t.append("Keep building amazing things!", style="italic #71717a")
        t.append(" 🚀\n\n\n", style="")
        log.write(t)

        # Exit after a short delay to show the goodbye screen
        self.set_timer(0.5, lambda: self.exit())
    def _cleanup_on_exit(self):
        """Clean up all running processes and timers before exit."""
        # Cancel any pending operations
        self._cancel_requested = True

        provider, model = self._active_local_provider_model()

        # Cancel BYOK/local agent loop and unload/stop local generation resources.
        try:
            pure = getattr(self, "_pure_mode", None)
            if pure is not None:
                pure.cancel()
                pure.disconnect()
        except Exception:
            pass
        if provider:
            self._teardown_local_model_runtime(provider, model)

        # Stop any running agent process
        if self._agent_process is not None:
            try:
                self._agent_process.terminate()
                self._agent_process.wait(timeout=1)
            except Exception:
                try:
                    self._agent_process.kill()
                except Exception:
                    pass
            self._agent_process = None

        # Force kill ACP client process if it exists (sync cleanup)
        if self._acp_client is not None:
            try:
                if hasattr(self._acp_client, "_process") and self._acp_client._process:
                    self._acp_client._process.terminate()
            except Exception:
                pass
            self._acp_client = None
            self._acp_client_key = None
        if self._acp_loop_runner is not None:
            try:
                self._acp_loop_runner.close()
            except Exception:
                pass
            self._acp_loop_runner = None

        # Stop all timers
        if self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None

        if self._stream_animation_timer:
            self._stream_animation_timer.stop()
            self._stream_animation_timer = None

        if self._permission_pulse_timer:
            self._permission_pulse_timer.stop()
            self._permission_pulse_timer = None

        # Clear busy state
        self.is_busy = False
        self._permission_pending = False

        # Stop any pending workers
        try:
            self.workers.cancel_all()
        except Exception:
            pass
