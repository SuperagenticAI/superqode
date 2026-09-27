"""Shared display order for local providers and their engine aliases."""

LOCAL_PROVIDER_ORDER = ("ollama", "lmstudio", "llamacpp", "sglang", "vllm", "mlx")


def local_provider_sort_key(provider_id: str) -> tuple[int, str]:
    """Put primary providers first, then remaining providers alphabetically."""
    canonical = {"llama.cpp": "llamacpp", "mlx-lm": "mlx"}.get(provider_id, provider_id)
    try:
        return LOCAL_PROVIDER_ORDER.index(canonical), provider_id
    except ValueError:
        return len(LOCAL_PROVIDER_ORDER), provider_id
