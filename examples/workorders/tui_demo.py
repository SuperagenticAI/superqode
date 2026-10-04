"""Prepare a real, small coding WorkOrder for the TUI; make no model calls."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from superqode.harness.loader import load_harness_spec
from superqode.workorders import (
    WorkOrder,
    WorkOrderBudget,
    WorkOrderStore,
    WorkOrderTask,
    WorkTaskRole,
)


def prepare(directory: Path, *, provider: str, model: str, recovery=False):
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "answer.py").write_text("def answer():\n    return 41\n")
    (directory / "test_answer.py").write_text(
        "import unittest\nfrom answer import answer\n\n"
        "class AnswerTest(unittest.TestCase):\n"
        "    def test_answer(self):\n        self.assertEqual(answer(), 42)\n"
    )
    (directory / "AGENTS.md").write_text(
        "Keep the change minimal. Never modify test_answer.py. Run the acceptance test.\n"
    )
    (directory / ".gitignore").write_text(".superqode/\n__pycache__/\n")
    subprocess.run(["git", "init", "-q", str(directory)], check=True)
    subprocess.run(["git", "-C", str(directory), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(directory),
            "-c",
            "user.name=SuperQode Demo",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-qm",
            "Failing answer acceptance test",
        ],
        check=True,
    )
    control = directory / ".superqode"
    control.mkdir()
    harness = {
        "version": 1,
        "name": "tui-demo-pipy",
        "flavor": "coding",
        "runtime": {
            "backend": "pipy",
            "config": {"recovery": {"enabled": recovery}, "mcp_config": False},
        },
        "model_policy": {"primary": model, "config": {"provider": provider}},
        "execution_policy": {
            "sandbox": "none",
            "allow_read": True,
            "allow_write": True,
            "allow_shell": True,
            "allow_network": False,
        },
        "agents": [
            {
                "id": "coder",
                "role": "implementation",
                "system_prompt": "Inspect the assigned task, make only requested changes, and finish with concise evidence.",
            }
        ],
    }
    harness_path = control / "demo-pipy.yaml"
    harness_path.write_text(yaml.safe_dump(harness, sort_keys=False))
    load_harness_spec(harness_path)
    investigate = control / "demo-investigate.yaml"
    harness["name"] = "tui-demo-investigate"
    harness["execution_policy"]["allow_write"] = False
    investigate.write_text(yaml.safe_dump(harness, sort_keys=False))
    load_harness_spec(investigate)
    store = WorkOrderStore(control / "workorders" / "store.sqlite3")
    acceptance = f"{shlex.quote(sys.executable)} -m unittest -v"
    store.create(
        WorkOrder(
            "tui-demo",
            "Fix answer() to satisfy the unchanged acceptance test",
            str(directory),
            acceptance_tests=(acceptance,),
            harness=str(harness_path),
            budget=WorkOrderBudget(max_seconds=900, max_workers=1, max_tool_calls=20),
            metadata={"evidence_reuse": True},
            tasks=(
                WorkOrderTask(
                    "investigate",
                    "Investigate the failing answer",
                    "Read answer.py and test_answer.py, run the acceptance test, report the cause and smallest fix. Do not edit files.",
                    role=WorkTaskRole.INVESTIGATOR,
                    harness=str(investigate),
                    provider=provider,
                    model=model,
                    max_attempts=4,
                ),
                WorkOrderTask(
                    "implement",
                    "Implement and verify the fix",
                    "Retrieve assigned investigator evidence. Fix answer.py only, keep test_answer.py unchanged, run the acceptance test and report its outcome.",
                    dependencies=("investigate",),
                    harness=str(harness_path),
                    provider=provider,
                    model=model,
                    max_attempts=4,
                ),
            ),
        )
    )
    store.queue("tui-demo")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="New directory; existing directories are refused"
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="Explicitly enable experimental PiPy process recovery",
    )
    args = parser.parse_args()
    root = prepare(args.directory, provider=args.provider, model=args.model, recovery=args.recovery)
    print(
        f"Prepared {root}; no model calls made. Recovery: {'enabled' if args.recovery else 'off'}."
    )
    print(f"cd {shlex.quote(str(root))}\nsq\n:work view tui-demo --lease 10")
    print("Select Run ready tasks, then Execute. Inspect Evidence and Recovery while it runs.")
    print(
        "After completion: Acceptance checks, Prepare candidate, Review / Open, then Approve with your reason."
    )
    print(
        "Workers use the selected provider and may incur cost. This demo uses process permissions; it does not configure an OS sandbox."
    )


if __name__ == "__main__":
    main()
