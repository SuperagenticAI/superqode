"""Conservative setup intentions derived from the existing model/fit catalog.

These are resource heuristics, not speed or coding-quality measurements.
Selection never downloads, loads, changes a running server, or starts a task.
"""

from dataclasses import asdict
import hashlib
import math

from .context_contract import choose_contract

PRESETS = (
    ("fast", "Fast", 4096, "Prefer smaller weights and a shorter context for quick iteration."),
    ("balanced", "Balanced", 8192, "Balance model size, context and memory headroom."),
    (
        "capable",
        "Capable",
        16384,
        "Consider larger fitting models; verify coding quality with evaluations.",
    ),
)


def setup_presets(choices, hardware):
    results = []
    for identity, name, context, detail in PRESETS:
        candidates = []
        for row in choices:
            if row.get("preset") == "previous" or row.get("setup_preset"):
                continue
            metadata = row.get("metadata") or {}
            weights = (row.get("fit") or {}).get("weights_gb")
            if type(weights) not in {int, float} or not math.isfinite(weights) or weights <= 0:
                continue
            if any(term in row["model"].lower() for term in ("embed", "rerank", "cloud")):
                continue
            contract = choose_contract(
                row["model"],
                hardware,
                provider=row["engine"],
                context=context,
                metadata=metadata,
                weights_gb=weights,
            )
            if contract.fit["rating"] != "Fits":
                continue
            candidates.append((row, contract, weights))
        if candidates:
            # Reuse fits on disk first. A new download is never a silent
            # upgrade over a usable existing model, including Gemma models.
            installed = [c for c in candidates if c[0].get("installed")]
            pool = installed or candidates
            pool.sort(key=lambda c: (c[2], c[0]["model"], c[0]["engine"]))
            target = (
                0
                if identity == "fast"
                else (len(pool) - 1) // 2
                if identity == "balanced"
                else len(pool) - 1
            )
            chosen, contract, _ = pool[target]
            # Prefer Chinese-family choices only within the same weight tier;
            # never infer that a family name proves tool support or quality.
            peers = [c for c in pool if c[2] == pool[target][2]]
            peers.sort(
                key=lambda c: (
                    not any(f in c[0]["model"].lower() for f in ("qwen", "glm", "deepseek")),
                    c[0]["engine"] != "ollama",
                    c[0]["model"],
                )
            )
            chosen, contract, _ = peers[0]
            fingerprint = f"{chosen['id']}\n{identity}\n{contract.context}\n{contract.max_tokens}"
            choice = {
                **chosen,
                "id": hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
                "name": name + " · " + chosen["model"],
                "setup_preset": identity,
                "preset": "setup",
                "suggested_context": contract.context,
                "max_tokens": contract.max_tokens,
                "kv_cache": contract.kv_cache,
                "fit": contract.fit,
                "detail": detail
                + " "
                + (
                    "Reuses installed weights."
                    if chosen.get("installed")
                    else "Review the model download before proceeding."
                ),
            }
            if (
                contract.context > chosen.get("suggested_context", 0)
                and choice.get("evaluation_status") == "tested"
            ):
                choice["evaluation_status"] = "catalog-verified"
            results.append(
                {
                    "id": identity,
                    "name": name,
                    "detail": detail,
                    "choice": choice,
                    "contract": asdict(contract),
                    "basis": "memory estimate; speed and quality unmeasured",
                }
            )
        else:
            results.append(
                {
                    "id": identity,
                    "name": name,
                    "detail": "No model with a known fitting working set is available in this catalog.",
                    "choice": None,
                    "basis": "insufficient fit evidence",
                }
            )
    return results
