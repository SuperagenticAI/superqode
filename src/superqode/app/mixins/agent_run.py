"""Agent execution, streaming, and thinking animation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import os
import re
import subprocess
import shutil
import shlex
import time
from pathlib import Path
from textual import work
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    TopScanningLine,
    BottomScanningLine,
    StreamingThinkingIndicator,
    ConversationLog,
)
from superqode.danger import (
    analyze_command,
    DangerLevel,
    DANGER_STYLES,
)
from superqode.sidebar import (
    get_git_changes,
)
from superqode.design_system import (
    COLORS as SQ_COLORS,
    GRADIENT_PURPLE,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput
from superqode.app.welcome import _harness_display_name
from superqode.app.recipes import LocalRecipe
from superqode.app.async_utils import _AsyncLoopThread
from superqode.app.session_state import get_session


class AgentRunMixin:
    """_run_/_send_/_stream_ agent execution and thinking/throbber animation."""

    def _current_thinking_state(self) -> str:
        if not self.show_thinking_logs:
            return "off"
        return "verbose" if self.thinking_verbosity == "verbose" else "normal"

    def _apply_thinking_state(self, state: str) -> None:
        """Set the reactive flags for a thinking state ('normal'|'verbose'|'off')."""
        if state == "off":
            self.show_thinking_logs = False
        else:
            self.show_thinking_logs = True
            self.thinking_verbosity = "verbose" if state == "verbose" else "normal"
        # Mirror onto the current TUI logger if one exists.
        if getattr(self, "_current_tui_logger", None):
            self._current_tui_logger.logger.config.show_thinking = self.show_thinking_logs

    def action_toggle_thinking(self):
        """Cycle thinking-log detail: Normal → Verbose → Off."""
        current = self._current_thinking_state()
        nxt = self._THINKING_CYCLE[
            (self._THINKING_CYCLE.index(current) + 1) % len(self._THINKING_CYCLE)
        ]
        self._apply_thinking_state(nxt)
        log = self.query_one("#log", ConversationLog)
        blurbs = {
            "normal": "Thinking: NORMAL — iterations fold into a live status, reasoning is trimmed",
            "verbose": "Thinking: VERBOSE — full per-iteration reasoning and loop logs",
            "off": "Thinking: OFF — compact stream view, only tool calls and the answer",
        }
        log.add_info(blurbs[nxt])

    def _start_stream_animation(self, log: ConversationLog):
        """Start animation during agent streaming."""
        self._stream_animation_frame = 0
        self._stream_log = log
        self.is_busy = True

        # IMPORTANT: Enable auto-scroll so user sees agent's work in real-time
        log.auto_scroll = True

        # Hide prompt area when agent is thinking
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.add_class("hidden")
        except Exception:
            pass

        # Show streaming thinking indicator with changing text
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = True
            thinking_indicator.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = True
            thinking_wave.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = True
            thinking_wave_bottom.add_class("visible")
        except Exception:
            pass

    def _stop_stream_animation(self):
        """Stop the streaming animation."""
        self.is_busy = False

        # Show prompt area again
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.remove_class("hidden")
            # Re-focus the input
            self.query_one("#prompt-input", SelectionAwareInput).focus()
        except Exception:
            pass

        # Hide streaming thinking indicator
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = False
            thinking_indicator.status = ""
            thinking_indicator.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = False
            thinking_wave.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = False
            thinking_wave_bottom.remove_class("visible")
        except Exception:
            pass

    def _start_thinking(self, msg: str = "🧠 Thinking..."):
        self.is_busy = True
        self._thinking_start = time.time()
        self._thinking_idx = 0
        # Reset per-turn thinking state (live status step + reasoning rate limiter).
        self._thinking_step = 0
        self._last_thinking_flush = 0.0
        self._calm_actions = 0

        # Show streaming thinking indicator with changing text
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = True
            # Start each turn with the whimsical phrases; loop bookkeeping in
            # normal mode will swap in a steady "Working… (step N)" status.
            thinking_indicator.status = ""
            thinking_indicator.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = True
            thinking_wave.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = True
            thinking_wave_bottom.add_class("visible")
        except Exception:
            pass

        # Hide prompt area
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.add_class("hidden")
        except Exception:
            pass

    def _stop_thinking(self, show_done: bool = False):
        """Stop the thinking animation.

        Args:
            show_done: If True, show "Done in X.Xs" message. Default False for streaming.
        """
        self.is_busy = False

        # Calm mode: commit the end-of-turn action roll-up before tearing down.
        if self._is_calm_output() and getattr(self, "_calm_actions", 0) > 0:
            try:
                self._show_calm_summary(self.query_one("#log", ConversationLog))
            except Exception:
                pass

        # Hide streaming thinking indicator
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = False
            thinking_indicator.status = ""
            thinking_indicator.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = False
            thinking_wave.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = False
            thinking_wave_bottom.remove_class("visible")
        except Exception:
            pass

        # Show prompt area again
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.remove_class("hidden")
            self.query_one("#prompt-input", SelectionAwareInput).focus()
        except Exception:
            pass

        # Only show done message if requested (not during streaming)
        if show_done:
            elapsed = time.time() - self._thinking_start
            self.query_one("#log", ConversationLog).add_success(f"Done in {elapsed:.1f}s ✨")

    @work(exclusive=True, thread=True)
    def _run_shell(self, cmd: str, log: ConversationLog):
        import os

        # Analyze command for danger
        project_dir = str(Path.cwd())
        level, reason, target = analyze_command(project_dir, project_dir, cmd)

        # Show warning for dangerous commands
        if level >= DangerLevel.DANGEROUS:
            style = DANGER_STYLES[level]

            def show_warning():
                t = Text()
                t.append(f"\n  {style['icon']} ", style=f"bold {style['color']}")
                t.append(f"{style['label']}: ", style=f"bold {style['color']}")
                t.append(f"{reason}\n", style=style["color"])
                if target:
                    t.append(f"  📁 Target: {target}\n", style=THEME["muted"])
                if level == DangerLevel.DESTRUCTIVE:
                    t.append(
                        f"  ⚠️  This may affect files outside the project!\n", style=THEME["error"]
                    )
                log.write(t)

            self._call_ui(show_warning)

        self._call_ui(lambda: setattr(self, "is_busy", True))

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd(), timeout=60
            )
            output = (result.stdout + result.stderr).strip()
            ok = result.returncode == 0
            self._call_ui(log.add_shell, cmd, output, ok)

            # Record in history
            self._history_manager.append_sync(f">{cmd}", success=ok)

        except subprocess.TimeoutExpired:
            self._call_ui(log.add_shell, cmd, "⏰ Timed out", False)
        except Exception as e:
            self._call_ui(log.add_error, str(e))
        finally:
            self._call_ui(lambda: setattr(self, "is_busy", False))

    def _run_cli_passthrough(
        self,
        command_parts: list[str],
        log: ConversationLog,
        label: str,
    ) -> None:
        """Run a CLI-backed command from the TUI."""
        self.run_worker(self._superqode_cli_cmd(command_parts, log, label))

    def _run_cli_group(self, group: str, args: str, log: ConversationLog, label: str) -> None:
        """Run `superqode <group> ...` from a TUI command handler."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :{group} arguments: {exc}")
            return
        self._run_cli_passthrough([group, *tokens], log, label)

    async def _run_recipe(self, recipe: LocalRecipe, extra: str, log: ConversationLog) -> None:
        issues = self._recipe_issues(recipe)
        if issues:
            log.add_error(
                f"Recipe {recipe.name} has {len(issues)} issue(s). Run :recipe doctor {recipe.name}."
            )
            return
        prompt = self._recipe_prompt_text(recipe, extra)
        refs = list(getattr(self, "_attached_refs", []))
        base = recipe.path.parent if recipe.path else Path.cwd()
        for ref in recipe.attachments:
            if ref.startswith(("http://", "https://", "@", "mcp://")):
                normalized = ref
            else:
                path = Path(ref).expanduser()
                if not path.is_absolute():
                    path = base / path
                path = path.resolve()
                try:
                    normalized = "@" + str(path.relative_to(Path.cwd()))
                except ValueError:
                    normalized = "@" + str(path)
            if normalized not in refs:
                refs.append(normalized)
        for ref in recipe.mcp_resources:
            normalized = ref if ref.startswith("mcp://") else f"mcp://{ref}"
            if normalized not in refs:
                refs.append(normalized)
        self._attached_refs = refs
        self._sync_attachment_prefill()

        if recipe.harness and recipe.path:
            harness_path = Path(recipe.harness).expanduser()
            if not harness_path.is_absolute():
                harness_path = recipe.path.parent / harness_path
            try:
                from superqode.harness import load_harness_spec

                spec = load_harness_spec(harness_path)
                self.active_harness_path = harness_path
                self.active_harness_name = spec.name
                os.environ["SUPERQODE_HARNESS"] = str(harness_path)
                pure = self._ensure_pure_mode()
                pure.set_harness(spec, path=harness_path)
                self._refresh_harness_panel()
                log.add_info(f"Loaded harness for recipe: {spec.name}")
            except Exception as exc:
                log.add_error(f"Could not load recipe harness: {exc}")
                return

        if (
            recipe.provider
            and recipe.model
            and (self.current_provider != recipe.provider or self.current_model != recipe.model)
        ):
            try:
                from superqode.providers.registry import PROVIDERS, ProviderCategory

                provider_def = PROVIDERS.get(recipe.provider)
                if provider_def and provider_def.category == ProviderCategory.LOCAL:
                    self._connect_local_mode(recipe.provider, recipe.model, log)
                else:
                    self._connect_byok_mode(recipe.provider, recipe.model, log)
            except Exception as exc:
                log.add_error(f"Could not connect recipe model: {exc}")

        if not prompt:
            log.add_error(f"Recipe {recipe.name} produced an empty prompt.")
            return
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            log.add_info(f"Running recipe: {recipe.name}")
            self._handle_message(prompt, log)
        else:
            self._set_prompt_prefill(prompt)
            log.add_info(f"Loaded recipe prompt: {recipe.name}")
            log.add_info("Connect a model, then press Enter to run it.")

    async def _send_chat_message(self, text: str, log: ConversationLog):
        """Stream a raw model reply and report speed (TTFT + decode tok/s)."""
        from time import monotonic
        from superqode.providers.gateway.base import Message
        from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

        try:
            provider = self._pure_mode.session.provider
            model = self._pure_mode.session.model
            if not provider or not model:
                self._call_ui(
                    log.add_error,
                    "No model is selected. Reconnect with :connect local before chatting.",
                )
                return
            history = self._chat_history
            if not isinstance(history, list):
                history = self._chat_history = []
            history.append(Message(role="user", content=text))
            who = f"{provider}/{model}"
            self._call_ui(lambda: log.reset_response_stream(who))

            # Use the same animated thinking indicator + scanning waves as the
            # agent path so chat mode looks alive during a slow first token
            # (a 30B local model can take many seconds to prefill).
            self._call_ui(self._start_thinking, f"💬 {provider}/{model}")

            gateway = LiteLLMGateway()
            t0 = monotonic()
            first_token_t = None
            pieces: list[str] = []
            thinking_chars = 0
            usage_completion = None

            async for chunk in gateway.stream_completion(
                messages=list(history),
                model=model,
                provider=provider,
                tools=None,
                temperature=0.7,
                max_tokens=2048,
            ):
                if getattr(self, "_cancel_requested", False):
                    break
                if chunk.thinking_content:
                    if first_token_t is None:
                        first_token_t = monotonic()
                    thinking_chars += len(chunk.thinking_content)
                if chunk.content:
                    if first_token_t is None:
                        first_token_t = monotonic()
                    pieces.append(chunk.content)
                    self._call_ui(log.add_response_chunk, chunk.content)
                if chunk.usage and chunk.usage.completion_tokens:
                    usage_completion = chunk.usage.completion_tokens

            end_t = monotonic()
            full = "".join(pieces)
            history.append(Message(role="assistant", content=full))

            if not full.strip():
                if thinking_chars > 0:
                    note = (
                        f"Model produced {thinking_chars} chars of hidden reasoning but no "
                        "final answer (it likely ran out of the 2048-token budget). "
                        "Try a shorter prompt or a non-reasoning model."
                    )
                else:
                    note = (
                        "Model returned no text. Check the model is loaded in the server "
                        "and not an embedding-only model."
                    )
                self._call_ui(log.add_info, note)
                return
            self._call_ui(lambda: log.write_final_response(full, agent=who))

            ttft = (first_token_t - t0) if first_token_t is not None else None
            decode_dur = (end_t - first_token_t) if first_token_t is not None else None
            tokens = usage_completion or max(1, len(full) // 4)
            tps = (tokens / decode_dur) if decode_dur and decode_dur > 0 else None
            self._call_ui(self._write_chat_stats, log, ttft, tps, tokens, end_t - t0)
        except Exception as exc:  # noqa: BLE001 - surface any model/transport error
            self._call_ui(log.add_error, f"Chat error: {exc}")
        finally:
            # Stops the indicator + scanning waves and restores the prompt.
            self._call_ui(self._stop_thinking)

    @work(exclusive=True)
    async def _send_to_pure_mode(self, text: str, log: ConversationLog):
        """Send message to provider session with streaming output."""
        from time import monotonic
        import traceback

        # Handle session commands
        if text.strip().startswith("/sessions"):
            parts = text.strip().split(maxsplit=2)
            if len(parts) >= 2 and parts[1].lower() in {"resume", "switch", "select"}:
                session_id = parts[2] if len(parts) >= 3 else ""
                self._call_ui(self._handle_resume_session, session_id, log)
                return
            sessions = self._pure_mode.list_sessions() if hasattr(self, "_pure_mode") else []
            if not sessions:
                log.add_info("No sessions found.")
            else:
                for s in sessions:
                    log.add_info(
                        f"  {s['session_id']} | {s['model'] or 'N/A'} | {s['message_count']} msgs"
                    )
            return
        elif text.strip().startswith("/resume"):
            parts = text.strip().split()
            if len(parts) < 2:
                log.add_info("Usage: /resume <session_id>")
                return
            session_id = parts[1]
            if hasattr(self, "_pure_mode"):
                messages = self._pure_mode.resume_session(session_id)
                if messages:
                    log.add_info(f"Resumed session {session_id[:8]}")
                    for m in messages:
                        role = m.get("role", "?").upper()
                        content = m.get("content", "")[:100]
                        log.add_info(f"[{role}] {content}...")
                else:
                    log.add_info(f"Session {session_id} not found.")
            return
        elif text.strip().startswith("/compact"):
            if hasattr(self, "_pure_mode") and hasattr(self._pure_mode, "compact"):
                self._pure_mode.compact()
                log.add_info("Context compacted.")
            return

        mcp_context = await self._resolve_mcp_attachment_context(log)
        if mcp_context:
            text = f"{mcp_context}\n\n{text}"

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            text = f"{file_context}\n\n{text}"
            self._current_file_context = ""  # Clear after use

        # Check if connected
        if not hasattr(self, "_pure_mode"):
            log.add_error("Not connected to a model. Use :connect byok to select a provider/model.")
            log.add_system("Example: :connect local ollama/qwen3.6:35b-a3b")
            self.is_busy = False
            return

        if not self._pure_mode.session.connected:
            log.add_error("Connection not established. Please reconnect using :connect byok")
            log.add_system("Example: :connect local ollama/qwen3.6:35b-a3b")
            self.is_busy = False
            return

        # A builtin AgentLoop (._agent), a harness, OR a self-contained runtime
        # (e.g. codex-sdk, which has no ._agent) all count as initialized.
        if (
            not self._pure_mode._agent
            and not getattr(self._pure_mode, "harness_enabled", False)
            and getattr(self._pure_mode, "_runtime", None) is None
        ):
            log.add_error("Agent not initialized. Please reconnect using :connect byok")
            log.add_system("Example: :connect local ollama/qwen3.6:35b-a3b")
            self.is_busy = False
            return

        provider = self._pure_mode.session.provider
        model = self._pure_mode.session.model
        if getattr(self._pure_mode, "harness_enabled", False) and hasattr(
            self._pure_mode, "_resolve_harness_route"
        ):
            try:
                provider, model = self._pure_mode._resolve_harness_route()
            except Exception:
                # Let the run path raise the user-facing error with full context.
                provider = self._pure_mode.session.provider
                model = self._pure_mode.session.model
        plan_mode_for_run = bool(getattr(self, "_active_plan_mode_for_current_message", False))
        if plan_mode_for_run:
            text = (
                "PLAN MODE: Analyze the request and produce a concrete implementation plan. "
                "Do not call tools, edit files, run commands, or make changes. "
                "Include goal, steps, files likely involved, risks, and verification.\n\n"
                f"{text}"
            )

        # Set up callbacks for BYOK/Local modes
        # Tool calls are ALWAYS visible (the agent's actual work)
        # Thinking logs are toggleable with Ctrl+T
        from superqode.providers.registry import PROVIDERS, ProviderCategory

        provider_def = PROVIDERS.get(provider)
        is_local = provider_def and provider_def.category == ProviderCategory.LOCAL
        tool_actions: list[dict] = []
        files_read: list[str] = []
        files_modified: list[str] = []
        commands_run: list[str] = []
        pre_existing_modified: set[str] = set()
        try:
            root_path = Path(os.getcwd())
            pre_existing_modified = {
                change.path for change in get_git_changes(root_path) if change.status in ("M", "A")
            }
        except Exception:
            pre_existing_modified = set()

        def _append_unique(items: list[str], value: str):
            if value and value not in items:
                items.append(value)

        def _record_tool_activity(name: str, args: dict):
            tool_lower = name.lower()
            file_path = args.get("path") or args.get("file_path") or args.get("filePath") or ""
            command = args.get("command", "")
            query = args.get("query") or args.get("pattern") or args.get("include") or ""
            started_at = monotonic()
            kind = "tool"
            if command:
                kind = "command"
            elif file_path and any(
                marker in tool_lower
                for marker in ("write", "edit", "insert", "patch", "multi_edit", "delete")
            ):
                kind = "write"
            elif file_path or tool_lower in (
                "grep",
                "glob",
                "repo_search",
                "code_search",
                "list_directory",
            ):
                kind = "read"

            tool_actions.append(
                {
                    "name": name,
                    "kind": kind,
                    "path": file_path,
                    "command": command,
                    "query": query,
                    "status": "running",
                    "started_at": started_at,
                    "duration": 0.0,
                }
            )

            if command:
                _append_unique(commands_run, command)

            if file_path:
                if any(
                    marker in tool_lower
                    for marker in ("write", "edit", "insert", "patch", "multi_edit", "delete")
                ):
                    _append_unique(files_modified, file_path)
                elif any(
                    marker in tool_lower for marker in ("read", "list", "grep", "glob", "search")
                ):
                    _append_unique(files_read, file_path)
            elif tool_lower in ("grep", "glob", "repo_search", "code_search", "list_directory"):
                search_root = args.get("path") or args.get("directory") or "."
                _append_unique(files_read, str(search_root))

        def _complete_tool_activity(name: str, status: str):
            completed_at = monotonic()
            for action in reversed(tool_actions):
                if action.get("name") == name and action.get("status") == "running":
                    action["status"] = status
                    action["duration"] = max(
                        0.0, completed_at - action.get("started_at", completed_at)
                    )
                    return
            tool_actions.append(
                {
                    "name": name,
                    "kind": "tool",
                    "path": "",
                    "command": "",
                    "query": "",
                    "status": status,
                    "started_at": completed_at,
                    "duration": 0.0,
                }
            )

        def _safe_call(func, *args):
            """Call function safely - handles threading correctly."""
            try:
                self._call_ui(func, *args)
            except RuntimeError as e:
                message = str(e).lower()
                if "different thread" in message or "app thread" in message:
                    func(*args)
                else:
                    raise

        def on_tool_call(name: str, args: dict):
            """Handle tool call - calm mode folds it into the live throbber."""
            _record_tool_activity(name, args)
            if self._is_calm_output():
                _safe_call(self._calm_tool_running, name, args, log)
                return
            file_path = args.get("path", args.get("file_path", args.get("filePath", "")))
            command = args.get("command", "")
            if not file_path and not command:
                command = (
                    args.get("query")
                    or args.get("pattern")
                    or args.get("old_text")
                    or args.get("task")
                    or ""
                )
            _safe_call(log.add_tool_call, name, "running", file_path, command, "", args)

        def on_tool_result(name: str, result):
            """Handle tool result - calm mode shows one tidy line; verbose full."""
            from superqode.tools.base import ToolResult

            if isinstance(result, ToolResult):
                status = "success" if result.success else "error"
                _complete_tool_activity(name, status)
                if self._is_calm_output():
                    meta = result.metadata or {}
                    done_args = {"path": meta.get("path")} if meta.get("path") else {}
                    _safe_call(self._calm_tool_done, name, done_args, log, result.success)
                    return
                output = result.output if result.output else result.error
                output_str = str(output) if output else ""
                metadata = result.metadata or {}
                result_path = str(metadata.get("path") or "")
                if result_path:
                    try:
                        path_obj = Path(result_path)
                        if path_obj.is_absolute():
                            result_path = os.path.relpath(path_obj, os.getcwd())
                    except Exception:
                        pass
                diff_text = str(metadata.get("diff_text") or "")
                additions = metadata.get("additions")
                deletions = metadata.get("deletions")
                if not diff_text and output_str and self._looks_like_diff(output_str):
                    diff_text = output_str
                    output_str = "updated"

                # Try to parse and display JSON nicely
                if status == "success" and output_str and not diff_text:
                    formatted = self._format_tool_output(name, output_str, log)
                    if formatted:
                        return

                # Fallback - show full output, no truncation
                _safe_call(
                    log.add_tool_call,
                    name,
                    status,
                    result_path,
                    "",
                    output_str,
                    None,
                    diff_text,
                    None,
                    additions if isinstance(additions, int) else None,
                    deletions if isinstance(deletions, int) else None,
                    metadata,
                )
            else:
                _complete_tool_activity(name, "success")
                if self._is_calm_output():
                    _safe_call(self._calm_tool_done, name, {}, log, True)
                    return
                output_str = str(result) if result else ""

                # Try JSON parsing first
                if output_str:
                    formatted = self._format_tool_output(name, output_str, log)
                    if formatted:
                        return

                # Show full output, no truncation
                _safe_call(log.add_tool_call, name, "success", "", "", output_str)

        async def on_thinking_async(text: str):
            """Handle thinking - toggleable with Ctrl+T."""
            if not (text and text.strip()):
                return
            # Normal mode: fold the agent loop's per-iteration bookkeeping into
            # the live throbber instead of writing each line to the scrollback.
            loop_status = self._thinking_loop_status(text)
            if loop_status is not None and self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, loop_status)
                return
            # Calm mode: keep raw reasoning quiet; just pulse the throbber.
            if self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, "💭 Thinking…")
                self._call_ui(self._maybe_show_thinking_hint, log)
                return
            # Verbose: cleaner, categorized output with varied emojis (ACP style).
            _safe_call(log.add_thinking, text, "general")

        # Set callbacks on pure_mode (for both local and cloud providers)
        self._pure_mode.on_tool_call = on_tool_call
        self._pure_mode.on_tool_result = on_tool_result
        self._pure_mode.on_thinking = on_thinking_async

        # Ensure callbacks are set on the agent
        if self._pure_mode._agent:
            self._pure_mode._agent.on_tool_call = on_tool_call
            self._pure_mode._agent.on_tool_result = on_tool_result
            self._pure_mode._agent.on_thinking = on_thinking_async

        # Start thinking animation - shows animated bar and thinking indicator
        self._start_thinking(f"🤖 Processing with {provider}/{model}...")

        try:
            start_time = monotonic()
            full_response = ""
            chunk_count = 0
            response_started = False

            # Stop thinking animation (spinning bar), start streaming animation (flowing line)
            self._stop_thinking()
            self._start_stream_animation(log)

            # Use enhanced agent session header (always visible)
            _safe_call(
                log.start_agent_session,
                self._agent_session_label(provider),
                model,
                "byok" if not is_local else "local",
                self.approval_mode,
            )

            # Stream the response
            # CRITICAL: Accumulate ALL chunks including final response after tool calls
            try:
                from superqode.tools.question_tool import (
                    get_question_handler,
                    set_question_handler,
                )

                previous_question_handler = get_question_handler()

                async def tui_question_handler(question):
                    return await self._ask_agent_question(question, log)

                set_question_handler(tui_question_handler)

                # Accumulate chunks to avoid showing each tiny piece as separate thinking line
                accumulated_chunk = ""
                last_display_time = time.time()

                try:
                    async for chunk in self._pure_mode.run_streaming(
                        text, plan_mode=plan_mode_for_run
                    ):
                        chunk_count += 1

                        # Process chunk
                        if chunk is not None:
                            chunk_str = str(chunk) if not isinstance(chunk, str) else chunk

                            # Always accumulate for final display
                            full_response += chunk_str

                            # Accumulate chunks and display in batches to avoid weird chunking
                            if chunk_str.strip():
                                accumulated_chunk += chunk_str
                                response_started = True

                                # Display accumulated chunk every 100ms or when we hit a newline
                                # Response chunks go to log.add_response_chunk (not add_assistant)
                                current_time = time.time()
                                if (
                                    "\n" in chunk_str
                                    or current_time - last_display_time > 0.1
                                    or len(accumulated_chunk) > 100
                                ):
                                    _safe_call(log.add_response_chunk, accumulated_chunk)
                                    accumulated_chunk = ""
                                    last_display_time = current_time

                    if accumulated_chunk:
                        _safe_call(log.add_response_chunk, accumulated_chunk)
                finally:
                    if get_question_handler() is tui_question_handler:
                        set_question_handler(previous_question_handler)

            except StopAsyncIteration:
                # Normal end of stream - display any remaining accumulated chunks
                if accumulated_chunk:
                    _safe_call(log.add_response_chunk, accumulated_chunk)

                # Stop streaming animation
                self._stop_stream_animation()

                # End agent session with summary
                # Extract stats if available from pure_mode
                stats = getattr(self._pure_mode, "_last_stats", {})
                _safe_call(
                    log.end_agent_session,
                    True,
                    full_response,
                    stats.get("prompt_tokens", 0),
                    stats.get("completion_tokens", 0),
                    stats.get("thinking_tokens", 0),
                    stats.get("total_cost", 0.0),
                )
                if hasattr(self._pure_mode, "get_pending_approvals"):
                    self._announce_pending_approvals(self._pure_mode, log)
                pass
            except Exception as stream_error:
                # Error during streaming
                error_msg = str(stream_error)
                error_type = type(stream_error).__name__

                # Stop animation and show error
                if is_local:
                    self._stop_thinking()
                self._stop_stream_animation()
                self._show_error_card(
                    log,
                    f"{error_type} while running agent",
                    error_msg,
                    provider=provider,
                    model=model,
                    hint=(
                        self._codex_error_hint(error_msg)
                        if getattr(self._pure_mode, "runtime_name", "") == "codex-sdk"
                        else "Use :retry after fixing the provider or model issue."
                    ),
                )

                # Show detailed error info
                import traceback

                full_traceback = traceback.format_exc()
                log.add_info(f"Full error:\n{full_traceback}")

                # Provider-specific troubleshooting
                if "ollama" in provider.lower():
                    log.add_info("💡 Ollama Troubleshooting:")
                    log.add_info("   1. Check Ollama is running: ollama serve")
                    log.add_info(f"   2. Verify model exists: ollama list | grep {model}")
                    log.add_info(f"   3. Pull model if missing: ollama pull {model}")
                    import os

                    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                    log.add_info(f"   4. Current OLLAMA_HOST: {ollama_host}")
                elif "mlx" in provider.lower():
                    # Check for specific MLX error types
                    if (
                        "broadcast_shapes" in error_msg.lower()
                        or "cannot be broadcast" in error_msg.lower()
                    ):
                        log.add_error("🚨 MLX KV Cache Conflict Detected!")
                        log.add_info("   MLX servers can only handle ONE request at a time.")
                        log.add_info("   Multiple concurrent requests cause memory conflicts.")
                        log.add_info("")
                        log.add_info("   To fix:")
                        log.add_info("   1. Wait for any running requests to complete")
                        log.add_info("   2. Check server status: superqode providers mlx list")
                        log.add_info(
                            f"   3. Restart server: superqode providers mlx server --model {model}"
                        )
                        log.add_info("   4. Try again with only one active session")
                        log.add_info("")
                        log.add_info(
                            "   💡 Tip: Run separate servers on different ports for concurrent use"
                        )
                    else:
                        log.add_info("💡 MLX Troubleshooting:")
                        log.add_info("   1. Check if server crashed: superqode providers mlx list")
                        log.add_info(
                            f"   2. Restart server: superqode providers mlx server --model {model}"
                        )
                        log.add_info(
                            "   3. Verify connection: curl http://localhost:8080/v1/models"
                        )
                        log.add_info("")
                        log.add_info("   ⚠️  MLX servers handle only ONE request at a time")
                        log.add_info("   • Keep server terminal open while using")
                        log.add_info("   • Start separate servers for concurrent model use")

                if not full_response:
                    full_response = f"[Error: {error_type}] {error_msg}"

            # Stop animation
            self._stop_stream_animation()

            elapsed = monotonic() - start_time

            # Clean up the response - remove any error markers that might have been added
            cleaned_response = full_response.strip()

            if cleaned_response:
                # Check if response contains an error message
                if "[Error:" in cleaned_response or cleaned_response.startswith("Error:"):
                    log.add_error(cleaned_response)
                else:
                    # Display the response using ACP-style formatting for consistency
                    response_text = cleaned_response

                    # Get stats for display
                    stats = self._pure_mode.get_status()["stats"]
                    tool_count = max(stats.get("total_tool_calls", 0), len(tool_actions))

                    # Merge tool-tracked writes with git changes detected after the run.
                    try:
                        root_path = Path(os.getcwd())
                        git_changes = get_git_changes(root_path)
                        git_files_modified = [
                            change.path
                            for change in git_changes
                            if change.status in ("M", "A")
                            and change.path not in pre_existing_modified
                        ]
                        for changed_path in git_files_modified:
                            _append_unique(files_modified, changed_path)
                    except Exception:
                        pass

                    # Compute file diffs for detected files
                    file_diffs = self._compute_file_diffs(files_modified) if files_modified else {}

                    # Use ACP-style outcome display for both ACP and BYOK
                    self._show_final_outcome(
                        response_text,
                        f"BYOK {provider}/{model}",
                        {
                            "tool_count": tool_count,
                            "duration": elapsed,
                            "files_modified": files_modified,
                            "files_read": files_read,
                            "file_diffs": file_diffs,  # NEW: Store diff data
                            "tools": tool_actions,
                            "commands_run": commands_run,
                            "provider": provider,
                            "model": model,
                            "prompt": text,
                            "skip_git_fallback": True,
                        },
                        log,
                    )
                    self._last_run_summary = {
                        "tool_count": tool_count,
                        "duration": elapsed,
                        "files_modified": files_modified,
                        "files_read": files_read,
                        "file_diffs": file_diffs,
                        "tools": tool_actions,
                        "commands_run": commands_run,
                        "provider": provider,
                        "model": model,
                        "prompt": text,
                        "response": response_text,
                        "skip_git_fallback": True,
                    }

                    # Track usage
                    self._track_byok_usage(text, response_text, tool_count)
            elif chunk_count > 0:
                # Got chunks but no content - might be tool calls only
                log.add_warning(
                    f"⚠️ Received {chunk_count} chunks but no text content after stripping."
                )
                log.add_info(f"🔍 Debug: Raw response (before strip): {repr(full_response[:500])}")
                log.add_info("Model may have returned tool calls only or whitespace-only response.")
                # Check if there were tool calls
                stats = self._pure_mode.get_status()["stats"]
                tool_count = max(stats.get("total_tool_calls", 0), len(tool_actions))
                if tool_count > 0:
                    log.add_info(f"Note: {tool_count} tool calls were executed.")

                    # Compute file diffs even when no text response.
                    try:
                        root_path = Path(os.getcwd())
                        git_changes = get_git_changes(root_path)
                        git_files_modified = [
                            change.path
                            for change in git_changes
                            if change.status in ("M", "A")
                            and change.path not in pre_existing_modified
                        ]
                        for changed_path in git_files_modified:
                            _append_unique(files_modified, changed_path)
                    except Exception:
                        pass

                    file_diffs = self._compute_file_diffs(files_modified) if files_modified else {}

                    # Show completion summary with file changes
                    self._show_completion_summary(
                        f"BYOK {provider}/{model}",
                        {
                            "tool_count": tool_count,
                            "duration": elapsed,
                            "files_modified": files_modified,
                            "files_read": files_read,
                            "file_diffs": file_diffs,
                            "tools": tool_actions,
                            "commands_run": commands_run,
                            "provider": provider,
                            "model": model,
                            "prompt": text,
                            "skip_git_fallback": True,
                        },
                        log,
                    )
                    self._last_run_summary = {
                        "tool_count": tool_count,
                        "duration": elapsed,
                        "files_modified": files_modified,
                        "files_read": files_read,
                        "file_diffs": file_diffs,
                        "tools": tool_actions,
                        "commands_run": commands_run,
                        "provider": provider,
                        "model": model,
                        "prompt": text,
                        "response": "",
                        "skip_git_fallback": True,
                    }
                else:
                    log.add_warning(
                        "⚠️ No tool calls and no text response. The model may not be responding correctly."
                    )
            else:
                log.add_error("❌ No response received from model.")
                log.add_info(f"🔍 Debug: provider={provider}, model={model}, chunks={chunk_count}")
                log.add_info("💡 Check if the model is running and accessible.")
                if provider == "ollama":
                    log.add_info("   Try: ollama list (to see available models)")
                    log.add_info("   Try: ollama serve (to start the server)")

        except Exception as e:
            self._stop_thinking()
            self._stop_stream_animation()
            self.is_busy = False
            error_msg = str(e)
            error_trace = traceback.format_exc()

            # Show user-friendly error
            self._show_error_card(
                log,
                "Provider communication failed",
                error_msg,
                provider=provider,
                model=model,
                hint="Check provider readiness with :doctor current, then use :retry.",
            )

            # For local providers, add helpful hints
            if provider in ("ollama", "lmstudio", "vllm", "sglang", "mlx", "tgi"):
                # Show experimental warning for vLLM and SGLang
                if provider in ("vllm", "sglang"):
                    log.add_warning(
                        f"⚠️  {provider.upper()} support is EXPERIMENTAL - features may be unstable"
                    )
                log.add_info(f"💡 Make sure {provider} is running:")
                if provider == "ollama":
                    log.add_info("   Run: ollama serve")
                elif provider == "lmstudio":
                    log.add_info("   Open LM Studio and start the local server")
                elif provider == "vllm":
                    log.add_info(
                        "   Start vLLM server: python -m vllm.entrypoints.openai.api_server --model <model>"
                    )
                elif provider == "sglang":
                    log.add_info(
                        "   Start SGLang server: python -m sglang.launch_server --model-path <model> --port 30000"
                    )

            # Log full traceback for debugging (only in verbose mode)
            if hasattr(self, "show_thinking_logs") and self.show_thinking_logs:
                log.add_info(f"Debug: {error_trace}")

        self._active_plan_mode_for_current_message = False
        self.is_busy = False

    @work(exclusive=True, thread=True)
    def _send_to_agent(self, text: str, name: str, log: ConversationLog):
        """Send message to agent with real-time streaming output."""
        session = get_session()
        agent = session.connected_agent

        # Reset cancellation flag
        self._cancel_requested = False

        self._call_ui(self._start_thinking, f"🤖 Connecting to {name}...")

        short_name = agent.get("short_name", "") if agent else ""

        if short_name == "opencode":
            # Check if model is selected
            if not self.current_model:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "No model selected. Press 1-5 to select a model first."
                )
                return

            # Use unified agent runner with opencode
            model_name = self.current_model
            if model_name.startswith("opencode/"):
                model_name = model_name[9:]  # Remove "opencode/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="opencode",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        elif short_name == "gemini":
            # Use unified agent runner with gemini
            model_name = self.current_model if self.current_model else "auto"
            if model_name.startswith("gemini/"):
                model_name = model_name[7:]  # Remove "gemini/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="gemini",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        elif short_name == "claude":
            # Check if model is selected
            if not self.current_model:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "No model selected. Press 1-4 to select a model first."
                )
                return

            # Use unified agent runner with claude
            model_name = self.current_model
            if model_name.startswith("claude/"):
                model_name = model_name[7:]  # Remove "claude/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="claude",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        elif short_name == "codex":
            # Check if model is selected
            if not self.current_model:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "No model selected. Press 1-4 to select a model first."
                )
                return

            # Use unified agent runner with codex
            model_name = self.current_model
            if model_name.startswith("codex/"):
                model_name = model_name[6:]  # Remove "codex/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="codex",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        else:
            # Handle all other ACP-compatible agents generically.
            acp_agents = {
                "bub",
                "cagent",
                "codeassistant",
                "fast-agent",
                "goose",
                "hermes",
                "junie",
                "kimi",
                "llmlingagent",
                "minion",
                "mistral-vibe",
                "openhands",
                "pi",
                "stakpak",
                "vtcode",
                "auggie",
                "amp",
                "grok",
            }
            if short_name in acp_agents:
                model_name = self.current_model if self.current_model else "auto"
                # Remove any prefix like "junie/" if present
                if "/" in model_name:
                    model_name = model_name.split("/", 1)[1]

                self._run_agent_unified(
                    message=text,
                    agent_type=short_name,
                    model=model_name,
                    display_name=name,
                    log=log,
                    persona_context=None,
                )
            else:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_info, f"🚧 {name} integration coming soon!")

    def _run_agent_unified(
        self,
        message: str,
        agent_type: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Unified agent runner - supports multiple ACP-compatible agents via JSON streaming.

        Args:
            message: The message/prompt to send
            agent_type: Agent type ("opencode", "gemini", "claude", "codex", "openhands")
            model: Model name
            display_name: Display name for UI
            log: ConversationLog for output
            persona_context: Optional persona context for role-based execution
        """
        import subprocess
        import json
        from time import monotonic

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            message = f"{file_context}\n\n{message}"
            self._current_file_context = ""  # Clear after use
        mcp_context = self._resolve_mcp_attachment_context_sync(log)
        if mcp_context:
            message = f"{mcp_context}\n\n{message}"

        # Route ACP-compatible agents to the JSON-RPC ACP client
        # All 15 official ACP agents support the Agent Client Protocol
        acp_agents = (
            "opencode",
            "claude",
            "codex",
            "gemini",
            "bub",
            "cagent",
            "codeassistant",
            "fast-agent",
            "goose",
            "hermes",
            "junie",
            "kimi",
            "llmlingagent",
            "minion",
            "mistral-vibe",
            "openhands",
            "pi",
            "stakpak",
            "vtcode",
            "auggie",
            "amp",
            "grok",
        )

        if agent_type in acp_agents:
            self._run_acp_jsonrpc_client(
                message, agent_type, model, display_name, log, persona_context
            )
            return

        try:
            start_time = monotonic()

            # Build command based on agent type
            if agent_type == "gemini":
                cmd = ["gemini", "--output-format", "stream-json"]

                # Add approval mode
                if self.approval_mode == "auto":
                    cmd.append("--yolo")
                elif self.approval_mode == "deny":
                    # Gemini doesn't have deny mode, use default
                    pass

                # Add model if specified
                if model and model != "auto":
                    cmd.extend(["-m", model])

                # Add the message
                cmd.append(message)

                model_display = f"gemini/{model}" if model else "gemini/auto"
            else:  # opencode (default)
                cmd = ["opencode", "run", "--format", "json"]

                # Add session continuity
                if not self._is_first_message:
                    cmd.append("--continue")

                # Add model
                if model:
                    cmd.extend(["-m", f"opencode/{model}"])

                # Add the message
                cmd.append(message)

                model_display = f"opencode/{model}" if model else "opencode/default"

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

            # Show mode-specific info on first message
            if self._is_first_message:
                if self.approval_mode == "deny":
                    self._call_ui(log.add_info, "🔴 DENY mode: ALL tool calls will be blocked")
                elif self.approval_mode == "ask":
                    self._call_ui(log.add_info, "ASK mode: prompts for external tools (y/n/a)")

            # Build environment
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=os.getcwd(),
                text=True,
                bufsize=1,
                env=env,
            )

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Read output line by line
            while True:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
                    break

                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    line = line.rstrip("\n\r")
                    if line:
                        # Parse JSON events
                        try:
                            event = json.loads(line)

                            # Handle based on agent type
                            if agent_type == "gemini":
                                self._handle_gemini_event(
                                    event,
                                    text_parts,
                                    tool_actions,
                                    files_modified,
                                    files_read,
                                    log,
                                    process,
                                )
                            else:
                                self._handle_opencode_event(
                                    event,
                                    text_parts,
                                    tool_actions,
                                    files_modified,
                                    files_read,
                                    log,
                                    process,
                                )

                        except json.JSONDecodeError:
                            # Not JSON - show as thinking line with emoji
                            if line.strip() and not line.startswith("Loaded cached"):
                                # Add emoji if line doesn't already have one
                                if not any(
                                    ord(c) > 127 for c in line[:2]
                                ):  # Check if first 2 chars have emoji
                                    emoji = "📋"  # Default console output emoji
                                    self._call_ui(self._show_thinking_line, f"{emoji} {line}", log)
                                else:
                                    self._call_ui(self._show_thinking_line, line, log)

            # Cleanup
            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

            process.wait()
            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            agent_name = "gemini" if agent_type == "gemini" else "opencode"
            self._call_ui(log.add_error, f"❌ {agent_name} CLI not found. Install it first.")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")

    def _run_fast_agent_cli(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
    ) -> None:
        """Run FastAgent through its installed CLI when ACP is unavailable."""
        import subprocess
        from time import monotonic

        start_time = monotonic()
        cmd = ["fast-agent", "go", "--message", message]
        if model and model != "auto":
            cmd[2:2] = ["--model", model]

        text_parts: list[str] = []
        try:
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)
            self._call_ui(
                log.start_agent_session,
                display_name,
                model or "auto",
                "cli",
                self.approval_mode,
            )

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._agent_process = process

            assert process.stdout is not None
            for line in process.stdout:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
                    break
                if line:
                    text_parts.append(line)
                    self._call_ui(log.add_response_chunk, line)

            if self._cancel_requested:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                self._call_ui(
                    log.end_agent_session,
                    False,
                    "🛑 Agent operation cancelled",
                )
                return

            return_code = process.wait()
            response_text = "".join(text_parts).strip()
            if return_code != 0:
                self._call_ui(
                    log.end_agent_session,
                    False,
                    response_text or f"fast-agent exited with code {return_code}",
                )
                return

            if not response_text:
                self._call_ui(
                    log.end_agent_session,
                    False,
                    "No response received from fast-agent CLI.",
                )
                return

            self._call_ui(
                log.end_agent_session,
                True,
                response_text,
            )
            self._call_ui(
                self._show_final_outcome,
                response_text,
                display_name,
                {
                    "tool_count": 0,
                    "files_modified": [],
                    "files_read": [],
                    "duration": monotonic() - start_time,
                    "file_diffs": {},
                },
                log,
            )
        except FileNotFoundError:
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(
                log.end_agent_session,
                False,
                "fast-agent CLI not found. Install with: uv tool install fast-agent-mcp",
            )
        except Exception as e:
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.end_agent_session, False, f"❌ Error: {str(e)}")
        finally:
            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

    def _run_acp_jsonrpc_client(
        self,
        message: str,
        agent_type: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ) -> None:
        """Run an ACP agent using the custom JSON-RPC client (opt-in)."""
        import asyncio
        import os
        import time
        from pathlib import Path

        from superqode.acp.client import ACPClient

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            message = f"{file_context}\n\n{message}"
            self._current_file_context = ""

        # Choose command and model display based on agent type
        # All 15 official ACP agents are supported
        if agent_type == "gemini":
            command = "gemini --experimental-acp"
            model_display = f"gemini/{model}" if model and model != "auto" else "gemini/auto"
            if "GEMINI_API_KEY" not in os.environ and "GOOGLE_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ GEMINI_API_KEY or GOOGLE_API_KEY not set. Export it first:"
                )
                self._call_ui(log.add_info, "  export GEMINI_API_KEY=your_api_key")
                self._call_ui(log.add_info, "  or export GOOGLE_API_KEY=your_api_key")
                return
        elif agent_type == "claude":
            command = "claude --acp"
            model_display = f"claude/{model}" if model else "claude/auto"
            if "ANTHROPIC_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "❌ ANTHROPIC_API_KEY not set. Export it first:")
                self._call_ui(log.add_info, "  export ANTHROPIC_API_KEY=sk-ant-...")
                return
        elif agent_type == "codex":
            command = "codex --acp"
            model_display = f"codex/{model}" if model else "codex/auto"
            if "OPENAI_API_KEY" not in os.environ and "CODEX_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ OPENAI_API_KEY or CODEX_API_KEY not set. Export one first:"
                )
                self._call_ui(log.add_info, "  export OPENAI_API_KEY=sk-...")
                self._call_ui(log.add_info, "  or export CODEX_API_KEY=sk-...")
                return
        elif agent_type == "grok":
            command = "grok agent stdio"
            model_display = f"grok/{model}" if model and model != "auto" else "grok/grok-build"
            if shutil.which("grok") is None:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "Grok CLI not found. Install it before connecting.")
                self._call_ui(log.add_info, "  curl -fsSL https://x.ai/cli/install.sh | bash")
                return
        elif agent_type == "junie":
            command = "junie --acp"
            model_display = f"junie/{model}" if model else "junie/auto"
        elif agent_type == "goose":
            command = "goose mcp"
            model_display = f"goose/{model}" if model else "goose/auto"
        elif agent_type == "kimi":
            command = "kimi --acp"
            model_display = f"kimi/{model}" if model else "kimi/auto"
            if "MOONSHOT_API_KEY" not in os.environ and "KIMI_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ MOONSHOT_API_KEY or KIMI_API_KEY not set. Export it first:"
                )
                self._call_ui(log.add_info, "  export MOONSHOT_API_KEY=your_api_key")
                return
        elif agent_type == "opencode":
            command = "opencode acp"
            model_display = f"opencode/{model}" if model else "opencode/auto"
            # OpenCode handles its own API keys via its config
        elif agent_type == "openhands":
            command = "openhands acp"
            model_display = f"openhands/{model}" if model else "openhands/auto"
            # OpenHands reads its own configuration from ~/.openhands/settings.json
        elif agent_type == "stakpak":
            command = "stakpak --acp"
            model_display = f"stakpak/{model}" if model else "stakpak/auto"
        elif agent_type == "vtcode":
            command = "vtcode --acp"
            model_display = f"vtcode/{model}" if model else "vtcode/auto"
        elif agent_type == "auggie":
            command = "auggie --acp"
            model_display = f"auggie/{model}" if model else "auggie/auto"
            if "AUGMENT_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "❌ AUGMENT_API_KEY not set. Export it first:")
                self._call_ui(log.add_info, "  export AUGMENT_API_KEY=your_api_key")
                return
        elif agent_type == "codeassistant":
            command = "code-assistant --acp"
            model_display = f"codeassistant/{model}" if model else "codeassistant/auto"
        elif agent_type == "cagent":
            command = "cagent --acp"
            model_display = f"cagent/{model}" if model else "cagent/auto"
        elif agent_type == "fast-agent":
            command = os.getenv(
                "SUPERQODE_FAST_AGENT_ACP_COMMAND",
                "uvx --from fast-agent-mcp@latest fast-agent-acp",
            )
            model_display = f"fast-agent/{model}" if model else "fast-agent/auto"
        elif agent_type == "llmlingagent":
            command = "llmling-agent --acp"
            model_display = f"llmlingagent/{model}" if model else "llmlingagent/auto"
        elif agent_type == "bub":
            command = "bub acp serve"
            model_display = f"bub/{model}" if model else "bub/auto"
        elif agent_type == "hermes":
            command = "hermes acp"
            model_display = f"hermes/{model}" if model else "hermes/auto"
        elif agent_type == "minion":
            command = "mcode acp"
            model_display = f"minion/{model}" if model else "minion/auto"
        elif agent_type == "mistral-vibe":
            command = "vibe-acp"
            model_display = f"mistral-vibe/{model}" if model else "mistral-vibe/auto"
        elif agent_type == "pi":
            command = "pi-acp"
            model_display = f"pi/{model}" if model else "pi/auto"
        elif agent_type == "amp":
            command = "acp-amp"
            model_display = f"amp/{model}" if model else "amp/auto"
            # Amp handles its own authentication via `amp login`
        else:
            self._call_ui(self._stop_thinking)
            self._call_ui(log.add_error, f"Unsupported ACP agent type: {agent_type}")
            return

        mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
            self.approval_mode, "🟡 ASK"
        )
        session_type = "new session"
        self._call_ui(
            log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
        )

        if persona_context and persona_context.is_valid:
            self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

        # Stop thinking, start streaming animation
        self._call_ui(self._stop_thinking)
        self._call_ui(self._start_stream_animation, log)

        # Use enhanced agent session header (always visible)
        self._call_ui(
            log.start_agent_session,
            display_name,
            model_display,
            "acp",
            self.approval_mode,
        )

        text_parts: list[str] = []
        tool_actions: list[dict] = []
        files_modified: list[str] = []
        files_read: list[str] = []

        # Buffer for accumulating thinking chunks
        thinking_buffer: list[str] = []
        last_thinking_time = [0.0]  # Use list to allow mutation in nested function

        def _flush_thinking_buffer():
            """Flush accumulated thinking chunks to display.

            In normal mode the reasoning is condensed to a single trimmed line so
            it reads as a calm summary rather than a wall of streamed text. In
            verbose mode the full thought is shown verbatim.
            """
            if thinking_buffer:
                full_text = "".join(thinking_buffer).strip()
                if full_text:
                    if self.thinking_verbosity != "verbose":
                        # Collapse whitespace and cap length for a tidy one-liner.
                        condensed = " ".join(full_text.split())
                        if len(condensed) > 240:
                            condensed = condensed[:237].rstrip() + "…"
                        full_text = condensed
                    self._call_ui(self._show_thinking_line, f"💭 {full_text}", log)
                thinking_buffer.clear()

        def _pick_option(options: list[dict], preferred_kinds: list[str]) -> str:
            for kind in preferred_kinds:
                match = next((o for o in options if o.get("kind") == kind), None)
                if match:
                    return match.get("optionId", "")
            if options:
                return options[0].get("optionId", "")
            return ""

        async def on_message(text: str) -> None:
            """Handle agent message chunks - stream to response area."""
            if text:
                # Flush any pending thinking before showing response
                _flush_thinking_buffer()

                text_parts.append(text)
                # Stream response chunks directly - always visible
                self._call_ui(log.add_response_chunk, text)

        async def on_thinking(text: str) -> None:
            """Handle agent thinking/session logs - toggleable with Ctrl+T."""
            import time

            if not text:
                return

            # Handle raw agent stdout logs - these show what the agent is doing
            # The [agent] prefix comes from non-JSON output from the agent process
            if text.startswith("[agent]"):
                clean_text = text[8:]  # Remove "[agent] " prefix
                # Calm mode: surface it live in the throbber, don't fill scrollback.
                if self._is_calm_output():
                    snippet = " ".join(clean_text.split())[:60]
                    if snippet:
                        self._call_ui(self._set_thinking_status, f"📡 {snippet}")
                    return
                self._call_ui(self._show_thinking_line, f"📡 {clean_text}", log)
                return

            # Filter out other verbose prefixes
            if text.startswith("[error]") or text.startswith("[startup"):
                # Show errors but in a cleaner format
                clean_text = text.replace("[error] ", "").replace("[startup error] ", "")
                self._call_ui(log.add_error, clean_text)
                return

            # Normal mode: fold the agent loop's per-iteration bookkeeping into
            # the live throbber rather than printing each line. Verbose mode lets
            # these flow through to the scrollback as before.
            loop_status = self._thinking_loop_status(text)
            if loop_status is not None and self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, loop_status)
                return

            if not self.show_thinking_logs:
                return

            # Calm mode: keep raw reasoning out of the scrollback - just show a
            # quiet "Thinking…" pulse and the one-time toggle hint.
            if self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, "💭 Thinking…")
                self._call_ui(self._maybe_show_thinking_hint, log)
                return

            # Buffer thinking chunks and display as complete thoughts
            # This prevents word-by-word display when chunks come in small pieces
            current_time = time.time()
            thinking_buffer.append(text)
            buffer_text = "".join(thinking_buffer)

            # Only flush when we have a complete thought:
            # 1. Buffer ends with sentence-ending punctuation followed by space or end
            # 2. Buffer has accumulated substantial text (>150 chars with any word boundary)
            # 3. Text ends with double newline (paragraph break)
            buffer_stripped = buffer_text.rstrip()

            # Check for complete sentences (punctuation followed by end or space)
            ends_with_sentence = (
                buffer_stripped.endswith(".")
                or buffer_stripped.endswith("!")
                or buffer_stripped.endswith("?")
                or buffer_stripped.endswith(":")
            ) and (
                text.endswith((".", "!", "?", ":"))  # Chunk itself ends with punct
                or text.endswith(" ")  # Or followed by space
                or len(buffer_text) > 50  # Or buffer is substantial
            )

            # Check for paragraph breaks
            has_paragraph_break = "\n\n" in buffer_text or buffer_text.endswith("\n")

            # Check for substantial accumulated text
            has_enough_text = len(buffer_text) > 150 and buffer_text.rstrip()[-1] in " \n.!?:"

            should_flush = ends_with_sentence or has_paragraph_break or has_enough_text

            if should_flush:
                _flush_thinking_buffer()

            last_thinking_time[0] = current_time

        # One committed calm line per tool call id, whether the completion
        # arrives on the initial tool_call or a later tool_call_update.
        calm_committed_tool_ids: set = set()

        async def on_tool_call(tool_call: dict) -> None:
            """Handle tool calls - ALWAYS visible (this is the agent's actual work)."""
            # Flush any pending thinking before showing tool call
            _flush_thinking_buffer()

            title = tool_call.get("title", "")
            raw_input = tool_call.get("rawInput", {})
            kind = tool_call.get("kind", "")
            tool_actions.append({"tool": title, "input": raw_input})

            file_path = raw_input.get("path", raw_input.get("filePath", ""))
            if file_path:
                if kind in ("edit", "write", "delete"):
                    if file_path not in files_modified:
                        files_modified.append(file_path)
                elif kind == "read":
                    if file_path not in files_read:
                        files_read.append(file_path)

            # Calm mode: fold the action into the live throbber instead of a
            # row. Some agents send a single tool_call already carrying its
            # final status with no follow-up update; without honoring it here
            # the tool never left a visible line at all.
            command = raw_input.get("command", "")
            if self._is_calm_output():
                from superqode.acp.render import normalize_acp_tool_status

                call_status = normalize_acp_tool_status(tool_call.get("status", ""))
                call_id = str(tool_call.get("toolCallId") or "")
                if call_status in ("completed", "failed"):
                    if call_id not in calm_committed_tool_ids:
                        if call_id:
                            calm_committed_tool_ids.add(call_id)
                        self._call_ui(
                            self._calm_tool_done,
                            title,
                            raw_input,
                            log,
                            call_status == "completed",
                        )
                else:
                    self._call_ui(self._calm_tool_running, title, raw_input, log)
                return
            # Verbose: show the tool call row - the agent's actual work.
            self._call_ui(
                log.add_tool_call,
                title,
                "running",
                file_path,
                command,
                "",  # output
                raw_input,  # Pass arguments so format_tool_call_compact can display them properly
            )

        async def on_tool_update(update: dict) -> None:
            """Handle tool updates, keeping normal streaming output compact.

            Order of preference for the "output" cell:
            1. Diff blocks from ``content`` — rendered as a unified diff
               so the user sees what changed in the file (this is the
               feature the user explicitly asked for).
            2. Text blocks from ``content`` — the spec-canonical channel.
            3. Legacy ``rawOutput`` / ``output`` / ``result`` — same as
               before, but suppressed for completed Read/Execute calls
               in normal mode (where the one-liner action row already
               tells the story).
            Verbose mode (``log.tool_output_mode == "verbose"``) opts
            back into the full payload.
            """
            from superqode.acp.render import (
                display_title_from_update,
                extract_tool_arguments,
                normalize_acp_tool_status,
                render_acp_tool_output,
            )

            status = normalize_acp_tool_status(update.get("status", ""))
            raw_output = update.get("rawOutput") or update.get("output") or update.get("result")
            content = update.get("content")
            kind = update.get("kind") or ""
            tool_title = display_title_from_update(update)
            raw_input = extract_tool_arguments(update)
            file_path = raw_input.get("path", raw_input.get("filePath", ""))
            command = raw_input.get("command", "")
            mode = getattr(log, "tool_output_mode", "normal")

            # Calm mode: one tidy line on completion/failure, throbber while
            # running - no raw output/diffs (flip to :thinking verbose for all).
            if self._is_calm_output():
                call_id = str(update.get("toolCallId") or "")
                if status in ("completed", "failed"):
                    if call_id and call_id in calm_committed_tool_ids:
                        return  # already committed from the initial tool_call
                    if call_id:
                        calm_committed_tool_ids.add(call_id)
                    self._call_ui(
                        self._calm_tool_done, tool_title, raw_input, log, status == "completed"
                    )
                elif status == "running":
                    self._call_ui(self._calm_tool_running, tool_title, raw_input, log)
                return

            if status == "completed":
                output_str = render_acp_tool_output(
                    kind=kind,
                    status="completed",
                    content=content,
                    raw_output=raw_output,
                    mode=mode,
                )

                # Diff path: emit directly without JSON-parsing — the
                # output is already formatted unified diff text.
                if output_str and self._looks_like_diff(output_str):
                    self._call_ui(
                        log.add_tool_call,
                        tool_title,
                        "success",
                        file_path,
                        command,
                        "updated",
                        raw_input,
                        output_str,
                    )
                    return

                # Suppressed path: no output line, just the action row
                # stays as the visual record. The user can flip to
                # verbose with `:log verbose` if they need details.
                if output_str is None:
                    return

                # Legacy path: JSON parsing for structured outputs,
                # fallback to summary line.
                formatted = self._format_tool_output(tool_title, output_str, log)
                if not formatted:
                    self._call_ui(
                        log.add_tool_call,
                        tool_title,
                        "success",
                        file_path,
                        command,
                        output_str,
                        raw_input,
                    )
            elif status == "failed":
                # Errors are *always* shown, even in minimal mode.
                # A failure is the one place where hiding output
                # would cost more than the noise saves.
                error_payload = (
                    render_acp_tool_output(
                        kind=kind,
                        status="failed",
                        content=content,
                        raw_output=raw_output,
                        mode="verbose",  # never suppress errors
                    )
                    or "failed"
                )
                self._call_ui(
                    log.add_tool_call,
                    tool_title,
                    "error",
                    file_path,
                    command,
                    str(error_payload),
                    raw_input,
                )
            elif status == "running":
                self._call_ui(
                    log.add_tool_call,
                    tool_title,
                    "running",
                    file_path,
                    command,
                    "",
                    raw_input,
                )

        async def on_plan(entries: list[dict]) -> None:
            """Handle plan updates - ALWAYS visible."""
            if entries:
                # Plans are important - always show
                self._call_ui(log.add_thinking, f"📋 Plan: {len(entries)} tasks", "planning")

        async def on_available_commands(commands: list[dict]) -> None:
            """Remember agent-advertised commands without spamming the transcript."""
            if commands:
                self._call_ui(log.add_info, f"Agent commands available: {len(commands)}")

        async def on_mode_update(mode_id: str) -> None:
            """Surface ACP mode changes from the agent."""
            if mode_id:
                self._call_ui(log.add_info, f"ACP mode: {mode_id}")

        async def on_usage_update(usage: dict) -> None:
            """Surface compact ACP context usage updates."""
            used = usage.get("used")
            size = usage.get("size")
            if isinstance(used, int) and isinstance(size, int) and size:
                pct = (used / size) * 100
                self._call_ui(
                    log.add_info, f"Context: {used / 1000:.1f}K/{size / 1000:.1f}K ({pct:.1f}%)"
                )

        async def on_permission_request(options: list[dict], tool_call: dict) -> str:
            tool_name = tool_call.get("title", "unknown")
            tool_input = tool_call.get("rawInput", {})

            if self.approval_mode == "deny":
                self._call_ui(self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log)
                return _pick_option(options, ["reject_once", "reject_always"])

            if self.approval_mode == "auto":
                self._call_ui(self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log)
                return _pick_option(options, ["allow_once", "allow_always"])

            needs_permission = self._tool_needs_permission(tool_name, tool_input)
            if needs_permission:
                self._call_ui(self._show_permission_prompt, tool_name, tool_input, log)
                self._permission_pending = True
                self._permission_response = None

                wait_start = time.monotonic()
                timeout = 60
                while self._permission_pending and (time.monotonic() - wait_start) < timeout:
                    if self._cancel_requested:
                        self._permission_pending = False
                        break
                    time.sleep(0.1)

                if self._permission_response == "allow":
                    return _pick_option(options, ["allow_once", "allow_always"])
                if self._permission_response == "allow_all":
                    self.approval_mode = "auto"
                    self._call_ui(self._sync_approval_mode)
                    return _pick_option(options, ["allow_always", "allow_once"])

                self._call_ui(log.add_info, f"Denied: {tool_name}")
                return _pick_option(options, ["reject_once", "reject_always"])

            return _pick_option(options, ["allow_once", "allow_always"])

        async def run_prompt() -> tuple[str | None, dict]:
            total_start = time.monotonic()
            model_id = self._normalize_acp_model_id(agent_type, model)

            project_root = Path.cwd()
            client_key = (str(project_root), command, model_id or "")
            ui_terminals = getattr(self, "_acp_ui_terminals", None)
            if ui_terminals is None:
                ui_terminals = {}
                self._acp_ui_terminals = ui_terminals
            terminal_counter_ref = getattr(self, "_acp_ui_terminal_counter_ref", None)
            if terminal_counter_ref is None:
                terminal_counter_ref = [0]
                self._acp_ui_terminal_counter_ref = terminal_counter_ref

            app = self

            class AppTerminalService:
                async def _run(self, method: str, params: dict) -> dict:
                    result, _handled = await asyncio.to_thread(
                        app._handle_terminal_method,
                        method,
                        params,
                        ui_terminals,
                        terminal_counter_ref,
                        log,
                    )
                    return result

                async def create(self, params: dict) -> dict:
                    return await self._run("terminal/create", params)

                async def output(self, params: dict) -> dict:
                    return await self._run("terminal/output", params)

                async def kill(self, params: dict) -> dict:
                    return await self._run("terminal/kill", params)

                async def release(self, params: dict) -> dict:
                    return await self._run("terminal/release", params)

                async def wait_for_exit(self, params: dict) -> dict:
                    return await self._run("terminal/wait_for_exit", params)

            client = getattr(self, "_acp_client", None)
            if (
                client is None
                or getattr(self, "_acp_client_key", None) != client_key
                or not client.is_running()
            ):
                if client is not None:
                    try:
                        await client.stop()
                    except Exception:
                        pass
                client = ACPClient(
                    project_root=project_root,
                    command=command,
                    model=model_id,
                    startup_timeout=float(os.getenv("SUPERQODE_ACP_STARTUP_TIMEOUT", "15")),
                    request_timeout=float(os.getenv("SUPERQODE_ACP_REQUEST_TIMEOUT", "12")),
                    prompt_timeout=float(os.getenv("SUPERQODE_ACP_PROMPT_TIMEOUT", "180")),
                )
                self._acp_client = client
                self._acp_client_key = client_key

            client.on_message = on_message
            client.on_thinking = on_thinking
            client.on_tool_call = on_tool_call
            client.on_tool_update = on_tool_update
            client.on_permission_request = on_permission_request
            client.on_plan = on_plan
            client.on_available_commands = on_available_commands
            client.on_mode_update = on_mode_update
            client.on_usage_update = on_usage_update
            client.terminal_service = AppTerminalService()

            try:
                if client.is_running():
                    self._call_ui(log.add_info, "Reusing warm ACP session. Sending prompt...")
                else:
                    self._call_ui(log.add_info, f"Starting ACP process: {command}")
                    ok = await client.start()
                    if not ok:
                        self._acp_client = None
                        self._acp_client_key = None
                        if agent_type == "grok":
                            self._call_ui(
                                log.add_info,
                                "If Grok is not signed in, run `grok login` or `grok login --device-auth`, then retry.",
                            )
                        return None, {}

                # Store for cancellation cleanup
                self._acp_client = client
                self._acp_client_key = client_key
                if getattr(client, "_process", None) is not None:
                    self._agent_process = client._process  # type: ignore[attr-defined]

                if not text_parts and not tool_actions:
                    self._call_ui(log.add_info, "ACP session ready. Sending prompt...")
                prompt_task = asyncio.create_task(client.send_prompt(message))
                prompt_started_at = time.monotonic()
                waiting_notice_sent = False

                while not prompt_task.done():
                    if self._cancel_requested:
                        try:
                            await client.cancel()
                        except Exception:
                            pass
                        prompt_task.cancel()
                        try:
                            await prompt_task
                        except asyncio.CancelledError:
                            pass
                        await client.stop()
                        self._acp_client = None
                        self._acp_client_key = None
                        self._agent_process = None
                        stats = client.get_stats().__dict__
                        stats["duration"] = time.monotonic() - total_start
                        return "cancelled", stats
                    if (
                        not waiting_notice_sent
                        and time.monotonic() - prompt_started_at > 3.0
                        and not text_parts
                        and not tool_actions
                    ):
                        self._call_ui(
                            log.add_info,
                            "Waiting for the ACP agent/model to emit its first update...",
                        )
                        waiting_notice_sent = True
                    await asyncio.sleep(0.1)

                stop_reason = await prompt_task
                stats = client.get_stats().__dict__
                stats["duration"] = time.monotonic() - total_start
                return stop_reason, stats
            except Exception:
                try:
                    await client.stop()
                finally:
                    self._acp_client = None
                    self._acp_client_key = None
                    self._agent_process = None
                raise

        try:
            if self._acp_loop_runner is None:
                self._acp_loop_runner = _AsyncLoopThread()
            stop_reason, stats = self._acp_loop_runner.run(run_prompt())
            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

            # Get response text
            response_text = "".join(text_parts) if text_parts else ""
            if stop_reason == "cancelled":
                self._call_ui(
                    log.end_agent_session,
                    False,
                    "🛑 Agent operation cancelled",
                    stats.get("prompt_tokens", 0),
                    stats.get("completion_tokens", 0),
                    stats.get("thinking_tokens", 0),
                    stats.get("cost", 0.0),
                )
                self._cancel_requested = False
                self.is_busy = False
                return
            if not response_text.strip() and not tool_actions:
                self._call_ui(
                    log.end_agent_session,
                    False,
                    (
                        "No response received from the ACP agent. "
                        "Check the agent configuration and run :log verbose for startup output."
                    ),
                    stats.get("prompt_tokens", 0),
                    stats.get("completion_tokens", 0),
                    stats.get("thinking_tokens", 0),
                    stats.get("cost", 0.0),
                )
                self.is_busy = False
                return

            # Use enhanced end_agent_session for consistent output
            self._call_ui(
                log.end_agent_session,
                True,  # success
                response_text,
                stats.get("prompt_tokens", 0),
                stats.get("completion_tokens", 0),
                stats.get("thinking_tokens", 0),
                stats.get("cost", 0.0),
            )

            # Also show the final outcome if there's response text
            if response_text.strip():
                action_summary = {
                    "tool_count": stats.get("tool_count", len(tool_actions)),
                    "files_modified": stats.get("files_modified", files_modified),
                    "files_read": stats.get("files_read", files_read),
                    "duration": stats.get("duration", 0.0),
                    "file_diffs": self._compute_file_diffs(
                        stats.get("files_modified", files_modified)
                    ),
                }
                self._call_ui(
                    self._show_final_outcome, response_text, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self._acp_client = None
            self._acp_client_key = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(
                log.end_agent_session,
                False,  # failed
                f"❌ {command} not found. Install it first.",
            )
        except Exception as e:
            self._agent_process = None
            self._acp_client = None
            self._acp_client_key = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(
                log.end_agent_session,
                False,  # failed
                f"❌ Error: {str(e)}",
            )

    # Legacy method - calls the unified runner
    def _run_opencode_unified(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """Legacy wrapper - calls _run_agent_unified with opencode agent type."""
        self._run_agent_unified(
            message=message,
            agent_type="opencode",
            model=model,
            display_name=display_name,
            log=log,
            persona_context=persona_context,
        )

    def _run_claude_acp(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Run Claude Code using the ACP protocol via claude-code-acp adapter.

        Claude Code ACP uses full bidirectional JSON-RPC protocol, not simple JSON streaming.
        This method uses subprocess with JSON-RPC communication.
        Supports multi-turn by keeping the process alive and reusing session.
        """
        import subprocess
        import json
        from time import monotonic

        try:
            start_time = monotonic()

            model_display = f"claude/{model}" if model else "claude/auto"

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

            # Build environment - need ANTHROPIC_API_KEY
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Check for API key
            if "ANTHROPIC_API_KEY" not in env:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "❌ ANTHROPIC_API_KEY not set. Export it first:")
                self._call_ui(log.add_info, "  export ANTHROPIC_API_KEY=sk-ant-...")
                return

            # Check if we can reuse existing process and session
            reuse_session = False
            process = None

            if (
                self._claude_process is not None
                and self._claude_process.poll() is None
                and self._claude_session_id
            ):
                # Process is still running and we have a session - reuse it
                process = self._claude_process
                reuse_session = True
                self._call_ui(self._show_thinking_line, "🔄 Continuing conversation...", log)
            else:
                # Start new process
                cmd = ["claude-code-acp"]
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.getcwd(),
                    text=True,
                    bufsize=1,
                    env=env,
                )
                self._claude_process = process
                self._claude_session_id = ""

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Terminal tracking for this session
            terminals = {}
            terminal_counter = 0

            # JSON-RPC request ID counter
            request_id = getattr(self, "_claude_request_id", 0)
            session_id = self._claude_session_id if reuse_session else None

            def send_request(method: str, params: dict = None) -> int:
                """Send a JSON-RPC request to the agent."""
                nonlocal request_id
                request_id += 1
                self._claude_request_id = request_id
                request = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                try:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except Exception as e:
                    self._call_ui(self._show_thinking_line, f"⚠️ Send error: {e}", log)
                return request_id

            def send_response(req_id: int, result: dict):
                """Send a JSON-RPC response to the agent."""
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id,
                }
                try:
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass

            # Step 1: Initialize the protocol
            self._call_ui(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
            send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {
                        "name": "SuperQode",
                        "title": "SuperQode - Multi-Agent Coding Team",
                        "version": "0.1.0",
                    },
                },
            )

            # Read and process messages
            pending_requests = {}
            initialized = False
            session_created = False
            prompt_sent = False

            while True:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
                    break

                # Read a line from stdout
                try:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if not line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON-RPC message
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        # Not JSON - might be debug output
                        if line and not line.startswith("Loaded"):
                            self._call_ui(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self._call_ui(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "Claude Code")
                            self._call_ui(
                                self._show_thinking_line, f"✅ Connected to {agent_name}", log
                            )

                            # Step 2: Create a new session
                            send_request(
                                "session/new",
                                {
                                    "cwd": os.getcwd(),
                                    "mcpServers": [],
                                },
                            )
                            continue

                        # Handle session/new response
                        if not session_created:
                            session_id = result.get("sessionId", "")
                            session_created = True

                            # Check available models
                            models = result.get("models", {})
                            available_models = models.get("availableModels", [])
                            if available_models:
                                model_names = [
                                    m.get("name", m.get("modelId", ""))
                                    for m in available_models[:3]
                                ]
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            self._call_ui(self._show_thinking_line, f"🚀 Session started", log)

                            # Step 3: Send the prompt
                            send_request(
                                "session/prompt",
                                {
                                    "sessionId": session_id,
                                    "prompt": [{"type": "text", "text": message}],
                                },
                            )
                            prompt_sent = True
                            continue

                        # Handle prompt response (completion)
                        if prompt_sent:
                            stop_reason = result.get("stopReason", "end_turn")
                            self._call_ui(
                                self._show_thinking_line, f"✅ Completed ({stop_reason})", log
                            )
                            break

                    # Handle request from agent (notifications/requests)
                    elif "method" in msg:
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        req_id = msg.get("id")

                        if method == "session/update":
                            # Handle session updates (streaming content)
                            update = params.get("update", params)
                            update_type = update.get("sessionUpdate", "")

                            if update_type == "agent_message_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    # Show full text, no truncation
                                    self._call_ui(self._show_thinking_line, f"💬 {text}", log)

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self._call_ui(self._show_thinking_line, f"🧠 {text}", log)

                            elif update_type == "tool_call":
                                tool_id = update.get("toolCallId", "")
                                title = update.get("title", "")
                                raw_input = update.get("rawInput", {})
                                status = update.get("status", "")

                                # Track tool_id to title mapping for detailed logging
                                if not hasattr(self, "_tool_id_map"):
                                    self._tool_id_map = {}
                                self._tool_id_map[tool_id] = {"title": title, "input": raw_input}

                                tool_actions.append({"tool": title, "input": raw_input})

                                # Track files
                                file_path = raw_input.get("path", raw_input.get("filePath", ""))
                                if file_path:
                                    kind = update.get("kind", "")
                                    if kind in ("edit", "write", "delete"):
                                        if file_path not in files_modified:
                                            files_modified.append(file_path)
                                    elif kind == "read":
                                        if file_path not in files_read:
                                            files_read.append(file_path)

                                msg_text = self._format_tool_message_rich(title, raw_input)
                                self._call_ui(self._show_thinking_line, msg_text, log)

                            elif update_type == "tool_call_update":
                                tool_id = update.get("toolCallId", "")
                                status = update.get("status", "")
                                output = update.get("output", update.get("result", ""))
                                # Get tool info from our tracking map
                                tool_info = getattr(self, "_tool_id_map", {}).get(tool_id, {})
                                tool_title = tool_info.get("title", "Tool")
                                if status == "completed":
                                    if output:
                                        output_str = str(output)
                                        # Show full output, no truncation
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"📋 Plan: {len(entries)} tasks",
                                        log,
                                    )

                        elif method == "session/request_permission":
                            # Handle permission request
                            options = params.get("options", [])
                            tool_call = params.get("toolCall", {})
                            tool_name = tool_call.get("title", "unknown")
                            tool_input = tool_call.get("rawInput", {})

                            # Handle based on approval mode
                            if self.approval_mode == "deny":
                                # Reject
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"🔴 BLOCKED: {tool_name} (DENY mode)",
                                    log,
                                )
                                reject_option = next(
                                    (o for o in options if o.get("kind") == "reject_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": reject_option.get("optionId", ""),
                                        }
                                    },
                                )
                            elif self.approval_mode == "auto":
                                # Auto-allow
                                allow_option = next(
                                    (o for o in options if o.get("kind") == "allow_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": allow_option.get("optionId", ""),
                                        }
                                    },
                                )
                                self._call_ui(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self._call_ui(
                                        self._show_permission_prompt, tool_name, tool_input, log
                                    )
                                    self._permission_pending = True
                                    self._permission_response = None

                                    wait_start = monotonic()
                                    timeout = 60
                                    while (
                                        self._permission_pending
                                        and (monotonic() - wait_start) < timeout
                                    ):
                                        if self._cancel_requested:
                                            self._permission_pending = False
                                            break
                                        time.sleep(0.1)

                                    if (
                                        self._permission_response == "deny"
                                        or self._permission_response is None
                                    ):
                                        reject_option = next(
                                            (o for o in options if o.get("kind") == "reject_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": reject_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self._call_ui(log.add_info, f"Denied: {tool_name}")
                                    else:
                                        allow_option = next(
                                            (o for o in options if o.get("kind") == "allow_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": allow_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self._call_ui(self._sync_approval_mode)
                                else:
                                    # Auto-allow safe operations
                                    allow_option = next(
                                        (o for o in options if o.get("kind") == "allow_once"),
                                        options[0] if options else {"optionId": ""},
                                    )
                                    send_response(
                                        req_id,
                                        {
                                            "outcome": {
                                                "outcome": "selected",
                                                "optionId": allow_option.get("optionId", ""),
                                            }
                                        },
                                    )

                        elif method == "fs/read_text_file":
                            # Handle file read request
                            path = params.get("path", "")
                            if path not in files_read:
                                files_read.append(path)

                            try:
                                read_path = Path(os.getcwd()) / path
                                content = read_path.read_text(encoding="utf-8", errors="ignore")
                                send_response(req_id, {"content": content})
                            except Exception:
                                send_response(req_id, {"content": ""})

                        elif method == "fs/write_text_file":
                            # Handle file write request
                            path = params.get("path", "")
                            content = params.get("content", "")

                            if path not in files_modified:
                                files_modified.append(path)

                            try:
                                write_path = Path(os.getcwd()) / path
                                write_path.parent.mkdir(parents=True, exist_ok=True)
                                write_path.write_text(content, encoding="utf-8")
                                send_response(req_id, {})
                            except Exception as e:
                                send_response(req_id, {"error": str(e)})

                        elif method.startswith("terminal/"):
                            # Handle terminal methods using helper
                            terminal_counter_ref = [terminal_counter]
                            result, handled = self._handle_terminal_method(
                                method, params, terminals, terminal_counter_ref, log
                            )
                            terminal_counter = terminal_counter_ref[0]
                            if handled:
                                send_response(req_id, result)
                            else:
                                if req_id is not None:
                                    send_response(req_id, {})

                        else:
                            # Unknown method - send empty response if it has an ID
                            if req_id is not None:
                                send_response(req_id, {})

                except Exception as e:
                    self._call_ui(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, "❌ claude-code-acp not found. Install it first:")
            self._call_ui(log.add_info, "  npm install -g @zed-industries/claude-code-acp")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")

    def _run_openhands_acp(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Run OpenHands using the ACP protocol.

        OpenHands uses full bidirectional JSON-RPC protocol via `openhands acp`.
        """
        import subprocess
        import json
        from time import monotonic

        try:
            start_time = monotonic()

            # Build command - openhands acp
            cmd = ["openhands", "acp"]

            model_display = (
                f"openhands/{model}" if model and model != "default" else "openhands/default"
            )

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

            # Build environment
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Start process with bidirectional communication
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
                text=True,
                bufsize=1,
                env=env,
            )

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Terminal tracking for this session
            terminals = {}
            terminal_counter = 0

            # JSON-RPC request ID counter
            request_id = 0
            session_id = None

            def send_request(method: str, params: dict = None) -> int:
                """Send a JSON-RPC request to the agent."""
                nonlocal request_id
                request_id += 1
                request = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                try:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except Exception as e:
                    self._call_ui(self._show_thinking_line, f"⚠️ Send error: {e}", log)
                return request_id

            def send_response(req_id: int, result: dict):
                """Send a JSON-RPC response to the agent."""
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id,
                }
                try:
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass

            # Step 1: Initialize the protocol
            self._call_ui(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
            send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {
                        "name": "SuperQode",
                        "title": "SuperQode - Multi-Agent Coding Team",
                        "version": "0.1.0",
                    },
                },
            )

            # Read and process messages
            pending_requests = {}
            initialized = False
            session_created = False
            prompt_sent = False

            while True:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
                    break

                # Read a line from stdout
                try:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if not line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON-RPC message
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        # Not JSON - might be debug output
                        if line and not line.startswith("Loaded"):
                            self._call_ui(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self._call_ui(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "OpenHands")
                            self._call_ui(
                                self._show_thinking_line, f"✅ Connected to {agent_name}", log
                            )

                            # Step 2: Create a new session
                            send_request(
                                "session/new",
                                {
                                    "cwd": os.getcwd(),
                                    "mcpServers": [],
                                },
                            )
                            continue

                        # Handle session/new response
                        if not session_created:
                            session_id = result.get("sessionId", "")
                            session_created = True

                            # Check available models
                            models = result.get("models", {})
                            available_models = models.get("availableModels", [])
                            if available_models:
                                model_names = [
                                    m.get("name", m.get("modelId", ""))
                                    for m in available_models[:3]
                                ]
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            self._call_ui(self._show_thinking_line, f"🚀 Session started", log)

                            # Step 3: Send the prompt
                            send_request(
                                "session/prompt",
                                {
                                    "sessionId": session_id,
                                    "prompt": [{"type": "text", "text": message}],
                                },
                            )
                            prompt_sent = True
                            continue

                        # Handle prompt response (completion)
                        if prompt_sent:
                            stop_reason = result.get("stopReason", "end_turn")
                            self._call_ui(
                                self._show_thinking_line, f"✅ Completed ({stop_reason})", log
                            )
                            break

                    # Handle request from agent (notifications/requests)
                    elif "method" in msg:
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        req_id = msg.get("id")

                        # Handle OpenHands-specific metadata
                        _meta = params.get("_meta", {})
                        if _meta:
                            field_meta = _meta.get("field_meta", {})
                            if oh_metrics := field_meta.get("openhands.dev/metrics"):
                                status_line = oh_metrics.get("status_line", "")
                                if status_line:
                                    self._call_ui(
                                        self._show_thinking_line, f"📊 {status_line}", log
                                    )

                        if method == "session/update":
                            # Handle session updates (streaming content)
                            update = params.get("update", params)
                            update_type = update.get("sessionUpdate", "")

                            if update_type == "agent_message_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    # Show full text, no truncation
                                    self._call_ui(self._show_thinking_line, f"💬 {text}", log)

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self._call_ui(self._show_thinking_line, f"🧠 {text}", log)

                            elif update_type == "tool_call":
                                tool_id = update.get("toolCallId", "")
                                title = update.get("title", "")
                                raw_input = update.get("rawInput", {})
                                status = update.get("status", "")

                                # Track tool_id to title mapping for detailed logging
                                if not hasattr(self, "_tool_id_map"):
                                    self._tool_id_map = {}
                                self._tool_id_map[tool_id] = {"title": title, "input": raw_input}

                                tool_actions.append({"tool": title, "input": raw_input})

                                # Track files
                                file_path = raw_input.get("path", raw_input.get("filePath", ""))
                                if file_path:
                                    kind = update.get("kind", "")
                                    if kind in ("edit", "write", "delete"):
                                        if file_path not in files_modified:
                                            files_modified.append(file_path)
                                    elif kind == "read":
                                        if file_path not in files_read:
                                            files_read.append(file_path)

                                msg_text = self._format_tool_message_rich(title, raw_input)
                                self._call_ui(self._show_thinking_line, msg_text, log)

                            elif update_type == "tool_call_update":
                                tool_id = update.get("toolCallId", "")
                                status = update.get("status", "")
                                output = update.get("output", update.get("result", ""))
                                # Get tool info from our tracking map
                                tool_info = getattr(self, "_tool_id_map", {}).get(tool_id, {})
                                tool_title = tool_info.get("title", "Tool")
                                if status == "completed":
                                    if output:
                                        output_str = str(output)
                                        # Show full output, no truncation
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"📋 Plan: {len(entries)} tasks",
                                        log,
                                    )

                        elif method == "session/request_permission":
                            # Handle permission request
                            options = params.get("options", [])
                            tool_call = params.get("toolCall", {})
                            tool_name = tool_call.get("title", "unknown")
                            tool_input = tool_call.get("rawInput", {})

                            # Handle based on approval mode
                            if self.approval_mode == "deny":
                                # Reject
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"🔴 BLOCKED: {tool_name} (DENY mode)",
                                    log,
                                )
                                reject_option = next(
                                    (o for o in options if o.get("kind") == "reject_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": reject_option.get("optionId", ""),
                                        }
                                    },
                                )
                            elif self.approval_mode == "auto":
                                # Auto-allow
                                allow_option = next(
                                    (o for o in options if o.get("kind") == "allow_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": allow_option.get("optionId", ""),
                                        }
                                    },
                                )
                                self._call_ui(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self._call_ui(
                                        self._show_permission_prompt, tool_name, tool_input, log
                                    )
                                    self._permission_pending = True
                                    self._permission_response = None

                                    wait_start = monotonic()
                                    timeout = 60
                                    while (
                                        self._permission_pending
                                        and (monotonic() - wait_start) < timeout
                                    ):
                                        if self._cancel_requested:
                                            self._permission_pending = False
                                            break
                                        time.sleep(0.1)

                                    if (
                                        self._permission_response == "deny"
                                        or self._permission_response is None
                                    ):
                                        reject_option = next(
                                            (o for o in options if o.get("kind") == "reject_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": reject_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self._call_ui(log.add_info, f"Denied: {tool_name}")
                                    else:
                                        allow_option = next(
                                            (o for o in options if o.get("kind") == "allow_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": allow_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self._call_ui(self._sync_approval_mode)
                                else:
                                    # Auto-allow safe operations
                                    allow_option = next(
                                        (o for o in options if o.get("kind") == "allow_once"),
                                        options[0] if options else {"optionId": ""},
                                    )
                                    send_response(
                                        req_id,
                                        {
                                            "outcome": {
                                                "outcome": "selected",
                                                "optionId": allow_option.get("optionId", ""),
                                            }
                                        },
                                    )

                        elif method == "fs/read_text_file":
                            # Handle file read request
                            path = params.get("path", "")
                            if path not in files_read:
                                files_read.append(path)

                            try:
                                read_path = Path(os.getcwd()) / path
                                content = read_path.read_text(encoding="utf-8", errors="ignore")
                                send_response(req_id, {"content": content})
                            except Exception:
                                send_response(req_id, {"content": ""})

                        elif method == "fs/write_text_file":
                            # Handle file write request
                            path = params.get("path", "")
                            content = params.get("content", "")

                            if path not in files_modified:
                                files_modified.append(path)

                            try:
                                write_path = Path(os.getcwd()) / path
                                write_path.parent.mkdir(parents=True, exist_ok=True)
                                write_path.write_text(content, encoding="utf-8")
                                send_response(req_id, {})
                            except Exception as e:
                                send_response(req_id, {"error": str(e)})

                        elif method.startswith("terminal/"):
                            # Handle terminal methods using helper
                            terminal_counter_ref = [terminal_counter]
                            result, handled = self._handle_terminal_method(
                                method, params, terminals, terminal_counter_ref, log
                            )
                            terminal_counter = terminal_counter_ref[0]
                            if handled:
                                send_response(req_id, result)
                            else:
                                if req_id is not None:
                                    send_response(req_id, {})

                        else:
                            # Unknown method - send empty response if it has an ID
                            if req_id is not None:
                                send_response(req_id, {})

                except Exception as e:
                    self._call_ui(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, "❌ openhands not found. Install it first:")
            self._call_ui(log.add_info, "  uv tool install openhands -U --python 3.12")
            self._call_ui(log.add_info, "  openhands login")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")

    def _send_permission_response(self, process, response: str):
        """Send a permission response to the process."""
        try:
            if process.stdin:
                process.stdin.write(f"{response}\n")
                process.stdin.flush()
        except Exception:
            pass

    def _thinking_loop_status(self, text: str) -> Optional[str]:
        """If `text` is agent-loop bookkeeping, return a compact live-status label.

        Returns None for genuine reasoning/content, which should be shown normally.
        """
        if not text:
            return None
        stripped = text.strip()
        lowered = stripped.lower()
        if not any(marker in lowered for marker in self._LOOP_BOOKKEEPING_MARKERS):
            return None
        if "reached maximum iterations" in lowered:
            return "Reached max iterations"
        match = re.search(r"iteration\s+(\d+)", lowered)
        if match:
            return f"Working… (step {match.group(1)})"
        return "Working…"

    def _set_thinking_status(self, status: str) -> None:
        """Update the live throbber's steady status label (normal thinking mode)."""
        try:
            indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            indicator.status = status
        except Exception:
            pass

    def _calm_verb_target(self, name: str, args: Optional[dict] = None) -> tuple:
        """Map a tool name + args to a friendly (verb, short target) pair."""
        args = args or {}
        try:
            log = self.query_one("#log", ConversationLog)
            verb = log._format_tool_name(name)
        except Exception:
            verb = (name or "tool").replace("_", " ").split(" ")[0].lower()
        target = (
            args.get("path")
            or args.get("file_path")
            or args.get("filePath")
            or args.get("command")
            or args.get("pattern")
            or args.get("query")
            or ""
        )
        target = str(target).strip()
        if target and "/" in target and " " not in target:
            parts = target.rstrip("/").split("/")
            target = "/".join(parts[-2:]) if len(parts) > 1 else parts[-1]
        if len(target) > 52:
            target = "…" + target[-51:]
        return verb, target

    def _maybe_show_thinking_hint(self, log: ConversationLog) -> None:
        """Once per session, tell the user how to see full detail."""
        if getattr(self, "_thinking_hint_shown", False):
            return
        self._thinking_hint_shown = True
        t = Text()
        t.append("  💡 ", style=THEME["muted"])
        t.append("Ctrl+T", style=f"bold {THEME['cyan']}")
        t.append(" or ", style=THEME["muted"])
        t.append(":thinking verbose", style=f"bold {THEME['cyan']}")
        t.append(" to see full reasoning & tool detail\n", style=THEME["muted"])
        log.write(t)

    def _calm_tool_running(self, name: str, args: Optional[dict], log: ConversationLog) -> None:
        """Update the live throbber with the in-progress action."""
        verb, target = self._calm_verb_target(name, args)
        icon = self._CALM_VERB_ICONS.get(verb, "✷")
        label = verb.capitalize()
        status = f"{icon} {label} {target}…" if target else f"{icon} {label}…"
        self._set_thinking_status(status)
        self._maybe_show_thinking_hint(log)

    def _calm_tool_done(
        self, name: str, args: Optional[dict], log: ConversationLog, ok: bool = True
    ) -> None:
        """Commit one tidy line for a finished tool (no raw output/diff)."""
        verb, target = self._calm_verb_target(name, args)
        self._calm_actions = getattr(self, "_calm_actions", 0) + 1
        icon = "✷" if ok else "✗"
        color = THEME["success"] if ok else THEME["error"]
        t = Text()
        t.append(f"  {icon} ", style=f"bold {color}")
        t.append(f"{verb:<7}", style=f"bold {THEME['text']}")
        if target:
            t.append(f" {target}", style=THEME["muted"])
        t.append("\n", style="")
        log.write(t)

    def _show_thinking_line(self, line: str, log: ConversationLog):
        """Show a thinking/log line - SuperQode quantum style.

        Uses quantum-inspired animation (◇◆◈) instead of arrows.
        Automatically adds emoji if line doesn't have one.
        """
        # Check if thinking logs should be shown
        if not self.show_thinking_logs:
            return

        # Skip empty lines
        if not line.strip():
            return

        # Ensure auto-scroll is ON during agent work so user sees updates
        log.auto_scroll = True

        # Check if line already has an emoji (check first 3 characters)
        has_emoji = False
        if line.strip():
            first_chars = line.strip()[:3]
            # Check if any character is an emoji (Unicode emoji range)
            for char in first_chars:
                # Check for emoji ranges
                code = ord(char)
                if (
                    0x1F600 <= code <= 0x1F64F  # Emoticons
                    or 0x1F300 <= code <= 0x1F5FF  # Misc Symbols and Pictographs
                    or 0x1F680 <= code <= 0x1F6FF  # Transport and Map
                    or 0x1F1E0 <= code <= 0x1F1FF  # Flags
                    or 0x2600 <= code <= 0x26FF  # Misc symbols
                    or 0x2700 <= code <= 0x27BF  # Dingbats
                    or 0xFE00 <= code <= 0xFE0F  # Variation Selectors
                    or 0x1F900 <= code <= 0x1F9FF  # Supplemental Symbols and Pictographs
                    or 0x1FA00 <= code <= 0x1FA6F
                ):  # Chess Symbols, etc.
                    has_emoji = True
                    break

        # Add appropriate emoji based on content type if line doesn't have one
        if not has_emoji:
            emoji = self._get_emoji_for_line(line)
            line = f"{emoji} {line}"

        # Show the line with animated quantum prefix
        text = Text()
        frame = getattr(self, "_stream_animation_frame", 0)

        # Quantum animation frames
        quantum_frames = ["◇", "◆", "◈", "◆"]
        quantum_icon = quantum_frames[frame % len(quantum_frames)]

        # Cycling colors from SuperQode palette
        prefix_color = GRADIENT_PURPLE[frame % len(GRADIENT_PURPLE)]

        # Show with quantum prefix - don't truncate, show full line
        # Split long lines into multiple lines to prevent any truncation
        text.append(f"  {quantum_icon} ", style=f"bold {prefix_color}")

        # If line is very long, we'll let it wrap naturally
        # Rich will handle wrapping if console width is set correctly
        text.append(f"{line}\n", style=SQ_COLORS.text_muted)

        # Write the text - ensure console width is unlimited
        log.write(text)

    def _agent_session_label(self, provider: str) -> str:
        """Session-banner label that names what actually runs the turn.

        Self-contained runtimes (Codex, Claude Agent SDK) execute their own
        agent loop and tools; labelling those sessions with SuperQode's
        native harness ("Harness: Core") misled users about whose harness
        was active.
        """
        pure = getattr(self, "_pure_mode", None)
        runtime_name = str(getattr(pure, "runtime_name", "") or "")
        if runtime_name in self._SELF_CONTAINED_RUNTIMES:
            friendly = {
                "codex-sdk": "Codex",
                "claude-agent-sdk": "Claude Agent SDK",
            }.get(runtime_name, runtime_name)
            return f"Runtime: {friendly} (agent-owned harness)"
        harness_name = ""
        try:
            harness_name = pure.get_status().get("harness", {}).get("name", "") if pure else ""
        except Exception:  # noqa: BLE001 - banner must never fail a send
            harness_name = ""
        if harness_name:
            return f"Harness: {_harness_display_name(harness_name)}"
        return f"BYOK {provider}"
