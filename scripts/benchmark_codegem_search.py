#!/usr/bin/env python3
"""Measure EmbeddingGemma retrieval on a small, labeled CodeGem source set."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from superqode.codegem.retrieval import CodeGemIndex

QUERIES = [
    (
        "which provider converts a Gemini function call response into CodeGem tool-call blocks",
        "src/superqode/codegem/provider.py",
    ),
    (
        "terminate child processes when Python or Bash commands time out or are canceled",
        "src/superqode/codegem/tools.py",
    ),
    (
        "Gemma generation profiles choose default temperature thinking and system role",
        "src/superqode/codegem/profiles.py",
    ),
    (
        "where CodeGem stores local semantic code vectors in a project index",
        "src/superqode/codegem/retrieval.py",
    ),
    (
        "how does CodeGem resume an existing session",
        "src/superqode/harness/codegem_adapter.py",
    ),
    (
        "where the built in CodeGem harness backend gets registered",
        "src/superqode/harness/backends/registry.py",
    ),
]


async def run(args):
    default = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    base = args.base_url or (default if args.provider == "ollama" else "http://127.0.0.1:8081")
    config = {
        "provider": args.provider,
        "base_url": base.rstrip("/") + "/v1",
        "dimensions": args.dimensions,
        "scope": args.scope,
    }
    if args.model:
        config["model"] = args.model
    if args.device:
        config["device"] = args.device
    if args.local_files_only:
        config["local_files_only"] = True
    index = CodeGemIndex(args.root, config)
    build = await index.build()
    results = []
    reciprocal_ranks = []
    for query, expected in QUERIES:
        matches = await index.search(query, limit=5)
        rank = next((i for i, item in enumerate(matches, 1) if item["path"] == expected), None)
        reciprocal_ranks.append(1 / rank if rank else 0)
        results.append(
            {
                "query": query,
                "expected_path": expected,
                "rank": rank,
                "top_paths": [item["path"] for item in matches],
            }
        )
    report = {
        "provider": args.provider,
        "model": args.model,
        "dimensions": args.dimensions,
        "index": build,
        "recall_at_5": sum(r is not None for r in (item["rank"] for item in results))
        / len(results),
        "mrr_at_5": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "results": results,
        "scope": args.scope,
        "scope_note": "six hand-labeled CodeGem source-file queries; not a general code-search benchmark",
    }
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n")
    print(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument(
        "--provider", choices=("ollama", "openai", "sentence-transformers"), default="ollama"
    )
    parser.add_argument(
        "--base-url", help="local embedding server; defaults to Ollama or llama-server"
    )
    parser.add_argument(
        "--model", help="model tag or Hugging Face model ID (provider default if omitted)"
    )
    parser.add_argument("--device", choices=("auto", "cuda", "mps", "cpu"), default=None)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--dimensions", type=int, choices=(128, 256, 512, 768), default=256)
    parser.add_argument(
        "--scope",
        action="append",
        default=None,
        help="relative source directory to index; repeat to include several directories",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.scope is None:
        args.scope = ["src/superqode/codegem", "src/superqode/harness"]
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
