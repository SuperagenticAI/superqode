#!/usr/bin/env python3
"""One real Gemini baseline and mounted TUI refinement under one API budget.

The secret is held in memory and passed to the provider; it is not placed in
process environments, runtime configs, model evidence, or the ledger. Prices
and full model limits below were verified on 2026-10-18 against Google's docs.
The budget is process-scoped and this runner never resumes or resets a ledger.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from textual.app import App
from textual.widgets import Button, Input

from superqode.codegem.request_budget import GeminiRequestBudget
from superqode.harness.refinement import RefinementRequest
from superqode.harness.refinement.executor import NativeExecutor
from superqode.harness.refinement.store import write_json
from superqode.harness.refinement.workspace import collect_changes, file_manifest, snapshot
from superqode.harness.templates import codegem_template
from superqode.widgets.refinement_inspector import RefinementScreen

MODEL = "gemini-3.1-flash-lite"
TASK = "Fix calculator.mean so both tests pass, including the empty input case. Read the files first, make a focused source change, and run the tests. Keep test_calculator.py unchanged."


def load_key(path):
    path = path.expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Use a small regular key file")
    path.chmod(0o600)
    raw = path.read_text().lstrip("\ufeff").strip()
    if raw.startswith("export "):
        raw = raw[7:].strip()
    if raw.startswith("{"):
        obj = json.loads(raw)
        raw = obj.get("GEMINI_API_KEY") or obj.get("GOOGLE_API_KEY") or obj.get("api_key") or ""
    elif assignment := re.fullmatch(r"(?:GEMINI_API_KEY|GOOGLE_API_KEY)\s*=(.*)", raw, re.S):
        raw = assignment[1].strip()
    values = shlex.split(raw)
    if len(values) != 1 or not re.fullmatch(r"[!-~]{20,512}", values[0]):
        raise ValueError("Key file must contain one API key or a supported key assignment")
    return values[0]


class SmokeApp(App):
    def __init__(self, view):
        super().__init__()
        self.view = view

    def on_mount(self):
        self.push_screen(self.view)


async def grade(workspace, verifier):
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(verifier), str(workspace)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


async def run(args):
    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    key = load_key(args.key_file)
    # API credentials are supplied through the private provider budget scope.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(name, None)
    guard = GeminiRequestBudget(
        limit_usd=args.max_cost_usd,
        model=MODEL,
        input_per_million="0.25",
        output_per_million="1.50",
        max_input_tokens=1048576,
        max_output_tokens=65536,
        path=root / "api-budget.json",
        api_key=key,
    )
    source = root / "project"
    source.mkdir()
    (source / "calculator.py").write_text(
        "def mean(values):\n    return sum(values) / (len(values) + 1)\n"
    )
    test_text = "from calculator import mean\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n\ndef test_empty():\n    assert mean([]) == 0\n"
    (source / "test_calculator.py").write_text(test_text)
    verifier = root / "independent_verify.py"
    verifier.write_text(
        "import importlib.util, sys\nfrom pathlib import Path\n"
        "path=Path(sys.argv[1])/'calculator.py'\n"
        "spec=importlib.util.spec_from_file_location('checked_calculator',path)\n"
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
        "assert module.mean([2,4,6]) == 4\nassert module.mean([]) == 0\n"
        "assert module.mean([-2,2]) == 0\nassert module.mean([5]) == 5\n"
        "print('4 independent assertions passed')\n"
    )
    spec = codegem_template()
    spec = replace(
        spec,
        runtime=replace(
            spec.runtime,
            config={
                "stream": False,
                "context_window": 32768,
                "max_attempts": 1,
                "max_continuation_hops": 1,
                "max_stream_resumes": 0,
                "max_output_tokens_ceiling": 4096,
                "thinking_config": {"thinkingLevel": "MINIMAL"},
            },
        ),
        optimization=replace(
            spec.optimization,
            enabled=True,
            config={
                "method": "harness2",
                "max_sessions": 10,
                "max_turns": 16,
                "max_output_tokens": 4096,
                "max_wall_seconds": 600,
            },
        ),
    )
    request = RefinementRequest(
        task=TASK,
        source=source,
        output=root / "refinement",
        spec=spec,
        provider="google",
        model=MODEL,
        max_sessions=10,
        max_turns=16,
        max_output_tokens=4096,
        max_wall_seconds=600,
        checks=((sys.executable, "-m", "pytest", "-q"),),
        protected_paths=("test_calculator.py",),
    )
    write_json(
        root / "plan.json",
        {
            **request.plan(),
            "total_authorized_usd": args.max_cost_usd,
            "conditions": [
                "one ordinary CodeGem baseline",
                "one sequential k=1 refinement launched in mounted TUI",
            ],
            "prices_verified_on": "2026-10-18",
            "pricing_source": "https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-lite",
            "limits_source": "https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite",
        },
    )
    baseline_workspace = root / "baseline/stages/base/workspace"
    snapshot(source, baseline_workspace, file_manifest(source))
    baseline_executor = NativeExecutor()
    print("Gemini baseline: starting", flush=True)
    summary = {
        "model": MODEL,
        "authorized_usd": args.max_cost_usd,
        "tui_launched": False,
        "patch_applied": False,
    }
    with guard.scope():
        try:
            async with asyncio.timeout(600):
                response = await baseline_executor.run(
                    request, label="base", prompt=TASK, workspace=baseline_workspace, overlay=""
                )
            write_json(root / "baseline/result.json", response)
            summary["baseline"] = {
                "execution_status": response["status"],
                "independent_checks": await grade(baseline_workspace, verifier),
                "protected_test_unchanged": (baseline_workspace / "test_calculator.py").read_text()
                == test_text,
                "usage": response["usage"],
            }
            _, patch = collect_changes(source, baseline_workspace)
            (root / "baseline/changes.patch").write_text(patch)
        finally:
            await baseline_executor.cancel()
        print("Gemini baseline: " + json.dumps(summary.get("baseline", {})), flush=True)
        if not guard.closed_reason:
            print("Gemini mounted TUI refinement: starting", flush=True)
            view = RefinementScreen(
                source=source,
                output=request.output,
                spec=spec,
                provider="google",
                model=MODEL,
                task=TASK,
            )
            app = SmokeApp(view)
            async with app.run_test(size=(110, 40)) as pilot:
                await pilot.pause()
                view.query_one("#refinement-check", Input).value = shlex.join(request.checks[0])
                view.query_one("#refinement-protect", Input).value = "test_calculator.py"
                assert await pilot.click("#refinement-plan")
                assert not view.query_one("#refinement-start", Button).disabled
                assert await pilot.click("#refinement-start")
                summary["tui_launched"] = True
                async with asyncio.timeout(620):
                    while view.running:
                        await asyncio.sleep(0.2)
                await pilot.pause()
                result = json.loads((request.output / "result.json").read_text())
                summary["refinement"] = result
                if result.get("chosen_label"):
                    workspace = request.output / "stages" / result["chosen_label"] / "workspace"
                    summary["refinement_independent_checks"] = await grade(workspace, verifier)
                assert await pilot.click("#refinement-inspect")
                await pilot.pause()
                app.save_screenshot(filename="gemini-refinement-tui.svg", path=str(root))
                if result.get("validation") == "passed" and summary.get(
                    "refinement_independent_checks", {}
                ).get("passed"):
                    assert not view.query_one("#refinement-apply", Button).disabled
                    assert await pilot.click("#refinement-apply")
                    await pilot.pause()
                    receipt = request.output / "application.json"
                    summary["patch_applied"] = receipt.is_file()
                    summary["applied_source_checks"] = await grade(source, verifier)
        else:
            summary["refinement_skipped"] = guard.closed_reason
    summary["api_budget"] = guard.snapshot()
    write_json(root / "summary.json", summary)
    # Check the complete evidence tree without printing or hashing the secret.
    secret = key.encode()
    leaks = [
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and secret in path.read_bytes()
    ]
    if leaks:
        raise RuntimeError(
            "Secret appeared in experiment artifacts; do not share this output directory"
        )
    print(
        json.dumps(
            {
                "output": str(root),
                "patch_applied": summary["patch_applied"],
                "budget": guard.snapshot(),
            },
            indent=2,
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--max-cost-usd", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
