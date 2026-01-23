"""Provider manager for discovering and managing LLM providers and models."""

import os
import pathlib
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum

# litellm is imported lazily to avoid import errors when CWD doesn't exist
# (litellm tries to resolve current directory during import via pydantic plugins)


def _safe_import_litellm():
    """Safely import litellm, handling cases where CWD doesn't exist."""
    try:
        import litellm

        return litellm
    except (FileNotFoundError, OSError) as e:
        # Handle case where current directory doesn't exist during import
        # This can happen if CWD was deleted or is invalid
        try:
            # Try to change to a safe directory if current one doesn't exist
            cwd = os.getcwd()
            if not pathlib.Path(cwd).exists():
                # Use home directory as fallback
                os.chdir(os.path.expanduser("~"))
            # Try importing again
            import litellm

            return litellm
        except Exception:
            # If we still can't import, raise a more helpful error
            raise ImportError(
                f"Failed to import litellm. This may be due to an invalid current working directory. "
                f"Please ensure you're in a valid directory. Original error: {str(e)}"
            )


@dataclass
class ModelInfo:
    """Information about an LLM model."""

    id: str
    name: str
    provider_id: str
    description: Optional[str] = None
    context_size: Optional[int] = None
    available: bool = True


@dataclass
class ProviderInfo:
    """Information about an LLM provider."""

    id: str
    name: str
    description: str
    requires_api_key: bool = True
    configured: bool = False
    models: List[ModelInfo] = None

    def __post_init__(self):
        if self.models is None:
            self.models = []


class ProviderManager:
    """Lightweight LLM provider manager using LiteLLM."""

    # Provider priority for sorting (lower number = higher priority)
    PROVIDER_PRIORITY = {
        "ollama": 1,
        "vllm": 2,
        "sglang": 2,
        "openai": 3,
        "anthropic": 4,
        "google": 5,
        "xai": 6,
        "groq": 7,
        "openrouter": 8,
        "qwen": 9,
        "deepseek": 10,
        "together": 11,
        "deepinfra": 12,
        "github-copilot": 13,
        "perplexity": 14,
        "mistral": 15,
        "cerebras": 16,
        "zhipu": 17,
        "moonshot": 18,
        "minimax": 19,
        "baidu": 20,
        "tencent": 21,
        "doubao": 22,
        "01-ai": 23,
        "azure-openai": 24,
        "vertex-ai": 25,
        "openai-compatible": 26,
    }

    def __init__(self):
        """Initialize the provider manager."""
        self._configured_providers: Dict[str, Dict[str, Any]] = {}

        # Set up LiteLLM API keys from environment
        self._setup_litellm_keys()

    def _setup_litellm_keys(self):
        """Set up LiteLLM API keys from environment variables."""
        # OpenAI
        if os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

        # Anthropic
        if os.getenv("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.getenv("ANTHROPIC_API_KEY")

        # Google - supports both GOOGLE_API_KEY and GEMINI_API_KEY
        google_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if google_key:
            os.environ["GOOGLE_API_KEY"] = google_key
            # Also set GEMINI_API_KEY if it's not already set (for compatibility)
            if not os.getenv("GEMINI_API_KEY"):
                os.environ["GEMINI_API_KEY"] = google_key

        # xAI
        if os.getenv("XAI_API_KEY"):
            os.environ["XAI_API_KEY"] = os.getenv("XAI_API_KEY")

        # Other providers
        if os.getenv("GROQ_API_KEY"):
            os.environ["GROQ_API_KEY"] = os.getenv("GROQ_API_KEY")

        if os.getenv("OPENROUTER_API_KEY"):
            os.environ["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY")

        if os.getenv("DASHSCOPE_API_KEY"):
            os.environ["DASHSCOPE_API_KEY"] = os.getenv("DASHSCOPE_API_KEY")

        if os.getenv("DEEPSEEK_API_KEY"):
            os.environ["DEEPSEEK_API_KEY"] = os.getenv("DEEPSEEK_API_KEY")

        if os.getenv("GITHUB_TOKEN"):
            os.environ["GITHUB_TOKEN"] = os.getenv("GITHUB_TOKEN")

    def _is_provider_configured(self, provider_id: str) -> bool:
        """Check if a provider has API keys configured."""
        if provider_id in ("ollama", "mlx", "vllm", "sglang"):
            # Local providers don't need API keys
            return True

        key_mapping = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],  # Google supports both
            "xai": "XAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "qwen": "DASHSCOPE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "github-copilot": "GITHUB_TOKEN",
            "together": "TOGETHER_API_KEY",
            "deepinfra": "DEEPINFRA_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "moonshot": "MOONSHOT_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "baidu": "BAIDU_API_KEY",
            "tencent": "TENCENT_API_KEY",
            "doubao": "DOUBAO_API_KEY",
            "01-ai": "ZEROONE_API_KEY",
            "azure-openai": "AZURE_OPENAI_API_KEY",
            "vertex-ai": "GOOGLE_APPLICATION_CREDENTIALS",
            "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
        }

        env_vars = key_mapping.get(provider_id)
        if not env_vars:
            return False

        # Handle both single string and list of env vars (for Google)
        if isinstance(env_vars, list):
            # Check if any of the environment variables exist and have valid values
            for env_var in env_vars:
                api_key = os.getenv(env_var)
                if api_key and api_key.strip():
                    return True
            return False
        else:
            # Single environment variable
            api_key = os.getenv(env_vars)
            return bool(api_key and api_key.strip())

    def _check_api_key(self, key_name: str) -> bool:
        """Check if an API key is available."""
        return bool(os.getenv(key_name))

    def _get_ollama_models(self) -> List[ModelInfo]:
        """Get available models from Ollama daemon."""
        try:
            import requests

            # Try to connect to Ollama API
            ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            response = requests.get(f"{ollama_host}/api/tags", timeout=5)

            if response.status_code == 200:
                data = response.json()
                models = []

                for model_data in data.get("models", []):
                    name = model_data.get("name", "")
                    size = model_data.get("size", 0)
                    modified = model_data.get("modified_at", "")

                    # Estimate context size based on model size (rough heuristic)
                    if "3.1" in name or "llama3.1" in name:
                        if "405b" in name:
                            context_size = 131072
                        elif "70b" in name:
                            context_size = 131072
                        else:
                            context_size = 131072
                    elif "3.2" in name or "llama3.2" in name:
                        context_size = 32768
                    elif "codellama" in name or "code" in name:
                        context_size = 16384
                    elif "mistral" in name:
                        context_size = 32768
                    elif "mixtral" in name:
                        context_size = 32768
                    elif "phi3" in name:
                        context_size = 128000
                    elif "gemma" in name:
                        context_size = 8192
                    elif "qwen" in name:
                        context_size = 32768
                    else:
                        context_size = 4096  # Default

                    size_str = self._format_size(size)
                    models.append(
                        ModelInfo(
                            id=name,
                            name=f"{name} ({size_str})",
                            provider_id="ollama",
                            context_size=context_size,
                        )
                    )

                return models if models else self._get_default_ollama_models()
            else:
                # Fallback to default models if Ollama is not running
                return self._get_default_ollama_models()

        except Exception as e:
            # Fallback to default models if there's any error
            return self._get_default_ollama_models()

    def _get_default_ollama_models(self) -> List[ModelInfo]:
        """Get default Ollama models when API is not available."""
        return [
            ModelInfo("llama3.2:3b", "Llama 3.2 3B (default)", "ollama", context_size=32768),
            ModelInfo("llama3.1:8b", "Llama 3.1 8B (default)", "ollama", context_size=131072),
            ModelInfo("codellama:7b", "Code Llama 7B (default)", "ollama", context_size=16384),
        ]

    def _get_mlx_models(self) -> List[ModelInfo]:
        """Get available MLX models from server and cache."""
        models = []

        # Try to get models from running MLX server
        try:
            import asyncio
            from ..providers.local.mlx import get_mlx_client

            async def get_mlx_server_models():
                client = await get_mlx_client()
                if client:
                    server_models = await client.list_models()
                    return [
                        ModelInfo(
                            id=model.id,
                            name=model.name,
                            provider_id="mlx",
                            description=f"{model.family} - {model.parameter_count} params",
                            context_size=model.context_window or 4096,
                        )
                        for model in server_models
                    ]
                return []

            # Run in sync context
            server_models = asyncio.run(get_mlx_server_models())
            models.extend(server_models)
        except Exception:
            # If MLX client fails, continue with cached models
            pass

        # Add cached models if no server models found
        if not models:
            try:
                from ..providers.local.mlx import MLXClient

                cache_models = MLXClient.discover_huggingface_models()
                for model_info in cache_models[:5]:  # Limit to 5 cached models
                    model_id = model_info["id"]
                    size_mb = model_info["size_bytes"] / (1024 * 1024)
                    models.append(
                        ModelInfo(
                            id=model_id,
                            name=f"{model_id.split('/')[-1]} (cached)",
                            provider_id="mlx",
                            description=".1f",
                            context_size=4096,
                        )
                    )
            except Exception:
                pass

        # Fallback to registry models if nothing found
        if not models:
            from ..providers.registry import PROVIDERS

            mlx_provider = PROVIDERS.get("mlx")
            if mlx_provider and mlx_provider.example_models:
                for model_id in mlx_provider.example_models[:3]:
                    models.append(
                        ModelInfo(
                            id=model_id,
                            name=model_id.split("/")[-1],
                            provider_id="mlx",
                            description="Example MLX model",
                            context_size=4096,
                        )
                    )

        return models

    def _get_vllm_models(self) -> List[ModelInfo]:
        """Get available vLLM models from server."""
        models = []

        # Try to get models from running vLLM server
        try:
            import asyncio
            from ..providers.local.vllm import get_vllm_client

            async def get_vllm_server_models():
                client = await get_vllm_client()
                if client:
                    server_models = await client.list_models()
                    return [
                        ModelInfo(
                            id=model.id,
                            name=model.name,
                            provider_id="vllm",
                            description=f"{model.family} - {model.parameter_count} params"
                            if model.parameter_count
                            else model.family,
                            context_size=model.context_window or 4096,
                        )
                        for model in server_models
                    ]
                return []

            # Run in sync context
            server_models = asyncio.run(get_vllm_server_models())
            models.extend(server_models)
        except Exception:
            # If vLLM client fails, continue with default models
            pass

        # Fallback to registry models if nothing found
        if not models:
            from ..providers.registry import PROVIDERS

            vllm_provider = PROVIDERS.get("vllm")
            if vllm_provider and vllm_provider.example_models:
                for model_id in vllm_provider.example_models[:3]:
                    models.append(
                        ModelInfo(
                            id=model_id,
                            name=model_id.split("/")[-1],
                            provider_id="vllm",
                            description="Example vLLM model (server not running)",
                            context_size=131072,
                        )
                    )

        return models

    def _get_sglang_models(self) -> List[ModelInfo]:
        """Get available SGLang models from server."""
        models = []

        # Try to get models from running SGLang server
        try:
            import asyncio
            from ..providers.local.sglang import get_sglang_client

            async def get_sglang_server_models():
                client = await get_sglang_client()
                if client:
                    server_models = await client.list_models()
                    return [
                        ModelInfo(
                            id=model.id,
                            name=model.name,
                            provider_id="sglang",
                            description=f"{model.family} - {model.parameter_count} params"
                            if model.parameter_count
                            else model.family,
                            context_size=model.context_window or 4096,
                        )
                        for model in server_models
                    ]
                return []

            # Run in sync context
            server_models = asyncio.run(get_sglang_server_models())
            models.extend(server_models)
        except Exception:
            # If SGLang client fails, continue with default models
            pass

        # Fallback to registry models if nothing found
        if not models:
            from ..providers.registry import PROVIDERS

            sglang_provider = PROVIDERS.get("sglang")
            if sglang_provider and sglang_provider.example_models:
                for model_id in sglang_provider.example_models[:3]:
                    models.append(
                        ModelInfo(
                            id=model_id,
                            name=model_id.split("/")[-1],
                            provider_id="sglang",
                            description="Example SGLang model (server not running)",
                            context_size=131072,
                        )
                    )

        return models

    def _format_size(self, size_bytes: int) -> str:
        """Format size in human readable format."""
        if size_bytes >= 1024**3:  # GB
            return f"{size_bytes / 1024**3:.1f}GB"
        elif size_bytes >= 1024**2:  # MB
            return f"{size_bytes / 1024**2:.1f}MB"
        else:  # KB
            return f"{size_bytes / 1024:.1f}KB"

    def list_providers(self) -> List[ProviderInfo]:
        """List available LLM providers with latest models."""
        providers = []

        # Local & Self-hosted Models
        ollama_models = self._get_ollama_models()
        providers.append(
            ProviderInfo(
                id="ollama",
                name="Ollama",
                description="Local models via Ollama daemon (privacy-focused, no API key required)",
                requires_api_key=False,
                configured=self._is_provider_configured("ollama"),
                models=ollama_models,
            )
        )

        # MLX (Apple Silicon) Models
        mlx_models = self._get_mlx_models()
        providers.append(
            ProviderInfo(
                id="mlx",
                name="MLX (Apple Silicon)",
                description="Local MLX models optimized for Apple Silicon (requires mlx_lm.server)",
                requires_api_key=False,
                configured=self._is_provider_configured("mlx"),
                models=mlx_models,
            )
        )

        # vLLM (Experimental) Models
        vllm_models = self._get_vllm_models()
        providers.append(
            ProviderInfo(
                id="vllm",
                name="vLLM (Experimental)",
                description="High-throughput local inference with PagedAttention [EXPERIMENTAL]",
                requires_api_key=False,
                configured=self._is_provider_configured("vllm"),
                models=vllm_models,
            )
        )

        # SGLang (Experimental) Models
        sglang_models = self._get_sglang_models()
        providers.append(
            ProviderInfo(
                id="sglang",
                name="SGLang (Experimental)",
                description="Fast structured generation with RadixAttention [EXPERIMENTAL]",
                requires_api_key=False,
                configured=self._is_provider_configured("sglang"),
                models=sglang_models,
            )
        )

        # US Labs - Premium Cloud Models
        providers.append(
            ProviderInfo(
                id="openai",
                name="OpenAI",
                description="Latest GPT-5.2, GPT-5.1, o1 models from models.dev",
                requires_api_key=True,
                configured=self._is_provider_configured("openai"),
                models=[
                    ModelInfo("gpt-5.2", "GPT-5.2 (Latest)", "openai", context_size=256000),
                    ModelInfo("gpt-5.2-pro", "GPT-5.2 Pro", "openai", context_size=256000),
                    ModelInfo("gpt-5.2-codex", "GPT-5.2 Codex", "openai", context_size=256000),
                    ModelInfo("gpt-5.1", "GPT-5.1", "openai", context_size=200000),
                    ModelInfo("gpt-5.1-codex", "GPT-5.1 Codex", "openai", context_size=200000),
                    ModelInfo(
                        "gpt-5.1-codex-mini", "GPT-5.1 Codex Mini", "openai", context_size=200000
                    ),
                    ModelInfo(
                        "gpt-4o-2024-11-20", "GPT-4o (Nov 2024)", "openai", context_size=128000
                    ),
                    ModelInfo("gpt-4o", "GPT-4o", "openai", context_size=128000),
                    ModelInfo("gpt-4o-mini", "GPT-4o Mini", "openai", context_size=128000),
                    ModelInfo("o1", "o1 (Reasoning)", "openai", context_size=200000),
                    ModelInfo("o1-mini", "o1 Mini", "openai", context_size=128000),
                    ModelInfo("gpt-4-turbo", "GPT-4 Turbo", "openai", context_size=128000),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="anthropic",
                name="Anthropic",
                description="Latest Claude 4.5 models from models.dev",
                requires_api_key=True,
                configured=self._is_provider_configured("anthropic"),
                models=[
                    ModelInfo(
                        "claude-opus-4-5-20251101",
                        "Claude Opus 4.5 (Latest)",
                        "anthropic",
                        context_size=200000,
                    ),
                    ModelInfo(
                        "claude-sonnet-4-5-20250929",
                        "Claude Sonnet 4.5",
                        "anthropic",
                        context_size=200000,
                    ),
                    ModelInfo(
                        "claude-haiku-4-5-20251001",
                        "Claude Haiku 4.5",
                        "anthropic",
                        context_size=200000,
                    ),
                    ModelInfo(
                        "claude-sonnet-4-20250514",
                        "Claude Sonnet 4",
                        "anthropic",
                        context_size=200000,
                    ),
                    ModelInfo(
                        "claude-opus-4-20250514", "Claude Opus 4", "anthropic", context_size=200000
                    ),
                    ModelInfo(
                        "claude-haiku-4-20250514",
                        "Claude Haiku 4",
                        "anthropic",
                        context_size=200000,
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="google",
                name="Google",
                description="Latest Gemini 3.x models from models.dev",
                requires_api_key=True,
                configured=self._is_provider_configured("google"),
                models=[
                    ModelInfo(
                        "gemini-3-pro-preview",
                        "Gemini 3 Pro Preview (Latest)",
                        "google",
                        context_size=2000000,
                    ),
                    ModelInfo(
                        "gemini-3-flash-preview",
                        "Gemini 3 Flash Preview (Latest)",
                        "google",
                        context_size=1000000,
                    ),
                    ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro", "google", context_size=2000000),
                    ModelInfo(
                        "gemini-2.5-flash", "Gemini 2.5 Flash", "google", context_size=1000000
                    ),
                    ModelInfo(
                        "gemini-2.0-flash", "Gemini 2.0 Flash", "google", context_size=1000000
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="xai",
                name="xAI",
                description="Latest Grok models",
                requires_api_key=True,
                configured=self._is_provider_configured("xai"),
                models=[
                    ModelInfo("grok-3", "Grok-3 (Latest)", "xai", context_size=262144),
                    ModelInfo("grok-3-mini", "Grok-3 Mini", "xai", context_size=131072),
                    ModelInfo("grok-2", "Grok-2", "xai", context_size=131072),
                    ModelInfo("grok-beta", "Grok Beta", "xai", context_size=131072),
                ],
            )
        )

        # Other Labs & Providers
        providers.append(
            ProviderInfo(
                id="groq",
                name="Groq",
                description="Ultra-fast inference for open-source models",
                requires_api_key=True,
                configured=self._is_provider_configured("groq"),
                models=[
                    ModelInfo(
                        "llama-3.1-8b-instant", "Llama 3.1 8B Instant", "groq", context_size=131072
                    ),
                    ModelInfo(
                        "llama-3.1-70b-versatile",
                        "Llama 3.1 70B Versatile",
                        "groq",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "llama-3.1-405b-instruct", "Llama 3.1 405B", "groq", context_size=131072
                    ),
                    ModelInfo("llama3-8b-8192", "Llama 3 8B", "groq", context_size=8192),
                    ModelInfo("llama3-70b-8192", "Llama 3 70B", "groq", context_size=8192),
                    ModelInfo("mixtral-8x7b-32768", "Mixtral 8x7B", "groq", context_size=32768),
                    ModelInfo("gemma2-9b-it", "Gemma 2 9B", "groq", context_size=8192),
                    ModelInfo("llama2-70b-4096", "Llama 2 70B", "groq", context_size=4096),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="openrouter",
                name="OpenRouter",
                description="Unified API for 100+ LLMs (Claude, GPT-4, Llama, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("openrouter"),
                models=[
                    ModelInfo(
                        "anthropic/claude-3.5-sonnet",
                        "Claude 3.5 Sonnet",
                        "openrouter",
                        context_size=200000,
                    ),
                    ModelInfo("openai/gpt-4o", "GPT-4o", "openrouter", context_size=128000),
                    ModelInfo(
                        "openai/gpt-4o-mini", "GPT-4o Mini", "openrouter", context_size=128000
                    ),
                    ModelInfo("openai/o1-preview", "o1 Preview", "openrouter", context_size=128000),
                    ModelInfo("openai/o1-mini", "o1 Mini", "openrouter", context_size=128000),
                    ModelInfo(
                        "meta-llama/llama-3.1-405b-instruct",
                        "Llama 3.1 405B",
                        "openrouter",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "meta-llama/llama-3.1-70b-instruct",
                        "Llama 3.1 70B",
                        "openrouter",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "google/gemini-pro-1.5",
                        "Gemini Pro 1.5",
                        "openrouter",
                        context_size=2097152,
                    ),
                    ModelInfo(
                        "mistralai/mistral-7b-instruct",
                        "Mistral 7B",
                        "openrouter",
                        context_size=32768,
                    ),
                    ModelInfo(
                        "anthropic/claude-3-haiku",
                        "Claude 3 Haiku",
                        "openrouter",
                        context_size=200000,
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="github-copilot",
                name="GitHub Copilot",
                description="GitHub Copilot models (Claude, GPT-4, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("github-copilot"),
                models=[
                    ModelInfo("gpt-4", "GPT-4 (Copilot)", "github-copilot", context_size=8192),
                    ModelInfo(
                        "claude-3.5-sonnet",
                        "Claude 3.5 Sonnet (Copilot)",
                        "github-copilot",
                        context_size=200000,
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="together",
                name="Together AI",
                description="High-performance open-source models",
                requires_api_key=True,
                configured=self._is_provider_configured("together"),
                models=[
                    ModelInfo(
                        "meta-llama/Llama-3.1-405B-Instruct-Turbo",
                        "Llama 3.1 405B Turbo",
                        "together",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "meta-llama/Llama-3.1-70B-Instruct-Turbo",
                        "Llama 3.1 70B Turbo",
                        "together",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "meta-llama/Llama-3.1-8B-Instruct-Turbo",
                        "Llama 3.1 8B Turbo",
                        "together",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "meta-llama/Llama-3-70B-Instruct-Turbo",
                        "Llama 3 70B Turbo",
                        "together",
                        context_size=8192,
                    ),
                    ModelInfo(
                        "meta-llama/Llama-3-8B-Instruct-Turbo",
                        "Llama 3 8B Turbo",
                        "together",
                        context_size=8192,
                    ),
                    ModelInfo(
                        "mistralai/Mistral-7B-Instruct-v0.1",
                        "Mistral 7B",
                        "together",
                        context_size=32768,
                    ),
                    ModelInfo(
                        "mistralai/Mixtral-8x7B-Instruct-v0.1",
                        "Mixtral 8x7B",
                        "together",
                        context_size=32768,
                    ),
                    ModelInfo(
                        "mistralai/Mistral-7B-Instruct-v0.2",
                        "Mistral 7B v0.2",
                        "together",
                        context_size=32768,
                    ),
                    ModelInfo(
                        "Qwen/Qwen2-72B-Instruct", "Qwen2 72B", "together", context_size=32768
                    ),
                    ModelInfo(
                        "codellama/CodeLlama-34b-Instruct-hf",
                        "Code Llama 34B",
                        "together",
                        context_size=16384,
                    ),
                    ModelInfo(
                        "codellama/CodeLlama-13b-Instruct-hf",
                        "Code Llama 13B",
                        "together",
                        context_size=16384,
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="deepinfra",
                name="DeepInfra",
                description="Fast inference for open source models",
                requires_api_key=True,
                configured=self._is_provider_configured("deepinfra"),
                models=[
                    ModelInfo(
                        "meta-llama/Llama-2-70b-chat-hf",
                        "Llama 2 70B",
                        "deepinfra",
                        context_size=4096,
                    ),
                    ModelInfo(
                        "meta-llama/Llama-2-13b-chat-hf",
                        "Llama 2 13B",
                        "deepinfra",
                        context_size=4096,
                    ),
                    ModelInfo(
                        "codellama/CodeLlama-34b-Instruct-hf",
                        "Code Llama 34B",
                        "deepinfra",
                        context_size=16384,
                    ),
                    ModelInfo(
                        "jondurbin/airoboros-l2-70b-gpt4-1.4.1",
                        "Airoboros 70B",
                        "deepinfra",
                        context_size=4096,
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="perplexity",
                name="Perplexity",
                description="Perplexity models (Sonar, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("perplexity"),
                models=[
                    ModelInfo("sonar-pro", "Sonar Pro", "perplexity", context_size=200000),
                    ModelInfo("sonar", "Sonar", "perplexity", context_size=127072),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="mistral",
                name="Mistral AI",
                description="Mistral models (Mistral Large, Medium, Small, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("mistral"),
                models=[
                    ModelInfo(
                        "mistral-large-latest", "Mistral Large", "mistral", context_size=128000
                    ),
                    ModelInfo("mistral-medium", "Mistral Medium", "mistral", context_size=32768),
                    ModelInfo("mistral-small", "Mistral Small", "mistral", context_size=32768),
                    ModelInfo("codestral-latest", "Codestral", "mistral", context_size=32768),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="cerebras",
                name="Cerebras",
                description="Cerebras models (Llama, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("cerebras"),
                models=[
                    ModelInfo("llama3.1-8b", "Llama 3.1 8B", "cerebras", context_size=8192),
                    ModelInfo("llama3.1-70b", "Llama 3.1 70B", "cerebras", context_size=8192),
                ],
            )
        )

        # Meta AI (Llama models)
        providers.append(
            ProviderInfo(
                id="meta",
                name="Meta AI",
                description="Latest Llama 4 models from models.dev",
                requires_api_key=True,
                configured=self._is_provider_configured("meta"),
                models=[
                    ModelInfo(
                        "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
                        "Llama 4 Maverick 17B (Latest)",
                        "meta",
                        context_size=262144,
                    ),
                    ModelInfo(
                        "llama-3.3-70b-versatile",
                        "Llama 3.3 70B Versatile",
                        "meta",
                        context_size=131072,
                    ),
                    ModelInfo(
                        "llama-3.1-405b-instruct", "Llama 3.1 405B", "meta", context_size=131072
                    ),
                    ModelInfo(
                        "llama-3.1-70b-instruct", "Llama 3.1 70B", "meta", context_size=131072
                    ),
                ],
            )
        )

        # Chinese AI Providers
        providers.append(
            ProviderInfo(
                id="qwen",
                name="Alibaba Qwen",
                description="Latest Qwen3 models from models.dev - Alibaba Cloud",
                requires_api_key=True,
                configured=self._is_provider_configured("qwen"),
                models=[
                    ModelInfo("qwen3-max", "Qwen3 Max (Latest)", "qwen", context_size=262144),
                    ModelInfo(
                        "qwen3-coder-480b-a35b-instruct",
                        "Qwen3 Coder 480B",
                        "qwen",
                        context_size=131072,
                    ),
                    ModelInfo("qwen-flash", "Qwen Flash", "qwen", context_size=32768),
                    ModelInfo("qwen2.5-72b-instruct", "Qwen2.5 72B", "qwen", context_size=32768),
                    ModelInfo(
                        "qwen2.5-coder-32b-instruct",
                        "Qwen2.5 Coder 32B",
                        "qwen",
                        context_size=32768,
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="deepseek",
                name="DeepSeek",
                description="Latest DeepSeek V3.2, R1 models from models.dev",
                requires_api_key=True,
                configured=self._is_provider_configured("deepseek"),
                models=[
                    ModelInfo(
                        "deepseek-ai/DeepSeek-V3.2",
                        "DeepSeek V3.2 (Latest)",
                        "deepseek",
                        context_size=128000,
                    ),
                    ModelInfo(
                        "deepseek-ai/DeepSeek-R1",
                        "DeepSeek R1 (Reasoning)",
                        "deepseek",
                        context_size=64000,
                    ),
                    ModelInfo(
                        "deepseek-chat", "DeepSeek Chat (V3)", "deepseek", context_size=64000
                    ),
                    ModelInfo("deepseek-coder", "DeepSeek Coder", "deepseek", context_size=64000),
                    ModelInfo(
                        "deepseek-reasoner", "DeepSeek Reasoner", "deepseek", context_size=64000
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="zhipu",
                name="Zhipu AI",
                description="GLM models (GLM-4, ChatGLM, etc.) - Tsinghua University",
                requires_api_key=True,
                configured=self._is_provider_configured("zhipu"),
                models=[
                    ModelInfo("glm-4", "GLM-4", "zhipu", context_size=128000),
                    ModelInfo("glm-3-turbo", "GLM-3 Turbo", "zhipu", context_size=128000),
                    ModelInfo("chatglm_turbo", "ChatGLM Turbo", "zhipu", context_size=32768),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="moonshot",
                name="Moonshot AI",
                description="Kimi models (Kimi-2, Kimi-K2, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("moonshot"),
                models=[
                    ModelInfo("moonshot-v1-8k", "Moonshot v1 8K", "moonshot", context_size=8192),
                    ModelInfo("moonshot-v1-32k", "Moonshot v1 32K", "moonshot", context_size=32768),
                    ModelInfo(
                        "moonshot-v1-128k", "Moonshot v1 128K", "moonshot", context_size=131072
                    ),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="minimax",
                name="MiniMax",
                description="MiniMax models (abab-6, abab-6.5, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("minimax"),
                models=[
                    ModelInfo("abab-6-5-chat", "abab-6.5 Chat", "minimax", context_size=24576),
                    ModelInfo("abab-6-chat", "abab-6 Chat", "minimax", context_size=8192),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="baidu",
                name="Baidu",
                description="Ernie models (ERNIE-4.0, ERNIE-3.5, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("baidu"),
                models=[
                    ModelInfo("ernie-4.0-8k", "ERNIE-4.0 8K", "baidu", context_size=8192),
                    ModelInfo("ernie-3.5-8k", "ERNIE-3.5 8K", "baidu", context_size=8192),
                    ModelInfo("ernie-speed-8k", "ERNIE Speed 8K", "baidu", context_size=8192),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="tencent",
                name="Tencent",
                description="Hunyuan models (Hunyuan-Lite, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("tencent"),
                models=[
                    ModelInfo("hunyuan-lite", "Hunyuan Lite", "tencent", context_size=32768),
                    ModelInfo(
                        "hunyuan-standard", "Hunyuan Standard", "tencent", context_size=32768
                    ),
                    ModelInfo("hunyuan-pro", "Hunyuan Pro", "tencent", context_size=32768),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="doubao",
                name="ByteDance Doubao",
                description="Doubao models (Doubao-Pro, Doubao-Lite, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("doubao"),
                models=[
                    ModelInfo("doubao-lite-4k", "Doubao Lite 4K", "doubao", context_size=4096),
                    ModelInfo("doubao-lite-32k", "Doubao Lite 32K", "doubao", context_size=32768),
                    ModelInfo("doubao-pro-4k", "Doubao Pro 4K", "doubao", context_size=4096),
                    ModelInfo("doubao-pro-32k", "Doubao Pro 32K", "doubao", context_size=32768),
                ],
            )
        )

        providers.append(
            ProviderInfo(
                id="01-ai",
                name="01.AI",
                description="Yi models (Yi-1.5, Yi-34B, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("01-ai"),
                models=[
                    ModelInfo("yi-large", "Yi Large", "01-ai", context_size=32768),
                    ModelInfo("yi-medium", "Yi Medium", "01-ai", context_size=16384),
                    ModelInfo("yi-spark", "Yi Spark", "01-ai", context_size=16384),
                ],
            )
        )

        # Azure OpenAI
        providers.append(
            ProviderInfo(
                id="azure-openai",
                name="Azure OpenAI",
                description="Azure-hosted OpenAI models (GPT-4, GPT-3.5, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("azure-openai"),
                models=[
                    ModelInfo("gpt-4", "GPT-4 (Azure)", "azure-openai", context_size=8192),
                    ModelInfo("gpt-4-32k", "GPT-4 32K (Azure)", "azure-openai", context_size=32768),
                    ModelInfo(
                        "gpt-35-turbo", "GPT-3.5 Turbo (Azure)", "azure-openai", context_size=4096
                    ),
                    ModelInfo(
                        "gpt-35-turbo-16k",
                        "GPT-3.5 Turbo 16K (Azure)",
                        "azure-openai",
                        context_size=16384,
                    ),
                ],
            )
        )

        # Google Vertex AI
        providers.append(
            ProviderInfo(
                id="vertex-ai",
                name="Google Vertex AI",
                description="Google Vertex AI models (Gemini, PaLM, etc.)",
                requires_api_key=True,
                configured=self._is_provider_configured("vertex-ai"),
                models=[
                    ModelInfo("gemini-pro", "Gemini Pro (Vertex)", "vertex-ai", context_size=32768),
                    ModelInfo(
                        "gemini-pro-vision",
                        "Gemini Pro Vision (Vertex)",
                        "vertex-ai",
                        context_size=16384,
                    ),
                    ModelInfo(
                        "palm-2-chat-bison", "PaLM 2 Chat Bison", "vertex-ai", context_size=8192
                    ),
                    ModelInfo(
                        "palm-2-codechat-bison",
                        "PaLM 2 CodeChat Bison",
                        "vertex-ai",
                        context_size=8192,
                    ),
                ],
            )
        )

        # OpenAI Compatible
        providers.append(
            ProviderInfo(
                id="openai-compatible",
                name="OpenAI Compatible",
                description="Any OpenAI-compatible API endpoint",
                requires_api_key=True,
                configured=self._is_provider_configured("openai-compatible"),
                models=[
                    ModelInfo("gpt-4", "GPT-4 Compatible", "openai-compatible", context_size=8192),
                    ModelInfo(
                        "gpt-3.5-turbo",
                        "GPT-3.5 Turbo Compatible",
                        "openai-compatible",
                        context_size=4096,
                    ),
                    ModelInfo(
                        "claude-3-sonnet",
                        "Claude 3 Sonnet Compatible",
                        "openai-compatible",
                        context_size=200000,
                    ),
                ],
            )
        )

        # Sort by priority
        providers.sort(key=lambda p: self.PROVIDER_PRIORITY.get(p.id, 99))

        return providers

    def get_models(self, provider_id: str, refresh: bool = False) -> List[ModelInfo]:
        """Get available models for a provider."""
        # Return basic model list for now
        provider = next((p for p in self.list_providers() if p.id == provider_id), None)
        return provider.models if provider else []

    def test_connection(
        self, provider_id: str, model_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Test connection to a provider and optionally a specific model."""
        try:
            # For Ollama, we don't need to test connection
            if provider_id == "ollama":
                if model_id:
                    # Test if the specific Ollama model exists
                    try:
                        models = self.get_models(provider_id)
                        if any(m.id == model_id for m in models):
                            return True, None
                        else:
                            return (
                                False,
                                f"Model '{model_id}' not found. Available models: {', '.join([m.id for m in models[:5]])}",
                            )
                    except Exception as e:
                        return False, f"Failed to check Ollama models: {str(e)}"
                return True, None

            # Test specific model if provided
            if model_id:
                try:
                    # Try a minimal chat completion to test the model
                    messages = [{"role": "user", "content": "Hi"}]
                    response = self.chat_completion(provider_id, model_id, messages, max_tokens=5)
                    if response and response.strip():
                        return True, None
                    else:
                        return False, f"Model '{model_id}' returned empty response"
                except Exception as e:
                    error_msg = str(e).lower()
                    if "model not found" in error_msg or "invalid model" in error_msg:
                        return False, f"Model '{model_id}' not found or not available"
                    elif "authentication" in error_msg or "api key" in error_msg:
                        return False, f"Authentication failed for provider '{provider_id}'"
                    elif "rate limit" in error_msg:
                        return False, f"Rate limit exceeded for provider '{provider_id}'"
                    else:
                        return False, f"Model '{model_id}' failed: {str(e)}"

            # For other providers without specific model, check API key first
            if not self._is_provider_configured(provider_id):
                key_mapping = {
                    "openai": "OPENAI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY",
                    "google": "GOOGLE_API_KEY or GEMINI_API_KEY",  # Google supports both
                    "xai": "XAI_API_KEY",
                    "groq": "GROQ_API_KEY",
                    "openrouter": "OPENROUTER_API_KEY",
                    "qwen": "DASHSCOPE_API_KEY",
                    "deepseek": "DEEPSEEK_API_KEY",
                    "github-copilot": "GITHUB_TOKEN",
                    "together": "TOGETHER_API_KEY",
                    "deepinfra": "DEEPINFRA_API_KEY",
                    "perplexity": "PERPLEXITY_API_KEY",
                    "mistral": "MISTRAL_API_KEY",
                    "cerebras": "CEREBRAS_API_KEY",
                    "zhipu": "ZHIPU_API_KEY",
                    "moonshot": "MOONSHOT_API_KEY",
                    "minimax": "MINIMAX_API_KEY",
                    "baidu": "BAIDU_API_KEY",
                    "tencent": "TENCENT_API_KEY",
                    "doubao": "DOUBAO_API_KEY",
                    "01-ai": "ZEROONE_API_KEY",
                    "azure-openai": "AZURE_OPENAI_API_KEY",
                    "vertex-ai": "GOOGLE_APPLICATION_CREDENTIALS",
                    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
                }
                env_var = key_mapping.get(provider_id)
                if env_var:
                    return False, f"API key not set. Please set {env_var} environment variable."
                else:
                    return False, f"Provider '{provider_id}' requires API key configuration."

            # Try to get models - this will also validate the API key works
            models = self.get_models(provider_id)
            if models:
                # If we have models, try a quick test with the first model to validate API key
                try:
                    test_model = models[0].id
                    messages = [{"role": "user", "content": "Hi"}]
                    response = self.chat_completion(provider_id, test_model, messages, max_tokens=5)
                    if response and response.strip():
                        return True, None
                    else:
                        return False, f"API key validation failed - received empty response"
                except Exception as e:
                    error_msg = str(e).lower()
                    if (
                        "authentication" in error_msg
                        or "api key" in error_msg
                        or "api_key" in error_msg
                    ):
                        key_mapping = {
                            "openai": "OPENAI_API_KEY",
                            "anthropic": "ANTHROPIC_API_KEY",
                            "google": "GOOGLE_API_KEY or GEMINI_API_KEY",  # Google supports both
                            "xai": "XAI_API_KEY",
                            "groq": "GROQ_API_KEY",
                            "openrouter": "OPENROUTER_API_KEY",
                            "qwen": "DASHSCOPE_API_KEY",
                            "deepseek": "DEEPSEEK_API_KEY",
                        }
                        env_var = key_mapping.get(provider_id, "API_KEY")
                        return (
                            False,
                            f"API key validation failed: {str(e)}. Please check your {env_var} environment variable.",
                        )
                    else:
                        return False, f"Connection test failed: {str(e)}"
            else:
                return False, "No models available"
        except Exception as e:
            return False, str(e)

    def chat_completion(
        self, provider_id: str, model_id: str, messages: List[Dict[str, str]], **kwargs
    ) -> str:
        """Make a chat completion request."""
        try:
            # Construct the full model name for LiteLLM
            if provider_id == "ollama":
                full_model = f"ollama/{model_id}"
            elif provider_id == "openai":
                full_model = f"openai/{model_id}"
            elif provider_id == "anthropic":
                full_model = f"anthropic/{model_id}"
            elif provider_id == "google":
                full_model = f"gemini/{model_id}"
            elif provider_id == "xai":
                full_model = f"xai/{model_id}"
            elif provider_id == "groq":
                full_model = f"groq/{model_id}"
            elif provider_id == "openrouter":
                full_model = f"openrouter/{model_id}"
            elif provider_id == "qwen":
                full_model = f"qwen/{model_id}"
            elif provider_id == "deepseek":
                full_model = f"deepseek/{model_id}"
            else:
                full_model = f"{provider_id}/{model_id}"

            # Lazy import litellm to avoid import errors when CWD doesn't exist
            litellm = _safe_import_litellm()

            # Make the request
            response = litellm.completion(model=full_model, messages=messages, **kwargs)

            return response.choices[0].message.content

        except Exception as e:
            raise Exception(f"Failed to get response from {provider_id}: {str(e)}")
