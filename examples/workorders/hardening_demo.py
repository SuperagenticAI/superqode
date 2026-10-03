"""Offline WorkOrder/context mechanics demo; no model requests or credentials.

Run: python examples/workorders/hardening_demo.py [--directory NEW_DIRECTORY]
The synthetic finding is labelled reported, not independently verified.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from superqode.harness.context_artifacts import ContextArtifactStore
from superqode.harness.context_policy import ContextItem, ContextPolicy, ContextPolicyEngine
from superqode.workorders import WorkOrder, WorkOrderStore, WorkOrderTask, WorkTaskRole
from superqode.workorders.evidence import (
    dependency_catalog,
    publish_evidence,
    read_workorder_evidence,
)


async def demonstrate(directory: Path) -> dict:
    repo = directory / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text("def answer():\n    return 0\n", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("add", "app.py"),
        (
            "-c",
            "user.name=Demo",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-qm",
            "Demo fixture",
        ),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    investigate = WorkOrderTask(
        "investigate", "Investigate", "Inspect answer()", role=WorkTaskRole.INVESTIGATOR
    )
    implement = WorkOrderTask(
        "implement", "Implement", "Repair answer()", dependencies=("investigate",)
    )
    store = WorkOrderStore(directory / "work.sqlite3")
    order = WorkOrder(
        "work-hardening-demo",
        "Demonstrate durable evidence and retry-safe admission",
        str(repo),
        harness="pipy",
        tasks=(investigate, implement),
        metadata={
            "evidence_reuse": {"enabled": True, "store_path": str(directory / "evidence.sqlite3")}
        },
    )
    admitted = store.create(order, request_id="demo-request-1", queue=True)
    retry = WorkOrderStore(store.path).create(
        replace(order, work_order_id="retry-generated-id"), request_id="demo-request-1", queue=True
    )
    assert retry.work_order_id == admitted.work_order_id
    store.claim_next_task(reference=admitted.work_order_id, worker_id="demo-worker")
    artifact = publish_evidence(
        store,
        admitted,
        investigate,
        "Synthetic finding: app.py answer() currently returns 0.",
        repo,
    )
    store.complete_task(admitted.work_order_id, investigate.task_id, worker_id="demo-worker")
    order = WorkOrderStore(store.path).get(admitted.work_order_id)
    catalog = dependency_catalog(order, implement, repo)
    assert catalog[0]["freshness"] == "current"
    scope = SimpleNamespace(
        store=store, work_order_id=order.work_order_id, task_id=implement.task_id
    )
    page = read_workorder_evidence(scope, artifact.metadata["reference"], repo, limit=1000)
    assert "Synthetic finding" in page.text
    source.write_text("def answer():\n    return 42\n", encoding="utf-8")
    assert dependency_catalog(order, implement, repo)[0]["freshness"] == "stale"

    first = store.events(order.work_order_id, after_sequence=0, limit=2)
    rest = WorkOrderStore(store.path).events(order.work_order_id, after_sequence=first[-1].sequence)
    assert first + rest == store.events(order.work_order_id)

    original = "Synthetic old tool evidence: answer() returns 0.\n" * 300
    history = [
        ContextItem("user-1", "user", "Inspect app.py"),
        ContextItem("call-1", "assistant", "Read app.py"),
        ContextItem("result-1", "tool", original, "read_file", "read-1", {"path": "app.py"}),
        ContextItem("assistant-2", "assistant", "Continue"),
        ContextItem("user-2", "user", "Repair answer() in app.py"),
    ]
    contexts = ContextArtifactStore(directory / "context.sqlite3")
    shadow = await ContextPolicyEngine(
        contexts, "demo-session", ContextPolicy(mode="shadow", recent_messages=1)
    ).prepare(history)
    assert shadow.replacements == {}
    assert shadow.trace["proposed_chars_after"] < shadow.trace["chars_before"]
    enforced = await ContextPolicyEngine(
        contexts, "demo-session", ContextPolicy(mode="enforce", recent_messages=1)
    ).prepare(history)
    assert len(enforced.replacements[2]) < len(original)
    reference = enforced.decisions[0].reference
    restored = ContextArtifactStore(contexts.path).read_page(
        "demo-session", reference, offset=30, limit=100
    )
    assert restored.text == original[30:130]
    assert history[2].text == original

    return {
        "directory": str(directory),
        "work_order_id": order.work_order_id,
        "inference_calls": 0,
        "duplicate_submission": "same WorkOrder; no requeue",
        "event_cursor_restart": "no missing or repeated events",
        "evidence_verification": catalog[0]["verification"],
        "source_freshness": "current -> stale after app.py changes",
        "shadow": {
            "original_characters": shadow.trace["chars_before"],
            "proposed_characters": shadow.trace["proposed_chars_after"],
            "prompt_changed": False,
        },
        "opt_in_rules_enforcement": "excerpt with retrievable reference; original retained",
        "reference_restart": "exact bounded page restored",
        "jev_service": "not called; this demonstrates compatible engineering mechanics",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, help="A new directory for the fixture and persisted artifacts"
    )
    args = parser.parse_args()
    if args.directory:
        directory = args.directory.expanduser().resolve()
        if directory.exists():
            parser.error("--directory must not already exist")
        directory.mkdir(parents=True)
    else:
        directory = Path(tempfile.mkdtemp(prefix="superqode-hardening-demo-"))
    result = asyncio.run(demonstrate(directory))
    (directory / "demo-result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    print("\nInspect the persisted demo:")
    print(
        f"sq work --store {directory / 'work.sqlite3'} events {result['work_order_id']} --after-sequence 0 --json"
    )
    print(
        f"sq work --store {directory / 'work.sqlite3'} evidence {result['work_order_id']} --task implement --json"
    )


if __name__ == "__main__":
    main()
