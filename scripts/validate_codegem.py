#!/usr/bin/env python3
"""Reproducible local/cloud CodeGem coding trials, scored by actual artifacts.

Uses temporary workspaces; never edits the checkout or requires a cloud key
for local validation. Reports usage and elapsed time, not invented quality scores.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.registry import create_harness_backend
from superqode.harness.templates import codegem_template, pipy_template

CASES = {
    "repair": {
        "files": {
            "calculator.py": "def mean(values):\n    return sum(values) / (len(values) + 1)\n",
            "test_calculator.py": "from calculator import mean\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n\ndef test_empty():\n    assert mean([]) == 0\n",
        },
        "prompt": "Fix calculator.mean so all tests pass. Read the code first, make a focused edit, and run the tests with bash. Do not change the tests.",
    },
    "create": {
        "files": {
            "test_slug.py": "from slug import slugify\n\ndef test_slug():\n    assert slugify(' Hello, WORLD! ') == 'hello-world'\n    assert slugify('a---b___c') == 'a-b-c'\n    assert slugify('!!!') == ''\n"
        },
        "prompt": "Use search to find the test file, read it, then write slug.py implementing slugify. Use Python to check an example and Bash to run the tests. Do not change the test file.",
    },
}


async def run(args):
    results = []
    for name in args.cases:
        case = CASES[name]
        with tempfile.TemporaryDirectory(prefix="codegem-eval-") as temp:
            root = Path(temp)
            for file, content in case["files"].items():
                (root / file).write_text(content)
            spec = codegem_template() if args.harness == "codegem" else pipy_template()
            config = {
                **spec.runtime.config,
                "thinking": args.thinking,
                "max_turns": 20,
                "context_window": args.context_window,
                "tool_mode": args.tool_mode,
                "context_files": False,
            }
            if args.temperature is not None:
                config["temperature"] = args.temperature
            if args.base_url:
                config["base_url"] = args.base_url
            spec = replace(spec, runtime=replace(spec.runtime, config=config))
            backend = create_harness_backend(args.harness)
            start = time.monotonic()
            events = []
            changed_tests = set()
            async for event in backend.stream(
                HarnessBackendRequest(
                    spec=spec,
                    prompt=case["prompt"],
                    provider=args.provider,
                    model=args.model,
                    working_directory=root,
                    session_id=f"trial-{name}",
                )
            ):
                events.append(event)
                if event.type == "tool_result":
                    for file, original in case["files"].items():
                        if file.startswith("test_") and (
                            not (root / file).exists() or (root / file).read_text() != original
                        ):
                            changed_tests.add(file)
                if event.type in {"tool_call", "tool_result", "error", "turn_complete"}:
                    print(
                        json.dumps({"case": name, "event": event.type, "data": event.data}),
                        flush=True,
                    )
            # Run immutable reference tests through the current interpreter.
            tests_unchanged = all(
                (root / f).read_text() == c
                for f, c in case["files"].items()
                if f.startswith("test_")
            )
            import sys

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pytest",
                "-q",
                str(root),
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await proc.communicate()
            result = {
                "case": name,
                "harness": args.harness,
                "model": args.model,
                "passed": proc.returncode == 0
                and tests_unchanged
                and not changed_tests
                and not any(e.type == "error" for e in events),
                "protected_tests_changed": sorted(changed_tests),
                "tests_unchanged": tests_unchanged,
                "test_output": output.decode(),
                "seconds": round(time.monotonic() - start, 2),
                "tools": [e.data.get("tool_name") for e in events if e.type == "tool_call"],
                "usage": [e.data.get("usage") for e in events if e.type == "turn_complete"],
                "errors": [e.data for e in events if e.type == "error"],
            }
            results.append(result)
            print(json.dumps(result), flush=True)
    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {
                    "provider": args.provider,
                    "tool_mode": args.tool_mode,
                    "thinking": args.thinking,
                    "results": results,
                },
                indent=2,
            )
        )
    return all(r["passed"] for r in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:12b-mlx")
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--harness", choices=("codegem", "pipy"), default="codegem")
    parser.add_argument("--tool-mode", choices=("auto", "native", "json"), default="auto")
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--base-url")
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    parser.add_argument("--output")
    raise SystemExit(0 if asyncio.run(run(parser.parse_args())) else 1)
