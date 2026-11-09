"""Best-effort model size and GGUF architecture metadata from loopback servers."""

import json
import urllib.request


def read_metadata(engine, model):
    try:
        if engine == "lmstudio":
            from .lmstudio_api import models

            return next((row for row in models() if row.get("key") == model), {})
        if engine != "ollama":
            return {}
        base = "http://127.0.0.1:11434"
        req = urllib.request.Request(
            base + "/api/show",
            data=json.dumps({"model": model}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            info = json.loads(response.read(2_000_000)).get("model_info", {})
        result = {}
        fields = {
            "block_count": "num_hidden_layers",
            "context_length": "max_context_length",
            "attention.head_count_kv": "num_key_value_heads",
            "attention.head_count": "num_attention_heads",
            "embedding_length": "hidden_size",
            "attention.key_length": "head_dim",
        }
        for suffix, name in fields.items():
            value = next((v for k, v in info.items() if k.endswith("." + suffix)), None)
            if isinstance(value, (int, float)) and value > 0:
                result[name] = value
        # Values may be wider than keys on some architectures.
        value_dim = next(
            (v for k, v in info.items() if k.endswith(".attention.value_length")), None
        )
        if isinstance(value_dim, (int, float)) and value_dim > 0 and result.get("head_dim"):
            result["head_dim"] = max(value_dim, result["head_dim"])
        with urllib.request.urlopen(base + "/api/tags", timeout=2) as response:
            rows = json.loads(response.read(2_000_000)).get("models", [])
        size = next(
            (r.get("size") for r in rows if (r.get("name") or r.get("model")) == model), None
        )
        if isinstance(size, (int, float)) and size > 0:
            result["size_bytes"] = size
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
