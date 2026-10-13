#!/usr/bin/env python3
"""Build or query CodeGem's local EmbeddingGemma code index."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from superqode.codegem.retrieval import CodeGemIndex


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
    if args.query:
        print(json.dumps(await index.search(args.query, limit=args.limit), indent=2))
    else:
        print(json.dumps(await index.build(), indent=2))


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
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="use a previously downloaded Hugging Face model without network access",
    )
    parser.add_argument("--dimensions", type=int, choices=(128, 256, 512, 768), default=256)
    parser.add_argument(
        "--scope",
        action="append",
        default=None,
        help="relative directory to index; repeat to include several directories",
    )
    parser.add_argument("--query")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.scope is None:
        args.scope = ["."]
    try:
        asyncio.run(run(args))
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(1, f"CodeGem index: {exc}\n")


if __name__ == "__main__":
    main()
