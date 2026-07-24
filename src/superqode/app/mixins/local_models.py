"""Local providers/servers (Ollama, llama.cpp, MLX)."""

from __future__ import annotations
import shlex
from pathlib import Path
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.recipes import PromptCompletionCandidate, LocalRecipe


class LocalModelsMixin:
    """Local provider/model discovery, servers, and selection."""

    def _active_local_provider_model(self) -> tuple[str, str]:
        """Best-effort provider/model pair for the active local runtime."""
        provider = str(getattr(self, "current_provider", "") or "").strip().lower()
        model = str(getattr(self, "current_model", "") or "").strip()
        try:
            pure = getattr(self, "_pure_mode", None)
            session = getattr(pure, "session", None)
            if session is not None:
                provider = str(getattr(session, "provider", "") or provider).strip().lower()
                model = str(getattr(session, "model", "") or model).strip()
        except Exception:
            pass
        if not provider:
            provider = str(getattr(self, "_local_selected_provider", "") or "").strip().lower()
        if not model:
            model = str(getattr(self, "_local_selected_model", "") or "").strip()
        local_providers = {
            "ollama",
            "mlx",
            "lmstudio",
            "ds4",
            "llama.cpp",
            "llamacpp",
            "vllm",
            "sglang",
            "tgi",
            "huggingface-local",
        }
        if provider not in local_providers:
            return "", ""
        return provider, model

    def _teardown_local_model_runtime(self, provider: str = "", model: str = "") -> None:
        """Stop local generation resources owned or warmed by this TUI session."""
        provider = (provider or "").strip().lower()
        model = (model or "").strip()
        if not provider:
            provider, model = self._active_local_provider_model()
        if not provider:
            return

        if provider == "ollama" and model:
            self._unload_ollama_model(model)
        if provider == "mlx":
            try:
                from superqode.providers.local.mlx_engine import shutdown_mlx_engine

                shutdown_mlx_engine()
            except Exception:
                pass

        engine = {"llamacpp": "llama.cpp", "huggingface-local": "mlx"}.get(provider, provider)
        if engine in {"mlx", "ds4", "llama.cpp", "lmstudio"}:
            try:
                from superqode.local.servers import ServerManager

                ServerManager().stop(engine)
            except Exception:
                pass

    def _scroll_to_highlighted_local_model(self, log: ConversationLog, highlighted_idx: int):
        """Scroll the local-model picker so the highlighted multi-line row is visible."""
        try:
            log.auto_scroll = False
            visible_height = max(6, int(getattr(getattr(log, "size", None), "height", 18) or 18))
            header_lines = 5
            # Local model rows render as: title, id, details, optional capabilities,
            # blank line. Use a conservative row height so row 6+ scrolls into view.
            lines_per_item = 5
            highlighted_y = header_lines + highlighted_idx * lines_per_item
            target_y = max(0, highlighted_y - max(2, visible_height // 2))
            log.scroll_to(y=target_y, animate=False)
        except Exception:
            pass
        finally:
            log.auto_scroll = True

    def action_navigate_local_provider_up(self):
        """Navigate to previous local provider (arrow up)."""
        if not getattr(self, "_awaiting_local_provider", False):
            return

        provider_list = getattr(self, "_local_provider_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_local_highlighted_provider_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._local_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_local_provider_picker(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_local_provider_down(self):
        """Navigate to next local provider (arrow down)."""
        if not getattr(self, "_awaiting_local_provider", False):
            return

        provider_list = getattr(self, "_local_provider_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_local_highlighted_provider_index", 0)
        new_idx = min(len(provider_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._local_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_local_provider_picker(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_local_provider(self):
        """Select the currently highlighted local provider (Enter key)."""
        if not getattr(self, "_awaiting_local_provider", False):
            return

        provider_list = getattr(self, "_local_provider_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_local_highlighted_provider_index", 0)
        if 0 <= current_idx < len(provider_list):
            provider_id, provider_def = provider_list[current_idx]
            log = self.query_one("#log", ConversationLog)
            self._awaiting_local_provider = False
            # Reset local model highlight index when entering a new provider
            self._local_highlighted_model_index = 0
            self.run_worker(self._show_local_provider_models(provider_id, log))

    def action_navigate_local_model_up(self):
        """Navigate to previous local model (arrow up)."""
        if not getattr(self, "_awaiting_local_model", False):
            return

        model_list = getattr(self, "_local_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_local_highlighted_model_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._local_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._redraw_local_provider_models(log)
            self._scroll_to_highlighted_local_model(log, new_idx)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_local_model_down(self):
        """Navigate to next local model (arrow down)."""
        if not getattr(self, "_awaiting_local_model", False):
            return

        model_list = getattr(self, "_local_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_local_highlighted_model_index", 0)
        new_idx = min(len(model_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._local_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._redraw_local_provider_models(log)
            self._scroll_to_highlighted_local_model(log, new_idx)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_local_model(self):
        """Select the currently highlighted local model (Enter key)."""
        if not getattr(self, "_awaiting_local_model", False):
            return

        model_list = getattr(self, "_local_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_local_highlighted_model_index", 0)
        if 0 <= current_idx < len(model_list):
            model_id = model_list[current_idx]
            provider_id = getattr(self, "_local_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._awaiting_local_model = False
                self._connect_local_mode(provider_id, model_id, log)

    @staticmethod
    def _load_local_recipes() -> dict[str, LocalRecipe]:
        from superqode.app_main import SuperQodeApp

        recipes: dict[str, LocalRecipe] = {}
        for directory in SuperQodeApp._recipe_dirs():
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*")):
                if path.suffix.lower() not in {".yaml", ".yml", ".json"} or not path.is_file():
                    continue
                recipe = SuperQodeApp._load_recipe_file(path)
                if recipe:
                    recipes[recipe.name] = recipe
        return recipes

    @staticmethod
    def _local_provider_completion_candidates() -> list[PromptCompletionCandidate]:
        from superqode.app_main import SuperQodeApp

        return SuperQodeApp._provider_completion_candidates(local=True)

    @staticmethod
    def _local_skill_names() -> list[str]:
        try:
            from superqode.skills import load_skills

            return [skill.name for skill in load_skills(Path.cwd()).values()]
        except Exception:
            return []

    @staticmethod
    def _all_local_skill_names() -> list[str]:
        from superqode.app_main import SuperQodeApp

        names = set(SuperQodeApp._local_skill_names())
        skills_root = Path.cwd() / ".agents" / "skills"
        if not skills_root.exists():
            return sorted(names)
        for path in sorted(skills_root.rglob("*.md")):
            name = path.parent.name if path.name.upper() == "SKILL.MD" else path.stem
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:1000]
            except Exception:
                text = ""
            if text.startswith("---"):
                end = text.find("\n---", 3)
                front = text[:end] if end != -1 else text
                for line in front.splitlines():
                    if line.strip().startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"').strip("'") or name
                        break
            names.add(name)
        return sorted(names)

    @staticmethod
    def _local_provider_ids() -> list[str]:
        try:
            from superqode.providers.registry import PROVIDERS, ProviderCategory

            return [
                provider_id
                for provider_id, provider in PROVIDERS.items()
                if provider.category == ProviderCategory.LOCAL
            ]
        except Exception:
            return []

    def _pin_local_prompt_to_input(
        self,
        placeholder: str,
        log: ConversationLog | None = None,
        *,
        notify: str | None = None,
    ) -> None:
        """Keep critical local-runtime decisions visible near the cursor."""
        self._set_input_placeholder(placeholder)
        if log is not None:
            try:
                log.scroll_end(animate=False)
            except Exception:
                pass
        try:
            self._ensure_input_focus()
        except Exception:
            pass
        if notify:
            try:
                self.notify(notify, severity="warning", timeout=3)
            except Exception:
                pass

    def _surface_local_connection_failure(
        self,
        log: ConversationLog,
        message: str,
    ) -> None:
        """Keep a local connection failure visible in transcript and chrome."""
        self._announce_transition(
            title="Local connection failed",
            primary=message,
            detail="The selected local model is not ready",
            severity="error",
            log=log,
            guidance="Check the local server, then reconnect with :connect local.",
            timeout=5,
            dedupe_key=f"local-connection-error:{message}",
        )
        try:
            self._set_input_placeholder("Connection failed — fix the issue, then reconnect")
            self._ensure_input_focus()
        except Exception:
            pass

    def _should_show_thinking_for_local(self, text: str) -> bool:
        """Determine if a thinking log should be shown for local models.

        Aggressively filters out verbose content and keeps only important status messages.
        Returns True for important thinking logs, False for everything else to suppress.
        """
        if not text or not text.strip():
            return False

        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # Always keep lines with emojis (status indicators from AgentLoop)
        if any(ord(char) >= 0x1F600 for char in text_stripped[:3]):
            return True

        # Keep ONLY explicit status messages from AgentLoop (these are important)
        # These are the structured messages AgentLoop generates, not model thinking
        # Use more specific patterns to avoid matching code
        agent_status_patterns = [
            "processing request",
            "calling model",
            "executing tool",
            "received response",
            "iteration",
            "response complete",
            "reached maximum iterations",
            "operation cancelled by user",
        ]
        # Check if text starts with or contains these patterns (more specific)
        for pattern in agent_status_patterns:
            if pattern in text_lower:
                # Make sure it's not code (e.g., "def complete():" shouldn't match "complete")
                if not self._looks_like_code(text_stripped):
                    return True

        # Suppress ALL "Extended Thinking" content from models (often contains code)
        if "extended thinking" in text_lower or text_lower.startswith("[extended thinking]"):
            return False

        # Keep tool-related status messages (formatted by _format_tool_message_rich).
        # These now lead with a minimal icon glyph; recognize them directly.
        if text_stripped[:1] in ("↳", "↲", "⟳", "▸", "⌕", "⋮", "◎", "✕", "•"):
            return True
        # Legacy label patterns kept as a belt-and-braces fallback.
        tool_status_patterns = [
            "tool completed",
            "tool failed",
        ]
        if any(pattern in text_lower for pattern in tool_status_patterns):
            return True

        # Check if it looks like code - if so, suppress it
        if self._looks_like_code(text_stripped):
            return False

        # For local models, be VERY aggressive - suppress everything else by default
        # Only show explicit AgentLoop status messages and tool status, everything else is noise
        # This includes all model thinking content, code lines, and verbose output
        return False

    def _handle_local_provider_selection(self, selection: str, log: ConversationLog):
        """Handle local provider selection from :connect local picker."""
        # Check for _local_provider_list (from :connect local command)
        if hasattr(self, "_local_provider_list") and self._local_provider_list:
            try:
                # Strip whitespace and try to parse as number
                selection = selection.strip()
                idx = int(selection) - 1
                if 0 <= idx < len(self._local_provider_list):
                    provider_id, provider_def = self._local_provider_list[idx]
                    self._awaiting_local_provider = False
                    # Reset model highlight index when entering a new provider
                    self._local_highlighted_model_index = 0
                    # Show models for this local provider (async function)
                    self.run_worker(self._show_local_provider_models(provider_id, log))
                    return True
                else:
                    log.add_error(
                        f"Invalid selection. Enter a number between 1 and {len(self._local_provider_list)}"
                    )
                    return True  # Return True to prevent further processing
            except ValueError:
                # Not a number, might be a provider name - try to match
                selection_lower = selection.lower()
                for provider_id, provider_def in self._local_provider_list:
                    if (
                        selection_lower == provider_id.lower()
                        or selection_lower in provider_def.name.lower()
                    ):
                        self._awaiting_local_provider = False
                        # Reset model highlight index when entering a new provider
                        self._local_highlighted_model_index = 0
                        self.run_worker(self._show_local_provider_models(provider_id, log))
                        return True
                log.add_error(f"Unknown provider: {selection}")
                return True  # Return True to prevent further processing

        return False

    def _handle_local_model_selection(self, selection: str, log: ConversationLog):
        """Handle local model selection from :connect local picker."""
        if not hasattr(self, "_local_selected_provider"):
            return False

        provider_id = self._local_selected_provider
        model_list = getattr(self, "_local_model_list", [])

        model = None

        if selection.isdigit():
            # Number selection
            idx = int(selection)
            if model_list and 1 <= idx <= len(model_list):
                model = model_list[idx - 1]
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(model_list)}")
                return True
        else:
            # Search by model name/ID
            selection_lower = selection.lower().strip()

            # Try exact match first
            for m in model_list:
                if selection_lower == m.lower():
                    model = m
                    break
                # Try partial match (contains)
                if selection_lower in m.lower():
                    if model is None:  # First match
                        model = m
                    else:
                        # Multiple matches - prefer shorter match
                        if len(m) < len(model):
                            model = m

            if not model:
                log.add_error(f"Model '{selection}' not found for {provider_id}")
                if model_list:
                    log.add_info(f"Available models: {', '.join(model_list[:5])}")
                    if len(model_list) > 5:
                        log.add_info(f"... and {len(model_list) - 5} more")
                return True

        self._awaiting_local_model = False
        self._connect_local_mode(provider_id, model, log)
        return True

    def _local_provider_host(self, provider: str) -> str:
        import os

        if provider == "ollama":
            return os.getenv("OLLAMA_HOST", "http://localhost:11434")
        if provider == "ds4":
            return os.getenv("DS4_HOST", "http://127.0.0.1:8000/v1")
        if provider == "lmstudio":
            return os.getenv("LMSTUDIO_HOST", "http://localhost:1234/v1")
        if provider == "mlx":
            return os.getenv("MLX_HOST", "http://127.0.0.1:8080/v1")
        if provider == "vllm":
            return os.getenv("VLLM_HOST", "http://127.0.0.1:8000/v1")
        if provider == "sglang":
            return os.getenv("SGLANG_HOST", "http://127.0.0.1:30000/v1")
        if provider == "tgi":
            return os.getenv("TGI_HOST", "http://127.0.0.1:8080/v1")
        return ""

    async def _test_local_connection(
        self,
        provider: str,
        model: str,
        log: ConversationLog,
        *,
        quiet: bool = False,
    ):
        """Test connection to a local provider."""
        try:
            from superqode.providers.registry import PROVIDERS, ProviderCategory
            import os

            provider_def = PROVIDERS.get(provider)
            is_local = provider_def and provider_def.category == ProviderCategory.LOCAL

            if not quiet:
                log.add_info(f"Testing: {provider}/{model}")

            if is_local:
                if provider == "ds4":
                    from superqode.providers.local.ds4 import DS4Client

                    ds4_host = os.getenv("DS4_HOST", "http://127.0.0.1:8000/v1")
                    if not quiet:
                        log.add_info(f"DS4 host: {ds4_host}")
                    client = DS4Client(host=ds4_host)
                    health = await client.get_status()
                    if health.available:
                        if not quiet:
                            log.add_success(f"✓ DS4 server ready at {ds4_host}")
                        # Warm the model so the first real prompt isn't the one
                        # paying the one-time cold load (~81GB paged from disk).
                        await self._warmup_ds4(client, model, log)
                        self._announce_local_model_ready(
                            provider=provider,
                            model=model,
                            log=log,
                        )
                    else:
                        self._surface_local_connection_failure(
                            log,
                            f"DS4 connection failed: {health.error or 'server unavailable'}",
                        )
                elif provider == "ollama":
                    from superqode.providers.local.ollama import OllamaClient

                    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                    if not quiet:
                        log.add_info(f"Ollama host: {ollama_host}")
                    health = await OllamaClient(host=ollama_host).get_status()
                    if health.available:
                        if not quiet:
                            log.add_success(f"✓ Ollama server ready at {ollama_host}")
                        await self._warmup_local_generation(provider, model, log)
                        self._announce_local_model_ready(
                            provider=provider,
                            model=model,
                            log=log,
                        )
                    else:
                        self._surface_local_connection_failure(
                            log,
                            f"Ollama connection failed: {health.error or 'server unavailable'}",
                        )
                else:
                    if not quiet:
                        log.add_info(
                            "Local provider selected. First prompt will validate generation."
                        )
                    await self._warmup_local_generation(provider, model, log)
                    self._announce_local_model_ready(
                        provider=provider,
                        model=model,
                        log=log,
                    )
            else:
                from superqode.providers.gateway.litellm_gateway import LiteLLMGateway
                from superqode.providers.gateway.base import Message

                gateway = LiteLLMGateway()
                model_string = gateway.get_model_string(provider, model)
                log.add_info(f"Testing: {model_string}")

                # Cloud/BYOK providers can afford a tiny completion test. Local
                # providers avoid this path so we do not contend with the first
                # real user prompt on single-request local servers.
                test_messages = [Message(role="user", content="Say 'test'")]
                response = await gateway.chat_completion(
                    messages=test_messages,
                    model=model,
                    provider=provider,
                    max_tokens=10,
                )

                if response and response.content:
                    log.add_success(f"✓ Connected to {provider}/{model}")
                    log.add_info(f"Test response: {response.content[:50]}")
                else:
                    log.add_warning(f"Connected but no response content. Response: {response}")

            # Ensure focus returns to input after connection test
            # Use set_timer since we're in the app's event loop, not a separate thread
            self.set_timer(0.1, self._ensure_input_focus)

        except Exception as e:
            import traceback

            error_msg = str(e)
            error_type = type(e).__name__
            self._surface_local_connection_failure(
                log,
                f"Connection failed ({error_type}): {error_msg}",
            )

            # Show full traceback for debugging
            if hasattr(self, "show_thinking_logs") and self.show_thinking_logs:
                log.add_info(f"Traceback:\n{traceback.format_exc()}")

            # Show helpful hints based on provider
            if provider == "ollama":
                log.add_info("💡 Troubleshooting:")
                log.add_info("   1. Make sure Ollama is running: ollama serve")
                log.add_info(f"   2. Check if model exists: ollama list")
                log.add_info(f"   3. Pull the model if needed: ollama pull {model}")
                log.add_info(f"   4. Test manually: curl http://localhost:11434/api/tags")
                log.add_info(
                    f"   5. Check Ollama host: echo $OLLAMA_HOST (default: http://localhost:11434)"
                )
            elif provider == "lmstudio":
                log.add_info("💡 Troubleshooting:")
                log.add_info("   1. Open LM Studio application")
                log.add_info("   2. Load a model in LM Studio")
                log.add_info("   3. Start the local server (usually on port 1234)")
            elif provider == "ds4":
                log.add_info("💡 Troubleshooting:")
                log.add_info("   1. Start ds4-server")
                log.add_info("   2. Test manually: curl http://127.0.0.1:8000/v1/models")
                log.add_info("   3. Set DS4_HOST if using a different URL")
            elif provider in ("vllm", "sglang", "mlx", "tgi"):
                log.add_info(f"💡 Make sure {provider} server is running and accessible")
                log.add_info(f"   Check the base URL in environment or provider config")

            # Still allow connection attempt (user might fix the issue)
            self._clear_for_workspace(log, f"BYOK • {provider}")

            # Ensure focus returns to input even after error
            # Use set_timer since we're in the app's event loop, not a separate thread
            self.set_timer(0.1, self._ensure_input_focus)

    async def _warmup_local_generation(
        self,
        provider: str,
        model: str,
        log: ConversationLog,
    ) -> None:
        """Send a tiny local request so the first real prompt avoids cold start.

        This is best-effort and never fails the connection. Local servers often
        load weights, allocate KV cache, or JIT paths on the first generation;
        doing that visibly during connect makes the first user response feel
        much less broken.
        """
        import asyncio
        import os
        import time

        if os.getenv("SUPERQODE_LOCAL_WARMUP", "1").strip().lower() in (
            "0",
            "false",
            "no",
            "off",
        ):
            return
        if provider == "ds4":
            return

        from superqode.providers.gateway.base import Message
        from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

        self._call_ui(self._start_thinking, "Warming local model…")
        self._call_ui(self._set_thinking_status, "Warming local model…")
        gateway = LiteLLMGateway()
        started = time.monotonic()
        try:
            try:
                await asyncio.wait_for(
                    gateway.chat_completion(
                        messages=[Message(role="user", content="Reply with exactly: ok")],
                        model=model,
                        provider=provider,
                        max_tokens=4,
                        temperature=0.0,
                    ),
                    timeout=float(os.getenv("SUPERQODE_LOCAL_WARMUP_TIMEOUT", "45")),
                )
            except asyncio.TimeoutError:
                log.add_warning(
                    "Local warmup timed out; connected, but the first prompt may still be slow."
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._surface_local_connection_failure(
                    log,
                    f"Local model check failed: {exc}",
                )
                return

            elapsed = time.monotonic() - started
            log.add_meta(f"Ready · {provider}/{model} · warm {elapsed:.1f}s")
            self._announce_local_model_ready(
                provider=provider,
                model=model,
                log=log,
                detail=f"warmup {elapsed:.1f}s",
            )
        finally:
            self._call_ui(self._stop_thinking)

    def _connect_local_cmd(self, args: str, log: ConversationLog):
        """Handle :connect local command - Interactive local provider/model picker."""
        args = args.strip()

        # :connect local - (switch to previous)
        if args == "-":
            self._connect_previous(log)
            return

        # :connect local ! (show history)
        if args == "!":
            self._connect_history(log)
            return

        # :connect local last (reconnect to last used)
        if args == "last":
            self._connect_last(log)
            return

        # :connect local <provider>[/<model>] (direct connect with / separator)
        if args:
            # Support provider/model syntax
            if "/" in args:
                parts = args.split("/", 1)
                provider = parts[0].strip()
                model = parts[1].strip() if len(parts) > 1 else None
                if provider and model:
                    self._connect_local_mode(provider, model, log)
                    return

            # Support space-separated syntax
            parts = args.split(maxsplit=1)
            provider = parts[0]
            model = parts[1] if len(parts) > 1 else None

            if model:
                # Direct connect with provider and model
                self._connect_local_mode(provider, model, log)
            else:
                # Show models for this local provider
                self.run_worker(self._show_local_provider_models(provider, log))
            return

        # :connect local (show interactive local provider picker)
        # CRITICAL: Clear any existing state to ensure we show provider picker, not models
        self._awaiting_local_provider = False
        self._awaiting_local_model = False
        if hasattr(self, "_local_selected_provider"):
            delattr(self, "_local_selected_provider")
        if hasattr(self, "_local_provider_list"):
            delattr(self, "_local_provider_list")
        if hasattr(self, "_local_model_list"):
            delattr(self, "_local_model_list")
        if hasattr(self, "_local_highlighted_provider_index"):
            self._local_highlighted_provider_index = 0
        if hasattr(self, "_local_highlighted_model_index"):
            self._local_highlighted_model_index = 0

        # Now show the provider picker
        self._show_local_provider_picker(log)

    def _connect_local_mode(
        self,
        provider: str,
        model: str,
        log: ConversationLog,
        *,
        session_id: str | None = None,
    ):
        """Connect to LOCAL mode with specified provider/model.

        This is a wrapper around _connect_byok_mode() that ensures
        local providers are properly identified. Local providers are
        already handled in _connect_byok_mode() via ProviderCategory.LOCAL.
        """
        # HuggingFace cached models need a local runtime (e.g., MLX/TGI), not HF Inference API
        if provider == "huggingface-local":
            model_lower = model.lower()
            if "mlx" in model_lower or model_lower.startswith("mlx-community/"):
                log.add_info("Routing cached MLX model to MLX local provider.")
                provider = "mlx"
            else:
                log.add_error(
                    "HuggingFace cached models require a local runtime (mlx/tgi/vllm/sglang)."
                )
                log.add_info("Use: :connect local <provider> <model>")
                return

        # MLX, DwarfStar, and llama.cpp serve exactly one model per process and are NOT
        # always-on background apps like Ollama or LM Studio. Connecting alone
        # would point at a dead endpoint, so if their server is not already up
        # ask before launching a managed server. Note the provider id
        # "llamacpp" maps to the server-manager engine "llama.cpp".
        engine_for_provider = {"mlx": "mlx", "ds4": "ds4", "llamacpp": "llama.cpp"}
        if provider in engine_for_provider and model:
            engine = engine_for_provider[provider]
            try:
                from superqode.local.servers import get_manager

                running = bool(get_manager().status(engine).get("running"))
            except Exception:
                running = False
            if not running:
                self._prompt_local_connect_start(provider, engine, model, log)
                return

        # Local providers use the same connection mechanism as BYOK
        # but are identified by ProviderCategory.LOCAL
        if session_id is None:
            self._connect_byok_mode(provider, model, log)
        else:
            self._connect_byok_mode(provider, model, log, session_id=session_id)

    @staticmethod
    def _local_serve_command(engine: str, model: str) -> str:
        import shlex

        from superqode.local.laguna import LAGUNA_SAFE_CONTEXT, is_laguna_model

        command = f":local serve {engine} --model {shlex.quote(model)}"
        if is_laguna_model(model):
            command += f" --ctx {LAGUNA_SAFE_CONTEXT}"
            if engine == "ds4":
                command += " --build"
        return command

    @staticmethod
    def _native_local_server_command(
        engine: str,
        *,
        model: str = "",
        host: str | None = None,
        port: int | None = None,
        ctx: int | None = None,
    ) -> str:
        """Native command users can run outside SuperQode."""
        import shlex
        import sys

        from superqode.local.servers import (
            DS4_DEFAULT_CTX,
            DS4_DEFAULT_KV_DIR,
            DS4_DEFAULT_KV_DISK_MB,
            SPECS,
        )

        spec = SPECS[engine]
        host = host or spec.default_host
        port = port or spec.default_port
        q = shlex.quote
        from superqode.local.laguna import is_laguna_model, resolve_laguna_gguf

        if is_laguna_model(model):
            resolved_laguna = resolve_laguna_gguf(model)
            if resolved_laguna is not None:
                model = str(resolved_laguna)

        if engine == "ollama":
            env = [f"OLLAMA_HOST={host}:{port}"]
            # Ollama recommends at least 64K for coding and agent workloads.
            env.append(f"OLLAMA_CONTEXT_LENGTH={ctx or 64000}")
            return " ".join([*env, "ollama", "serve"])

        if engine == "lmstudio":
            cmd = ["lms", "server", "start", "--port", str(port)]
            if host not in ("127.0.0.1", "localhost"):
                cmd += ["--bind", host]
            return shlex.join(cmd)

        if engine == "mlx":
            cmd = [
                sys.executable,
                "-m",
                "mlx_lm.server",
                "--model",
                model or "<model-id>",
                "--host",
                host,
                "--port",
                str(port),
            ]
            return shlex.join(cmd)

        if engine == "ds4":
            cmd = [
                "ds4-server",
            ]
            if model:
                cmd += ["-m", model]
            cmd += [
                "--host",
                host,
                "--port",
                str(port),
                "--ctx",
                # Current DS4 agent-client guidance uses 100K. The managed
                # fallback remains conservative at DS4_DEFAULT_CTX.
                str(ctx or 100000),
                "--kv-disk-dir",
                str(DS4_DEFAULT_KV_DIR),
                "--kv-disk-space-mb",
                str(DS4_DEFAULT_KV_DISK_MB),
            ]
            return shlex.join(cmd)

        if engine == "llama.cpp":
            from superqode.local.laguna import LAGUNA_MODEL_ID

            cmd = [
                "llama-server",
                "-m",
                model or "/path/to/model.gguf",
                "--host",
                host,
                "--port",
                str(port),
            ]
            if ctx:
                cmd += ["-c", str(ctx)]
            if is_laguna_model(model):
                cmd += ["--jinja", "--reasoning-preserve", "--alias", LAGUNA_MODEL_ID]
            return shlex.join(cmd)

        return q(f":local serve {engine}")

    @staticmethod
    def _local_server_docs_url(engine: str) -> str:
        """Return the upstream server guide used for the displayed command."""
        return {
            "ollama": "https://docs.ollama.com/context-length",
            "lmstudio": "https://lmstudio.ai/docs/developer/core/server",
            "mlx": "https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md",
            "ds4": "https://github.com/antirez/ds4#server",
            "llama.cpp": "https://github.com/ggml-org/llama.cpp/tree/master/tools/server",
            "vllm": "https://docs.vllm.ai/en/stable/serving/openai_compatible_server/",
            "sglang": (
                "https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/"
                "server_arguments.md"
            ),
            "tgi": "https://huggingface.co/docs/text-generation-inference/basic_tutorials/using_cli",
        }.get(engine, "")

    @staticmethod
    def _advanced_local_server_command(provider: str) -> str:
        """Vendor-documented manual start template for externally managed servers."""
        return {
            "vllm": "vllm serve <model-id-or-path> --host 127.0.0.1 --port 8000",
            "sglang": (
                "python -m sglang.launch_server --model-path <model-id-or-path> "
                "--host 127.0.0.1 --port 30000"
            ),
            "tgi": (
                "text-generation-launcher --model-id <model-id-or-path> "
                "--hostname 127.0.0.1 --port 8080"
            ),
        }.get(provider, "")

    def _prompt_local_connect_start(
        self, provider: str, engine: str, model: str, log: ConversationLog
    ) -> None:
        """Ask before starting a one-model local server during connect."""
        from pathlib import Path as _Path

        label = _Path(model).name if engine == "llama.cpp" else model
        command = self._local_serve_command(engine, model)
        from superqode.local.laguna import LAGUNA_SAFE_CONTEXT, is_laguna_model

        laguna = is_laguna_model(model)
        native_command = self._native_local_server_command(
            engine,
            model=model,
            ctx=LAGUNA_SAFE_CONTEXT if laguna else None,
        )
        self._awaiting_local_connect_start = {
            "provider": provider,
            "engine": engine,
            "model": model,
            "command": command,
            "native_command": native_command,
        }
        self._awaiting_local_model = False

        t = Text()
        t.append("\n  🟡 ", style=THEME["warning"])
        t.append(f"{engine} is not running", style=f"bold {THEME['text']}")
        t.append(f" for {label}\n", style=THEME["cyan"])
        t.append(
            "  Recommended: start the server yourself with the native command:\n",
            style=THEME["muted"],
        )
        t.append("      ", style="")
        t.append(native_command, style=THEME["cyan"])
        t.append("\n", style="")
        docs_url = self._local_server_docs_url(engine)
        if docs_url:
            t.append("      Vendor guide: ", style=THEME["muted"])
            t.append(f"{docs_url}\n", style=THEME["cyan"])
        t.append(
            "      Edit the model, port, or context if your setup needs it.\n", style=THEME["dim"]
        )
        t.append(
            "      If a separate terminal is impractical, managed fallback: ",
            style=THEME["muted"],
        )
        t.append(command, style=THEME["cyan"])
        t.append("\n", style="")
        t.append("  SuperQode can also help by starting a managed server.\n", style=THEME["muted"])
        t.append("  Managed start runs in the background, writes logs under ", style=THEME["muted"])
        t.append("~/.superqode/servers/", style=THEME["cyan"])
        t.append(", and can be stopped with ", style=THEME["muted"])
        t.append(f":local stop {engine}", style=THEME["success"])
        t.append(".\n", style=THEME["muted"])
        t.append("\n  Press ", style=THEME["muted"])
        t.append("Enter", style=f"bold {THEME['success']}")
        t.append(" if you want SuperQode to start it for you, ", style=THEME["muted"])
        t.append("'n'", style=THEME["warning"])
        t.append(" to skip, or type ", style=THEME["muted"])
        t.append("manual", style=THEME["cyan"])
        t.append(" to show the command again.\n", style=THEME["muted"])
        if engine == "mlx":
            t.append(
                "  MLX will not download missing Hugging Face weights unless you explicitly use --allow-download.\n",
                style=THEME["dim"],
            )
        if laguna:
            from superqode.local.laguna import resolve_laguna_gguf

            selected_gguf = resolve_laguna_gguf(model)
            selected_location = str(selected_gguf or model)
            t.append(
                f"  Laguna GGUF: {selected_location}\n  Run only one local engine at a time.\n",
                style=THEME["dim"],
            )
        log.write(t)
        self._pin_local_prompt_to_input(
            f"Start {engine} yourself, or press Enter for SuperQode managed start",
            log,
            notify=f"{engine} is stopped. Start it yourself, or press Enter for help.",
        )

    def _handle_local_connect_start_input(self, text: str, log: ConversationLog) -> bool:
        pending = getattr(self, "_awaiting_local_connect_start", None)
        if not pending:
            return False

        choice = text.strip().lower()
        command = pending["command"]
        engine = pending["engine"]
        provider = pending["provider"]
        model = pending["model"]

        if choice in ("n", "no", "skip", "cancel", "q"):
            self._awaiting_local_connect_start = None
            self._reset_input_placeholder()
            t = Text()
            t.append("\n  ⏭  ", style=THEME["warning"])
            t.append(f"Left {engine} stopped.", style=f"bold {THEME['text']}")
            t.append(" Start it later with: ", style=THEME["muted"])
            t.append(f"{command}\n", style=THEME["cyan"])
            log.write(t)
            self._show_local_provider_picker(log, clear_log=False)
            return True

        if choice in ("manual", "command", "cmd"):
            self._awaiting_local_connect_start = None
            self._reset_input_placeholder()
            native_command = pending.get("native_command", command)
            log.add_system(f"Native command: {native_command}")
            log.add_system(f"SuperQode managed fallback: {command}")
            self._show_local_provider_picker(log, clear_log=False)
            return True

        if choice not in ("", "y", "yes", "start", "ok"):
            log.add_error(
                "Start it yourself with the shown command, press Enter for SuperQode help, "
                "type 'manual' to repeat the command, or 'n' to skip."
            )
            self._pin_local_prompt_to_input(
                f"Start {engine} yourself, or press Enter for SuperQode managed start",
                log,
            )
            return True

        self._awaiting_local_connect_start = None
        self._reset_input_placeholder()
        self.run_worker(self._start_local_then_connect(provider, engine, model, log))
        return True

    async def _start_local_then_connect(
        self, provider: str, engine: str, model: str, log: ConversationLog
    ):
        """Launch a one-model local server (MLX/DwarfStar/llama.cpp), then connect to it.

        ``model`` is an HF id for MLX, a DwarfStar model id/path, or a GGUF
        path/alias for llama.cpp.
        """
        import asyncio
        from pathlib import Path as _Path

        from superqode.local.laguna import (
            LAGUNA_DS4_REF,
            LAGUNA_MODEL_ID,
            LAGUNA_SAFE_CONTEXT,
            is_laguna_model,
        )
        from superqode.local.servers import ServerError, ds4_build, get_manager

        label = _Path(model).name if engine == "llama.cpp" else model
        laguna = is_laguna_model(model)
        t0 = Text()
        t0.append("\n  ⏳ ", style=THEME["warning"])
        t0.append(f"Starting {engine} server", style=f"bold {THEME['text']}")
        t0.append(f" with {label}", style=THEME["cyan"])
        t0.append(
            " — loading the model into memory, this can take a minute...\n", style=THEME["muted"]
        )
        self._call_ui(log.write, t0)

        self.is_busy = True
        try:
            manager = get_manager()
            if engine == "ds4" and (laguna or not manager.is_installed("ds4")):
                self._call_ui(
                    log.add_info,
                    "Checking and building DwarfStar's Laguna support branch before launch...",
                )
                await asyncio.to_thread(
                    ds4_build,
                    ref=LAGUNA_DS4_REF if laguna else None,
                )
            # Large models load slowly; give the server room before the
            # readiness probe gives up. Cached files only, so no download.
            handle = await asyncio.to_thread(
                manager.start,
                engine,
                model=model,
                ctx=LAGUNA_SAFE_CONTEXT if laguna else None,
                timeout=300.0,
            )
        except ServerError as exc:
            self._call_ui(log.add_error, str(exc))
            self._call_ui(
                log.add_system,
                f"Start it manually with: superqode local serve {engine} --model {model}",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self._call_ui(log.add_error, f"Failed to start {engine}: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        verb = "Adopted running" if getattr(handle, "adopted", False) else "Started"
        t.append("  ● ", style=f"bold {THEME['success']}")
        t.append(f"{verb} {engine}", style=f"bold {THEME['text']}")
        t.append(f"  {handle.base_url}\n", style=THEME["cyan"])
        self._call_ui(log.write, t)

        # Laguna is given a stable alias by the managed llama.cpp command.
        # Other llama.cpp models use the GGUF basename; MLX and DS4 retain
        # their selected model id.
        connect_model = (
            LAGUNA_MODEL_ID if laguna else (_Path(model).name if engine == "llama.cpp" else model)
        )
        self._call_ui(self._connect_byok_mode, provider, connect_model, log)

    def _show_local_provider_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show interactive local provider picker with discovery.

        Args:
            log: The conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        # CRITICAL: Force complete state reset - we MUST show provider picker, not models
        # Clear ALL local-related state to prevent any auto-selection
        self._awaiting_local_provider = True
        self._awaiting_local_model = False  # MUST be False - we're selecting provider, not model
        # Clear any BYOK selection state so numeric input routes to local picker
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False
        self._just_showed_byok_picker = False

        # Delete local selection state (but keep _local_provider_list - we'll set it later)
        for attr in ["_local_selected_provider", "_local_model_list", "_local_cached_models"]:
            if hasattr(self, attr):
                delattr(self, attr)

        # Reset indices only on a fresh show. Navigation redraws pass
        # clear_log=False and must preserve the highlighted provider, otherwise
        # arrow keys move the index and it's immediately reset back to 0 here.
        if clear_log:
            self._local_highlighted_provider_index = 0
            if hasattr(self, "_local_highlighted_model_index"):
                self._local_highlighted_model_index = 0

        from superqode.providers.registry import get_local_providers

        # Get local providers from registry FIRST
        local_providers = get_local_providers()

        # Filter out unsupported providers from TUI display
        # (they remain in registry for backward compatibility)
        unsupported_local_providers = {"ollama-cloud"}
        local_providers = {
            pid: pdef
            for pid, pdef in local_providers.items()
            if pid not in unsupported_local_providers
        }

        # huggingface-local removed: downloaded HF weights aren't directly
        # runnable — they need a runtime (Ollama/mlx_lm.server/vLLM/TGI) to
        # serve them. Use `superqode models download` then connect to that
        # runtime. (Filtered above via the registry no longer listing it.)

        t = Text()
        t.append(f"  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Providers\n", style=f"bold {THEME['text']}")
        t.append(
            "  Select a local/self-hosted runtime. No API key required.\n\n", style=THEME["muted"]
        )
        t.append("  Local Model Lab\n", style=f"bold {THEME['text']}")
        t.append("  Start with ", style=THEME["muted"])
        t.append(":chat on", style=f"bold {THEME['cyan']}")
        t.append(
            " to sanity-check a Local/BYOK model with no repo context or tools.\n",
            style=THEME["muted"],
        )
        t.append("  Switch to ", style=THEME["muted"])
        t.append(":build", style=f"bold {THEME['cyan']}")
        t.append(" when you want the repo-aware coding harness and tools.\n", style=THEME["muted"])
        t.append("  Use ", style=THEME["muted"])
        t.append(":plan on", style=f"bold {THEME['cyan']}")
        t.append(
            " to reason first before any edits or native tool execution.\n", style=THEME["muted"]
        )
        t.append("  Toggle modes anytime with ", style=THEME["muted"])
        t.append(":mode", style=f"bold {THEME['cyan']}")
        t.append(" (Chat / Build / Plan).\n", style=THEME["muted"])
        t.append("  Explore: ", style=THEME["dim"])
        t.append(":local doctor", style=THEME["cyan"])
        t.append(" · ", style=THEME["dim"])
        t.append(":local setup", style=THEME["cyan"])
        t.append(" · ", style=THEME["dim"])
        t.append(":local build", style=THEME["cyan"])
        t.append(" · ", style=THEME["dim"])
        t.append(":local optimize", style=THEME["cyan"])
        t.append(" · ", style=THEME["dim"])
        t.append(":local labs", style=THEME["cyan"])
        t.append("\n\n", style="")
        t.append(
            "  Start and supervise local model servers in their own terminal when possible.\n",
            style=f"bold {THEME['text']}",
        )
        t.append(
            "  SuperQode connects to your server; managed startup is a convenience fallback.\n\n",
            style=THEME["muted"],
        )

        if not local_providers:
            t.append("  ⚠️  No local providers configured\n", style=THEME["warning"])
            t.append(
                "  Local providers include: ds4, ollama, lmstudio, mlx, vllm, etc.\n",
                style=THEME["dim"],
            )
            if clear_log:
                log.clear()
            log.write(t)
            return

        # Sort providers: prioritize main local coding flows first.
        priority_order = ["ds4", "ollama", "mlx", "lmstudio", "vllm", "sglang"]

        def sort_key(item):
            provider_id, _ = item
            if provider_id in priority_order:
                return (0, priority_order.index(provider_id))
            return (1, provider_id)

        # Show local providers with highlighting
        highlighted_idx = getattr(self, "_local_highlighted_provider_index", 0)
        local_providers_list = sorted(local_providers.items(), key=sort_key)

        # Debug: Ensure all providers are included
        if not local_providers_list:
            t.append("  ⚠️  No local providers found in registry\n", style=THEME["warning"])
            if clear_log:
                log.clear()
            log.write(t)
            return

        provider_count = len(local_providers_list)
        t.append(f"  Available ({provider_count})\n", style=f"bold {THEME['text']}")

        # Provider-specific emojis
        provider_emojis = {
            "ds4": "◆",
            "ollama": "🐼",  # Panda
            "lmstudio": "🎨",  # Paint palette (GUI application)
            "mlx": "🍏",  # Green Apple (Apple Silicon)
            "vllm": "🚀",  # Rocket (high performance)
            "sglang": "🪝",  # Hook
            "tgi": "📚",  # Books
            "huggingface": "🤗",  # HuggingFace signature emoji
            "openai-compatible": "🔌",  # Plug (generic connection)
        }

        for idx, (provider_id, provider_def) in enumerate(local_providers_list, 1):
            status_icon = provider_emojis.get(provider_id, "🟢")
            labels = ["local"]
            if provider_id == "ds4":
                labels.extend(["recommended", "tools", "1M ctx"])
            elif provider_id in ("ollama", "mlx", "lmstudio"):
                labels.extend(["popular", "tools"])
            elif provider_id in ("vllm", "sglang", "tgi"):
                labels.extend(["server", "advanced"])

            is_highlighted = (idx - 1) == highlighted_idx
            marker = "▶ " if is_highlighted else "  "
            name_style = f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['cyan']}"
            num_style = (
                self._picker_link_style(f"bold {THEME['success']}", idx)
                if is_highlighted
                else self._picker_link_style(THEME["dim"], idx)
            )
            t.append(f"  {marker}", style=f"bold {THEME['success']}")
            t.append(f"[{idx}] ", style=num_style)
            t.append(f"{status_icon} ", style=THEME["success"])
            t.append(f"{provider_def.name}", style=name_style)
            if provider_id in ("vllm", "sglang"):
                t.append(" [EXPERIMENTAL]", style=f"bold {THEME['warning']}")
            t.append(f" ({provider_id})", style=THEME["muted"])
            t.append("  ", style=THEME["dim"])
            t.append(" • ".join(labels), style=THEME["dim"])
            t.append("\n", style="")

        t.append("\n  Type a number or use ", style=THEME["muted"])
        t.append("↑↓ Enter", style=f"bold {THEME['cyan']}")
        t.append(". Direct connect: ", style=THEME["muted"])
        t.append(f":connect local <provider>/<model>\n", style=THEME["cyan"])
        t.append(f"  Example: ", style=THEME["dim"])
        t.append(f":connect local ds4/deepseek-v4-flash\n", style=THEME["cyan"])

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker
        else:
            # Update during navigation - clear and write but preserve scroll position better
            # by not calling scroll_home which resets to top
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            # The scroll will be adjusted by _scroll_to_highlighted_item if needed
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker

        # Set up selection handler for local providers
        # CRITICAL: Always set these flags to ensure provider picker is shown, NOT model selection
        # This MUST happen AFTER we write to log, to prevent any race conditions
        self._awaiting_local_provider = True
        self._awaiting_local_model = False  # Make sure we're NOT in model selection mode
        self._local_provider_list = local_providers_list  # Use sorted list
        # Preserve current highlight if already set, otherwise start with first
        if not hasattr(self, "_local_highlighted_provider_index"):
            self._local_highlighted_provider_index = 0
        # CRITICAL: Ensure NO provider is selected - we must show the picker
        if hasattr(self, "_local_selected_provider"):
            delattr(self, "_local_selected_provider")
        if hasattr(self, "_local_model_list"):
            delattr(self, "_local_model_list")
        if hasattr(self, "_local_cached_models"):
            delattr(self, "_local_cached_models")

        # CRITICAL: Set flag to prevent auto-selection when picker first appears
        # This prevents empty input from immediately selecting the first provider
        self._just_showed_local_picker = True
        # Clear the flag after a delay to allow normal selection
        self.set_timer(0.5, lambda: setattr(self, "_just_showed_local_picker", False))

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    async def _show_local_provider_models(self, provider_id: str, log: ConversationLog):
        """Show models for a local provider by discovering them."""
        import asyncio

        from superqode.providers.registry import PROVIDERS
        from superqode.providers.local import (
            DS4Client,
            OllamaClient,
            LMStudioClient,
            VLLMClient,
            SGLangClient,
            MLXClient,
            TGIClient,
            estimate_tool_support,
        )

        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            log.add_error(f"Unknown provider: {provider_id}")
            return

        # Ensure local model selection is active, and BYOK selection is inactive
        self._awaiting_local_provider = False
        self._awaiting_local_model = True
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False
        # Reset any stale inline prompts from a previous provider.
        self._awaiting_local_server_start = None
        self._awaiting_local_dep_install = None

        # Show experimental warning for vLLM and SGLang
        if provider_id in ("vllm", "sglang"):
            t = Text()
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append(f"Experimental Provider Warning\n\n", style=f"bold {THEME['warning']}")
            t.append(f"  {provider_def.name} support is ", style=THEME["text"])
            t.append(f"EXPERIMENTAL", style=f"bold {THEME['warning']}")
            t.append(f". Features may be unstable and behavior may change.\n", style=THEME["text"])
            t.append(f"  Please report any issues you encounter.\n", style=THEME["dim"])
            log.write(t)

        log.add_info(f"Discovering models from {provider_def.name}...")

        # Special handling for HuggingFace (show locally cached models)
        if provider_id == "huggingface-local":
            from superqode.providers.huggingface import discover_cached_models

            cached = discover_cached_models()
            cached_models = [m["id"] for m in cached]

            # Display models
            t = Text()
            t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
            t.append(f"  {len(cached_models)} locally cached model(s)\n\n", style=THEME["dim"])

            # Store model list for selection
            self._local_selected_provider = provider_id
            self._local_model_list = cached_models
            self._local_cached_models = cached_models
            self._awaiting_local_model = True
            self._awaiting_local_provider = False

            highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

            if cached_models:
                for idx, model_id in enumerate(cached_models, 1):
                    is_highlighted = (idx - 1) == highlighted_idx

                    if is_highlighted:
                        t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                        t.append(
                            f"[{idx:2}] ",
                            style=self._picker_link_style(f"bold {THEME['success']}", idx),
                        )
                    else:
                        t.append(
                            f"    [{idx:2}] ",
                            style=self._picker_link_style(THEME["dim"], idx),
                        )

                    name_style = (
                        f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
                    )
                    t.append(f"{model_id}", style=name_style)
                    if is_highlighted:
                        t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
                    t.append(f"\n", style="")
            else:
                t.append(f"  ○ No local HuggingFace models found\n\n", style=THEME["muted"])

            t.append(f"  💡 ", style=THEME["muted"])
            t.append(f"Select a model number or name\n", style=THEME["text"])
            t.append(f"  Use ", style=THEME["muted"])
            t.append(f":hf search <query>", style=THEME["cyan"])
            t.append(f" to find and download models\n", style=THEME["muted"])

            log.write(t)
            return

        # llama.cpp (provider id "llamacpp") has no dedicated client class. Its
        # server (llama-server) is OpenAI-compatible and serves one GGUF model
        # the user launches themselves, so we list straight from its endpoint
        # and connect. This avoids the old "not supported" dead-end.
        if provider_id in ("llamacpp", "openai-compatible"):
            await self._show_openai_compatible_models(provider_id, log)
            return

        # Map provider ID to client class
        client_map = {
            "ds4": DS4Client,
            "ollama": OllamaClient,
            "lmstudio": LMStudioClient,
            "vllm": VLLMClient,
            "sglang": SGLangClient,
            "mlx": MLXClient,
            "tgi": TGIClient,
        }

        client_class = client_map.get(provider_id)
        if not client_class:
            log.add_error(f"Local provider '{provider_id}' is not yet supported")
            # Don't dead-end: hand control back to the provider picker.
            self._show_local_provider_picker(log)
            return

        # Create client and check availability
        client = client_class()
        server_running = await client.is_available()

        # DwarfStar normally has a legacy default model, so its generic stopped
        # state offers an immediate start. When the shared Laguna GGUF exists,
        # let the user select it first so the managed launch includes ``-m``.
        if provider_id == "ds4" and not server_running:
            from superqode.local.laguna import (
                LAGUNA_CONTEXT_WINDOW,
                is_laguna_model,
            )
            from superqode.local.servers import discover_gguf_models
            from superqode.providers.local.base import LocalModel

            discovered_ggufs = await asyncio.to_thread(discover_gguf_models)
            laguna_entry = next(
                (item for item in discovered_ggufs if is_laguna_model(item["path"])),
                None,
            )
            if laguna_entry is not None:
                laguna_gguf = Path(laguna_entry["path"])
                laguna_model = LocalModel(
                    id=str(laguna_gguf),
                    name="Poolside Laguna S 2.1",
                    size_bytes=laguna_gguf.stat().st_size,
                    quantization="Q4_K_M",
                    context_window=LAGUNA_CONTEXT_WINDOW,
                    parameter_count="118B-A8B",
                    family="laguna",
                    running=False,
                )
                self._local_selected_provider = provider_id
                self._local_model_list = [str(laguna_gguf)]
                self._local_cached_models = [laguna_model]
                self._awaiting_local_model = True
                self._awaiting_local_provider = False
                self._local_highlighted_model_index = 0

                t = Text()
                t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
                t.append("DwarfStar 4 Models\n", style=f"bold {THEME['text']}")
                t.append(
                    "  Shared Laguna GGUF found; select it to build/start DwarfStar.\n\n",
                    style=THEME["success"],
                )
                t.append("  ▶ [ 1] ", style=f"bold {THEME['success']}")
                t.append("○ Poolside Laguna S 2.1", style=f"bold {THEME['success']}")
                t.append("  recommended  ← SELECTED\n", style=THEME["success"])
                t.append(f"       {laguna_gguf}\n", style=THEME["muted"])
                t.append(
                    f"       {laguna_model.size_display} • Q4_K_M • "
                    f"{LAGUNA_CONTEXT_WINDOW:,} ctx • excellent tools\n\n",
                    style=THEME["dim"],
                )
                t.append(
                    "  Press Enter or type 1. SuperQode will confirm before launching.\n",
                    style=THEME["muted"],
                )
                t.append(
                    "  Alternative runtime: choose llama.cpp from the provider picker.\n",
                    style=THEME["dim"],
                )
                log.clear()
                log.write(t)
                self.set_timer(0.05, self._ensure_input_focus)
                return

        # For DS4, MLX and LM Studio, try to discover models even if server check fails
        # Sometimes the server is running but the availability check fails
        if provider_id in ("ds4", "mlx", "lmstudio") and not server_running:
            # Try anyway - the list_models() call will handle errors gracefully
            pass

        # State-aware setup guidance (running / installed-but-stopped / missing).
        # Driven by ServerManager so the TUI matches `superqode local serve`.
        # When it offers an inline start prompt, stop here and wait for the
        # user's decision; models are listed after the server comes up.
        if provider_id in ("ollama", "lmstudio", "mlx", "ds4"):
            if await self._render_local_server_state(provider_id, log):
                return

        # Get models - try discovery even if server check failed
        try:
            models = await client.list_models()
        except Exception as e:
            # Log error but continue - show helpful message below
            models = []

            error_msg = str(e)
            if provider_id == "mlx":
                log.add_info(f"MLX model discovery failed: {error_msg}")
                log.add_info("Make sure MLX server is running with a model loaded")
            elif provider_id == "lmstudio":
                log.add_info(f"LM Studio model discovery failed: {error_msg}")
                log.add_info("Make sure LM Studio server is running with a model loaded")

        # Filter out embedding / reranker models everywhere: they are not chat
        # models and only confuse the picker (esp. LM Studio, which lists any
        # loaded embedder on /v1/models).
        from superqode.providers.local.base import is_embedding_model

        filtered_embeddings = [m for m in models if is_embedding_model(m.id, m.name)]
        models = [m for m in models if not is_embedding_model(m.id, m.name)]

        if filtered_embeddings and not models and provider_id == "lmstudio":
            log.add_info(
                "Only embedding models are loaded in LM Studio. Load a chat model: "
                "lms load <model-key> --context-length <ctx>   (or pick one in the LM Studio app)"
            )

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
        t.append(f"  {len(models)} available", style=THEME["dim"])
        if provider_id == "ds4":
            t.append("  •  recommended for local coding", style=THEME["success"])
        t.append("\n", style=THEME["dim"])
        t.append(
            "  Type a number or use ↑↓ Enter. Labels: tools, context, size.\n\n",
            style=THEME["muted"],
        )

        if models:
            idx = 1
            model_list = []
            highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

            for model in models:
                is_highlighted = (idx - 1) == highlighted_idx

                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))

                # Running status
                if model.running:
                    t.append("● ", style=THEME["success"])
                else:
                    t.append("○ ", style=THEME["dim"])

                name_style = (
                    f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
                )
                t.append(f"{model.name}", style=name_style)
                if provider_id == "ds4" or "deepseek" in model.id.lower():
                    t.append("  recommended", style=THEME["success"])
                if is_highlighted:
                    t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
                t.append(f"\n", style="")
                t.append(f"       ", style="")
                id_style = f"bold {THEME['success']}" if is_highlighted else THEME["muted"]
                t.append(f"{model.id}\n", style=id_style)

                # Model details
                details = []
                if model.size_display != "unknown":
                    details.append(model.size_display)
                if model.quantization != "unknown":
                    details.append(model.quantization)
                if model.context_window > 0:
                    details.append(f"{model.context_window:,} ctx")

                if details:
                    t.append(f"       ", style="")
                    t.append(" • ".join(details), style=THEME["dim"])
                    t.append("\n", style="")

                tool_level = estimate_tool_support(model)
                label_parts = []
                if tool_level == "excellent":
                    label_parts.append(("excellent tools", THEME["success"]))
                elif tool_level == "good":
                    label_parts.append(("good tools", THEME["cyan"]))
                elif tool_level == "none":
                    label_parts.append(("no tools", THEME["dim"]))

                if model.supports_vision:
                    label_parts.append(("vision", THEME["cyan"]))

                if label_parts:
                    t.append(f"       ", style="")
                    for part_idx, (label, style) in enumerate(label_parts):
                        if part_idx:
                            t.append(" • ", style=THEME["dim"])
                        t.append(label, style=style)
                    t.append("\n", style="")

                t.append("\n", style="")
                model_list.append(model.id)
                idx += 1
        else:
            t.append(f"  ○ No models found\n\n", style=THEME["muted"])
            if provider_id == "ollama":
                t.append(f"  💡 Pull a model with:\n", style=THEME["muted"])
                t.append(f"    ollama pull qwen3.6:35b-a3b\n", style=THEME["cyan"])
                t.append(f"    # or browse trusted labs with :local labs\n", style=THEME["dim"])
            elif provider_id == "mlx":
                t.append(
                    f"  💡 MLX only lists models reported by a running server.\n",
                    style=THEME["muted"],
                )
                t.append(
                    f"     Start MLX with the model you want, then reconnect:\n",
                    style=THEME["muted"],
                )
                t.append(
                    f"    mlx_lm.server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit\n",
                    style=THEME["cyan"],
                )
                t.append(
                    f"    # Edit the model id/port/context for your setup.\n",
                    style=THEME["dim"],
                )
                if not server_running:
                    t.append(
                        f"\n  ⚠️  MLX server is not running. Start it first!\n",
                        style=THEME["warning"],
                    )
            elif provider_id == "lmstudio":
                t.append(f"  💡 LM Studio requires:\n", style=THEME["muted"])
                t.append(f"    1. Start LM Studio application\n", style=THEME["cyan"])
                t.append(f"    2. Download and load a model\n", style=THEME["cyan"])
                t.append(f"    3. Start the local server (Local Server tab)\n", style=THEME["cyan"])
                t.append("       or: lms server start --port 1234\n", style=THEME["cyan"])
                if not server_running:
                    t.append(
                        f"\n  ⚠️  LM Studio server is not running. Start the server in LM Studio first!\n",
                        style=THEME["warning"],
                    )
            elif provider_id in ("vllm", "sglang", "tgi"):
                command = self._advanced_local_server_command(provider_id)
                docs_url = self._local_server_docs_url(provider_id)
                t.append(
                    "  💡 Start and supervise this server in a separate terminal:\n",
                    style=THEME["muted"],
                )
                t.append(f"    {command}\n", style=THEME["cyan"])
                t.append(
                    "    Replace <model-id-or-path> and tune GPU/context settings for your machine.\n",
                    style=THEME["dim"],
                )
                t.append("    Vendor guide: ", style=THEME["muted"])
                t.append(f"{docs_url}\n", style=THEME["cyan"])
                t.append(
                    "    Stop it from that terminal with Ctrl+C, then reconnect here when restarted.\n",
                    style=THEME["dim"],
                )
            model_list = []

        if not model_list:
            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(f":connect {provider_id} <model>", style=THEME["success"])
            t.append(" to connect\n", style=THEME["muted"])

        log.clear()
        log.auto_scroll = False
        log.write(t)
        log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker

        # Store for selection
        self._local_model_list = model_list
        self._local_cached_models = models  # Cache full model objects for redraw
        self._local_selected_provider = provider_id
        self._awaiting_local_model = True
        # Preserve current highlight if already set, otherwise start with first
        if not hasattr(self, "_local_highlighted_model_index"):
            self._local_highlighted_model_index = 0

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _redraw_local_provider_models(self, log: ConversationLog):
        """Redraw the local provider models list with updated highlighting.

        This is a synchronous method used during navigation to update the
        display without re-fetching models from the provider.
        """
        from superqode.providers.registry import PROVIDERS
        from superqode.providers.local import estimate_tool_support

        provider_id = getattr(self, "_local_selected_provider", None)
        models = getattr(self, "_local_cached_models", [])
        model_list = getattr(self, "_local_model_list", [])

        if not provider_id:
            return

        # HuggingFace cached models are stored as plain IDs
        if provider_id == "huggingface-local":
            if not model_list:
                return
            provider_def = PROVIDERS.get(provider_id)
            if not provider_def:
                return

            t = Text()
            t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
            t.append(f"  {len(model_list)} locally cached model(s)\n\n", style=THEME["dim"])

            highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)
            for idx, model_id in enumerate(model_list, 1):
                is_highlighted = (idx - 1) == highlighted_idx
                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))

                name_style = (
                    f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
                )
                t.append(f"{model_id}", style=name_style)
                if is_highlighted:
                    t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
                t.append(f"\n", style="")

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append("Select a model number or name\n", style=THEME["text"])
            t.append(f"  Use ", style=THEME["muted"])
            t.append(f":hf search <query>", style=THEME["cyan"])
            t.append(f" to find and download models\n", style=THEME["muted"])

            log.auto_scroll = False
            log.clear()
            log.write(t)
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker
            return

        if not models:
            return

        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            return

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
        t.append(f"  {len(models)} model(s) available\n", style=THEME["dim"])
        t.append(f"  💡 ", style=THEME["muted"])
        t.append("Type number to select • Scroll with mouse to see more\n\n", style=THEME["muted"])

        highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

        for idx, model in enumerate(models, 1):
            # Entries can be rich LocalModel objects or plain id strings (e.g.
            # from OpenAI-compatible endpoints / the HF cache list). Coerce so
            # attribute access below never explodes on a str.
            if isinstance(model, str):
                from superqode.providers.local.base import LocalModel

                model = LocalModel(id=model, name=model.split("/")[-1] or model)

            is_highlighted = (idx - 1) == highlighted_idx

            if is_highlighted:
                t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                t.append(
                    f"[{idx:2}] ",
                    style=self._picker_link_style(f"bold {THEME['success']}", idx),
                )
            else:
                t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))

            # Running status
            if model.running:
                t.append("● ", style=THEME["success"])
            else:
                t.append("○ ", style=THEME["dim"])

            name_style = f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
            t.append(f"{model.name}", style=name_style)
            if is_highlighted:
                t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
            t.append(f"\n", style="")
            t.append(f"       ", style="")
            id_style = f"bold {THEME['success']}" if is_highlighted else THEME["muted"]
            t.append(f"{model.id}\n", style=id_style)

            # Model details
            details = []
            if model.size_display != "unknown":
                details.append(model.size_display)
            if model.quantization != "unknown":
                details.append(model.quantization)
            if model.context_window > 0:
                details.append(f"{model.context_window:,} ctx")

            if details:
                t.append(f"       ", style="")
                t.append(" • ".join(details), style=THEME["dim"])
                t.append("\n", style="")

            # Tool support
            tool_level = estimate_tool_support(model)
            if tool_level == "excellent":
                t.append(f"       ", style="")
                t.append("🔧🔧 Excellent tool support", style=THEME["success"])
                t.append("\n", style="")
            elif tool_level == "good":
                t.append(f"       ", style="")
                t.append("🔧 Good tool support", style=THEME["cyan"])
                t.append("\n", style="")
            elif tool_level == "none":
                t.append(f"       ", style="")
                t.append("No tool support", style=THEME["dim"])
                t.append("\n", style="")

            if model.supports_vision:
                t.append(f"       ", style="")
                t.append("👁️ Vision support", style=THEME["cyan"])
                t.append("\n", style="")

            t.append("\n", style="")

        if not model_list:
            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(f":connect {provider_id} <model>", style=THEME["success"])
            t.append(" to connect\n", style=THEME["muted"])

        log.clear()
        log.auto_scroll = False
        log.write(t)
        log.scroll_home(animate=False)
        log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker

    def _format_local_smoke_result(self, payload: dict) -> Text:
        """Render local provider smoke result for TUI."""
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Provider Check\n\n", style=f"bold {THEME['text']}")

        name = payload.get("name") or payload.get("provider") or "-"
        provider = payload.get("provider") or "-"
        t.append("  Provider     ", style=THEME["muted"])
        t.append(f"{name} ({provider})\n", style=f"bold {THEME['cyan']}")

        supported = bool(payload.get("supported"))
        support_style = THEME["success"] if supported else THEME["warning"]
        t.append("  Smoke client ", style=THEME["muted"])
        t.append(("available" if supported else "missing") + "\n", style=support_style)

        if payload.get("host"):
            t.append("  Host         ", style=THEME["muted"])
            t.append(f"{payload['host']}\n", style=THEME["text"])

        if not supported:
            if payload.get("setup_hint"):
                t.append("  Setup        ", style=THEME["muted"])
                t.append(f"{payload['setup_hint']}\n", style=THEME["text"])
            if payload.get("error"):
                t.append("  Error        ", style=THEME["muted"])
                t.append(f"{payload['error']}\n", style=THEME["error"])
            return t

        available = bool(payload.get("available"))
        t.append("  Server       ", style=THEME["muted"])
        t.append(
            "reachable\n" if available else "not reachable\n",
            style=THEME["success"] if available else THEME["warning"],
        )

        model = payload.get("model") or "-"
        t.append("  Model        ", style=THEME["muted"])
        t.append(f"{model}\n", style=f"bold {THEME['text']}")

        models = payload.get("models") or []
        running = payload.get("running_models") or []
        t.append("  Models       ", style=THEME["muted"])
        t.append(f"{len(models)} discovered", style=THEME["text"])
        if running:
            t.append(f"  ({len(running)} running)", style=THEME["success"])
        t.append("\n")

        tools = "yes" if payload.get("tool_support") else "no"
        t.append("  Tools        ", style=THEME["muted"])
        t.append(
            f"{tools}\n", style=THEME["success"] if payload.get("tool_support") else THEME["dim"]
        )
        tool_result = payload.get("tool_result") or {}
        if tool_result.get("notes"):
            t.append("  Tool notes   ", style=THEME["muted"])
            t.append(f"{tool_result['notes']}\n", style=THEME["dim"])
        if tool_result.get("error"):
            t.append("  Tool error   ", style=THEME["muted"])
            t.append(f"{tool_result['error']}\n", style=THEME["error"])

        if payload.get("completion_ran"):
            status = "ok" if payload.get("completion_ok") else "failed"
            t.append("  Completion   ", style=THEME["muted"])
            t.append(
                f"{status}\n",
                style=THEME["success"] if payload.get("completion_ok") else THEME["warning"],
            )
            if payload.get("response_preview"):
                t.append("  Response     ", style=THEME["muted"])
                t.append(f"{payload['response_preview']}\n", style=THEME["text"])

        if payload.get("error"):
            t.append("  Error        ", style=THEME["muted"])
            t.append(f"{payload['error']}\n", style=THEME["error"])
        elif not payload.get("completion_ran"):
            t.append("\n  Action: ", style=THEME["muted"])
            t.append(f":providers smoke {provider} --run", style=THEME["cyan"])
            t.append(" to run a real completion\n", style=THEME["muted"])

        return t

    def _local_cmd(self, args: str, log: ConversationLog):
        """Local Agentic Coding stack commands: doctor and packs."""
        sub = (args or "").strip().lower()
        if sub in ("", "doctor"):
            log.add_info("Running the Local Stack Doctor (hardware, engines, models)...")
            self.run_worker(self._run_local_doctor(log))
        elif sub == "packs":
            from superqode.local.packs import USER_PACKS_DIR, list_packs

            t = Text()
            t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append("Model Policy Packs\n\n", style=f"bold {THEME['text']}")
            for pack in list_packs():
                t.append(f"  {pack.name:<12}", style=THEME["cyan"])
                t.append(f"{pack.description}\n", style=THEME["text"])
                if pack.match:
                    t.append(f"  {'':<12}matches: {', '.join(pack.match)}\n", style=THEME["dim"])
            t.append(f"\n  Override or add packs in {USER_PACKS_DIR}\n", style=THEME["muted"])
            self._show_command_output(log, t)
        else:
            log.add_info("Usage: :local [doctor|packs]")

    async def _run_local_doctor(self, log: ConversationLog):
        """Run the Local Stack Doctor off the event loop and render its report."""
        import asyncio as _asyncio

        from superqode.local.doctor import render_report, run_doctor

        try:
            report = await _asyncio.to_thread(run_doctor)
        except Exception as exc:
            log.add_error(f"Local Stack Doctor failed: {exc}")
            return
        t = Text()
        t.append("\n")
        for line in render_report(report).splitlines():
            if line.startswith(("SuperQode", "Verdict", "Engines", "Recommended models")):
                t.append(f"  {line}\n", style=f"bold {THEME['text']}")
            elif line.startswith("="):
                t.append(f"  {line}\n", style=THEME["dim"])
            else:
                t.append(f"  {line}\n", style=THEME["text"])
        t.append("\n  Generate a tuned harness: ", style=THEME["muted"])
        t.append("superqode local doctor --generate harness.yaml\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    def _local_cmd(self, args: str, log: ConversationLog):
        """Handle :local command - Manage local LLM providers."""
        args = args.strip()
        parts = args.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if sub == "" or sub == "status":
            # :local - Show all local providers status
            self.run_worker(self._local_status(log))
        elif sub == "scan":
            # :local scan - Scan for running providers
            self.run_worker(self._local_scan(log))
        elif sub == "models":
            # :local models - List all local models
            self.run_worker(self._local_models(log))
        elif sub == "init":
            self.run_worker(self._local_init(subargs, log))
        elif sub == "setup":
            self.run_worker(self._local_setup(subargs, log))
        elif sub == "smoke":
            self.run_worker(self._local_smoke(subargs, log))
        elif sub == "labs":
            self.run_worker(self._local_labs(subargs, log))
        elif sub == "optimize":
            try:
                tokens = shlex.split(subargs or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :local optimize arguments: {exc}")
                return
            self.run_worker(
                self._superqode_cli_cmd(["local", "optimize", *tokens], log, "Local optimization")
            )
        elif sub == "airplane":
            try:
                tokens = shlex.split(subargs or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :local airplane arguments: {exc}")
                return
            if not tokens:
                log.add_info(
                    "Usage: :local airplane <doctor|prepare|index|smoke|models|health> [options]"
                )
                log.add_system(
                    "e.g. :local airplane prepare --repo . --model ollama/qwen3:8b --force"
                )
                return
            self.run_worker(
                self._superqode_cli_cmd(
                    ["local", "airplane", *tokens],
                    log,
                    "Airplane Mode",
                )
            )
        elif sub == "build":
            self.run_worker(self._local_build(subargs, log))
        elif sub == "migrate":
            self.run_worker(self._local_migrate(subargs, log))
        elif sub == "pack":
            parts2 = subargs.split(maxsplit=1)
            if parts2 and parts2[0].lower() == "init":
                self.run_worker(self._local_pack_init(parts2[1] if len(parts2) > 1 else "", log))
            else:
                log.add_info("Usage: :local pack init [name] [--model MODEL] [--dry-run]")
        elif sub == "search":
            if subargs.strip():
                self.run_worker(self._local_search(subargs.strip(), log))
            else:
                log.add_info("Usage: :local search <query>   (e.g. :local search qwen3-coder)")
        elif sub == "warm":
            self.run_worker(self._local_warm(subargs, log))
        elif sub == "test":
            # :local test <model> - Test tool calling
            if subargs:
                self.run_worker(self._local_test(subargs, log))
            else:
                log.add_info("Usage: :local test <model>")
        elif sub == "info":
            # :local info <model> - Show model info
            if subargs:
                self.run_worker(self._local_info(subargs, log))
            else:
                log.add_info("Usage: :local info <model>")
        elif sub == "recommend":
            # :local recommend - Show recommended coding models
            self._local_recommend(log)
        elif sub == "serve":
            # :local serve <engine> [--model X] [--port N] [--ctx N]
            if subargs:
                self.run_worker(self._local_serve(subargs, log))
            else:
                log.add_info(
                    "Usage: :local serve <ollama|lmstudio|mlx|ds4|llama.cpp> [--model X] [--port N] [--ctx N] [--host H]"
                )
                log.add_system(
                    "e.g. :local serve mlx --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --port 8090"
                )
                log.add_system(
                    "e.g. :local serve ds4 --ctx 32768   ·   long DS4: --ctx 100000   ·   Think Max: --ctx 393216"
                )
                log.add_system("Laguna: :local serve ds4 --model laguna-s-2.1 --ctx 32768")
                log.add_system("or: :local serve llama.cpp --model laguna-s-2.1 --ctx 32768")
        elif sub == "servers":
            # :local servers - Show managed/running server status
            self.run_worker(self._local_servers(log))
        elif sub == "stop":
            # :local stop <engine> - Stop a server SuperQode started
            if subargs:
                self.run_worker(self._local_stop(subargs.strip(), log))
            else:
                log.add_info("Usage: :local stop <ollama|lmstudio|mlx|ds4|llama.cpp>")
        else:
            try:
                tokens = shlex.split(args or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :local arguments: {exc}")
                return
            self._run_cli_passthrough(["local", *tokens], log, "Local command")

    @staticmethod
    def _parse_local_kv_args(subargs: str) -> dict:
        import shlex

        opts: dict = {"_pos": []}
        for tok in shlex.split(subargs or ""):
            if tok.startswith("--repo="):
                opts["repo"] = tok.split("=", 1)[1]
            elif tok == "--repo":
                opts["_expect"] = "repo"
            elif tok.startswith("--output="):
                opts["output"] = tok.split("=", 1)[1]
            elif tok == "--output":
                opts["_expect"] = "output"
            elif tok.startswith("--engine="):
                opts["engine"] = tok.split("=", 1)[1]
            elif tok == "--engine":
                opts["_expect"] = "engine"
            elif tok.startswith("--model="):
                opts["model"] = tok.split("=", 1)[1]
            elif tok == "--model":
                opts["_expect"] = "model"
            elif tok.startswith("--endpoint="):
                opts["endpoint"] = tok.split("=", 1)[1]
            elif tok == "--endpoint":
                opts["_expect"] = "endpoint"
            elif tok.startswith("--pack="):
                opts["pack"] = tok.split("=", 1)[1]
            elif tok == "--pack":
                opts["_expect"] = "pack"
            elif tok.startswith("--from-smoke="):
                opts["from_smoke"] = tok.split("=", 1)[1]
            elif tok == "--from-smoke":
                opts["_expect"] = "from_smoke"
            elif tok in ("--skip-smoke", "--no-smoke"):
                opts["skip_smoke"] = True
            elif tok in ("--yes", "-y"):
                opts["yes"] = True
            elif tok == "--dry-run":
                opts["dry_run"] = True
            elif tok == "--force":
                opts["force"] = True
            elif tok == "--write-pack":
                opts["write_pack"] = True
            elif tok == "--json":
                opts["json"] = True
            elif opts.get("_expect"):
                opts[opts.pop("_expect")] = tok
            else:
                opts["_pos"].append(tok)
        opts.pop("_expect", None)
        return opts

    async def _local_init(self, subargs: str, log: ConversationLog):
        """Run the MVP local setup path from the TUI."""
        import asyncio

        from superqode.local.doctor import generate_harness_yaml, render_report, run_doctor
        from superqode.local.smoke import render_smoke, run_smoke

        try:
            opts = self._parse_local_kv_args(subargs)
        except ValueError as exc:
            log.add_error(f"Could not parse :local init arguments: {exc}")
            return

        repo = Path(opts.get("repo") or ".")
        output = Path(opts.get("output") or "superqode.local.yaml")
        if output.exists() and not opts.get("yes"):
            log.add_error(f"{output} already exists. Use :local init --yes to overwrite.")
            return

        t0 = Text()
        t0.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t0.append("Local Coding Init\n\n", style=f"bold {THEME['text']}")
        t0.append(
            "  Detecting hardware, engines, trusted model routes, and repo shape...\n",
            style=THEME["muted"],
        )
        log.write(t0)

        self.is_busy = True
        try:
            report = await asyncio.to_thread(run_doctor, str(repo), include_guardrails=True)
            smoke = None
            if not opts.get("skip_smoke"):
                best = report.recommendation.best_model
                chosen_engine = opts.get("engine") or report.recommendation.engine or ""
                chosen_model = opts.get("model") or ""
                if not chosen_model and best is not None:
                    chosen_model = (
                        best.downloaded.bare_id if best.downloaded else best.pull.split()[-1]
                    )
                smoke = await asyncio.to_thread(
                    run_smoke,
                    engine=chosen_engine,
                    model=chosen_model,
                    repo_path=repo,
                )
            harness = generate_harness_yaml(
                report,
                name="local-coder",
                pack_override=opts.get("pack", ""),
            )
            await asyncio.to_thread(output.write_text, harness, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Local init failed: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Coding Init\n\n", style=f"bold {THEME['text']}")
        for line in render_report(report).splitlines():
            t.append(
                f"  {line}\n",
                style=f"bold {THEME['text']}"
                if line in {"Verdict", "Engines", "Recommended models"}
                or line.startswith("SuperQode")
                else THEME["text"],
            )
        if smoke is not None:
            t.append("\n")
            for line in render_smoke(smoke).splitlines():
                t.append(f"  {line}\n", style=THEME["text"])
        t.append("\n  Wrote local harness: ", style=THEME["muted"])
        t.append(f"{output}\n", style=f"bold {THEME['success']}")
        if opts.get("pack"):
            t.append("  Model pack: ", style=THEME["muted"])
            t.append(f"{opts['pack']}\n", style=f"bold {THEME['cyan']}")
        t.append("  Start coding with: ", style=THEME["muted"])
        t.append(f"superqode --harness {output}\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    async def _local_setup(self, subargs: str, log: ConversationLog):
        """Show the non-mutating local model setup guide from the TUI."""
        import asyncio

        from superqode.local.setup import build_local_setup_guide, render_local_setup_guide

        try:
            opts = self._parse_local_kv_args(subargs)
        except ValueError as exc:
            log.add_error(f"Could not parse :local setup arguments: {exc}")
            return
        query = " ".join(opts.get("_pos") or [])
        repo = Path(opts.get("repo") or ".")
        self.is_busy = True
        try:
            guide = await asyncio.to_thread(build_local_setup_guide, query, repo_path=repo)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Local setup guide failed: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        t.append("\n")
        for line in render_local_setup_guide(guide, tui_first=True).splitlines():
            style = f"bold {THEME['text']}" if line.startswith("SuperQode") else THEME["text"]
            if line.startswith(("1.", "2.", "3.", "4.", "5.", "6.")):
                style = f"bold {THEME['cyan']}"
            t.append(f"  {line}\n", style=style)
        self._show_command_output(log, t)

    async def _local_migrate(self, subargs: str, log: ConversationLog):
        """Show a non-mutating local migration plan from the TUI."""
        import asyncio

        from superqode.local.migrate import plan_local_migration, render_migration_report

        try:
            opts = self._parse_local_kv_args(subargs)
        except ValueError as exc:
            log.add_error(f"Could not parse :local migrate arguments: {exc}")
            return
        repo = Path(opts.get("repo") or ".")
        self.is_busy = True
        try:
            report = await asyncio.to_thread(
                plan_local_migration,
                repo,
                endpoint=opts.get("endpoint", ""),
                model=opts.get("model", ""),
            )
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Local migrate failed: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        t.append("\n")
        for line in render_migration_report(report).splitlines():
            style = f"bold {THEME['text']}" if line.startswith("SuperQode") else THEME["text"]
            t.append(f"  {line}\n", style=style)
        self._show_command_output(log, t)

    async def _local_pack_init(self, subargs: str, log: ConversationLog):
        """Create or preview a project-owned model policy pack from the TUI."""
        import asyncio

        from superqode.local.packs import draft_pack, render_pack_draft, write_pack_draft

        try:
            opts = self._parse_local_kv_args(subargs)
        except ValueError as exc:
            log.add_error(f"Could not parse :local pack init arguments: {exc}")
            return
        name = opts["_pos"][0] if opts.get("_pos") else ""
        output = opts.get("output")
        self.is_busy = True
        try:
            draft = await asyncio.to_thread(
                draft_pack,
                name=name,
                model=opts.get("model", ""),
                endpoint=opts.get("endpoint", ""),
                from_smoke=opts.get("from_smoke"),
            )
            if not opts.get("dry_run"):
                draft = await asyncio.to_thread(
                    write_pack_draft,
                    draft,
                    output=output,
                    force=bool(opts.get("force")),
                )
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Local pack init failed: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        t.append("\n")
        for line in render_pack_draft(draft).splitlines():
            style = f"bold {THEME['text']}" if line.startswith("SuperQode") else THEME["text"]
            t.append(f"  {line}\n", style=style)
        if opts.get("dry_run"):
            t.append(
                "\n  Dry run only; pass without --dry-run to write the pack.\n",
                style=THEME["muted"],
            )
        self._show_command_output(log, t)

    async def _local_build(self, subargs: str, log: ConversationLog):
        """Run the non-live local harness builder from the TUI."""
        import asyncio

        from superqode.local.build import build_local_harness, render_local_build_report

        try:
            opts = self._parse_local_kv_args(subargs)
        except ValueError as exc:
            log.add_error(f"Could not parse :local build arguments: {exc}")
            return
        self.is_busy = True
        try:
            report = await asyncio.to_thread(
                build_local_harness,
                repo_path=Path(opts.get("repo") or "."),
                model=opts.get("model", ""),
                endpoint=opts.get("endpoint", ""),
                pack=opts.get("pack", ""),
                output=Path(opts.get("output") or "superqode.local.yaml"),
                write_pack=bool(opts.get("write_pack")),
                force=bool(opts.get("force") or opts.get("yes")),
                dry_run=bool(opts.get("dry_run")),
            )
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Local build failed: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        t.append("\n")
        for line in render_local_build_report(report).splitlines():
            style = f"bold {THEME['text']}" if line.startswith("SuperQode") else THEME["text"]
            t.append(f"  {line}\n", style=style)
        self._show_command_output(log, t)

    async def _local_smoke(self, subargs: str, log: ConversationLog):
        """Run the non-destructive local coding readiness test from the TUI."""
        import asyncio

        from superqode.local.smoke import render_smoke, run_smoke

        try:
            opts = self._parse_local_kv_args(subargs)
        except ValueError as exc:
            log.add_error(f"Could not parse :local smoke arguments: {exc}")
            return
        repo = opts.get("repo") or "."
        log.add_info("Running local coding smoke test...")
        self.is_busy = True
        try:
            report = await asyncio.to_thread(
                run_smoke,
                engine=opts.get("engine", ""),
                endpoint=opts.get("endpoint", ""),
                model=opts.get("model", ""),
                repo_path=repo,
            )
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Local smoke failed: {exc}")
            return
        finally:
            self.is_busy = False

        t = Text()
        t.append("\n")
        for line in render_smoke(report).splitlines():
            t.append(f"  {line}\n", style=THEME["text"])
        self._show_command_output(log, t)

    async def _local_labs(self, subargs: str, log: ConversationLog):
        """Show trusted models.dev local labs in the TUI."""
        import asyncio

        from superqode.local.labs import list_curated_labs, list_lab_models

        lab = (subargs or "").strip().split()[0] if (subargs or "").strip() else ""
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        if not lab:
            t.append("Trusted Local Model Labs\n\n", style=f"bold {THEME['text']}")
            for item in list_curated_labs():
                t.append(f"  {item.id:<10}", style=f"bold {THEME['cyan']}")
                t.append(f"{item.name}\n", style=THEME["text"])
                t.append(f"    {item.description}\n", style=THEME["dim"])
            t.append("\n  Open one with: ", style=THEME["muted"])
            t.append(":local labs zhipuai\n", style=THEME["cyan"])
            self._show_command_output(log, t)
            return

        t.append(f"models.dev Lab: {lab}\n\n", style=f"bold {THEME['text']}")
        try:
            rows = await asyncio.to_thread(list_lab_models, lab)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not load models.dev Labs data: {exc}")
            return
        for row in rows[:10]:
            mark = "*" if row.recommended_for_local else "-"
            t.append(
                f"  {mark} ", style=THEME["success"] if row.recommended_for_local else THEME["dim"]
            )
            t.append(f"{row.id}", style=f"bold {THEME['text']}")
            traits = []
            if row.open_weights:
                traits.append("open")
            if row.supports_tools:
                traits.append("tools")
            if row.supports_reasoning:
                traits.append("reasoning")
            if row.context_window:
                traits.append(f"{row.context_window:,} ctx")
            if traits:
                t.append(f"  {' • '.join(traits)}", style=THEME["dim"])
            t.append("\n", style="")
            if row.recommended_for_local and row.install_hint:
                t.append(f"      install: {row.install_hint}\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    async def _local_search(self, query: str, log: ConversationLog):
        """Search the trusted catalog for a model + how to get it, in the TUI.

        Append ``--hub`` to also query Hugging Face live (trusted publishers).
        """
        import asyncio

        from superqode.local.hardware import detect_hardware
        from superqode.local.matrix import search_models

        want_hub = "--hub" in query.split()
        query = query.replace("--hub", "").strip()

        log.add_info(f"Searching trusted catalog for {query!r}...")
        try:
            hw = detect_hardware()
            tier = hw.tier
            ram_gb = hw.available_memory_gb
            hits = await asyncio.to_thread(search_models, query, tier=tier)
        except Exception as exc:  # noqa: BLE001
            self._call_ui(log.add_error, f"Search failed: {exc}")
            return

        # Always look up trusted Hub artifacts so each model lists every engine
        # it can run on (Ollama + MLX + GGUF), not just the catalog's command.
        from superqode.local.labs import search_hub_trusted
        from superqode.local.matrix import augment_commands_with_hub

        hub_models = []
        try:
            hub_models = await asyncio.to_thread(search_hub_trusted, query, limit=25)
        except Exception:  # noqa: BLE001 - offline / no huggingface_hub
            hub_models = []
        augment_commands_with_hub(hits, hub_models)
        matched_ids = {cmd.split()[-1] for h in hits for _, cmd in h.commands}
        hub_extra = [m for m in hub_models if m.id not in matched_ids]
        hub_models = hub_extra if want_hub else hub_extra[:3]

        if not hits and not hub_models:
            t = Text()
            t.append(f"\n  No models match {query!r}.\n", style=THEME["warning"])
            t.append("  Browse families with ", style=THEME["muted"])
            t.append(":local labs", style=f"bold {THEME['cyan']}")
            t.append("  ·  live: ", style=THEME["muted"])
            t.append(f":local search {query} --hub\n", style=f"bold {THEME['cyan']}")
            self._call_ui(self._show_command_output, log, t)
            return

        from superqode.local.matrix import estimate_model_memory_gb, memory_fit_phrase

        ram_note = f"  ·  your RAM: ~{ram_gb:g} GB" if ram_gb else ""
        t = Text()
        if hits:
            t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append("Curated matches", style=f"bold {THEME['text']}")
            t.append(f"  for {query!r}  ·  {tier}{ram_note}\n\n", style=THEME["dim"])
        for hit in hits:
            fit = memory_fit_phrase(hit.est_memory_gb, ram_gb)
            t.append("  ● ", style=f"bold {THEME['success']}")
            t.append(hit.name, style=f"bold {THEME['text']}")
            badges = []
            if hit.downloaded_as:
                badges.append("downloaded")
            badges.append(fit)
            if hit.role and hit.role != "main":
                badges.append(hit.role)
            badge_color = THEME["warning"] if "too large" in fit else THEME["success"]
            t.append(f"  [{', '.join(badges)}]\n", style=badge_color)
            if hit.downloaded_as:
                t.append(f"      you already have: {hit.downloaded_as}\n", style=THEME["success"])
            for engine, command in hit.commands:
                t.append(f"      {engine:<11} ", style=THEME["dim"])
                t.append(f"{command}\n", style=THEME["cyan"])
            if hit.hub_repo:
                t.append(f"      {'SuperQode':<11} ", style=THEME["dim"])
                t.append(f"superqode models download {hit.hub_repo}", style=THEME["cyan"])
                t.append("  (any engine)\n", style=THEME["dim"])
            if hit.sources:
                t.append(f"      (source: {', '.join(hit.sources)})\n", style=THEME["dim"])

        if hub_models:
            t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append("Latest on Hugging Face", style=f"bold {THEME['text']}")
            t.append("  (trusted publishers)\n\n", style=THEME["dim"])
            for m in hub_models:
                fmt = "GGUF" if m.is_gguf else ("MLX" if m.is_mlx else "safetensors")
                est = estimate_model_memory_gb(m.id, quantized_default=(m.is_gguf or m.is_mlx))
                fit = memory_fit_phrase(est, ram_gb)
                t.append("  ● ", style=f"bold {THEME['cyan']}")
                t.append(m.id, style=f"bold {THEME['text']}")
                t.append(f"  [{fmt}, {m.downloads:,} dl, {fit}]\n", style=THEME["dim"])
                t.append(f"      superqode models download {m.id}\n", style=THEME["cyan"])

        t.append(
            "\n  Sizes are rough estimates (params x quant), not a guarantee.\n", style=THEME["dim"]
        )
        if not want_hub:
            t.append("  Add ", style=THEME["muted"])
            t.append("--hub", style=f"bold {THEME['cyan']}")
            t.append(" to see the latest releases live from Hugging Face.\n", style=THEME["muted"])
        t.append("  After downloading, ", style=THEME["muted"])
        t.append(":connect local\n", style=f"bold {THEME['cyan']}")
        t.append("  For the full first-run path: ", style=THEME["muted"])
        t.append(f":local setup {query}\n", style=f"bold {THEME['cyan']}")
        self._call_ui(self._show_command_output, log, t)

    async def _local_warm(self, subargs: str, log: ConversationLog):
        """Warm a local model and show first-token latency in the TUI."""
        import asyncio

        from superqode.local.bench import list_endpoint_models, run_bench
        from superqode.local.servers import get_manager

        try:
            tokens = shlex.split(subargs or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :local warm arguments: {exc}")
            return
        if not tokens:
            log.add_info("Usage: :local warm <engine> [--model MODEL]")
            return
        engine = tokens[0]
        model = ""
        if "--model" in tokens:
            idx = tokens.index("--model")
            if idx + 1 < len(tokens):
                model = tokens[idx + 1]
        status = get_manager().status(engine)
        if not status.get("running"):
            log.add_error(f"{engine} is not running. Start it with :local serve {engine}")
            return
        endpoint = status["base_url"]
        if not model:
            models = await asyncio.to_thread(list_endpoint_models, endpoint)
            if not models:
                log.add_error(f"No models found at {endpoint}; pass --model explicitly")
                return
            model = models[0]
        log.add_info(f"Warming {model} at {endpoint} ...")
        self.is_busy = True
        try:
            result = await asyncio.to_thread(
                run_bench,
                endpoint,
                model,
                prompt="Reply with exactly: ok",
                max_tokens=8,
            )
        finally:
            self.is_busy = False
        if not result.ok:
            log.add_error(result.error or "warmup request failed")
            return
        t = Text()
        t.append("\n  ● ", style=f"bold {THEME['success']}")
        t.append(f"ready: {model}\n", style=f"bold {THEME['text']}")
        tps = f"{result.decode_tps} tok/s" if result.decode_tps is not None else "n/a"
        t.append(
            f"  TTFT {result.ttft_s}s · decode {tps} · total {result.total_s}s\n",
            style=THEME["text"],
        )
        self._show_command_output(log, t)

    async def _local_serve(self, subargs: str, log: ConversationLog):
        """Start a local model server from the TUI as a managed daemon."""
        import asyncio
        import shlex

        from superqode.local.servers import SPECS, ServerError, get_manager

        try:
            engine, opts = self._parse_serve_args(subargs)
        except ValueError:
            log.add_error("Bad value for --port/--ctx (must be a number)")
            return
        if engine not in SPECS:
            log.add_error(f"Unknown engine: {engine}")
            log.add_system(f"Available: {', '.join(SPECS)}")
            return

        manager = get_manager()
        if not manager.is_running(
            engine, opts.get("host"), opts.get("port")
        ) and not manager.is_installed(engine):
            log.add_error(f"{engine} is not installed on this machine")
            return

        host_eff = opts.get("host") or SPECS[engine].default_host
        port_eff = opts.get("port") or SPECS[engine].default_port
        if not manager.is_running(engine, host_eff, port_eff):
            try:
                cmd, env_overrides, cwd = manager.build_command(
                    engine,
                    host=host_eff,
                    port=port_eff,
                    model=opts.get("model"),
                    ctx=opts.get("ctx"),
                    extra_args=opts.get("extra_args"),
                )
                t0 = Text()
                t0.append(f"Starting managed {engine} server\n", style=f"bold {THEME['text']}")
                t0.append("  command: ", style=THEME["muted"])
                t0.append(" ".join(shlex.quote(part) for part in cmd), style=THEME["cyan"])
                t0.append("\n", style="")
                if env_overrides:
                    env_text = " ".join(
                        f"{key}={shlex.quote(value)}"
                        for key, value in sorted(env_overrides.items())
                    )
                    t0.append("  env: ", style=THEME["muted"])
                    t0.append(env_text, style=THEME["cyan"])
                    t0.append("\n", style="")
                if cwd:
                    t0.append(f"  cwd: {cwd}\n", style=THEME["dim"])
                t0.append(f"  log: ~/.superqode/servers/{engine}.log\n", style=THEME["dim"])
                log.write(t0)
            except ServerError:
                pass
        log.add_info(f"Starting {engine} server (this may take a moment while it binds)...")
        try:
            handle = await asyncio.to_thread(manager.start, engine, **opts)
        except ServerError as exc:
            log.add_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Failed to start {engine}: {exc}")
            return

        verb = "Adopted running" if handle.adopted else "Started"
        t = Text()
        t.append("  ● ", style=f"bold {THEME['success']}")
        t.append(f"{verb} {engine}", style=f"bold {THEME['text']}")
        t.append(f"  {handle.base_url}\n", style=THEME["cyan"])
        if handle.pid:
            t.append(f"      pid {handle.pid} · log {handle.log_path}\n", style=THEME["dim"])
        for note in handle.notes:
            t.append(f"      • {note}\n", style=THEME["muted"])
        t.append("      Connect with: ", style=THEME["muted"])
        t.append(f":connect {engine}\n", style=THEME["success"])
        if handle.adopted:
            t.append(
                "      Already running externally; SuperQode will not stop this process.\n",
                style=THEME["dim"],
            )
        else:
            t.append("      Stop with: ", style=THEME["muted"])
            t.append(f":local stop {engine}\n", style=f"bold {THEME['success']}")
        log.write(t)

    async def _local_servers(self, log: ConversationLog):
        """Show status of every known local server."""
        import asyncio

        from superqode.local.servers import get_manager

        rows = await asyncio.to_thread(get_manager().list_all)
        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Servers\n\n", style=f"bold {THEME['text']}")
        for row in rows:
            if row["running"]:
                t.append("  ● ", style=f"bold {THEME['success']}")
                state = "managed" if row["managed"] else "running"
            else:
                t.append("  ○ ", style=THEME["muted"])
                state = "stopped"
            t.append(f"{row['engine']:<10}", style=f"bold {THEME['text']}")
            t.append(f" {state:<8}", style=THEME["muted"])
            t.append(f" {row['base_url']}", style=THEME["dim"])
            if row["pid"]:
                t.append(f"  pid {row['pid']}", style=THEME["dim"])
            t.append("\n", style="")
        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":local serve <engine>", style=THEME["success"])
        t.append(" to start one\n", style=THEME["muted"])
        log.write(t)

    async def _local_stop(self, engine: str, log: ConversationLog):
        """Stop a server SuperQode started (adopted servers are left running)."""
        import asyncio

        from superqode.local.servers import SPECS, get_manager

        if engine not in SPECS:
            log.add_error(f"Unknown engine: {engine}")
            return
        stopped = await asyncio.to_thread(get_manager().stop, engine)
        if stopped:
            log.add_info(f"Stopped {engine}")
        else:
            log.add_info(f"Nothing to stop for {engine} (not managed by SuperQode)")

    async def _render_local_server_state(self, engine: str, log: ConversationLog) -> bool:
        """Tell the developer whether the server is up, stopped, or not installed.

        Three outcomes:
          running   -> green confirmation; returns False so models load below.
          stopped   -> installed; for engines that start without a model arg,
                       set up an inline "press Enter to start" prompt and return
                       True (caller stops and waits for the decision). Otherwise
                       show the typed start command and return False.
          missing   -> not installed; show the install guide, return False.

        Returns True when an inline start prompt is now awaiting user input.
        """
        import asyncio

        from superqode.local.servers import SPECS, get_manager

        manager = get_manager()
        readiness = await asyncio.to_thread(manager.precheck, engine)
        name = self._LOCAL_ENGINE_NAMES.get(engine, engine)

        t = Text()
        if readiness.state == "running":
            t.append("\n  🟢 ", style=THEME["success"])
            t.append(f"{name} server is running", style=f"bold {THEME['text']}")
            t.append(f"  {readiness.base_url}\n", style=THEME["dim"])
            if engine == "ds4":
                t.append("  DS4 models are local, free, and tool-capable.\n", style=THEME["muted"])
            log.write(t)
            return False

        # Per-engine note on what --ctx does, reused below.
        ctx_note = {
            "ollama": "--ctx sets OLLAMA_CONTEXT_LENGTH",
            "lmstudio": "--ctx applies when the model loads (lms load --context-length)",
            "ds4": "--ctx sets the KV window",
            "mlx": "context is fixed by the model (no --ctx)",
            "llama.cpp": "--ctx maps to -c",
        }.get(engine, "")

        if readiness.state == "stopped":
            # Engines that bind a server without needing a model id up front can
            # be started right here with one key.
            startable = not readiness.needs_model and readiness.startable
            default_port = SPECS[engine].default_port

            t.append("\n  🟡 ", style=THEME["warning"])
            t.append(
                f"{name} is installed but the server isn't running\n", style=f"bold {THEME['text']}"
            )

            if engine == "lmstudio":
                t.append(
                    "  LM Studio's CLI only works reliably after the LM Studio app/backend is open.\n",
                    style=THEME["muted"],
                )
                if readiness.startable:
                    self._awaiting_local_server_start = engine
                    self._awaiting_local_model = False
                    t.append(
                        "  LM Studio is open and the lms CLI is available.\n",
                        style=THEME["success"],
                    )
                    t.append(
                        "  Recommended: start the Local Server in LM Studio, or run:\n",
                        style=THEME["muted"],
                    )
                    t.append("      ", style="")
                    t.append("lms server start --port 1234", style=THEME["cyan"])
                    t.append("\n", style="")
                    t.append("  Need SuperQode to run that command? Press ", style=THEME["muted"])
                    t.append("Enter", style=f"bold {THEME['success']}")
                    t.append("   ·   ", style=THEME["dim"])
                    t.append("'n'", style=THEME["warning"])
                    t.append(" to skip\n", style=THEME["muted"])
                else:
                    t.append(
                        "  First open LM Studio, load a chat model, then start the Local Server.\n",
                        style=THEME["cyan"],
                    )
                    t.append("  Native app command: ", style=THEME["muted"])
                    t.append('open -a "LM Studio"', style=THEME["cyan"])
                    t.append("\n", style="")
                    t.append("  Optional CLI after the app is open: ", style=THEME["muted"])
                    t.append("lms server start --port 1234", style=THEME["cyan"])
                    t.append("\n", style="")
                t.append(
                    "  If you load by CLI, adjust model/context as needed: ", style=THEME["muted"]
                )
                t.append("lms load <model-key> --context-length <ctx>", style=THEME["cyan"])
                t.append("\n", style="")
                if not readiness.startable and not getattr(readiness, "cli_available", False):
                    t.append("  Optional CLI setup: ", style=THEME["muted"])
                    t.append("npx lmstudio install-cli", style=THEME["cyan"])
                    t.append("\n", style="")
                t.append("\n  Then run ", style=THEME["muted"])
                t.append(":connect local", style=f"bold {THEME['cyan']}")
                t.append(" again.\n", style=THEME["muted"])
                log.write(t)
                self._awaiting_local_model = False
                self._awaiting_local_provider = False
                if readiness.startable:
                    self._pin_local_prompt_to_input(
                        "LM Studio is open: press Enter to run lms server start, or n to skip",
                        log,
                        notify="LM Studio is open. Press Enter if you want SuperQode to start the server.",
                    )
                else:
                    self._pin_local_prompt_to_input(
                        "Open LM Studio, start Local Server, then run :connect local",
                        log,
                        notify="Open LM Studio and start its Local Server first.",
                    )
                return True

            if startable:
                self._awaiting_local_server_start = engine
                # The inline start prompt owns the next input, not model select.
                self._awaiting_local_model = False
                native_command = self._native_local_server_command(engine)
                managed_command = f":local serve {engine}"
                t.append(
                    "  Recommended: start it yourself with the native command:\n",
                    style=THEME["muted"],
                )
                t.append("      ", style="")
                t.append(native_command, style=THEME["cyan"])
                t.append(f"  # default port {default_port}\n", style=THEME["dim"])
                docs_url = self._local_server_docs_url(engine)
                if docs_url:
                    t.append("      Vendor guide: ", style=THEME["muted"])
                    t.append(f"{docs_url}\n", style=THEME["cyan"])
                t.append(
                    "      Edit the model, port, or context if your setup needs it.\n",
                    style=THEME["dim"],
                )
                t.append(
                    "      If a separate terminal is impractical, managed fallback: ",
                    style=THEME["muted"],
                )
                t.append(managed_command, style=THEME["cyan"])
                t.append("\n", style="")
                if engine == "ds4":
                    t.append(
                        "  Experimental convenience: SuperQode can run DS4 as a detached process.\n",
                        style=THEME["warning"],
                    )
                    t.append(
                        "    It binds to 127.0.0.1:8000 with a 32,768-token context, uses an\n",
                        style=THEME["muted"],
                    )
                    t.append(
                        "    8 GB disk KV cache under ~/.superqode/ds4-kv, writes logs to\n",
                        style=THEME["muted"],
                    )
                    t.append(
                        "    ~/.superqode/servers/ds4.log, then waits for /v1/models.\n",
                        style=THEME["muted"],
                    )
                    t.append(
                        "    It will not build DS4 or download model weights in this step.\n",
                        style=THEME["dim"],
                    )
                    t.append("    Stop the managed server with: ", style=THEME["muted"])
                    t.append(":local stop ds4\n", style=f"bold {THEME['success']}")
                    t.append("  Try the experimental managed start? Press ", style=THEME["muted"])
                else:
                    t.append(
                        "  Need SuperQode to start a managed server? Press ",
                        style=THEME["muted"],
                    )
                t.append("Enter", style=f"bold {THEME['success']}")
                t.append(f" to launch it on port {default_port}", style=THEME["muted"])
                t.append("   ·   ", style=THEME["dim"])
                t.append("'n'", style=THEME["warning"])
                t.append(" to skip\n", style=THEME["muted"])
                t.append("    Managed custom start: type ", style=THEME["muted"])
                t.append("port=8090 ctx=8192", style=THEME["cyan"])
                if ctx_note:
                    t.append(f"   ({ctx_note})", style=THEME["dim"])
                t.append("\n", style="")
                if engine == "lmstudio":
                    t.append(
                        "    Tip: add model=<key> to load a model at that context.\n",
                        style=THEME["dim"],
                    )
                log.write(t)
                self._pin_local_prompt_to_input(
                    f"Start {engine} yourself, or press Enter for SuperQode managed start",
                    log,
                    notify=f"{name} is stopped. Start it yourself, or press Enter for help.",
                )
                return True

            # Needs a model id (mlx / llama.cpp): show the typed command instead.
            native_command = self._native_local_server_command(engine, model="<model-id>")
            t.append(
                "  This server serves one model per process, so no models are available yet.\n",
                style=THEME["muted"],
            )
            t.append("  Start it yourself with the native command:\n", style=THEME["muted"])
            t.append("      ", style="")
            t.append(native_command, style=THEME["cyan"])
            t.append("\n", style="")
            t.append(
                "      Replace <model-id> with the model id/path you actually have.\n",
                style=THEME["dim"],
            )
            t.append("      SuperQode managed fallback: ", style=THEME["muted"])
            t.append(f"{readiness.start_hint}", style=f"bold {THEME['success']}")
            t.append(" --port <N>\n", style=THEME["cyan"])
            if ctx_note:
                t.append(f"    ({ctx_note})\n", style=THEME["dim"])
            t.append(
                "    Re-run :connect local after the server is answering.\n",
                style=THEME["dim"],
            )
            log.write(t)
            self._awaiting_local_model = False
            self._awaiting_local_provider = False
            self._pin_local_prompt_to_input(
                f"Start {engine} with a model first, then run :connect local",
                log,
            )
            return True

        # missing
        # MLX is a single pip dependency we can install for the user (with
        # consent) right here, into the same env that runs SuperQode.
        import platform as _platform
        import sys

        apple_silicon = sys.platform == "darwin" and _platform.machine() == "arm64"
        if engine == "mlx" and apple_silicon:
            from superqode.local.servers import mlx_install_command
            from superqode.providers.env_introspect import environment_info

            self._awaiting_local_dep_install = "mlx"
            self._awaiting_local_model = False
            # The dependency prompt owns the next input. Leaving the provider
            # picker active makes SelectionAwareInput consume Enter as another
            # provider selection before this prompt can handle it.
            self._awaiting_local_provider = False
            env = environment_info()
            command = mlx_install_command(sys.executable)
            t.append("\n  🔴 ", style=THEME["error"])
            t.append(
                "MLX (mlx-lm) is not installed in this environment\n", style=f"bold {THEME['text']}"
            )
            t.append("    SuperQode is running from: ", style=THEME["muted"])
            t.append(env.label, style=f"bold {THEME['text']}")
            t.append(f" ({env.python})\n", style=THEME["dim"])
            t.append("    This will modify: ", style=THEME["muted"])
            t.append(f"{env.target}\n", style=THEME["dim"])
            t.append("    Exact command:\n", style=THEME["muted"])
            t.append("      ", style="")
            t.append(command, style=THEME["cyan"])
            t.append("\n", style="")
            t.append("  ▶ Press ", style=THEME["muted"])
            t.append("Enter", style=f"bold {THEME['success']}")
            t.append(" to run that exact command", style=THEME["muted"])
            t.append("   ·   ", style=THEME["dim"])
            t.append("'n'", style=THEME["warning"])
            t.append(" to skip\n", style=THEME["muted"])
            t.append(
                "    Prefer to install it yourself? Copy the command above into another terminal,\n",
                style=THEME["muted"],
            )
            t.append(
                "    then restart SuperQode and run :connect local again.\n",
                style=THEME["dim"],
            )
            log.write(t)
            self._pin_local_prompt_to_input(
                "Install MLX: Enter runs the shown command, n skips",
                log,
                notify="MLX support is missing. Review the shown command, then press Enter to install or n to skip.",
            )
            return True

        t.append("\n  🔴 ", style=THEME["error"])
        t.append(f"{name} is not installed\n\n", style=f"bold {THEME['text']}")
        for line in readiness.install_guide:
            t.append(
                f"  {line}\n",
                style=THEME["cyan"]
                if line.strip().startswith(
                    ("brew", "uv", "curl", "npx", "superqode", "cd", "ollama")
                )
                else THEME["muted"],
            )
        t.append("\n  Once installed, start it with: ", style=THEME["muted"])
        t.append(f"{readiness.start_hint}\n", style=f"bold {THEME['success']}")
        log.write(t)
        return False

    def _handle_local_server_start_input(self, text: str, log: ConversationLog) -> bool:
        """Handle the inline start prompt for a stopped local server.

        Enter           -> start with engine defaults
        n / no / skip    -> cancel, leave the server stopped
        port=N ctx=N ... -> start with those overrides (also accepts a bare port)
        """
        engine = getattr(self, "_awaiting_local_server_start", None)
        if not engine:
            return False

        from superqode.local.servers import parse_inline_start

        action, opts, error = parse_inline_start(text)
        if action == "cancel":
            self._awaiting_local_server_start = None
            self._reset_input_placeholder()
            t = Text()
            t.append("\n  ⏭  ", style=THEME["warning"])
            t.append(f"Left {engine} stopped.", style=f"bold {THEME['text']}")
            t.append(f" Start it anytime with :local serve {engine}\n", style=THEME["muted"])
            log.write(t)
            # Re-open the provider picker so this is not a dead end.
            self._show_local_provider_picker(log)
            return True
        if action == "error":
            log.add_error(
                f"{error}. Start it yourself, press Enter for SuperQode managed defaults, "
                "type 'port=8090 ctx=8192', or 'n' to skip."
            )
            self._pin_local_prompt_to_input(
                f"Start {engine} yourself, or press Enter for SuperQode managed start",
                log,
            )
            return True  # keep the prompt active

        self._awaiting_local_server_start = None
        self._reset_input_placeholder()
        self.run_worker(self._start_local_server_then_list(engine, opts, log))
        return True

    def _handle_local_dep_install_input(self, text: str, log: ConversationLog) -> bool:
        """Handle the inline 'install mlx-lm?' prompt. Enter=install, n=skip."""
        engine = getattr(self, "_awaiting_local_dep_install", None)
        if not engine:
            return False

        low = text.strip().lower()
        if low in ("n", "no", "skip", "cancel", "q"):
            self._awaiting_local_dep_install = None
            self._reset_input_placeholder()
            t = Text()
            t.append("\n  ⏭  ", style=THEME["warning"])
            t.append(f"Skipped installing {engine}.", style=f"bold {THEME['text']}")
            t.append(" Pick another provider below, or install later with:\n", style=THEME["muted"])
            if engine == "mlx":
                from superqode.local.servers import mlx_install_command

                t.append(f"      {mlx_install_command()}\n", style=THEME["cyan"])
            log.write(t)
            # Re-open the provider picker so this is not a dead end.
            self._show_local_provider_picker(log)
            return True
        if low not in ("", "y", "yes", "install", "ok"):
            log.add_error("Press Enter to run the shown install command, or 'n' to skip.")
            self._pin_local_prompt_to_input(
                "Install MLX: Enter runs the shown command, n skips",
                log,
            )
            return True  # keep the prompt active

        self._awaiting_local_dep_install = None
        self._reset_input_placeholder()
        self.run_worker(self._install_local_dep_then_continue(engine, log))
        return True

    async def _install_local_dep_then_continue(self, engine: str, log: ConversationLog):
        """Install a missing engine dependency (mlx-lm), then re-list models."""
        import asyncio

        from superqode.local.servers import install_mlx

        t0 = Text()
        t0.append("\n  ⏳ ", style=THEME["warning"])
        t0.append("Installing mlx-lm", style=f"bold {THEME['text']}")
        t0.append(" — this downloads a few packages, please wait...\n", style=THEME["muted"])
        log.write(t0)

        self.is_busy = True
        try:
            ok, message = await asyncio.to_thread(install_mlx)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Install failed: {exc}")
            return
        finally:
            self.is_busy = False

        if not ok:
            log.add_error(f"Could not install mlx-lm: {message}")
            from superqode.local.servers import mlx_install_command

            log.add_system(f"Install manually: {mlx_install_command()}")
            return

        t = Text()
        t.append("  ✓ ", style=f"bold {THEME['success']}")
        t.append("mlx-lm installed", style=f"bold {THEME['text']}")
        t.append(" — now pick a cached MLX model below.\n", style=THEME["muted"])
        log.write(t)

        # Re-enter the picker: MLX is now installed, so it lists models.
        await self._show_local_provider_models(engine, log)

    async def _start_local_server_then_list(self, engine: str, opts: dict, log: ConversationLog):
        """Start a local server from the inline prompt, then list its models."""
        import asyncio

        from superqode.local.servers import ServerError, get_manager

        detail = ""
        if opts:
            detail = " (" + ", ".join(f"{k}={v}" for k, v in opts.items()) + ")"

        # Immediate, visible acknowledgement so the user knows we are working.
        t0 = Text()
        t0.append("\n  ⏳ ", style=THEME["warning"])
        t0.append(f"Starting {engine}{detail}", style=f"bold {THEME['text']}")
        if engine == "lmstudio":
            t0.append(" — running ", style=THEME["muted"])
            t0.append("lms server start --port 1234", style=THEME["cyan"])
            t0.append(" and checking the Local Server endpoint...\n", style=THEME["muted"])
        elif engine == "ds4":
            command = self._native_local_server_command(
                "ds4",
                host=opts.get("host"),
                port=opts.get("port"),
                ctx=opts.get("ctx"),
            )
            t0.append("\n    command: ", style=THEME["muted"])
            t0.append(command, style=THEME["cyan"])
            t0.append("\n    log: ~/.superqode/servers/ds4.log\n", style=THEME["dim"])
            t0.append(
                "    Launching it in the background, recording its PID, and waiting for /v1/models...\n",
                style=THEME["muted"],
            )
        else:
            t0.append(
                " — launching the server and waiting for it to bind...\n",
                style=THEME["muted"],
            )
        log.write(t0)

        # Drive the footer throbber while the (blocking) start runs in a thread.
        self.is_busy = True
        try:
            handle = await asyncio.to_thread(get_manager().start, engine, **opts)
        except ServerError as exc:
            log.add_error(str(exc))
            if engine == "lmstudio":
                log.add_system(
                    "Tip: open LM Studio, load a chat model, start the Local Server tab, "
                    "then run :connect local again."
                )
            else:
                log.add_system(f"Tip: start it manually with :local serve {engine}")
            return
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Failed to start {engine}: {exc}")
            return
        finally:
            self.is_busy = False

        verb = "Adopted running" if handle.adopted else "Started"
        t = Text()
        t.append("  ● ", style=f"bold {THEME['success']}")
        t.append(f"{verb} {engine}", style=f"bold {THEME['text']}")
        t.append(f"  {handle.base_url}\n", style=THEME["cyan"])
        if handle.pid:
            t.append(f"      pid {handle.pid} · log {handle.log_path}\n", style=THEME["dim"])
        for note in handle.notes:
            t.append(f"      • {note}\n", style=THEME["muted"])
        if handle.adopted:
            t.append(
                "      Already running externally; SuperQode will not stop this process.\n",
                style=THEME["dim"],
            )
        else:
            t.append("      Stop with: ", style=THEME["muted"])
            t.append(f":local stop {engine}\n", style=f"bold {THEME['success']}")
        log.write(t)

        # Now that the server is up, list its models in the same picker.
        await self._show_local_provider_models(engine, log)

    async def _local_status(self, log: ConversationLog):
        """Show status of all local providers."""
        from superqode.providers.local import (
            get_discovery_service,
            LocalProviderType,
        )

        log.add_info("Scanning local providers...")

        discovery = get_discovery_service()
        discovered = await discovery.scan_all()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Provider Status\n\n", style=f"bold {THEME['text']}")

        if discovered:
            for key, provider in discovered.items():
                # Provider type icon
                type_icons = {
                    LocalProviderType.OLLAMA: "🦙",
                    LocalProviderType.LMSTUDIO: "🎬",
                    LocalProviderType.VLLM: "⚡",
                    LocalProviderType.SGLANG: "🔥",
                    LocalProviderType.TGI: "🤗",
                    LocalProviderType.MLX: "🍎",
                    LocalProviderType.LLAMACPP: "🔧",
                    LocalProviderType.OPENAI_COMPAT: "🔌",
                }
                icon = type_icons.get(provider.provider_type, "●")

                t.append(f"  {icon} ", style=f"bold {THEME['success']}")
                t.append(f"{provider.provider_type.value}", style=f"bold {THEME['text']}")
                t.append(f"  {provider.host}", style=THEME["muted"])
                if provider.version:
                    t.append(f"  v{provider.version}", style=THEME["dim"])
                t.append("\n", style="")

                t.append(f"    Models: {provider.model_count}", style=THEME["muted"])
                if provider.running_count > 0:
                    t.append(f"  Running: ", style=THEME["muted"])
                    t.append(f"{provider.running_count}", style=f"bold {THEME['success']}")
                t.append(f"  Latency: {provider.latency_ms:.0f}ms\n", style=THEME["dim"])

                # Show running models
                if provider.running_models:
                    for model in provider.running_models[:3]:
                        t.append(f"      ● ", style=THEME["success"])
                        t.append(f"{model.id}\n", style=THEME["text"])
                t.append("\n", style="")
        else:
            t.append(f"  ○ No local providers detected\n\n", style=THEME["muted"])
            t.append(f"  💡 Start Ollama with: ", style=THEME["muted"])
            t.append("ollama serve\n", style=THEME["cyan"])

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":local models", style=THEME["success"])
        t.append(" to see all available models\n", style=THEME["muted"])

        # We are running in the app's event loop here, so write directly
        log.write(t)

    async def _local_scan(self, log: ConversationLog):
        """Scan for running local providers."""
        from superqode.providers.local import get_discovery_service

        log.add_info("Scanning all ports for local providers...")

        discovery = get_discovery_service()
        discovered = await discovery.scan_all()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Provider Scan Results\n\n", style=f"bold {THEME['text']}")

        if discovered:
            t.append(
                f"  ✓ Found {len(discovered)} provider(s)\n\n", style=f"bold {THEME['success']}"
            )
            for key, provider in discovered.items():
                t.append(f"  ● ", style=THEME["success"])
                t.append(f"{provider.provider_type.value}", style=f"bold {THEME['text']}")
                t.append(f" at port {provider.port}\n", style=THEME["muted"])
        else:
            t.append(f"  ○ No local providers found\n\n", style=THEME["muted"])
            t.append("  Ports scanned: 11434, 1234, 8000, 8080, 30000, 5000\n", style=THEME["dim"])

        log.write(t)

    async def _local_models(self, log: ConversationLog):
        """List all models from discovered local providers."""
        from superqode.providers.local import (
            get_discovery_service,
            estimate_tool_support,
        )

        discovery = get_discovery_service()
        discovered = await discovery.scan_all()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Models\n\n", style=f"bold {THEME['text']}")

        total = 0
        for key, provider in discovered.items():
            if provider.models:
                t.append(
                    f"  {provider.provider_type.value.upper()}\n", style=f"bold {THEME['cyan']}"
                )
                for model in provider.models[:10]:  # Limit to 10 per provider
                    status = "●" if model.running else "○"
                    status_style = THEME["success"] if model.running else THEME["dim"]
                    t.append(f"    {status} ", style=status_style)
                    t.append(f"{model.id}", style=THEME["text"])

                    # Show tool support estimate
                    tool_level = estimate_tool_support(model)
                    if tool_level == "excellent":
                        t.append(f"  [tools ✓✓]", style=THEME["success"])
                    elif tool_level == "good":
                        t.append(f"  [tools ✓]", style=THEME["cyan"])
                    elif tool_level == "none":
                        t.append(f"  [no tools]", style=THEME["dim"])

                    if model.size_display != "unknown":
                        t.append(f"  {model.size_display}", style=THEME["muted"])
                    t.append("\n", style="")
                    total += 1

                if len(provider.models) > 10:
                    t.append(f"    ... and {len(provider.models) - 10} more\n", style=THEME["dim"])
                t.append("\n", style="")

        if total == 0:
            t.append(f"  ○ No models found\n", style=THEME["muted"])
            t.append(f"  💡 Pull a model with: ", style=THEME["muted"])
            t.append("ollama pull qwen3.6:35b-a3b\n", style=THEME["cyan"])
            t.append("  Trusted recommendations: ", style=THEME["muted"])
            t.append(":local labs\n", style=THEME["cyan"])

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":local test <model>", style=THEME["success"])
        t.append(" to test tool calling\n", style=THEME["muted"])

        log.write(t)

    async def _local_test(self, model_id: str, log: ConversationLog):
        """Test tool calling capability for a model."""
        from superqode.providers.local import (
            test_tool_calling,
            get_tool_capability_info,
        )

        # First show heuristic info
        info = get_tool_capability_info(model_id)

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"Testing Tool Calling: {model_id}\n\n", style=f"bold {THEME['text']}")

        t.append(f"  Heuristic Assessment:\n", style=THEME["muted"])
        t.append(f"    Likely supports tools: ", style=THEME["text"])
        if info.supports_tools:
            t.append("Yes\n", style=f"bold {THEME['success']}")
        else:
            t.append("No\n", style=THEME["dim"])
        if info.notes:
            t.append(f"    Note: {info.notes}\n", style=THEME["dim"])
        t.append("\n", style="")

        log.write(t)
        log.add_info("Running actual test...")

        # Run actual test
        result = await test_tool_calling(model_id)

        t2 = Text()
        t2.append(f"\n  Test Results:\n", style=f"bold {THEME['text']}")

        if result.supports_tools:
            t2.append(f"    ✓ ", style=f"bold {THEME['success']}")
            t2.append("Tool calling works!\n", style=THEME["success"])
            if result.parallel_tools:
                t2.append(f"    ✓ Parallel tools: Yes\n", style=THEME["success"])
            if result.tool_choice:
                t2.append(
                    f"    ✓ Tool choice modes: {', '.join(result.tool_choice)}\n",
                    style=THEME["cyan"],
                )
        else:
            t2.append(f"    ✗ ", style=f"bold {THEME['error']}")
            t2.append("Tool calling not supported\n", style=THEME["error"])
            if result.error:
                t2.append(f"    Error: {result.error}\n", style=THEME["dim"])

        if result.latency_ms > 0:
            t2.append(f"    Latency: {result.latency_ms:.0f}ms\n", style=THEME["dim"])
        if result.notes:
            t2.append(f"    Note: {result.notes}\n", style=THEME["muted"])

        log.write(t2)

    async def _local_info(self, model_id: str, log: ConversationLog):
        """Show detailed info about a local model."""
        from superqode.providers.local import (
            OllamaClient,
            get_tool_capability_info,
        )

        client = OllamaClient()
        model = await client.get_model_info(model_id)

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"Model: {model_id}\n\n", style=f"bold {THEME['text']}")

        if model:
            t.append(f"  Family:         ", style=THEME["muted"])
            t.append(f"{model.family}\n", style=THEME["text"])
            t.append(f"  Parameters:     ", style=THEME["muted"])
            t.append(f"{model.parameter_count or 'unknown'}\n", style=THEME["text"])
            t.append(f"  Quantization:   ", style=THEME["muted"])
            t.append(f"{model.quantization}\n", style=THEME["text"])
            t.append(f"  Context Window: ", style=THEME["muted"])
            t.append(f"{model.context_window:,} tokens\n", style=THEME["text"])
            t.append(f"  Size:           ", style=THEME["muted"])
            t.append(f"{model.size_display}\n", style=THEME["text"])
            t.append(f"  Running:        ", style=THEME["muted"])
            if model.running:
                t.append("Yes\n", style=f"bold {THEME['success']}")
            else:
                t.append("No\n", style=THEME["dim"])

            # Tool support
            info = get_tool_capability_info(model_id)
            t.append(f"\n  Tool Support:\n", style=f"bold {THEME['cyan']}")
            t.append(f"    Supports Tools: ", style=THEME["muted"])
            if info.supports_tools:
                t.append("Yes\n", style=THEME["success"])
                t.append(f"    Parallel Tools: ", style=THEME["muted"])
                t.append(f"{'Yes' if info.parallel_tools else 'No'}\n", style=THEME["text"])
            elif info.confidence == "heuristic":
                t.append("No\n", style=THEME["dim"])
            else:
                t.append("Unknown (run :local test to verify)\n", style=THEME["dim"])

            if model.supports_vision:
                t.append(f"\n  ✓ Supports Vision/Images\n", style=THEME["success"])
        else:
            t.append(f"  ○ Model not found\n", style=THEME["error"])

        log.write(t)

    def _local_recommend(self, log: ConversationLog):
        """Show recommended local models for coding."""
        from superqode.providers.local import get_recommended_coding_models

        recommendations = get_recommended_coding_models()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Recommended Models for Coding\n\n", style=f"bold {THEME['text']}")

        for rec in recommendations:
            t.append(f"  ● ", style=THEME["cyan"])
            t.append(f"{rec['model']}", style=f"bold {THEME['text']}")
            t.append(f"  ({rec['params']})\n", style=THEME["muted"])

            t.append(f"    Tool Support: ", style=THEME["dim"])
            tool_style = THEME["success"] if rec["tool_support"] == "excellent" else THEME["cyan"]
            t.append(f"{rec['tool_support']}", style=tool_style)

            t.append(f"  │  Code Quality: ", style=THEME["dim"])
            code_style = THEME["success"] if rec["coding_quality"] == "excellent" else THEME["cyan"]
            t.append(f"{rec['coding_quality']}\n", style=code_style)

            t.append(f"    {rec['notes']}\n\n", style=THEME["dim"])

        t.append(f"  💡 Install with: ", style=THEME["muted"])
        t.append("ollama pull <model>\n", style=THEME["cyan"])

        self._show_command_output(log, t)
