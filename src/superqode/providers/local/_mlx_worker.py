"""MLX generation worker (runs as a subprocess).

Kept separate from the rest of SuperQode so the heavy, Apple-only ``mlx_lm``
import lives in its own process and only loads when MLX is actually used. The
parent (:mod:`mlx_engine`) talks to it with one JSON request/response per line
over stdin/stdout.

Protocol (one JSON object per line):
  request:  {"op": "generate", "model": str, "messages": [...], "tools": [...]|null,
             "max_tokens": int, "temperature": float}
  response: {"type": "progress", "phase": ...} (zero or more)
            {"type": "result", "text": str, "usage": {...}}
            {"type": "error", "error": str}

Run with: ``python -m superqode.providers.local._mlx_worker``
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict


def _emit(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _render_prompt(tokenizer, messages, tools):
    """Render the chat prompt, passing tools when the template supports them.

    Gemma 4 / Qwen templates accept a ``tools`` arg and emit native tool-call
    syntax. If a template rejects ``tools``, retry without (the model still sees
    the conversation; tools may have been folded into the system message upstream).
    """
    if tools:
        try:
            return tokenizer.apply_chat_template(
                messages, tools=tools, add_generation_prompt=True
            )
        except Exception:
            pass
    return tokenizer.apply_chat_template(messages, add_generation_prompt=True)


def main() -> int:
    try:
        from mlx_lm import load, stream_generate
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "error": f"mlx_lm not available: {exc}"})
        return 1

    cache: Dict[str, Any] = {}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            _emit({"type": "error", "error": f"bad request: {exc}"})
            continue

        if req.get("op") == "shutdown":
            return 0

        model_id = req.get("model", "")
        try:
            if model_id not in cache:
                _emit({"type": "progress", "phase": "model.loading", "model_id": model_id})
                cache[model_id] = load(model_id)
                _emit({"type": "progress", "phase": "model.loaded", "model_id": model_id})
            model, tokenizer = cache[model_id]

            prompt = _render_prompt(
                tokenizer, req.get("messages", []), req.get("tools")
            )
            max_tokens = int(req.get("max_tokens") or 2048)

            pieces = []
            for resp in stream_generate(model, tokenizer, prompt=prompt, max_tokens=max_tokens):
                pieces.append(resp.text)
            text = "".join(pieces)

            _emit(
                {
                    "type": "result",
                    "text": text,
                    "usage": {
                        "prompt_tokens": None,
                        "completion_tokens": None,
                    },
                    "backend": "mlx_lm",
                }
            )
        except Exception as exc:  # noqa: BLE001
            _emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
