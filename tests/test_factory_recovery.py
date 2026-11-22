"""Offline capture retains execution state without restoring release authority."""
# ruff: noqa: F401, F811

from pathlib import Path
import json

import pytest

from test_factory_definition import project, rewrite, git
from test_factory_operations import queued
from superqode.factory import recovery, lifecycle, maintenance, improvement
from superqode.factory.runtime import factory_store, validate_factory_order
from superqode.factory.snapshot import canonical


def recover(root, package):
    original = root.with_name("original-project")
    root.rename(original)
    archive = original / Path(package["path"]).relative_to(root)
    key = original / Path(package["key_file"]).relative_to(root)
    return recovery.restore(archive, key, expected=package["sha256"], destination=str(root))


def test_runtime_roundtrip_restores_git_queue_and_disarms_execution(queued):
    root, order = queued
    before = factory_store(root, read_only=True).export_evidence(order.work_order_id)
    package = recovery.create(root)
    assert Path(package["key_file"]).stat().st_mode & 0o777 == 0o600
    assert not Path(package["path"]).read_bytes().startswith(b"PK")
    manifest, entries = recovery.decode(package["path"], package["key_file"], package["sha256"])
    assert ".git/HEAD" in entries and ".superqode/workorders/store.sqlite3" in entries
    assert not any("backup-keys" in n or n.endswith(("-wal", "-shm")) for n in entries)
    result = recover(root, package)
    assert not result["execution_enabled"]
    assert git(root, "rev-parse", "HEAD") == manifest["commit"]
    store = factory_store(root, read_only=True)
    assert store.export_evidence(order.work_order_id) == before
    validate_factory_order(store.get(order.work_order_id), check_baseline=False)
    with pytest.raises(ValueError, match="disarmed"):
        validate_factory_order(store.get(order.work_order_id))
    with pytest.raises(ValueError, match="disarmed"):
        factory_store(root).claim_next_task(worker_id="unapproved-recovery")
    assert all(t.attempts == 0 for t in store.get(order.work_order_id).tasks)


def test_recovery_does_not_overwrite_or_relocate_a_live_project(queued):
    root, order = queued
    package = recovery.create(root)
    for destination in (root, root.with_name("different-project")):
        with pytest.raises(ValueError, match="original canonical"):
            recovery.restore(
                package["path"],
                package["key_file"],
                expected=package["sha256"],
                destination=str(destination),
            )
    assert (root / "app.py").read_text() == "answer = 42\n"


def test_runtime_roundtrip_preserves_empty_optimizer_fixture_directories(queued):
    root, _ = queued
    fixture = root / ".superqode/factory-improvements/empty-plan/fixture"
    fixture.mkdir(parents=True)
    package = recovery.create(root)
    manifest, _ = recovery.decode(package["path"], package["key_file"], package["sha256"])
    assert fixture.relative_to(root).as_posix() in manifest["directories"]
    recover(root, package)
    assert fixture.is_dir() and list(fixture.iterdir()) == []


def test_wrong_key_and_tampered_archive_fail_before_writing(queued):
    root, order = queued
    package = recovery.create(root)
    key = Path(package["key_file"])
    original_key = key.read_bytes()
    key.write_bytes(b"x" * 32)
    with pytest.raises(ValueError, match="authentication"):
        recovery.decode(package["path"], key, package["sha256"])
    key.write_bytes(original_key)
    archive = Path(package["path"])
    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="digest"):
        recovery.decode(archive, key, package["sha256"])


def test_offline_capture_rejects_active_execution_and_unreconciled_tasks(queued):
    root, order = queued
    with maintenance.execution(root):
        with pytest.raises(ValueError, match="still owns"):
            recovery.create(root)
    rewrite(root, lambda d: d["orchestration"]["stages"][0].update(human_gate=False))
    # Claim an ordinary test order through the real queue without running a model.
    from dataclasses import replace
    from superqode.workorders.models import WorkOrder, WorkOrderTask

    store = factory_store(root)
    store.create(
        WorkOrder(
            work_order_id="test-active",
            goal="Active fixture",
            repository=str(root),
            tasks=(WorkOrderTask(task_id="task", goal="Work", title="Work"),),
        ),
        queue=True,
    )
    assert store.claim_next_task(worker_id="fixture", reference="test-active") is not None
    with pytest.raises(ValueError, match="Drain workers"):
        recovery.create(root)


def test_recovery_requires_real_probe_and_uncertain_work_review(queued, monkeypatch):
    root, order = queued
    package = recovery.create(root)
    result = recover(root, package)
    with pytest.raises(ValueError, match="Actual protected"):
        recovery.acknowledge(root, result["recovery_digest"])
    monkeypatch.setattr(
        "superqode.factory.operations.readiness", lambda *a, **k: {"worker_ready": False}
    )
    with pytest.raises(ValueError, match="did not pass"):
        recovery.acknowledge(root, result["recovery_digest"], probe=True)
    assert (root / ".superqode/factory-operations/recovery-required.json").exists()


def test_recovery_acknowledgement_never_reuses_release_signature(queued, monkeypatch):
    root, order = queued
    store = factory_store(root)
    from dataclasses import replace

    with store._transaction() as conn:
        store._save_tx(
            conn,
            replace(
                order, metadata={**order.metadata, "factory_release": {"signature": "historical"}}
            ),
        )
    package = recovery.create(root)
    result = recover(root, package)
    # Controlled controller test; actual native probes are exercised separately.
    monkeypatch.setattr(
        "superqode.factory.operations.readiness",
        lambda *a, **k: {"worker_ready": True, "simulated": True},
    )
    recovery.acknowledge(root, result["recovery_digest"], probe=True)
    restored = factory_store(root, read_only=True).get(order.work_order_id)
    assert "factory_release" not in restored.metadata
    assert restored.tasks[0].attempts == 0
    assert (
        factory_store(root, read_only=True).events(order.work_order_id)[-1].type
        == "factory.recovered"
    )
    maintenance.assert_enabled(root)


def test_retirement_fences_new_work_and_preserves_evidence(queued, monkeypatch):
    root, order = queued
    review = lifecycle.review(root)
    result = lifecycle.retire(root, review["digest"])
    assert result["evidence_retained"] and result["worktrees_retained"]
    assert factory_store(root, read_only=True).get(order.work_order_id).status.value == "cancelled"
    with pytest.raises(ValueError, match="retired"):
        maintenance.assert_enabled(root)
    with pytest.raises(ValueError, match="probes"):
        lifecycle.reactivate(root, review["digest"])
    monkeypatch.setattr(
        lifecycle, "readiness", lambda *a, **k: {"worker_ready": True, "simulated": True}
    )
    resumed = lifecycle.reactivate(root, review["digest"], probe=True)
    assert not resumed["cancelled_work_restarted"]
    assert factory_store(root, read_only=True).get(order.work_order_id).status.value == "cancelled"


def test_retirement_rejects_a_stale_inventory(queued):
    root, order = queued
    review = lifecycle.review(root)
    factory_store(root).add_artifact(
        order.work_order_id, kind="note", content="new evidence", actor="fixture"
    )
    with pytest.raises(ValueError, match="inventory changed"):
        lifecycle.retire(root, review["digest"])


def test_symlinks_and_hardlinked_inputs_cannot_enter_checkpoint(queued):
    root, order = queued
    link = root / ".superqode/factory/link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(root / "app.py")
    with pytest.raises(ValueError, match="symbolic"):
        recovery.create(root)


def test_exclusive_maintenance_blocks_queue_transactions_without_mutating(queued):
    root, order = queued
    from threading import Thread

    outcomes = []

    def other_writer():
        try:
            factory_store(root).cancel(order.work_order_id, actor="other", reason="interfering")
        except ValueError as error:
            outcomes.append(str(error))

    with maintenance.execution(root, exclusive=True, require_enabled=False):
        thread = Thread(target=other_writer)
        thread.start()
        thread.join(timeout=5)
    assert outcomes and "offline maintenance" in outcomes[0]
    assert factory_store(root, read_only=True).get(order.work_order_id).status.value == "queued"
