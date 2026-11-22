"""Operational packages preserve source bytes, evidence and explicit authority."""
# ruff: noqa: F811

import io
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import stat
import sys
import zipfile

from click.testing import CliRunner
import pytest

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_improvement import prepared  # noqa: F401
from superqode.commands.factory import factory
from superqode.factory import handover, operations
from superqode.factory.compiler import compile_factory, materialize_snapshot
from superqode.factory.definition import load_factory
from superqode.factory.runtime import admit_factory, factory_store
from superqode.factory.snapshot import canonical, resolve_factory


@pytest.fixture
def queued(project):
    rewrite(project, lambda d: d["orchestration"]["stages"][0].update(human_gate=True))
    snapshot = resolve_factory(load_factory(root=project))
    plan = compile_factory(snapshot, root=project, goal="Wait for operator review")
    materialize_snapshot(plan)
    order = admit_factory(plan, request_id="operations-fixture", actor="test")
    return project, order


def test_structural_check_does_not_claim_worker_validation(project):
    before = (project / ".superqode/factory.yaml").read_bytes()
    result = operations.readiness(project)
    assert result["snapshot_digest"].startswith("sha256:")
    assert result["probe_executed"] is False and result["worker_ready"] is False
    assert (project / ".superqode/factory.yaml").read_bytes() == before
    assert not operations.path(project, "temporary").exists()


def test_wrong_platform_and_missing_sandbox_are_not_ready(project, monkeypatch):
    monkeypatch.setattr(operations.platform, "system", lambda: "Darwin")
    monkeypatch.setattr("superqode.sandbox.local_sandbox._backend_for_platform", lambda: "none")
    result = operations.readiness(project, require_platform="Linux")
    assert not result["structural_passed"] and not result["worker_ready"]
    assert [
        c["passed"] for c in result["checks"] if c["id"] in {"platform", "protected-sandbox"}
    ] == [False, False]


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Explicit native OS sandbox check"
)
def test_actual_host_readiness_probes(project):
    result = operations.readiness(project, probe=True, require_platform=platform.system())
    assert result["worker_ready"], result
    assert len([c for c in result["checks"] if c["id"].startswith("probe-")]) == 4


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Explicit native OS sandbox check"
)
def test_actual_target_worker_pauses_at_gate_without_models(queued):
    root, order = queued
    package = operations.deployment(
        root,
        target_platform=platform.system(),
        target_project=str(root),
        python=sys.executable,
        reference=order.work_order_id,
    )
    result = operations.run_deployment(Path(package["directory"]) / "manifest.json")
    assert result["readiness"]["worker_ready"]
    assert result["stats"]["claimed"] == 0
    assert result["work_order_id"] != order.work_order_id
    saved = factory_store(root, read_only=True).get(result["work_order_id"])
    assert saved.tasks[0].status.value == "waiting_for_human"
    assert all(t.attempts == 0 for t in saved.tasks)


def test_handover_roundtrip_sources_and_consistent_historical_evidence(queued):
    root, order = queued
    original = (root / ".superqode/factory.yaml").read_bytes()
    package = handover.create(root, runs=[order.work_order_id])
    inspected = handover.inspect(root, package["id"], expected=package["sha256"])
    assert inspected["inspection_only"] and not inspected["queue_restored"]
    restored = handover.restore(
        root,
        package["id"],
        expected=package["sha256"],
        destination=".superqode/factory-operations/restores/test",
    )
    destination = Path(restored["destination"])
    assert (destination / ".superqode/factory.yaml").read_bytes() == original
    assert not (destination / ".superqode/workorders").exists()
    assert not (destination / "app.py").exists()  # Application backup is separately owned.
    evidence = json.loads(
        (
            destination
            / ".superqode/factory-recovery/evidence/runs"
            / (order.work_order_id + ".json")
        ).read_text()
    )
    assert evidence["work_order"]["work_order_id"] == order.work_order_id
    assert evidence["events"] and evidence["inspection_only"]
    assert evidence["factory_snapshot"]["digest"] == inspected["snapshot_digest"]
    assert factory_store(root, read_only=True).get(order.work_order_id).to_dict() == order.to_dict()
    assert (root / ".superqode/factory.yaml").read_bytes() == original
    with pytest.raises(ValueError, match="already exists"):
        handover.restore(
            root,
            package["id"],
            expected=package["sha256"],
            destination=".superqode/factory-operations/restores/test",
        )


@pytest.mark.parametrize(
    "destination",
    [
        ".",
        "app.py",
        "../escape",
        ".superqode/workorders",
        ".superqode/factory-operations/restores/a/b",
    ],
)
def test_restore_cannot_target_existing_sources_or_runtime(project, destination):
    package = handover.create(project)
    with pytest.raises(ValueError):
        handover.restore(
            project, package["id"], expected=package["sha256"], destination=destination
        )


def test_restore_rejects_tampered_content_and_symlink_parents(project):
    package = handover.create(project)
    parent = operations.path(project, "restores")
    parent.symlink_to(project, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        handover.restore(
            project,
            package["id"],
            expected=package["sha256"],
            destination=".superqode/factory-operations/restores/test",
        )
    parent.unlink()
    location = Path(package["path"])
    location.write_bytes(location.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        handover.restore(
            project,
            package["id"],
            expected=package["sha256"],
            destination=".superqode/factory-operations/restores/test",
        )
    assert not operations.path(project, "restores/test").exists()


@pytest.mark.parametrize(
    "attack", ["traversal", "duplicate", "symlink", "compressed", "index", "authority"]
)
def test_archive_decoder_rejects_unsafe_or_inconsistent_packages(project, attack):
    package = handover.create(project)
    source = zipfile.ZipFile(package["path"])
    items = {i.filename: source.read(i) for i in source.infolist()}
    manifest = json.loads(items["manifest.json"])
    if attack == "authority":
        manifest["release_authorization"] = True
    if attack == "index":
        manifest["entries"]["snapshot.json"]["bytes"] += 1
    items["manifest.json"] = canonical(manifest).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, raw in items.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            if attack == "symlink" and name == "snapshot.json":
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            if attack == "compressed":
                info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
        if attack == "traversal":
            archive.writestr("../escape", b"no")
        if attack == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("manifest.json", items["manifest.json"])
    raw = buffer.getvalue()
    with pytest.raises(ValueError):
        handover.inspect_bytes(raw, expected=handover._hash(raw))


def test_retention_keeps_newest_and_rejects_changed_inventory(project, monkeypatch):
    real_now = operations.time.time()
    monkeypatch.setattr(handover.time, "time", lambda: real_now - 90 * 86400)
    for _ in range(3):
        handover.create(project)
    monkeypatch.setattr(handover.time, "time", lambda: real_now)
    review = handover.retention(project, keep=2, days=30)
    assert len(review["candidates"]) == 1
    handover.create(project)
    with pytest.raises(ValueError, match="inventory changed"):
        handover.prune(project, review)
    review = handover.retention(project, keep=2, days=30)
    result = handover.prune(project, review)
    assert len(result["deleted"]) == 2
    assert not result["runtime_deleted"] and not result["sources_deleted"]
    assert (project / ".superqode/factory.yaml").exists()
    assert len(handover.inventory(project)) == 2


def test_damaged_archive_is_preserved_by_retention(project, monkeypatch):
    now = operations.time.time()
    monkeypatch.setattr(handover.time, "time", lambda: now - 90 * 86400)
    first = handover.create(project)
    handover.create(project)
    Path(first["path"]).write_bytes(b"damaged")
    monkeypatch.setattr(handover.time, "time", lambda: now)
    review = handover.retention(project, keep=1, days=30)
    assert review["candidates"] == []
    assert any(not r["verified"] for r in review["inventory"])


def test_review_cutoff_cannot_shorten_the_declared_retention_period(project):
    with pytest.raises(ValueError, match="cutoff"):
        handover.retention(project, keep=2, days=30, cutoff=operations.time.time())


@pytest.mark.parametrize("system,suffix", [("Linux", "service"), ("Darwin", "plist")])
def test_service_packages_are_disabled_bounded_and_pin_one_order(queued, system, suffix):
    root, order = queued
    package = operations.deployment(
        root,
        target_platform=system,
        target_project=str(root),
        python=sys.executable,
        reference=order.work_order_id,
    )
    assert (
        package["once"]
        and not package["retry"]
        and not package["installed"]
        and package["concurrency"] == 1
    )
    destination = Path(package["directory"])
    if system == "Linux":
        unit = (destination / "worker.service").read_text()
        assert "Restart=no" in unit and "[Install]" not in unit
    else:
        manifest = plistlib.loads((destination / "worker.plist").read_bytes())
        assert not manifest["RunAtLoad"] and not manifest["KeepAlive"]
    assert factory_store(root, read_only=True).get(order.work_order_id).to_dict() == order.to_dict()


def test_wrong_host_and_changed_manifest_never_start_a_worker(queued, monkeypatch):
    root, order = queued
    package = operations.deployment(
        root,
        target_platform="Linux",
        target_project=str(root),
        python=sys.executable,
        reference=order.work_order_id,
    )
    monkeypatch.setattr(operations.platform, "system", lambda: "Darwin")
    with pytest.raises(ValueError, match="actual target platform"):
        operations.run_deployment(Path(package["directory"]) / "manifest.json")
    manifest_path = Path(package["directory"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["retry"] = True
    manifest_path.write_text(canonical(manifest))
    with pytest.raises(ValueError, match="manifest changed"):
        operations.run_deployment(manifest_path)


def test_deployment_prepares_fresh_work_in_another_checkout(queued, tmp_path, monkeypatch):
    root, source_order = queued
    target = tmp_path / "target"
    shutil.copytree(root, target, ignore=shutil.ignore_patterns(".superqode"))
    snapshot = resolve_factory(load_factory(root=root))
    for name, source in snapshot.payload["sources"].items():
        location = target / name
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_text(source["text"])
    package = operations.deployment(
        root,
        target_platform=platform.system(),
        target_project=str(target),
        python=sys.executable,
        reference=source_order.work_order_id,
    )
    install = operations.path(target, "deployments/" + package["id"])
    shutil.copytree(package["directory"], install)
    ready = operations.readiness(target)
    monkeypatch.setattr(operations, "readiness", lambda *a, **kw: {**ready, "worker_ready": True})
    result = operations.run_deployment(install / "manifest.json")
    order = factory_store(target, read_only=True).get(result["work_order_id"])
    assert order.repository == str(target)
    assert order.work_order_id != source_order.work_order_id
    assert result["source_reference"] == source_order.work_order_id
    assert result["stats"]["claimed"] == 0
    assert len(factory_store(target, read_only=True).list()) == 1
    assert (
        factory_store(root, read_only=True).get(source_order.work_order_id).to_dict()
        == source_order.to_dict()
    )


def test_bounded_existing_worker_pauses_at_gate_without_models(queued, monkeypatch):
    root, order = queued
    package = operations.deployment(
        root,
        target_platform=platform.system(),
        target_project=str(root),
        python=sys.executable,
        reference=order.work_order_id,
    )
    real_readiness = operations.readiness(root)
    monkeypatch.setattr(
        operations, "readiness", lambda *a, **kw: {**real_readiness, "worker_ready": True}
    )
    result = operations.run_deployment(Path(package["directory"]) / "manifest.json")
    assert result["stats"]["claimed"] == 0
    assert result["work_order_id"] != order.work_order_id
    saved = factory_store(root, read_only=True).get(result["work_order_id"])
    assert all(t.attempts == 0 for t in saved.tasks)
    repeated = operations.run_deployment(Path(package["directory"]) / "manifest.json")
    assert repeated["work_order_id"] == result["work_order_id"]
    assert repeated["stats"]["claimed"] == 0


def test_cli_requires_live_and_exact_archive_digest(project):
    runner = CliRunner()
    created = runner.invoke(factory, ["operations", "handover", "--project", str(project)])
    assert created.exit_code == 0, created.output
    package = json.loads(created.output)
    verified = runner.invoke(
        factory,
        [
            "operations",
            "verify",
            "--project",
            str(project),
            package["id"],
            "--digest",
            package["sha256"],
        ],
    )
    assert verified.exit_code == 0, verified.output
    failed = runner.invoke(
        factory,
        [
            "operations",
            "verify",
            "--project",
            str(project),
            package["id"],
            "--digest",
            "sha256:" + "0" * 64,
        ],
    )
    assert failed.exit_code != 0


def test_improvement_ledger_is_exported_only_as_inert_history(prepared):
    root, plan = prepared
    original = (root / ".superqode/factory-improvements" / plan["id"] / "usage.json").read_bytes()
    package = handover.create(root, improvements=[plan["id"]])
    restored = handover.restore(
        root,
        package["id"],
        expected=package["sha256"],
        destination=".superqode/factory-operations/restores/improvement",
    )
    recovered = Path(restored["destination"])
    assert (
        recovered / ".superqode/factory-recovery/evidence/improvements" / plan["id"] / "usage.json"
    ).read_bytes() == original
    assert not (recovered / ".superqode/factory-improvements").exists()


def test_native_operations_require_confirmation_and_respect_active_job(
    queued, tmp_path, monkeypatch
):
    from superqode.desktop_service.service import DesktopService

    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    root, _ = queued
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(root))["id"]
        result = service.dispatch("factory.operations.inspect", {"project": identity})
        assert result["packages"] == []
        with pytest.raises(ValueError, match="confirm"):
            service.dispatch("factory.operations.handover", {"project": identity})
        from superqode.desktop_service.ownership import Lease, project_lease_path

        lease = Lease(project_lease_path(service.root, root))
        try:
            with pytest.raises(ValueError, match="owns this workspace"):
                service.dispatch(
                    "factory.operations.handover", {"project": identity, "confirmed": True}
                )
        finally:
            lease.close()
        result = service.dispatch(
            "factory.operations.handover", {"project": identity, "confirmed": True}
        )
        assert result["inspection_only"] and not service.processes
    finally:
        service.close()
