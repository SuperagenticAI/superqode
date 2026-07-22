"""Interaction mode prompts, badges, and approval mode."""

from __future__ import annotations
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.app.inputs import SelectionAwareInput


class HelperInteractionModeMixin:
    """Interaction mode prompts, badges, and approval mode."""

    def _prompt_interaction_mode(self) -> tuple[str, str]:
        """Return the status mode and matching placeholder."""
        if getattr(self, "_chat_mode", False):
            return "chat", "Chat with the connected model. No repo context or tools."
        if getattr(self, "_plan_mode_enabled", False) or getattr(
            self, "_active_plan_mode_for_current_message", False
        ):
            return "plan", "Plan first. No native tools until you approve execution."
        return "build", SelectionAwareInput.DEFAULT_PLACEHOLDER

    def _refresh_prompt_mode_label(self) -> None:
        """Keep the prompt label in sync with Chat, Build, and Plan modes."""
        status_mode, placeholder = self._prompt_interaction_mode()
        try:
            symbol = self.query_one("#prompt-symbol")
            symbol.update("<>")
        except Exception:  # noqa: BLE001
            pass
        try:
            from superqode.app.widgets import ColorfulStatusBar

            self.query_one("#status-bar", ColorfulStatusBar).interaction_mode = status_mode
        except Exception:  # noqa: BLE001
            pass
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            if input_widget.placeholder not in {
                "Approve tool? y / n / a",
                "Answer the agent question...",
            }:
                input_widget.placeholder = placeholder
        except Exception:  # noqa: BLE001
            pass

    def _set_approval_mode(self, args: str, log: ConversationLog):
        """Set the approval mode for agent actions."""
        mode = args.strip().lower()

        if not mode:
            # Show current mode
            t = Text()
            t.append("\n  🔐 ", style=f"bold {THEME['purple']}")
            t.append("Approval Mode\n\n", style=f"bold {THEME['purple']}")

            t.append("  Controls how SuperQode handles tool calls\n", style=THEME["muted"])
            t.append("  (read, write, edit, bash, search, etc.)\n\n", style=THEME["muted"])

            modes = [
                ("auto", "🟢", THEME["success"], "Allow all tools without prompts"),
                ("ask", "🟡", THEME["warning"], "Prompt for external/outside-project tools"),
                ("deny", "🔴", THEME["error"], "Block ALL tools (read-only)"),
            ]

            for m, icon, color, desc in modes:
                current = " ◀ current" if self.approval_mode == m else ""
                t.append(f"    {icon} ", style=color)
                t.append(f":mode {m:<6}", style=f"bold {color}")
                t.append(f" - {desc}", style=THEME["muted"])
                if current:
                    t.append(current, style=f"bold {color}")
                t.append("\n", style="")

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(
                "ASK mode prompts for external tools & files outside project.\n", style=THEME["dim"]
            )
            t.append("     Tools within project directory are auto-allowed.\n", style=THEME["dim"])
            t.append("     DENY blocks ALL tools. AUTO allows everything.\n", style=THEME["dim"])

            self._show_command_output(log, t)
            return

        if mode in ("auto", "ask", "deny"):
            self.approval_mode = mode
            self._sync_approval_mode()

            icons = {"auto": "🟢", "ask": "🟡", "deny": "🔴"}
            colors = {"auto": THEME["success"], "ask": THEME["warning"], "deny": THEME["error"]}
            descs = {
                "auto": "All tools allowed without prompts",
                "ask": "Prompts for external tools & files outside project",
                "deny": "ALL tool calls will be blocked (read-only)",
            }

            log.add_success(f"{icons[mode]} Approval mode set to {mode.upper()}")
            log.add_system(descs[mode])
        else:
            log.add_error(f"Invalid mode: {mode}")
            log.add_system("Valid modes: auto, ask, deny")

    def _current_interaction_mode_name(self) -> str:
        if getattr(self, "_chat_mode", False):
            return "chat"
        if getattr(self, "_plan_mode_enabled", False):
            return "plan"
        return "build"

    def _apply_interaction_mode(self, mode: str, log: ConversationLog) -> None:
        mode = (mode or "").strip().lower()
        self._awaiting_mode_selection = False
        if mode == "chat":
            self._chat_cmd("on", log)
        elif mode == "build":
            self._build_cmd("", log)
        elif mode == "plan":
            self._chat_mode = False
            self._plan_mode_enabled = True
            self._refresh_plan_status_badge()
            log.add_success("Plan mode ON. New prompts will plan before native tools run.")
            log.add_info(
                "Use :mode build to return to the coding harness, or :plan run to execute."
            )
        else:
            log.add_info("Usage: :mode [chat|build|plan]")
            return

        descriptions = {
            "chat": "Conversation without repository tools",
            "build": "Coding harness and tools enabled",
            "plan": "Planning before native tool execution",
        }
        self._announce_transition(
            title="Mode changed",
            primary=mode.title(),
            detail=descriptions[mode],
            severity="information",
            log=log,
            persist=False,
            dedupe_key=f"interaction-mode:{mode}",
        )
