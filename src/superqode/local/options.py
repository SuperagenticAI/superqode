"""Typed runtime options shared by CLI, TUI and native model setup."""


def cache_options(engine, cache):
    if cache not in {"auto", "f16", "q8_0", "q4_0"}:
        raise ValueError("Choose Automatic, f16, q8_0 or q4_0 KV cache")
    if cache == "auto":
        return [], {}
    if engine == "ollama":
        return [], {"OLLAMA_KV_CACHE_TYPE": cache, "OLLAMA_FLASH_ATTENTION": "1"}
    if engine == "llama.cpp":
        return ["--cache-type-k", cache, "--cache-type-v", cache, "--flash-attn", "on"], {}
    raise ValueError("KV cache controls are not exposed for this runtime; choose Automatic")
