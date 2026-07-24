"""
LiteLLM Gateway Implementation.

Default gateway for BYOK mode using LiteLLM for unified API access
to 100+ LLM providers.

Performance features:
- Background prewarming to avoid cold-start latency
- Shared module instance across gateway instances
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from .base import (
    AuthenticationError,
    Cost,
    GatewayError,
    GatewayInterface,
    GatewayResponse,
    InvalidRequestError,
    Message,
    ModelNotFoundError,
    RateLimitError,
    StreamChunk,
    TaskBudgetExceeded,
    TaskTokenBudget,
    ToolDefinition,
    Usage,
)
from ..credentials import provider_api_key, sync_provider_env
from ..model_specs import (
    normalize_model_for_provider,
    normalize_provider_id,
    split_hf_provider_suffix,
    split_provider_model_ref,
)
from ..registry import PROVIDERS, ProviderCategory, ProviderDef

logger = logging.getLogger(__name__)


_LOCAL_DUMMY_API_KEYS = {
    "lmstudio": "sk-local-lmstudio-dummy",
    "vllm": "sk-local-vllm-dummy",
    "ds4": "sk-local-ds4-dummy",
    "sglang": "sk-local-sglang-dummy",
}


def _local_dummy_api_key(provider: str) -> str:
    return _LOCAL_DUMMY_API_KEYS.get(provider, "sk-local-dummy")


def _request_api_key(provider: str, provider_def: ProviderDef) -> Optional[str]:
    if (
        provider_def.category == ProviderCategory.LOCAL
        and provider_def.litellm_prefix == "openai/"
        and not provider_def.env_vars
    ):
        return _local_dummy_api_key(provider)
    return provider_api_key(provider_def)


def _resolve_provider_def(provider: Optional[str]) -> Optional[ProviderDef]:
    """Curated registry def, else a models.dev-synthesized one (imported lazily
    to avoid a circular import at module load)."""
    if not provider:
        return None
    curated = PROVIDERS.get(provider)
    if curated is not None:
        return curated
    try:
        from ..dynamic import resolve_provider_def

        return resolve_provider_def(provider)
    except Exception:  # noqa: BLE001 - resolution is best-effort
        return None


# Module-level shared state for prewarming
_litellm_module = None
_litellm_lock = threading.Lock()
_prewarm_task: Optional[asyncio.Task] = None
_prewarm_complete = threading.Event()


def _load_litellm():
    """Load and configure litellm module (thread-safe)."""
    global _litellm_module
    with _litellm_lock:
        if _litellm_module is None:
            import litellm

            litellm.drop_params = True  # Drop unsupported params
            litellm.set_verbose = False
            _litellm_module = litellm
            _prewarm_complete.set()
    return _litellm_module


class LiteLLMGateway(GatewayInterface):
    """LiteLLM-based gateway for BYOK mode.

    Uses LiteLLM to provide unified access to 100+ LLM providers.

    Performance:
        Call prewarm() during app startup to load litellm in background,
        avoiding ~500-800ms cold-start on first LLM request.
    """

    # Class-level executor for background tasks
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def __init__(
        self,
        track_costs: bool = True,
        timeout: float = 300.0,
    ):
        self.track_costs = track_costs
        self.timeout = timeout

    @classmethod
    def prewarm(cls) -> None:
        """Start prewarming litellm in background thread.

        Call this during app startup for faster first LLM request.
        Non-blocking - returns immediately while loading happens in background.

        Example:
            # In app startup
            LiteLLMGateway.prewarm()

            # Later, first request will be fast
            gateway = LiteLLMGateway()
            await gateway.chat_completion(...)
        """
        if _prewarm_complete.is_set():
            return  # Already loaded

        # Submit to thread pool (non-blocking)
        cls._executor.submit(_load_litellm)

    @classmethod
    async def prewarm_async(cls) -> None:
        """Async version of prewarm - await to ensure litellm is loaded.

        Use this if you want to wait for prewarming to complete.
        """
        if _prewarm_complete.is_set():
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(cls._executor, _load_litellm)

    @classmethod
    def is_prewarmed(cls) -> bool:
        """Check if litellm has been loaded."""
        return _prewarm_complete.is_set()

    @classmethod
    def wait_for_prewarm(cls, timeout: float = 5.0) -> bool:
        """Wait for prewarming to complete.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if prewarmed, False if timeout
        """
        return _prewarm_complete.wait(timeout=timeout)

    def _get_litellm(self):
        """Get litellm module (uses shared prewarmed instance if available)."""
        global _litellm_module
        if _litellm_module is not None:
            return _litellm_module

        # Not prewarmed - load synchronously (will be cached for next time)
        try:
            return _load_litellm()
        except ImportError as e:
            raise GatewayError("LiteLLM is not installed. Install with: pip install litellm") from e

    def get_model_string(self, provider: str, model: str) -> str:
        """Get the full model string for LiteLLM.

        Args:
            provider: Provider ID (e.g., "anthropic")
            model: Model ID (e.g., "claude-opus-4-8")

        Returns:
            Full model string for LiteLLM (e.g., "anthropic/claude-opus-4-8")
        """
        provider = normalize_provider_id(provider)
        model = normalize_model_for_provider(provider, model)

        # LiteLLM exposes two Ollama backends:
        #   ollama/X      -> POST /api/generate (no tool support)
        #   ollama_chat/X -> POST /api/chat     (full tool support)
        # The provider registry historically used ``ollama/``, which
        # silently dropped every tool call. Always route through the chat
        # endpoint so tool-using agents work out of the box. Plain text
        # completions still work fine on /api/chat.
        if provider == "ollama":
            if model.startswith("ollama_chat/"):
                return model
            if model.startswith("ollama/"):
                model = model[len("ollama/") :]
            return f"ollama_chat/{model}"

        provider_def = _resolve_provider_def(provider)

        if provider_def:
            # OpenAI models should always be provider-qualified for LiteLLM
            # to avoid "LLM Provider NOT provided" on newer model IDs.
            if provider == "openai":
                if model.startswith("openai/"):
                    return model
                return f"openai/{model}"

            if provider_def.litellm_prefix:
                # Don't double-prefix
                if model.startswith(provider_def.litellm_prefix):
                    return model
                return f"{provider_def.litellm_prefix}{model}"

        # Unknown provider - try as-is
        return model

    def _get_model_candidates(self, provider: str, model: str) -> List[str]:
        """Return model candidates to try in order for provider/model pair."""
        primary = self.get_model_string(provider, model) if provider != "unknown" else model
        candidates = [primary]

        # Compatibility fallbacks for OpenAI rollout lag by account/region.
        if provider == "openai":
            model_base = model.split("/")[-1]
            fallback_map = {
                "gpt-5.4": "openai/gpt-5.2",
                "gpt-5.4-pro": "openai/gpt-5.2-pro",
                # OpenAI may expose gpt-5-codex while gpt-5.3-codex
                # is still rolling out by account/region.
                "gpt-5.3-codex": "openai/gpt-5-codex",
            }
            fallback = fallback_map.get(model_base)
            if fallback and fallback not in candidates:
                candidates.append(fallback)

        return candidates

    @staticmethod
    def _is_model_not_found_error(error: Exception) -> bool:
        """Best-effort check for model-not-found style provider errors."""
        msg = str(error).lower()
        patterns = [
            "modelnotfound",
            "model not found",
            "invalid model",
            "does not exist",
            "not available",
        ]
        return any(pattern in msg for pattern in patterns)

    @staticmethod
    def _is_retryable_provider_transport_error(error: Exception) -> bool:
        """Detect provider transport/client errors where trying next model can recover."""
        msg = str(error).lower()
        # Observed with LiteLLM/OpenAI for some unreleased model aliases:
        # "APIConnectionError ... argument of type 'NoneType' is not iterable"
        return "noneType".lower() in msg and "not iterable" in msg

    # Transient-overload retry tuning. Hosted providers rate-limit (429/529),
    # and local servers (Ollama, vLLM, LM Studio) briefly 503 under load;
    # honoring Retry-After and backing off beats failing the whole agent turn.
    RATE_LIMIT_RETRIES_ENV = "SUPERQODE_RATE_LIMIT_RETRIES"
    _RATE_LIMIT_DEFAULT_RETRIES = 3
    _RATE_LIMIT_BASE_DELAY = 1.5
    _RATE_LIMIT_MAX_DELAY = 30.0
    # If the provider explicitly asks for a longer pause than this, surface
    # the error instead of silently hanging an interactive session.
    _RATE_LIMIT_MAX_HONORED_RETRY_AFTER = 60.0

    @staticmethod
    def _is_transient_overload_error(error: Exception) -> bool:
        """Rate limits / momentary overload: the same request can succeed shortly."""
        if "ratelimit" in type(error).__name__.lower():
            return True
        msg = str(error).lower()
        patterns = (
            "rate limit",
            "rate_limit",
            "too many requests",
            "429",
            "overloaded",
            "service unavailable",
            "503",
            "529",
            "server is busy",
            "at capacity",
        )
        return any(p in msg for p in patterns)

    @staticmethod
    def _retry_after_seconds(error: Exception) -> Optional[float]:
        """Extract Retry-After (seconds or ms) from a provider exception."""
        headers = None
        for attr in ("response", "http_response"):
            response = getattr(error, attr, None)
            if response is not None and getattr(response, "headers", None) is not None:
                headers = response.headers
                break
        if headers is None:
            headers = getattr(error, "headers", None)
        if headers is None:
            return None
        try:
            raw_ms = headers.get("retry-after-ms")
            if raw_ms:
                return max(0.0, float(raw_ms) / 1000.0)
            raw = headers.get("retry-after")
            if raw:
                return max(0.0, float(raw))
        except (TypeError, ValueError, AttributeError):
            return None
        return None

    @classmethod
    def _rate_limit_retries(cls) -> int:
        raw = os.environ.get(cls.RATE_LIMIT_RETRIES_ENV, "").strip()
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                pass
        return cls._RATE_LIMIT_DEFAULT_RETRIES

    @classmethod
    def _rate_limit_delay(cls, attempt: int, error: Exception) -> Optional[float]:
        """Delay before retry ``attempt`` (0-based), or None to give up."""
        import random

        retry_after = cls._retry_after_seconds(error)
        if retry_after is not None:
            if retry_after > cls._RATE_LIMIT_MAX_HONORED_RETRY_AFTER:
                return None
            return retry_after
        return min(
            cls._RATE_LIMIT_MAX_DELAY, cls._RATE_LIMIT_BASE_DELAY * (2**attempt)
        ) + random.uniform(0, 0.5)

    async def _acompletion_with_retry(self, request_kwargs: Dict[str, Any]):
        """``litellm.acompletion`` with bounded backoff on transient overload.

        Non-transient errors propagate immediately so the caller's
        model-candidate failover logic can handle them.
        """
        # LiteLLM 1.85 imports its proxy MCP handler whenever *any* tools are
        # present, before it checks whether they are MCP tools. That optional
        # proxy path imports FastAPI, which is intentionally absent from a
        # normal SuperQode tool install. SuperQode owns MCP orchestration and
        # sends ordinary model tool definitions here, so bypass that handler.
        request_kwargs.setdefault("_skip_mcp_handler", True)
        litellm = self._get_litellm()
        retries = self._rate_limit_retries()
        attempt = 0
        while True:
            try:
                return await litellm.acompletion(**request_kwargs)
            except Exception as e:
                if attempt >= retries or not self._is_transient_overload_error(e):
                    raise
                delay = self._rate_limit_delay(attempt, e)
                if delay is None:
                    raise
                logger.warning(
                    "Provider overloaded/rate-limited (%s); retrying in %.1fs (attempt %d/%d)",
                    type(e).__name__,
                    delay,
                    attempt + 1,
                    retries,
                )
                attempt += 1
                await asyncio.sleep(delay)

    def _setup_provider_env(self, provider: str) -> None:
        """Set up environment for a provider if needed."""
        provider_def = _resolve_provider_def(provider)
        if not provider_def:
            return

        # Dynamic (models.dev-synthesized) providers route as OpenAI-compatible
        # with api_base/api_key passed explicitly per-request (see
        # chat_completion). Don't mutate global OPENAI_* env here — that would
        # clobber a user's real OpenAI credentials.
        if provider_def.dynamic:
            return

        # Handle base URL for local/custom providers
        if provider_def.base_url_env:
            base_url = os.environ.get(provider_def.base_url_env)
            if not base_url and provider_def.default_base_url:
                # Set default base URL if not configured
                os.environ[provider_def.base_url_env] = provider_def.default_base_url
                base_url = provider_def.default_base_url

            # For Ollama, configure LiteLLM via OLLAMA_API_BASE environment variable
            # LiteLLM 1.80.11 uses OLLAMA_API_BASE env var (not ollama_base_url attribute)
            if provider == "ollama" and base_url:
                # Set both OLLAMA_HOST (our convention) and OLLAMA_API_BASE (LiteLLM convention)
                os.environ["OLLAMA_HOST"] = base_url
                os.environ["OLLAMA_API_BASE"] = base_url

            # For LM Studio - configure for local OpenAI-compatible API
            if provider == "lmstudio" and base_url:
                # LM Studio uses OpenAI-compatible API at /v1
                # Set OPENAI_API_BASE to the base URL (already includes /v1)
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                # Also set the provider-specific env var
                os.environ["LMSTUDIO_HOST"] = clean_url
                # For local LM Studio, set a dummy API key to avoid LiteLLM auth errors
                # Local servers typically don't require authentication
                os.environ.setdefault("OPENAI_API_KEY", _local_dummy_api_key(provider))

            # For vLLM - configure for OpenAI-compatible API
            if provider == "vllm" and base_url:
                # vLLM uses OpenAI-compatible API at /v1
                # Set OPENAI_API_BASE to the base URL (already includes /v1)
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                # Also set the provider-specific env var
                os.environ["VLLM_HOST"] = clean_url
                # For local vLLM, set a dummy API key to avoid LiteLLM auth errors
                # Local servers typically don't require authentication
                os.environ.setdefault("OPENAI_API_KEY", _local_dummy_api_key(provider))

            # DS4 server exposes an OpenAI-compatible API at /v1
            if provider == "ds4" and base_url:
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                os.environ["DS4_HOST"] = clean_url
                os.environ.setdefault("OPENAI_API_KEY", _local_dummy_api_key(provider))

            # For SGLang - configure for OpenAI-compatible API
            if provider == "sglang" and base_url:
                # SGLang uses OpenAI-compatible API at /v1
                # Set OPENAI_API_BASE to the base URL (already includes /v1)
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                # Also set the provider-specific env var
                os.environ["SGLANG_HOST"] = clean_url
                # For local SGLang, set a dummy API key to avoid LiteLLM auth errors
                # Local servers typically don't require authentication
                os.environ.setdefault("OPENAI_API_KEY", _local_dummy_api_key(provider))

            # MLX is handled directly, not through LiteLLM, so no env setup needed

            # Generic local OpenAI-compatible servers (llama.cpp, openai-compatible,
            # and any future local runtime). They route via litellm's openai/ path,
            # which needs OPENAI_API_BASE pointed at the local server; without this
            # they'd silently hit api.openai.com. Handled here so we don't have to
            # hardcode every runtime.
            already_handled = {"ollama", "lmstudio", "vllm", "ds4", "sglang", "mlx"}
            if (
                base_url
                and provider not in already_handled
                and provider_def.category == ProviderCategory.LOCAL
                and provider_def.litellm_prefix == "openai/"
            ):
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                os.environ.setdefault("OPENAI_API_KEY", _local_dummy_api_key(provider))

        # Ensure API keys are set for cloud providers (LiteLLM reads from environment)
        sync_provider_env(provider_def)

        # Google - supports both GOOGLE_API_KEY and GEMINI_API_KEY
        if provider == "google":
            google_key = provider_api_key(provider_def)
            if google_key:
                # Ensure both are set for maximum compatibility
                os.environ["GOOGLE_API_KEY"] = google_key
                if not os.environ.get("GEMINI_API_KEY"):
                    os.environ["GEMINI_API_KEY"] = google_key

    def _apply_dynamic_provider(
        self, provider: str, request_kwargs: Dict[str, Any], model: str = ""
    ) -> None:
        """Set api_base/api_key for dynamic (per-request-routed) providers.

        Curated providers are unaffected unless they opt in via
        ``ProviderDef.dynamic``. Passing these per-request keeps the
        OpenAI-compatible routing isolated from the user's global OPENAI_* env.
        Provider-required headers (``ProviderDef.extra_headers``) are attached
        here too. Placeholders: ``{model}`` → request model id;
        ``{cli_version}`` → installed Grok CLI version (subscription proxy).
        """
        provider_def = _resolve_provider_def(provider)
        if provider_def is None or not provider_def.dynamic:
            return
        from ..dynamic import resolve_base_url

        base_url = resolve_base_url(provider_def)
        api_key = provider_api_key(provider_def)
        if base_url and "api_base" not in request_kwargs:
            request_kwargs["api_base"] = base_url
        if api_key and "api_key" not in request_kwargs:
            request_kwargs["api_key"] = api_key
        if provider_def.extra_headers and "extra_headers" not in request_kwargs:
            cli_version = ""
            if any("{cli_version}" in v for v in provider_def.extra_headers.values()):
                from ..grok_cli_auth import detect_cli_version

                cli_version = detect_cli_version()
            resolved: Dict[str, str] = {}
            for name, value in provider_def.extra_headers.items():
                out = value
                if "{model}" in out:
                    out = out.replace("{model}", model)
                if "{cli_version}" in out:
                    out = out.replace("{cli_version}", cli_version)
                resolved[name] = out
            request_kwargs["extra_headers"] = resolved

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert Message objects to LiteLLM format."""
        result = []
        for msg in messages:
            m = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_calls:
                m["tool_calls"] = self._normalize_tool_calls(msg.tool_calls)
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.reasoning_content:
                m["reasoning_content"] = msg.reasoning_content
            result.append(m)
        return result

    # Providers whose backends honor explicit prompt-cache markers.
    # The dict value is the field name to attach to a content block.
    # OpenAI native auto-caches without explicit markers, so it's not listed.
    _CACHE_PROVIDERS: Dict[str, str] = {
        "anthropic": "cache_control",
        "openrouter": "cache_control",
        "amazon-bedrock": "cache_control",
        "bedrock": "cache_control",
        "vertex": "cache_control",
        "github-copilot": "copilot_cache_control",
    }

    def _apply_prompt_caching(
        self, message_dicts: List[Dict[str, Any]], provider: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Mark cache-eligible messages with provider-specific cache hints.

        Caching strategy: tag the first two
        system messages and the last two non-system messages so the long
        stable prefix (system + tools) and the immediate prior turn both
        cache cheaply across an agent loop's iterations.

        Skipped when:
        - ``SUPERQODE_DISABLE_PROMPT_CACHE`` is set in the environment.
        - The provider isn't known to honor cache markers (OpenAI auto-
          caches, Google/Gemini uses a separate ``cachedContent`` API, etc.).

        Idempotent: re-applying does not duplicate markers.
        """
        if not message_dicts or not provider:
            return message_dicts
        if os.environ.get("SUPERQODE_DISABLE_PROMPT_CACHE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return message_dicts

        field = self._CACHE_PROVIDERS.get(provider)
        if not field:
            return message_dicts

        marker = {field: {"type": "ephemeral"}}

        system_idx = [i for i, m in enumerate(message_dicts) if m.get("role") == "system"][:2]
        non_system_idx = [i for i, m in enumerate(message_dicts) if m.get("role") != "system"][-2:]
        targets = set(system_idx + non_system_idx)

        out: List[Dict[str, Any]] = []
        for i, m in enumerate(message_dicts):
            if i not in targets:
                out.append(m)
                continue
            out.append(self._mark_with_cache(m, field, marker[field]))
        return out

    @staticmethod
    def _mark_with_cache(msg: Dict[str, Any], field: str, value: Dict[str, Any]) -> Dict[str, Any]:
        """Tag the last text block of ``msg`` with ``{field: value}``.

        Converts string content to a one-block list so providers that
        require structured content (Anthropic, Bedrock) parse it correctly.
        Returns a new message — callers must not mutate the original.
        """
        content = msg.get("content")
        if isinstance(content, str):
            if not content:
                return msg
            blocks = [{"type": "text", "text": content, field: value}]
        elif isinstance(content, list) and content:
            blocks = list(content)
            last = blocks[-1]
            if isinstance(last, dict) and last.get("type") == "text":
                if field in last and last[field] == value:
                    return msg  # already marked — idempotent
                blocks[-1] = {**last, field: value}
            else:
                return msg
        else:
            return msg
        return {**msg, "content": blocks}

    # Provider-neutral reasoning effort levels. The names follow OpenAI's
    # o-series convention so users don't have to learn a new vocabulary per
    # backend.
    _REASONING_LEVELS = ("off", "low", "medium", "high", "max")
    _HF_GLM52_THINKING_PROVIDERS = {"zai-org", "novita", "together"}
    _HF_GLM52_REASONING_EFFORT_PROVIDERS = {"fireworks-ai", "deepinfra"}

    # Per-level thinking budgets for Anthropic-shape APIs (Claude
    # extended thinking, DS4's /v1/messages). Values mirror what DS4's
    # model card recommends and what Anthropic publishes for Claude.
    # ``max`` is intentionally just below the 32k ceiling to leave room
    # for the response itself.
    _THINKING_BUDGETS = {
        "low": 1024,
        "medium": 4096,
        "high": 16000,
        "max": 31999,
    }

    def _resolve_reasoning_effort(
        self,
        provider: str,
        model: str,
        level: Optional[str],
    ) -> Dict[str, Any]:
        """Map a neutral ``reasoning_effort`` level to provider-specific kwargs.

        Returns a dict that callers can ``request_kwargs.update(...)`` into
        their LiteLLM call. Empty dict means "no special reasoning config
        needed for this provider/level combo".

        Strategy per provider:

        - **Anthropic** (Claude extended thinking) — emits a top-level
          ``thinking={"type": "enabled", "budget_tokens": N}``. Caller
          must also send ``max_tokens > budget_tokens``.
        - **DS4** — same Anthropic-compatible shape; the gateway's DS4
          path already reads the thinking config inline via
          ``_ds4_thinking_config()`` so we mirror the budgets here for
          parity. The dedicated DS4 path keeps its own env override so
          ``SUPERQODE_DS4_THINKING`` continues to work session-wide.
        - **OpenAI** (o1, o3, GPT-5 family) — emits ``reasoning_effort``
          as a top-level kwarg with values ``low|medium|high`` (no
          ``max``). We collapse ``max`` to ``high`` since OpenAI doesn't
          expose a deeper tier through this field.
        - **OpenRouter** — passes the same field through to whichever
          backend it's routing to; OpenRouter normalizes it.
        - **Others** — no native concept; silently dropped. Better than
          erroring, since users may share one ``reasoning_effort=high``
          across a multi-provider workflow.
        """
        if not level:
            return {}
        level = level.strip().lower()
        if level not in self._REASONING_LEVELS:
            return {}

        hf_glm52 = self._resolve_hf_glm52_reasoning_effort(provider, model, level)
        if hf_glm52 is not None:
            return hf_glm52

        if provider == "zai":
            thinking_type = "disabled" if level == "off" else "enabled"
            result: Dict[str, Any] = {"extra_body": {"thinking": {"type": thinking_type}}}
            if (model or "").lower().split("/")[-1] == "glm-5.2":
                result["reasoning_effort"] = "none" if level == "off" else level
            return result

        if provider == "moonshot" and (model or "").lower().split("/")[-1] == "kimi-k3":
            # K3's pay-as-you-go API currently exposes only max effort and
            # always has thinking enabled. Collapse the provider-neutral
            # effort vocabulary to the one value the endpoint accepts.
            return {"reasoning_effort": "max"}

        model_lower = (model or "").lower()
        is_anthropic_shape = (
            provider == "anthropic" or provider == "ds4" or "deepseek-v4" in model_lower
        )
        if level == "off":
            if is_anthropic_shape:
                return {"thinking": {"type": "disabled"}}
            return {}
        if is_anthropic_shape:
            return {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": self._THINKING_BUDGETS[level],
                }
            }
        if provider in {"openai", "openrouter"}:
            # o-series/GPT-5 doesn't expose a "max" tier on this field.
            return {"reasoning_effort": "high" if level == "max" else level}
        return {}

    @staticmethod
    def _apply_zai_stream_shaping(
        provider: str,
        request_kwargs: Dict[str, Any],
        *,
        has_tools: bool,
    ) -> None:
        """Enable Z.AI's streamed function-call deltas when tools are present."""
        if provider != "zai" or not has_tools:
            return
        extra_body = dict(request_kwargs.get("extra_body") or {})
        extra_body.setdefault("tool_stream", True)
        request_kwargs["extra_body"] = extra_body

    @staticmethod
    def _apply_kimi_k3_request_shaping(
        provider: str,
        model: str,
        request_kwargs: Dict[str, Any],
    ) -> None:
        """Apply the fixed sampling contract of Moonshot's Kimi K3 API."""
        if provider != "moonshot" or (model or "").lower().split("/")[-1] != "kimi-k3":
            return

        for key in ("temperature", "top_p", "n", "presence_penalty", "frequency_penalty"):
            request_kwargs.pop(key, None)

        if "max_tokens" in request_kwargs:
            request_kwargs.setdefault("max_completion_tokens", request_kwargs.pop("max_tokens"))

    def _resolve_hf_glm52_reasoning_effort(
        self,
        provider: str,
        model: str,
        level: str,
    ) -> Optional[Dict[str, Any]]:
        """Map GLM-5.2 over HF Inference Providers to route-specific knobs."""
        if provider != "huggingface":
            return None

        base_model, hf_provider = split_hf_provider_suffix(model)
        if base_model.lower() != "zai-org/glm-5.2":
            return None
        if not hf_provider:
            return {}

        if hf_provider in self._HF_GLM52_REASONING_EFFORT_PROVIDERS:
            effort = "none" if level == "off" else level
            if hf_provider == "deepinfra" and effort == "max":
                effort = "xhigh"
            return {"reasoning_effort": effort}

        if hf_provider in self._HF_GLM52_THINKING_PROVIDERS:
            if level == "off":
                return {"extra_body": {"thinking": {"type": "disabled"}}}
            return {
                "extra_body": {"thinking": {"type": "enabled", "clear_thinking": False}},
                "reasoning_effort": level,
            }

        return {}

    # Structured-output mode. Two values are supported:
    # - ``json``    — request a JSON object back (response_format=json_object
    #                 for OpenAI, equivalent on others where available).
    # - ``tool_use`` — force a single tool call whose arguments are the
    #                  structured output. Works everywhere with tool calling.
    # ``auto`` (the default) means "let the gateway decide" — currently
    # behaves as if unset, leaving the request shape untouched.
    _STRUCTURED_OUTPUT_MODES = ("json", "tool_use", "auto")

    def _resolve_structured_output_mode(
        self,
        provider: str,
        mode: Optional[str],
        has_response_schema: bool,
    ) -> Dict[str, Any]:
        """Translate a neutral structured-output mode to provider kwargs.

        ``has_response_schema`` is informational — when ``True`` we know
        the caller has a JSON Schema to constrain output, so on providers
        that support strict schema mode (OpenAI) we can opt in.
        """
        if not mode:
            return {}
        mode = mode.strip().lower()
        if mode not in self._STRUCTURED_OUTPUT_MODES or mode == "auto":
            return {}

        if mode == "json":
            if provider in {"openai", "openrouter", "azure", "groq"}:
                return {"response_format": {"type": "json_object"}}
            # Anthropic/Bedrock/Vertex don't expose a json mode flag —
            # the agent loop is responsible for the prompt-level "respond
            # with JSON" instruction in that case.
            return {}
        # ``tool_use`` is a request-shape concern handled by the caller
        # (they bind a single tool and set tool_choice). Nothing for the
        # gateway to add as a generic kwarg, but we return the marker so
        # higher layers can detect it.
        return {"_structured_output_mode": "tool_use"}

    # Providers whose backends benefit from local-model request shaping
    # (Ollama-style options, keep_alive, num_ctx). MLX uses the temp-clamp
    # piece of this; the Ollama-specific knobs (keep_alive, num_ctx) are
    # gated on provider == "ollama" inside the shaper itself.
    _LOCAL_SHAPED_PROVIDERS = {"ollama", "mlx", "lmstudio", "vllm", "sglang", "tgi", "llamacpp"}

    # Models whose default Ollama context window is too small (4096) for a
    # coding agent's system + tools prefix. The override is conservative —
    # we cap at what the underlying model actually supports so we don't
    # silently exceed limits and force Ollama into truncation.
    _OLLAMA_CONTEXT_HINTS = {
        "qwen2.5-coder": 32768,
        "qwen2.5": 32768,
        "qwen3": 32768,
        "qwen": 32768,
        "llama3.3": 32768,
        "llama3.2": 32768,
        "llama3.1": 32768,
        "llama3": 8192,
        "deepseek-coder-v2": 32768,
        "deepseek-coder": 16384,
        "mistral": 32768,
        "mixtral": 32768,
        "gpt-oss": 32768,
        "phi": 16384,
        # Gemma 3 / Gemma 4 train at 128K; cap at a practical 32K like the
        # Llama/Qwen peers above. Gemma 1/2 are genuinely 8K.
        "gemma4": 32768,
        "gemma-4": 32768,
        "gemma3": 32768,
        "gemma-3": 32768,
        "gemma2": 8192,
        "gemma": 8192,
    }

    def _ollama_num_ctx_for(self, model: str) -> int:
        """Pick an Ollama num_ctx for ``model``.

        Why this exists: Ollama defaults to num_ctx=4096 regardless of what
        the model's training context allows. With a coding harness whose
        system prompt + tool schemas alone run 2–3k tokens, that leaves
        almost no room for the conversation — Ollama silently truncates
        from the *front*, dropping the system prompt, and the model then
        emits "rubbish" because it no longer knows what tools exist.

        Env override: ``SUPERQODE_OLLAMA_NUM_CTX`` (int) wins if set.
        Otherwise pick the highest hint matching the model name's family.
        Falls back to 8192 (safe-ish for most modern locals).
        """
        env = os.environ.get("SUPERQODE_OLLAMA_NUM_CTX", "").strip()
        if env.isdigit():
            return int(env)
        m = model.lower()
        # Longest-prefix match so "qwen2.5-coder" beats "qwen".
        best = 0
        best_ctx = 8192
        for key, ctx in self._OLLAMA_CONTEXT_HINTS.items():
            if key in m and len(key) > best:
                best = len(key)
                best_ctx = ctx
        return best_ctx

    def _apply_local_request_shaping(
        self,
        provider: str,
        model: str,
        request_kwargs: Dict[str, Any],
        has_tools: bool,
    ) -> None:
        """Tune request params for local-model backends in place.

        Ollama-specific:
        - ``num_ctx`` — see ``_ollama_num_ctx_for``.
        - ``keep_alive`` — hold the model resident between turns so the
          prompt prefix stays warm in KV cache (huge latency win on a
          multi-turn loop).
        - Clamp temperature to ≤0.2 when tools are in play; small local
          models lose tool-call discipline at higher temperatures.

        Mirrors what users would otherwise have to hand-tune via the Ollama
        Modelfile. Set ``SUPERQODE_DISABLE_LOCAL_SHAPING=1`` to opt out.
        """
        if provider not in self._LOCAL_SHAPED_PROVIDERS:
            return
        if os.environ.get("SUPERQODE_DISABLE_LOCAL_SHAPING", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return

        if has_tools:
            cur_temp = request_kwargs.get("temperature")
            if cur_temp is None or cur_temp > 0.2:
                request_kwargs["temperature"] = 0.2

        if provider == "ollama":
            keep_alive = os.environ.get("SUPERQODE_OLLAMA_KEEP_ALIVE", "30m")
            # LiteLLM forwards unknown kwargs into Ollama's "options" payload.
            request_kwargs.setdefault("keep_alive", keep_alive)
            options = dict(request_kwargs.get("options") or {})
            options.setdefault("num_ctx", self._ollama_num_ctx_for(model))
            request_kwargs["options"] = options

    # Patterns the in-band extractor recognizes. Order matters: try the
    # most specific (XML-style tag) first to avoid greedy code-fence matches
    # swallowing tagged blocks.
    _INLINE_TOOL_PATTERNS: List[Tuple[str, str]] = [
        # Qwen / Hermes style
        ("xml", r"<tool_call>\s*(\{.*?\})\s*</tool_call>"),
        # ```tool_call ... ``` or ```json ... ``` code fences
        ("fence", r"```(?:tool_call|json|tool)\s*\n?(\{.*?\})\s*```"),
        # Llama 3.x / Qwen3 function-call style: bare JSON object with a
        # ``name`` (or ``function_name``) field and ``parameters``/``arguments``.
        # Constrained to ``name``-shaped keys so we don't grab arbitrary JSON
        # the model cited in prose (e.g. example payloads in an explanation).
        (
            "bare",
            r'^\s*(\{\s*"(?:function_name|name)"\s*:\s*"[^"]+"\s*,\s*"(?:parameters|arguments)"\s*:\s*\{.*?\}\s*\})\s*$',
        ),
    ]

    def _extract_inline_tool_calls(
        self, content: str
    ) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """Pull tool calls out of plain content emitted by local models.

        Many open-weight models (Qwen 2.5, Llama 3.x, Hermes) emit tool
        calls inline as text instead of through the OpenAI-style
        ``tool_calls`` channel — either as ``<tool_call>{...}</tool_call>``
        or inside a fenced code block. LiteLLM passes those through as
        normal content; the agent loop then sees zero tool calls and the
        model appears to "narrate without acting".

        This shim recognizes those patterns, lifts them into proper
        ``tool_calls`` dicts, and returns the stripped content. Returns
        ``(content, None)`` if no patterns match — safe to call on any
        response.
        """
        import re

        if not content or "{" not in content:
            return content, None

        extracted: List[Dict[str, Any]] = []
        stripped = content
        for kind, pattern in self._INLINE_TOOL_PATTERNS:
            flags = re.DOTALL | (re.MULTILINE if kind == "bare" else 0)
            for match in re.finditer(pattern, stripped, flags):
                raw = match.group(1)
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                name = parsed.get("name") or parsed.get("function_name")
                if not name or not isinstance(name, str):
                    continue
                args = parsed.get("arguments")
                if args is None:
                    args = parsed.get("parameters") or {}
                # Normalize arguments to a JSON string (OpenAI's tool_calls
                # contract — agent loop json.loads it back).
                if isinstance(args, (dict, list)):
                    args_str = json.dumps(args)
                else:
                    args_str = str(args) if args else "{}"
                extracted.append(
                    {
                        "id": f"extracted_{len(extracted)}",
                        "type": "function",
                        "function": {"name": name, "arguments": args_str},
                    }
                )
            if extracted:
                # Strip the matched substrings so the content shown to the
                # user doesn't double up with the tool-call invocation.
                stripped = re.sub(pattern, "", stripped, flags=flags).strip()
                break  # one pattern is enough — don't re-scan the residue

        return stripped, (extracted or None)

    def _convert_tools(
        self, tools: Optional[List[ToolDefinition]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert ToolDefinition objects to LiteLLM format."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    def _normalize_tool_calls(self, tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
        """Normalize tool calls from LiteLLM to dictionaries.

        Handles both dict format and object format (ChatCompletionDeltaToolCall, etc.).
        This is necessary because different LiteLLM providers return tool calls in different formats.
        """
        if not tool_calls:
            return None

        if isinstance(tool_calls, list):
            normalized = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    # Already a dict - ensure the required OpenAI "type" field so
                    # strict parsers (llama.cpp) accept it on the next turn.
                    if "function" in tc and not tc.get("type"):
                        tc = {**tc, "type": "function"}
                    normalized.append(tc)
                else:
                    # Object format (e.g., ChatCompletionDeltaToolCall) - convert to dict
                    tc_dict: Dict[str, Any] = {"type": getattr(tc, "type", None) or "function"}

                    # Extract id if present
                    if hasattr(tc, "id"):
                        tc_dict["id"] = getattr(tc, "id", None)
                    elif hasattr(tc, "tool_call_id"):
                        tc_dict["id"] = getattr(tc, "tool_call_id", None)

                    # Extract function info
                    if hasattr(tc, "function"):
                        func = getattr(tc, "function")
                        if isinstance(func, dict):
                            tc_dict["function"] = func
                        else:
                            # Function object - extract fields
                            func_dict = {}
                            if hasattr(func, "name"):
                                func_dict["name"] = getattr(func, "name", "")
                            if hasattr(func, "arguments"):
                                func_dict["arguments"] = getattr(func, "arguments", "{}")
                            elif hasattr(func, "argument"):
                                func_dict["arguments"] = getattr(func, "argument", "{}")
                            tc_dict["function"] = func_dict
                    elif hasattr(tc, "name") or hasattr(tc, "function_name"):
                        # Tool call might have name directly
                        func_dict = {
                            "name": getattr(tc, "name", None) or getattr(tc, "function_name", ""),
                            "arguments": getattr(tc, "arguments", None)
                            or getattr(tc, "args", "{}")
                            or "{}",
                        }
                        tc_dict["function"] = func_dict

                    # If we couldn't extract anything useful, skip it
                    if not tc_dict or "function" not in tc_dict:
                        continue

                    normalized.append(tc_dict)
            return normalized if normalized else None

        # Single tool call (not a list) - wrap in list and process
        if isinstance(tool_calls, dict):
            return [tool_calls]
        else:
            # Object format - normalize it by wrapping in list
            result = self._normalize_tool_calls([tool_calls])
            return result

    def _handle_litellm_error(self, e: Exception, provider: str, model: str) -> None:
        """Convert LiteLLM exceptions to gateway errors."""
        litellm = self._get_litellm()
        error_msg = str(e)

        # Get provider info for helpful error messages
        provider_def = PROVIDERS.get(provider)
        docs_url = provider_def.docs_url if provider_def else ""
        env_vars = provider_def.env_vars if provider_def else []

        # Check for specific error types
        if isinstance(e, litellm.AuthenticationError):
            env_hint = f"Set {' or '.join(env_vars)}" if env_vars else ""
            raise AuthenticationError(
                f"Invalid API key for provider '{provider}'. {env_hint}. "
                f"Get your key at: {docs_url}",
                provider=provider,
                model=model,
                error_type="authentication",
            ) from e

        if isinstance(e, litellm.RateLimitError):
            raise RateLimitError(
                f"Rate limit exceeded for provider '{provider}'. "
                "Wait and retry, or upgrade your API plan.",
                provider=provider,
                model=model,
                error_type="rate_limit",
            ) from e

        if isinstance(e, litellm.NotFoundError):
            example_models = provider_def.example_models if provider_def else []
            models_hint = (
                f"Available models: {', '.join(example_models[:5])}" if example_models else ""
            )
            raise ModelNotFoundError(
                f"Model '{model}' not found for provider '{provider}'. {models_hint}",
                provider=provider,
                model=model,
                error_type="model_not_found",
            ) from e

        if isinstance(e, litellm.BadRequestError):
            raise InvalidRequestError(
                f"Invalid request to '{provider}': {error_msg}",
                provider=provider,
                model=model,
                error_type="invalid_request",
            ) from e

        # Generic error
        raise GatewayError(
            f"Error calling '{provider}/{model}': {error_msg}",
            provider=provider,
            model=model,
        ) from e

    async def _mlx_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """MLX chat completion.

        Primary path is the in-process engine (``mlx_lm`` via a worker), where
        SuperQode owns tool-call parsing — no ``mlx_lm.server`` and no reliance
        on its tool parser. Falls back to the HTTP server path when the engine
        is unavailable (mlx_lm not installed, worker error) or explicitly
        disabled via ``SUPERQODE_MLX_INPROCESS=0``.
        """
        use_inprocess = os.environ.get("SUPERQODE_MLX_INPROCESS", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        if use_inprocess:
            try:
                return await self._mlx_inprocess_chat_completion(
                    messages, model, temperature, max_tokens, tools, tool_choice, **dict(kwargs)
                )
            except Exception as exc:  # noqa: BLE001 - fall back to the HTTP server path
                logger.info("MLX in-process engine unavailable (%s); falling back to server", exc)
        return await self._mlx_http_chat_completion(
            messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
        )

    async def _mlx_inprocess_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Run MLX generation in-process and parse tool calls ourselves."""
        import asyncio

        from ..local.mlx_engine import get_mlx_engine
        from ..local.mlx_tools import parse_tool_calls, resolve_format

        budget_for_credit: Optional[TaskTokenBudget] = kwargs.pop("task_budget", None)
        fmt = resolve_format(model, kwargs.get("tool_call_format"))

        oai_messages = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools) if tools else None

        engine = get_mlx_engine()
        result = await asyncio.to_thread(
            engine.generate,
            model=model,
            messages=oai_messages,
            tools=converted_tools,
            max_tokens=max_tokens or 2048,
            temperature=temperature,
        )

        content, tool_calls = parse_tool_calls(result.text, fmt)

        usage = None
        total = result.usage.get("total_tokens") if result.usage else None
        if total:
            usage = Usage(
                prompt_tokens=result.usage.get("prompt_tokens") or 0,
                completion_tokens=result.usage.get("completion_tokens") or 0,
                total_tokens=total,
            )
            if budget_for_credit is not None:
                budget_for_credit.credit(total)

        return GatewayResponse(
            content=content,
            role="assistant",
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
            model=model,
            provider="mlx",
            tool_calls=tool_calls or None,
            raw_response={"text": result.text, "backend": result.backend},
        )

    async def _mlx_http_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Handle MLX chat completion via the mlx_lm.server HTTP API (fallback)."""
        from ..local.mlx import MLXClient

        client = MLXClient()

        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_msg = {"role": msg.role, "content": msg.content}
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            openai_messages.append(openai_msg)

        # Build request
        request_data = {
            "model": model,
            "messages": openai_messages,
        }

        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        # MLX doesn't honor reasoning/structured-output natively; strip
        # so the markers don't leak into the wire payload.
        kwargs.pop("reasoning_effort", None)
        kwargs.pop("structured_output_mode", None)
        budget_for_credit: Optional[TaskTokenBudget] = kwargs.pop("task_budget", None)

        # Same shaping the LiteLLM path applies for Ollama-family locals:
        # clamp temperature when tools are present so the small MLX model
        # doesn't dribble out half-formed tool JSON.
        self._apply_local_request_shaping("mlx", model, request_data, bool(tools))

        try:
            # Make direct request to MLX server (MLX models can be slow)
            response_data = await client._async_request(
                "POST", "/v1/chat/completions", request_data, timeout=300.0
            )

            # Extract response
            choice = response_data["choices"][0]
            message = choice["message"]

            # Build usage info
            usage_data = response_data.get("usage", {})
            usage = None
            if usage_data:
                usage = Usage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )
                if budget_for_credit is not None:
                    budget_for_credit.credit(usage.total_tokens)

            # Clean up MLX response content - remove special tokens that might confuse users
            content = message.get("content", "")
            if content:
                # Some MLX models return content with special tokens like <|channel|>, <|message|>, etc.
                # Clean these up for better user experience
                content = (
                    content.replace("<|channel|>", "")
                    .replace("<|message|>", "")
                    .replace("<|end|>", "")
                    .replace("<|start|>", "")
                )
                content = content.replace(
                    "assistant", ""
                ).strip()  # Remove duplicate assistant markers

            # Normalize native tool_calls and, failing that, scan the
            # content for in-band tool calls (Gemma/Llama don't emit
            # OpenAI-shaped tool_calls reliably under MLX).
            tool_calls = self._normalize_tool_calls(message.get("tool_calls"))
            if not tool_calls and isinstance(content, str) and content:
                stripped, extracted = self._extract_inline_tool_calls(content)
                if extracted:
                    tool_calls = extracted
                    content = stripped

            return GatewayResponse(
                content=content,
                role=message.get("role", "assistant"),
                finish_reason=choice.get("finish_reason"),
                usage=usage,
                model=response_data.get("model", model),
                provider="mlx",
                tool_calls=tool_calls,
                raw_response=response_data,
            )

        except Exception as e:
            # Provide more specific MLX error messages
            error_msg = str(e)
            if "broadcast_shapes" in error_msg or "cannot be broadcast" in error_msg:
                raise GatewayError(
                    f"MLX server encountered a KV cache conflict (concurrent request issue).\n\n"
                    f"This happens when multiple requests are sent to the MLX server simultaneously.\n"
                    f"MLX servers can only handle one request at a time to avoid memory conflicts.\n\n"
                    f"To fix:\n"
                    f"1. Wait for any running requests to complete\n"
                    f"2. superqode providers mlx list - Check server status\n"
                    f"3. If server crashed: superqode providers mlx server --model {model} - Restart server\n"
                    f"4. Try your request again with only one active session\n\n"
                    f"MLX Tip: Each model needs its own server instance for concurrent use",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Expecting value" in error_msg or "Invalid JSON" in error_msg:
                raise GatewayError(
                    f"MLX server returned invalid response.\n\n"
                    f"This usually means the MLX server crashed or is in an error state.\n\n"
                    f"To fix:\n"
                    f"1. superqode providers mlx list - Check if server is running\n"
                    f"2. If not running: superqode providers mlx server --model {model} - Start server\n"
                    f"3. Wait 1-2 minutes for large models to load\n"
                    f"4. Try again",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection refused" in error_msg:
                raise GatewayError(
                    f"Cannot connect to MLX server at http://localhost:8080.\n\n"
                    f"MLX server is not running. To fix:\n\n"
                    f"1. superqode providers mlx setup - Complete setup guide\n"
                    f"2. superqode providers mlx server --model {model} - Get server command\n"
                    f"3. Run the server command in a separate terminal\n"
                    f"4. Try connecting again",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection timed out" in error_msg or "timeout" in error_msg.lower():
                raise GatewayError(
                    f"MLX server timed out. Large MLX models (like {model}) can take 1-2 minutes for first response.\n\n"
                    f"Please wait and try again. If this persists:\n"
                    f"1. Check server is still running: superqode providers mlx list\n"
                    f"2. Try a smaller model for testing\n"
                    f"3. Restart the server if needed",
                    provider="mlx",
                    model=model,
                ) from e
            else:
                # Convert to gateway error
                self._handle_litellm_error(e, "mlx", model)

    async def _lmstudio_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Handle LM Studio chat completion directly to control endpoint."""
        import aiohttp
        from ..registry import PROVIDERS

        # Get LM Studio base URL
        provider_def = PROVIDERS.get("lmstudio")
        base_url = provider_def.default_base_url if provider_def else "http://localhost:1234"
        if provider_def and provider_def.base_url_env:
            base_url = os.environ.get(provider_def.base_url_env, base_url)

        # LM Studio typically serves at /v1/chat/completions
        url = f"{base_url.rstrip('/')}/v1/chat/completions"

        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_msg = {"role": msg.role, "content": msg.content}
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            openai_messages.append(openai_msg)

        # Build request
        request_data = {
            "model": model,
            "messages": openai_messages,
        }

        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_local_dummy_api_key('lmstudio')}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=request_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120.0),
                ) as response:
                    response_data = await response.json()

                    # Extract response
                    choice = response_data["choices"][0]
                    message = choice["message"]

                    # Build usage info
                    usage_data = response_data.get("usage", {})
                    usage = None
                    if usage_data:
                        usage = Usage(
                            prompt_tokens=usage_data.get("prompt_tokens", 0),
                            completion_tokens=usage_data.get("completion_tokens", 0),
                            total_tokens=usage_data.get("total_tokens", 0),
                        )

                    return GatewayResponse(
                        content=message.get("content", ""),
                        role=message.get("role", "assistant"),
                        finish_reason=choice.get("finish_reason"),
                        usage=usage,
                        model=response_data.get("model", model),
                        provider="lmstudio",
                        tool_calls=message.get("tool_calls"),
                        raw_response=response_data,
                    )

        except aiohttp.ClientError as e:
            if "Connection refused" in str(e):
                raise GatewayError(
                    f"Cannot connect to LM Studio server at {base_url}.\n\n"
                    f"LM Studio server is not running. To fix:\n\n"
                    f"1. [cyan]Open LM Studio application[/cyan]\n"
                    f"2. [cyan]Load a model (like qwen/qwen3-30b)[/cyan]\n"
                    f"3. [cyan]Start the local server[/cyan]\n"
                    f"4. Try connecting again",
                    provider="lmstudio",
                    model=model,
                ) from e
            else:
                raise GatewayError(
                    f"LM Studio request failed: {str(e)}",
                    provider="lmstudio",
                    model=model,
                ) from e
        except Exception as e:
            raise GatewayError(
                f"LM Studio error: {str(e)}",
                provider="lmstudio",
                model=model,
            ) from e

    def _ds4_thinking_config(self) -> Optional[Dict[str, Any]]:
        """Resolve DS4's ``thinking`` request field from env.

        ``SUPERQODE_DS4_THINKING`` controls reasoning effort for DS4's
        Anthropic-compatible ``/v1/messages`` endpoint:

        - ``off`` / ``disabled`` / ``none`` / ``0`` / ``false`` →
          ``{"type": "disabled"}`` (no thinking section).
        - ``low`` / ``medium`` / ``high`` / ``max`` →
          ``{"type": "enabled", "budget_tokens": N}`` with budgets that
          mirror the model card's regimes; ``max`` requests DS4's Think Max.
        - unset / ``auto`` / ``default`` → return ``None`` so DS4's own
          default applies (thinking enabled, normal regime).

        Returns ``None`` to mean "don't send a thinking field at all", which
        keeps the rendered prefix stable for sessions that don't pin a level.
        """
        mode = os.getenv("SUPERQODE_DS4_THINKING", "").strip().lower()
        if not mode or mode in {"auto", "default"}:
            return None
        if mode in {"off", "disabled", "none", "no", "0", "false"}:
            return {"type": "disabled"}
        budgets = {
            "low": 1024,
            "medium": 4096,
            "high": 16000,
            "max": 31999,
        }
        budget = budgets.get(mode)
        if budget is None:
            return None
        return {"type": "enabled", "budget_tokens": budget}

    def _ds4_server_url(self) -> str:
        """Return the DS4 server base URL with any trailing ``/v1`` stripped.

        Both ``/v1/messages`` and ``/v1/chat/completions`` are appended by
        callers, so this returns just the host root (e.g. ``http://127.0.0.1:8000``).
        """
        provider_def = PROVIDERS.get("ds4")
        base = provider_def.default_base_url if provider_def else "http://127.0.0.1:8000/v1"
        if provider_def and provider_def.base_url_env:
            base = os.environ.get(provider_def.base_url_env, base)
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base

    def _ds4_convert_tools_anthropic(
        self, tools: Optional[List[ToolDefinition]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert ToolDefinition list to DS4 ``/v1/messages`` (Anthropic) format."""
        if not tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.parameters or {"type": "object", "properties": {}},
            }
            for t in tools
        ]

    def _ds4_convert_to_anthropic(
        self, messages: List[Message]
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Convert gateway messages to DS4 ``/v1/messages`` format.

        Returns ``(system_text, messages)``:

        - System messages are joined and lifted to the top-level ``system`` field.
        - ``role="tool"`` messages become ``role="user"`` with ``tool_result``
          content blocks. Consecutive tool results are merged into a single
          user message, which the Anthropic spec requires when the previous
          assistant turn emitted multiple parallel ``tool_use`` blocks.
        - Assistant ``tool_calls`` become standalone ``tool_use`` blocks, each
          carrying the original ``id`` so DS4's exact-DSML replay map stays
          intact across turns.
        - Assistant reasoning becomes a ``thinking`` block. Laguna S 2.1
          explicitly requires prior reasoning to be preserved between tool
          calls; dropping it can make the model restart or stop reasoning.
        """
        system_parts: List[str] = []
        out: List[Dict[str, Any]] = []
        pending_tool_results: List[Dict[str, Any]] = []

        def flush_pending() -> None:
            if pending_tool_results:
                out.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results.clear()

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(
                        msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                    )
                continue

            if msg.role == "tool":
                content_text = (
                    msg.content
                    if isinstance(msg.content, str)
                    else (json.dumps(msg.content) if msg.content is not None else "")
                )
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": content_text,
                    }
                )
                continue

            # Any non-tool message terminates the run of pending tool results.
            flush_pending()

            content_blocks: List[Dict[str, Any]] = []
            if msg.role == "assistant" and msg.reasoning_content:
                content_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": msg.reasoning_content,
                    }
                )
            if msg.content:
                if isinstance(msg.content, str):
                    content_blocks.append({"type": "text", "text": msg.content})
                elif isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, str):
                            content_blocks.append({"type": "text", "text": part})
                        elif isinstance(part, dict) and part.get("type") == "text":
                            content_blocks.append(part)

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = tc.get("id")
                    if not tc_id:
                        # Without an id we cannot round-trip to a matching
                        # tool_result; drop the call rather than fabricate one
                        # that breaks DS4's exact-DSML replay map.
                        continue
                    func = tc.get("function", {}) or {}
                    args = func.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            tc_input = json.loads(args) if args else {}
                        except json.JSONDecodeError:
                            tc_input = {}
                    elif isinstance(args, dict):
                        tc_input = args
                    else:
                        tc_input = {}
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc_id,
                            "name": func.get("name", ""),
                            "input": tc_input,
                        }
                    )

            if content_blocks:
                out.append({"role": msg.role, "content": content_blocks})

        flush_pending()

        system_text = "\n\n".join(system_parts).strip() or None
        return system_text, out

    async def _ds4_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Handle DS4 directly through its OpenAI-compatible endpoint.

        DS4 is a local server; using LiteLLM's generic OpenAI adapter can add or
        transform parameters that strict local parsers reject. Keep the request
        payload small and explicit.
        """
        import aiohttp

        provider_def = PROVIDERS.get("ds4")
        base_url = provider_def.default_base_url if provider_def else "http://127.0.0.1:8000/v1"
        if provider_def and provider_def.base_url_env:
            base_url = os.environ.get(provider_def.base_url_env, base_url)

        url = f"{base_url.rstrip('/')}/chat/completions"

        request_data = {
            "model": model,
            "messages": self._convert_messages(messages),
        }
        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_local_dummy_api_key('ds4')}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=request_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    response_text = await response.text()
                    if response.status >= 400:
                        raise GatewayError(
                            f"DS4 request failed with HTTP {response.status}.\n\n"
                            f"Endpoint: {url}\n"
                            f"Response: {response_text}",
                            provider="ds4",
                            model=model,
                        )
                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        raise GatewayError(
                            f"DS4 returned non-JSON response from {url}:\n{response_text}",
                            provider="ds4",
                            model=model,
                        ) from e

            choice = response_data["choices"][0]
            message = choice["message"]
            usage_data = response_data.get("usage", {})
            usage = None
            if usage_data:
                usage = Usage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )

            return GatewayResponse(
                content=message.get("content", "") or "",
                role=message.get("role", "assistant"),
                finish_reason=choice.get("finish_reason"),
                usage=usage,
                model=response_data.get("model", model),
                provider="ds4",
                tool_calls=message.get("tool_calls"),
                raw_response=response_data,
            )

        except aiohttp.ClientError as e:
            raise GatewayError(
                f"Cannot connect to DS4 server at {base_url}.\n\n"
                f"Start ds4-server, then retry:\n"
                f"./ds4-server --ctx 100000 --kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 8192\n\n"
                f"If DS4 is running somewhere else, set DS4_HOST.",
                provider="ds4",
                model=model,
            ) from e

    async def _ds4_messages_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Handle DS4 using /v1/messages (Anthropic-compatible API).

        This endpoint provides better tool calling support with the native
        Anthropic-style tool format and supports KV cache persistence via
        the server's rendered-prefix lookup for efficient context reuse.
        """
        import aiohttp

        url = f"{self._ds4_server_url()}/v1/messages"

        system_text, anthropic_messages = self._ds4_convert_to_anthropic(messages)

        request_data: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 8192,
        }
        if system_text:
            request_data["system"] = system_text
        if temperature is not None:
            request_data["temperature"] = temperature

        # Per-call reasoning override (kwarg wins over the env-based
        # SUPERQODE_DS4_THINKING default). Lets a caller bump a single
        # turn to think_max without changing session-wide config.
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        if reasoning_effort:
            resolved = self._resolve_reasoning_effort("ds4", model, reasoning_effort)
            if "thinking" in resolved:
                request_data["thinking"] = resolved["thinking"]
        else:
            thinking_cfg = self._ds4_thinking_config()
            if thinking_cfg is not None:
                request_data["thinking"] = thinking_cfg

        anthropic_tools = self._ds4_convert_tools_anthropic(tools)
        if anthropic_tools:
            request_data["tools"] = anthropic_tools
            request_data["tool_choice"] = {"type": "auto"}

        # DS4 doesn't accept reasoning_effort / structured_output_mode /
        # task_budget on the wire. Strip so leftover kwargs don't fan out
        # into aiohttp by accident in any future refactor.
        budget_for_credit: Optional[TaskTokenBudget] = kwargs.pop("task_budget", None)
        kwargs.pop("structured_output_mode", None)

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "Authorization": f"Bearer {_local_dummy_api_key('ds4')}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=request_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    response_text = await response.text()
                    if response.status >= 400:
                        raise GatewayError(
                            f"DS4 /v1/messages request failed with HTTP {response.status}.\n\n"
                            f"Endpoint: {url}\n"
                            f"Response: {response_text}",
                            provider="ds4",
                            model=model,
                        )

                    response_data = json.loads(response_text)

            content = response_data.get("content", [])
            text_content = ""
            thinking_parts: List[str] = []
            tool_calls = []

            for block in content:
                if block.get("type") == "text":
                    text_content += block.get("text", "")
                elif block.get("type") in {"thinking", "summary"}:
                    thinking = (
                        block.get("thinking") or block.get("summary") or block.get("text") or ""
                    )
                    if thinking:
                        thinking_parts.append(str(thinking))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )

            usage_data = response_data.get("usage", {})
            usage = None
            if usage_data:
                usage = Usage(
                    prompt_tokens=usage_data.get("input_tokens", 0),
                    completion_tokens=usage_data.get("output_tokens", 0),
                    total_tokens=usage_data.get("input_tokens", 0)
                    + usage_data.get("output_tokens", 0),
                )
                if budget_for_credit is not None:
                    budget_for_credit.credit(usage.total_tokens)

            return GatewayResponse(
                content=text_content,
                role="assistant",
                finish_reason=response_data.get("stop_reason"),
                usage=usage,
                model=response_data.get("model", model),
                provider="ds4",
                tool_calls=tool_calls if tool_calls else None,
                raw_response=response_data,
                thinking_content="".join(thinking_parts) or None,
            )

        except aiohttp.ClientError as e:
            raise GatewayError(
                f"Cannot connect to DS4 server at {self._ds4_server_url()}.\n\n"
                f"Start ds4-server, then retry:\n"
                f"./ds4-server --ctx 32768 --kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 8192\n\n"
                f"For long coding sessions, use --ctx 100000 if you have memory headroom. "
                f"Think Max requires --ctx >= 393216.\n\n"
                f"If DS4 is running somewhere else, set DS4_HOST.",
                provider="ds4",
                model=model,
            ) from e

    async def _ds4_messages_stream(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Handle DS4 streaming with /v1/messages (Anthropic-compatible API).

        Uses SSE streaming for real-time token-by-token output with proper
        tool call handling.
        """
        import aiohttp

        url = f"{self._ds4_server_url()}/v1/messages"

        system_text, anthropic_messages = self._ds4_convert_to_anthropic(messages)

        request_data: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 8192,
            "stream": True,
        }
        if system_text:
            request_data["system"] = system_text
        if temperature is not None:
            request_data["temperature"] = temperature

        thinking_cfg = self._ds4_thinking_config()
        if thinking_cfg is not None:
            request_data["thinking"] = thinking_cfg

        anthropic_tools = self._ds4_convert_tools_anthropic(tools)
        if anthropic_tools:
            request_data["tools"] = anthropic_tools
            request_data["tool_choice"] = {"type": "auto"}

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "Authorization": f"Bearer {_local_dummy_api_key('ds4')}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=request_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    if response.status >= 400:
                        response_text = await response.text()
                        raise GatewayError(
                            f"DS4 streaming request failed with HTTP {response.status}.\n\n"
                            f"Response: {response_text}",
                            provider="ds4",
                            model=model,
                        )

                    # Parse the Anthropic SSE event stream. Per the spec, tool
                    # argument fragments arrive as ``input_json_delta`` events
                    # whose ``partial_json`` field is a raw substring of the
                    # final JSON — not a parseable object. We must concatenate
                    # the fragments and parse once at ``content_block_stop``.
                    # ``stop_reason`` and ``usage`` arrive on ``message_delta``,
                    # not on ``message_stop``.
                    final_stop_reason: Optional[str] = None
                    final_usage_data: Dict[str, Any] = {}
                    tool_blocks: Dict[int, Dict[str, Any]] = {}
                    tool_arg_buffers: Dict[int, str] = {}

                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if not line.startswith("data:"):
                            continue

                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue

                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        if event_type == "message_start":
                            msg_payload = event.get("message", {}) or {}
                            usage = msg_payload.get("usage")
                            if isinstance(usage, dict):
                                final_usage_data.update(usage)

                        elif event_type == "content_block_start":
                            index = event.get("index", 0)
                            block = event.get("content_block") or event.get("block") or {}
                            if block.get("type") == "tool_use":
                                tool_blocks[index] = {
                                    "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": block.get("name", ""),
                                        "arguments": "",
                                    },
                                }
                                tool_arg_buffers[index] = ""

                        elif event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            delta_type = delta.get("type")
                            index = event.get("index", 0)

                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield StreamChunk(
                                        content=text,
                                        role="assistant",
                                        finish_reason=None,
                                    )
                            elif delta_type == "input_json_delta":
                                if index in tool_arg_buffers:
                                    tool_arg_buffers[index] += delta.get("partial_json", "")
                            elif delta_type in ("thinking_delta", "summary_delta"):
                                thinking = (
                                    delta.get("thinking")
                                    or delta.get("text")
                                    or delta.get("summary")
                                    or ""
                                )
                                if thinking:
                                    yield StreamChunk(
                                        content="",
                                        role="assistant",
                                        finish_reason=None,
                                        thinking_content=thinking,
                                    )

                        elif event_type == "content_block_stop":
                            index = event.get("index", 0)
                            if index in tool_blocks:
                                raw = tool_arg_buffers.get(index, "") or "{}"
                                try:
                                    json.loads(raw)
                                    tool_blocks[index]["function"]["arguments"] = raw
                                except json.JSONDecodeError:
                                    tool_blocks[index]["function"]["arguments"] = "{}"

                        elif event_type == "message_delta":
                            delta = event.get("delta", {})
                            stop_reason = delta.get("stop_reason")
                            if stop_reason:
                                final_stop_reason = stop_reason
                            usage = event.get("usage")
                            if isinstance(usage, dict):
                                final_usage_data.update(usage)

                        elif event_type == "message_stop":
                            tool_calls_out = [
                                tc
                                for _, tc in sorted(tool_blocks.items())
                                if tc.get("function", {}).get("name")
                            ] or None

                            usage_obj: Optional[Usage] = None
                            if final_usage_data:
                                prompt_tokens = int(final_usage_data.get("input_tokens") or 0)
                                completion_tokens = int(final_usage_data.get("output_tokens") or 0)
                                usage_obj = Usage(
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    total_tokens=prompt_tokens + completion_tokens,
                                )

                            yield StreamChunk(
                                content="",
                                role="assistant",
                                finish_reason=final_stop_reason or "end_turn",
                                tool_calls=tool_calls_out,
                                usage=usage_obj,
                            )

        except aiohttp.ClientError as e:
            raise GatewayError(
                f"Cannot connect to DS4 server at {self._ds4_server_url()}",
                provider="ds4",
                model=model,
            ) from e

    async def _mlx_stream_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Handle MLX streaming completion directly."""
        from ..local.mlx import MLXClient

        client = MLXClient()

        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_msg = {"role": msg.role, "content": msg.content}
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            openai_messages.append(openai_msg)

        # Build request - MLX server may not support streaming properly, so use non-streaming
        request_data = {
            "model": model,
            "messages": openai_messages,
            # Note: Not setting stream=True as MLX server streaming may cause KV cache issues
        }

        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        # Same local-model shaping (temp clamp) as the non-streaming path.
        self._apply_local_request_shaping("mlx", model, request_data, bool(tools))

        try:
            # Make non-streaming request to MLX server (streaming causes KV cache issues)
            response_data = await client._async_request(
                "POST", "/v1/chat/completions", request_data, timeout=300.0
            )

            # Extract response and yield as single chunk
            choice = response_data["choices"][0]
            message = choice["message"]

            # Get content and clean it up
            content = message.get("content", "")

            # Clean up MLX response content - remove special tokens that might confuse users
            if content:
                # Some MLX models return content with special tokens like <|channel|>, <|message|>, etc.
                # Clean these up for better user experience
                content = (
                    content.replace("<|channel|>", "")
                    .replace("<|message|>", "")
                    .replace("<|end|>", "")
                    .replace("<|start|>", "")
                )
                content = content.replace(
                    "assistant", ""
                ).strip()  # Remove duplicate assistant markers

            # Same tool-call rescue as the non-streaming MLX path: normalize
            # native tool_calls, else scan for inline tool calls (Gemma/Llama
            # variants under MLX often emit <tool_call> tags instead).
            tool_calls = self._normalize_tool_calls(message.get("tool_calls"))
            if not tool_calls and isinstance(content, str) and content:
                stripped, extracted = self._extract_inline_tool_calls(content)
                if extracted:
                    tool_calls = extracted
                    content = stripped

            yield StreamChunk(
                content=content,
                role=message.get("role"),
                finish_reason="tool_calls" if tool_calls else choice.get("finish_reason"),
                tool_calls=tool_calls,
                usage=(
                    Usage(
                        prompt_tokens=int(response_data.get("usage", {}).get("prompt_tokens") or 0),
                        completion_tokens=int(
                            response_data.get("usage", {}).get("completion_tokens") or 0
                        ),
                        total_tokens=int(response_data.get("usage", {}).get("total_tokens") or 0),
                    )
                    if response_data.get("usage")
                    else None
                ),
            )

        except Exception as e:
            # Provide more specific MLX error messages
            error_msg = str(e)
            if "broadcast_shapes" in error_msg or "cannot be broadcast" in error_msg:
                raise GatewayError(
                    f"MLX server encountered a KV cache conflict (concurrent request issue).\n\n"
                    f"This happens when multiple requests are sent to the MLX server simultaneously.\n"
                    f"MLX servers can only handle one request at a time to avoid memory conflicts.\n\n"
                    f"To fix:\n"
                    f"1. [yellow]Wait for any running requests to complete[/yellow]\n"
                    f"2. [cyan]superqode providers mlx list[/cyan] - Check server status\n"
                    f"3. If server crashed: [cyan]superqode providers mlx server --model {model}[/cyan] - Restart server\n"
                    f"4. Try your request again with only one active session\n\n"
                    f"[dim]💡 MLX Tip: Each model needs its own server instance for concurrent use[/dim]",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection refused" in error_msg:
                raise GatewayError(
                    f"Cannot connect to MLX server at http://localhost:8080.\n\n"
                    f"MLX server is not running. To fix:\n\n"
                    f"1. [cyan]superqode providers mlx setup[/cyan] - Complete setup guide\n"
                    f"2. [cyan]superqode providers mlx server --model {model}[/cyan] - Get server command\n"
                    f"3. Run the server command in a separate terminal\n"
                    f"4. Try connecting again",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection timed out" in error_msg or "timeout" in error_msg.lower():
                raise GatewayError(
                    f"MLX server timed out. Large MLX models (like {model}) can take 1-2 minutes for first response.\n\n"
                    f"Please wait and try again. If this persists:\n"
                    f"1. Check server is still running: [cyan]superqode providers mlx list[/cyan]\n"
                    f"2. Try a smaller model for testing\n"
                    f"3. Restart the server if needed",
                    provider="mlx",
                    model=model,
                ) from e
            else:
                # Convert to gateway error
                self._handle_litellm_error(e, "mlx", model)

    async def chat_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Make a chat completion request via LiteLLM."""

        # Determine provider from model string if not specified.
        if provider:
            provider = normalize_provider_id(provider)
            model = normalize_model_for_provider(provider, model)
        else:
            parsed = split_provider_model_ref(model)
            provider = parsed.provider or "unknown"
            model = parsed.model

        # Per-task budget pre-check. Done before any provider dispatch so
        # DS4 / MLX / LMStudio all share the fail-fast behavior; the
        # specialized methods credit usage themselves on the way out.
        # We peek without popping so dispatched methods can still credit.
        task_budget: Optional[TaskTokenBudget] = kwargs.get("task_budget")
        if task_budget is not None:
            task_budget.check()

        # Special handling for MLX - use direct client instead of LiteLLM
        if provider == "mlx":
            return await self._mlx_chat_completion(
                messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
            )

        # Special handling for LM Studio - use direct client to avoid cloud API
        if provider == "lmstudio":
            return await self._lmstudio_chat_completion(
                messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
            )

        # Special handling for DS4 - use Anthropic-compatible /v1/messages endpoint
        # for better tool calling and KV cache support
        if provider == "ds4":
            return await self._ds4_messages_completion(
                messages, model, temperature, max_tokens, tools, **kwargs
            )

        litellm = self._get_litellm()

        # Set up provider environment
        self._setup_provider_env(provider)

        # Build request
        request_kwargs = {
            "messages": self._apply_prompt_caching(self._convert_messages(messages), provider),
            "timeout": self.timeout,
        }

        # Explicitly pass API keys for providers that need them
        # Some LiteLLM versions require explicit api_key parameter.
        provider_def = _resolve_provider_def(provider)
        if provider_def:
            api_key = _request_api_key(provider, provider_def)
            if api_key and "api_key" not in request_kwargs:
                request_kwargs["api_key"] = api_key

        # models.dev-synthesized providers: inject api_base/api_key explicitly.
        self._apply_dynamic_provider(provider, request_kwargs, model=model)

        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if tools:
            request_kwargs["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice

        # Provider-neutral reasoning effort + structured output. Pulled
        # from kwargs so callers can pass them through transparently;
        # the gateway translates to whatever the backend expects.
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        structured_output_mode = kwargs.pop("structured_output_mode", None)
        response_schema = kwargs.get("response_schema")
        if reasoning_effort:
            request_kwargs.update(self._resolve_reasoning_effort(provider, model, reasoning_effort))
        if structured_output_mode:
            request_kwargs.update(
                self._resolve_structured_output_mode(
                    provider, structured_output_mode, response_schema is not None
                )
            )
            # Internal-only marker — strip before sending to LiteLLM.
            request_kwargs.pop("_structured_output_mode", None)

        # Strip the budget marker — it's our concern, not LiteLLM's.
        # (Pre-check already happened at the dispatcher's entry point.)
        budget_for_credit: Optional[TaskTokenBudget] = kwargs.pop("task_budget", None)

        # Add any remaining extra kwargs
        request_kwargs.update(kwargs)

        # Local-model tuning (Ollama num_ctx, keep_alive, tool-temp clamp).
        # Applied after kwargs merge so user overrides via extra kwargs win.
        self._apply_local_request_shaping(provider, model, request_kwargs, bool(tools))
        self._apply_kimi_k3_request_shaping(provider, model, request_kwargs)

        try:
            model_candidates = self._get_model_candidates(provider, model)
            response = None
            last_error = None
            for i, candidate in enumerate(model_candidates):
                request_kwargs["model"] = candidate
                try:
                    response = await self._acompletion_with_retry(request_kwargs)
                    break
                except Exception as e:
                    last_error = e
                    is_last = i == len(model_candidates) - 1
                    retryable = self._is_model_not_found_error(
                        e
                    ) or self._is_retryable_provider_transport_error(e)
                    if is_last or not retryable:
                        raise
                    continue

            if response is None and last_error is not None:
                raise last_error

            # Extract response data
            choice = response.choices[0]
            message = choice.message

            # Parse content - handle Ollama JSON responses and detect empty responses
            content = message.content or ""

            # Check if response is completely empty (no content, no tool calls)
            if not content.strip() and not (hasattr(message, "tool_calls") and message.tool_calls):
                # This model returned nothing - provide a helpful error
                content = f"⚠️ Model '{provider}/{model}' returned an empty response.\n\nThis usually means:\n• The model is not properly configured or available\n• The model may be overloaded or rate-limited\n• Check that the model exists and is accessible\n\nTry using a different model or check your provider configuration."

            elif isinstance(content, str) and content.strip().startswith("{"):
                try:
                    parsed = json.loads(content)
                    # Extract text from common Ollama JSON formats
                    if isinstance(parsed, dict):
                        # Try common fields in order of preference
                        content = (
                            parsed.get("response")
                            or parsed.get("message")
                            or parsed.get("content")
                            or parsed.get("text")
                            or parsed.get("answer")
                            or parsed.get("output")
                            or content
                        )
                        # If content is still a dict, try to extract from it
                        if isinstance(content, dict):
                            content = (
                                content.get("content")
                                or content.get("text")
                                or content.get("message")
                                or str(content)
                            )
                        elif not isinstance(content, str):
                            content = str(content)
                except (json.JSONDecodeError, AttributeError):
                    # Not valid JSON or can't parse, use as-is
                    pass

            # Build usage info
            usage = None
            if response.usage:
                usage = Usage(
                    prompt_tokens=response.usage.prompt_tokens or 0,
                    completion_tokens=response.usage.completion_tokens or 0,
                    total_tokens=response.usage.total_tokens or 0,
                )
                if budget_for_credit is not None:
                    budget_for_credit.credit(usage.total_tokens)

            # Build cost info if tracking enabled
            cost = None
            if self.track_costs and hasattr(response, "_hidden_params"):
                hidden = response._hidden_params or {}
                if "response_cost" in hidden:
                    cost = Cost(total_cost=hidden["response_cost"])

            # Extract thinking/reasoning content from response
            thinking_content = None
            thinking_tokens = None

            # Check for extended thinking in various formats
            if hasattr(response, "_hidden_params"):
                hidden = response._hidden_params or {}
                # Claude extended thinking
                if "thinking" in hidden:
                    thinking_content = hidden["thinking"]
                elif "reasoning" in hidden:
                    thinking_content = hidden["reasoning"]
                # o1 reasoning tokens
                elif "reasoning_tokens" in hidden:
                    thinking_content = hidden.get("reasoning_content", "")
                    thinking_tokens = hidden.get("reasoning_tokens", 0)

            # Check raw response for thinking fields
            if not thinking_content and hasattr(response, "response_msgs"):
                # Some providers expose thinking in response_msgs
                for msg in response.response_msgs:
                    if hasattr(msg, "thinking") and msg.thinking:
                        thinking_content = msg.thinking
                        break

            # Check message for thinking fields (Claude format)
            if not thinking_content and hasattr(message, "thinking"):
                thinking_content = message.thinking
            if not thinking_content and hasattr(message, "reasoning_content"):
                thinking_content = message.reasoning_content

            # Check for stop_reason indicating thinking (Claude extended thinking)
            if not thinking_content and choice.finish_reason == "thinking":
                # Extended thinking mode - content might be in a different field
                if hasattr(choice, "thinking") and choice.thinking:
                    thinking_content = choice.thinking
                elif hasattr(message, "thinking") and message.thinking:
                    thinking_content = message.thinking

            # Extract thinking tokens from usage if available
            if thinking_content and usage and not thinking_tokens:
                # Some providers report thinking tokens separately
                if hasattr(response, "_hidden_params"):
                    hidden = response._hidden_params or {}
                    thinking_tokens = hidden.get("thinking_tokens") or hidden.get(
                        "reasoning_tokens"
                    )

            # Normalize tool calls from LiteLLM response (may be objects or dicts)
            tool_calls = None
            if hasattr(message, "tool_calls") and message.tool_calls:
                tool_calls = self._normalize_tool_calls(message.tool_calls)

            # Local models often emit tool calls in-band as text instead of
            # via the OpenAI tool_calls channel. If no native tool calls
            # came back and we're talking to a local provider, scan content
            # for <tool_call> / fenced JSON / bare function-call patterns.
            if (
                not tool_calls
                and provider in self._LOCAL_SHAPED_PROVIDERS
                and isinstance(content, str)
            ):
                stripped, extracted = self._extract_inline_tool_calls(content)
                if extracted:
                    tool_calls = extracted
                    content = stripped

            return GatewayResponse(
                content=content,
                role=message.role,
                finish_reason=choice.finish_reason,
                usage=usage,
                cost=cost,
                model=response.model,
                provider=provider,
                tool_calls=tool_calls,
                raw_response=response,
                thinking_content=thinking_content,
                thinking_tokens=thinking_tokens,
            )

        except Exception as e:
            self._handle_litellm_error(e, provider, model)

    async def stream_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Make a streaming chat completion request via LiteLLM."""

        # Determine provider from model string if not specified.
        if provider:
            provider = normalize_provider_id(provider)
            model = normalize_model_for_provider(provider, model)
        else:
            parsed = split_provider_model_ref(model)
            provider = parsed.provider or "unknown"
            model = parsed.model

        # Per-task budget pre-check (mirrors chat_completion).
        task_budget: Optional[TaskTokenBudget] = kwargs.get("task_budget")
        if task_budget is not None:
            task_budget.check()

        # Special handling for MLX - use direct client instead of LiteLLM
        if provider == "mlx":
            async for chunk in self._mlx_stream_completion(
                messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
            ):
                yield chunk
            return

        # DS4 - use /v1/messages streaming for better tool calling and KV cache support
        if provider == "ds4":
            async for chunk in self._ds4_messages_stream(
                messages, model, temperature, max_tokens, tools, **kwargs
            ):
                yield chunk
            return

        litellm = self._get_litellm()

        # Set up provider environment
        self._setup_provider_env(provider)

        # Build request
        request_kwargs = {
            "messages": self._apply_prompt_caching(self._convert_messages(messages), provider),
            "stream": True,
            "timeout": self.timeout,
        }

        # Ollama's OpenAI-compatible chat stream can include exact prompt and
        # completion counts on its terminal usage chunk. Ask LiteLLM to retain
        # that chunk so the TUI can show real per-turn tokens.
        if provider == "ollama":
            request_kwargs["stream_options"] = {"include_usage": True}

        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if tools:
            request_kwargs["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice

        # Explicitly pass API keys for providers that need them
        # Some LiteLLM versions require explicit api_key parameter.
        provider_def = _resolve_provider_def(provider)
        if provider_def:
            api_key = _request_api_key(provider, provider_def)
            if api_key and "api_key" not in request_kwargs:
                request_kwargs["api_key"] = api_key

        # models.dev-synthesized providers: inject api_base/api_key explicitly.
        self._apply_dynamic_provider(provider, request_kwargs, model=model)

        # Provider-neutral reasoning + structured output (stream path).
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        structured_output_mode = kwargs.pop("structured_output_mode", None)
        response_schema = kwargs.get("response_schema")
        if reasoning_effort:
            request_kwargs.update(self._resolve_reasoning_effort(provider, model, reasoning_effort))
        if structured_output_mode:
            request_kwargs.update(
                self._resolve_structured_output_mode(
                    provider, structured_output_mode, response_schema is not None
                )
            )
            request_kwargs.pop("_structured_output_mode", None)

        self._apply_zai_stream_shaping(
            provider,
            request_kwargs,
            has_tools=bool(tools),
        )

        # Strip budget marker; pre-check already happened above.
        budget_for_credit: Optional[TaskTokenBudget] = kwargs.pop("task_budget", None)

        request_kwargs.update(kwargs)

        # Local-model tuning. Same rationale as in chat_completion.
        self._apply_local_request_shaping(provider, model, request_kwargs, bool(tools))
        self._apply_kimi_k3_request_shaping(provider, model, request_kwargs)

        try:
            model_candidates = self._get_model_candidates(provider, model)
            response = None
            last_error = None
            for i, candidate in enumerate(model_candidates):
                request_kwargs["model"] = candidate
                try:
                    response = await self._acompletion_with_retry(request_kwargs)
                    break
                except Exception as e:
                    last_error = e
                    is_last = i == len(model_candidates) - 1
                    retryable = self._is_model_not_found_error(
                        e
                    ) or self._is_retryable_provider_transport_error(e)
                    if is_last or not retryable:
                        raise
                    continue

            if response is None and last_error is not None:
                raise last_error

            if not response:
                raise GatewayError(
                    f"No response from {provider}/{model}",
                    provider=provider,
                    model=model,
                )

            # Accumulators for end-of-stream in-band tool extraction
            # (only used when provider is a local-shaped one).
            inline_capture = provider in self._LOCAL_SHAPED_PROVIDERS
            inline_buffer: List[str] = []
            saw_native_tool_calls = False

            credited = False
            async for chunk in response:
                # Credit the budget from any usage field LiteLLM attaches
                # to the terminal stream chunk. LiteLLM typically only
                # emits ``.usage`` on the last chunk, but we guard with
                # ``credited`` so repeated echoes don't double-charge.
                if budget_for_credit is not None and not credited:
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        total = getattr(chunk_usage, "total_tokens", 0) or 0
                        if total > 0:
                            budget_for_credit.credit(total)
                            credited = True
                chunk_usage = getattr(chunk, "usage", None)
                usage_obj: Optional[Usage] = None
                if chunk_usage is not None:
                    prompt_tokens = int(getattr(chunk_usage, "prompt_tokens", 0) or 0)
                    completion_tokens = int(getattr(chunk_usage, "completion_tokens", 0) or 0)
                    total_tokens = int(getattr(chunk_usage, "total_tokens", 0) or 0)
                    if total_tokens <= 0:
                        total_tokens = prompt_tokens + completion_tokens
                    usage_obj = Usage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )

                # OpenAI-compatible APIs commonly send usage in a final chunk
                # with no choices. Do not discard it just because it has no
                # text delta.
                if not chunk.choices:
                    if usage_obj is not None:
                        yield StreamChunk(usage=usage_obj)
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Extract thinking content if available (for extended thinking models)
                thinking_content = None
                if hasattr(delta, "thinking") and delta.thinking:
                    thinking_content = delta.thinking
                elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    thinking_content = delta.reasoning_content
                elif hasattr(choice, "thinking") and choice.thinking:
                    thinking_content = choice.thinking

                # Extract content - handle Ollama JSON responses
                content = ""
                if delta and delta.content:
                    content_str = delta.content
                    # Note: In streaming mode, JSON might come in chunks, so we only parse
                    # if we have a complete JSON object (starts with { and ends with })
                    # Otherwise, we pass through the content as-is
                    if (
                        isinstance(content_str, str)
                        and content_str.strip().startswith("{")
                        and content_str.strip().endswith("}")
                    ):
                        try:
                            parsed = json.loads(content_str)
                            # Extract text from common Ollama JSON formats
                            if isinstance(parsed, dict):
                                # Try common fields in order of preference
                                content = (
                                    parsed.get("response")
                                    or parsed.get("message")
                                    or parsed.get("content")
                                    or parsed.get("text")
                                    or parsed.get("answer")
                                    or parsed.get("output")
                                    or content_str
                                )
                                # If content is still a dict, try to extract from it
                                if isinstance(content, dict):
                                    content = (
                                        content.get("content")
                                        or content.get("text")
                                        or content.get("message")
                                        or content_str
                                    )
                            else:
                                content = content_str
                        except (json.JSONDecodeError, AttributeError):
                            # Not valid JSON or can't parse, use as-is
                            content = content_str
                    else:
                        content = content_str

                stream_chunk = StreamChunk(
                    content=content,
                    role=delta.role if delta and hasattr(delta, "role") else None,
                    finish_reason=choice.finish_reason,
                    usage=usage_obj,
                    thinking_content=thinking_content,
                )

                # Handle tool calls in stream
                # Normalize tool calls (may be objects or dicts from LiteLLM)
                if delta and hasattr(delta, "tool_calls") and delta.tool_calls:
                    stream_chunk.tool_calls = self._normalize_tool_calls(delta.tool_calls)
                    if stream_chunk.tool_calls:
                        saw_native_tool_calls = True

                if inline_capture and content and not saw_native_tool_calls:
                    inline_buffer.append(content)

                # At end-of-stream for a local provider that emitted no native
                # tool_calls, scan the buffered content. If we find inline
                # tool calls, emit a synthesized terminal chunk carrying them
                # so the agent loop can act on them.
                if (
                    inline_capture
                    and choice.finish_reason
                    and not saw_native_tool_calls
                    and inline_buffer
                ):
                    full = "".join(inline_buffer)
                    _, extracted = self._extract_inline_tool_calls(full)
                    if extracted:
                        # Hand the tool calls to the loop. We do not echo the
                        # raw content again — earlier chunks already carried
                        # it — so the user sees the model's text once and the
                        # tool calls fire from the trailing chunk.
                        stream_chunk.tool_calls = extracted
                        stream_chunk.finish_reason = "tool_calls"

                yield stream_chunk

        except GatewayError:
            # Re-raise gateway errors (they're already formatted)
            raise
        except Exception as e:
            # Convert LiteLLM errors to gateway errors
            self._handle_litellm_error(e, provider, model)

    async def test_connection(
        self,
        provider: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Test connection to a provider."""
        provider_def = PROVIDERS.get(provider)

        if not provider_def:
            return {
                "success": False,
                "provider": provider,
                "error": f"Provider '{provider}' not found in registry",
            }

        # Use first example model if not specified
        test_model = model or (
            provider_def.example_models[0] if provider_def.example_models else None
        )

        if not test_model:
            return {
                "success": False,
                "provider": provider,
                "error": "No model specified and no example models available",
            }

        try:
            # Make a minimal test request
            response = await self.chat_completion(
                messages=[Message(role="user", content="Hi")],
                model=test_model,
                provider=provider,
                max_tokens=5,
            )

            return {
                "success": True,
                "provider": provider,
                "model": test_model,
                "response_model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
            }

        except GatewayError as e:
            return {
                "success": False,
                "provider": provider,
                "model": test_model,
                "error": str(e),
                "error_type": e.error_type,
            }
        except Exception as e:
            return {
                "success": False,
                "provider": provider,
                "model": test_model,
                "error": str(e),
            }
