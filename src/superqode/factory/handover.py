"""Bounded source recovery and inspection-only evidence packages.

These archives deliberately do not restore a live queue, approval authority,
credentials, application Git history, workers or model session state.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from uuid import uuid4
import zipfile

from superqode import __version__
from .definition import load_factory, project_path, relative_path
from .operations import path, read, write, ownership
from .snapshot import FactorySnapshot, canonical, digest, resolve_factory
from .versioning import _safe_text, source_path, source_name

FORMAT = "superqode.factory-handover/1"
MAX_BYTES = 64_000_000
MAX_ENTRIES = 512
PACKAGE_ID = re.compile(r"handover_[a-f0-9]{32}")


def _identity(value):
    if not isinstance(value, str) or not PACKAGE_ID.fullmatch(value):
        raise ValueError("Choose a Factory handover package")
    return value


def _hash(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value:
                raise ValueError("Duplicate manifest field")
            value[k] = v
        return value

    return json.loads(raw, object_pairs_hook=pairs)


def create(root, *, runs=(), improvements=()):
    """Capture pinned Factory sources plus explicitly selected historical evidence."""
    root = Path(root).resolve()
    if (
        len(runs) > 8
        or len(improvements) > 8
        or len(set(runs)) != len(runs)
        or len(set(improvements)) != len(improvements)
    ):
        raise ValueError("Select at most eight distinct runs and improvement plans each")
    with ownership(root):
        snapshot = resolve_factory(load_factory(root=root))
        entries = {}

        def add(name, content):
            if (
                len(entries) >= MAX_ENTRIES
                or sum(map(len, entries.values())) + len(content) > MAX_BYTES - 1_000_000
            ):
                raise ValueError("Handover exceeds its entry or byte limit")
            entries[name] = content

        add("snapshot.json", canonical(snapshot.to_dict()).encode())
        for name, value in snapshot.payload["sources"].items():
            source_path(root, name)
            _safe_text(name, value["text"])
        from .compiler import repository_revision
        from .runtime import factory_store, _pinned_plan
        from superqode.workorders.models import WorkOrder

        for reference in runs:
            store = factory_store(root, read_only=True)
            exported = store.export_evidence(reference)
            order = WorkOrder.from_dict(exported["work_order"])
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", order.work_order_id):
                raise ValueError("Invalid WorkOrder evidence identity")
            # Historical evidence may predate the baseline or its cleaned worktree.
            exported["factory_snapshot"] = _pinned_plan(order).snapshot.to_dict()
            add("evidence/runs/" + order.work_order_id + ".json", canonical(exported).encode())
        from . import improvement

        for identity in improvements:
            plan, _ = improvement.load(root, identity)
            directory = improvement.folder(root, identity)
            # Hold the same ownership lease used by optimiser actions during capture.
            with improvement.budget(root, plan).action():
                names = ["plan.json", "snapshot.json", "baseline.yaml", "tasks.yaml", "usage.json"]
                receipt_path = project_path(
                    root, (directory / "comparison/receipt.json").relative_to(root).as_posix()
                )
                if receipt_path.exists():
                    receipt = _json(read(receipt_path))
                    token = receipt.get("candidate", "")
                    candidate_path, _ = improvement.get_candidate(root, plan, token)
                    names.extend(
                        [
                            "comparison/receipt.json",
                            candidate_path.relative_to(directory).as_posix(),
                        ]
                    )
                for name in names:
                    incoming = project_path(root, (directory / name).relative_to(root).as_posix())
                    add("evidence/improvements/" + identity + "/" + name, read(incoming))
        identity = "handover_" + uuid4().hex
        manifest = {
            "format": FORMAT,
            "id": identity,
            "engine_version": __version__,
            "created": time.time(),
            "snapshot_digest": snapshot.digest,
            "repository_commit": repository_revision(root),
            "inspection_only": True,
            "queue_restored": False,
            "release_authorization": False,
            "scope": "Factory source recovery and selected historical evidence; application Git backup required separately",
            "entries": {
                name: {"sha256": _hash(raw), "bytes": len(raw)} for name, raw in entries.items()
            },
        }
        if (
            len(entries) > MAX_ENTRIES
            or sum(len(raw) for raw in entries.values()) > MAX_BYTES - 1_000_000
        ):
            raise ValueError("Handover exceeds its entry or byte limit")
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", canonical(manifest))
            for name, content in sorted(entries.items()):
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, content)
        content = raw.getvalue()
        # Exercise the same strict decoder before publishing the package.
        inspect_bytes(content, expected=_hash(content))
        location = path(root, "packages/" + identity + ".sqfactory")
        write(location, content)
        receipt = {
            "id": identity,
            "sha256": _hash(content),
            "bytes": len(content),
            "created": manifest["created"],
            "snapshot_digest": snapshot.digest,
        }
        write(path(root, "packages/" + identity + ".json"), canonical(receipt))
        return {
            **receipt,
            "path": str(location),
            "inspection_only": True,
            "execution_started": False,
        }


def inspect_bytes(raw, *, expected):
    """Verify a supplied whole-package digest and every indexed byte before use."""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", expected or "") or _hash(raw) != expected:
        raise ValueError("Handover package digest mismatch")
    if len(raw) > MAX_BYTES:
        raise ValueError("Handover exceeds 64 MB")
    entries = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if (
                not 2 <= len(infos) <= MAX_ENTRIES + 1
                or sum(i.file_size for i in infos) > MAX_BYTES
            ):
                raise ValueError("Handover entry or expanded byte limit exceeded")
            for info in infos:
                name = info.filename
                relative = relative_path(name)
                if (
                    name != relative.as_posix()
                    or name in entries
                    or info.is_dir()
                    or info.flag_bits & 1
                ):
                    raise ValueError("Handover requires unique regular canonical paths")
                mode = info.external_attr >> 16
                if (
                    stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                    or info.compress_type != zipfile.ZIP_STORED
                ):
                    raise ValueError(
                        "Handover links, devices and compressed entries are unsupported"
                    )
                if (
                    name != "manifest.json"
                    and name != "snapshot.json"
                    and not name.startswith("evidence/")
                ):
                    raise ValueError("Unexpected handover entry")
                entries[name] = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Invalid handover archive") from exc
    manifest = _json(entries.pop("manifest.json"))
    if (
        manifest.get("format") != FORMAT
        or manifest.get("inspection_only") is not True
        or manifest.get("queue_restored") is not False
        or manifest.get("release_authorization") is not False
    ):
        raise ValueError("Unsupported handover manifest or authority")
    _identity(manifest.get("id"))
    indexed = manifest.get("entries")
    if not isinstance(indexed, dict) or set(indexed) != set(entries):
        raise ValueError("Handover index does not match archive")
    for name, content in entries.items():
        if indexed[name] != {"sha256": _hash(content), "bytes": len(content)}:
            raise ValueError("Handover indexed content changed")
    snapshot = FactorySnapshot.from_dict(_json(entries["snapshot.json"]))
    if snapshot.digest != manifest.get("snapshot_digest"):
        raise ValueError("Handover snapshot binding mismatch")
    # Check writable source names at verification, not after extraction starts.
    for name, source in snapshot.payload["sources"].items():
        source_name(name)
        _safe_text(name, source["text"])
    return manifest, entries, snapshot


def inspect(root, identity, *, expected):
    identity = _identity(identity)
    raw = read(path(root, "packages/" + identity + ".sqfactory"), MAX_BYTES)
    manifest, _, _ = inspect_bytes(raw, expected=expected)
    if manifest["id"] != identity:
        raise ValueError("Handover identity mismatch")
    return {"verified": True, "sha256": expected, **manifest}


def restore(root, identity, *, expected, destination):
    """Recover into a new project-local folder; never overwrite or resume work."""
    root = Path(root).resolve()
    identity = _identity(identity)
    target = project_path(root, destination)
    # Fixed recovery namespace prevents writing into sources/runtime/project root.
    if not re.fullmatch(
        r"\.superqode/factory-operations/restores/[A-Za-z0-9][A-Za-z0-9_-]{0,63}", destination
    ):
        raise ValueError("Restore into a new Factory operations restores/<name> directory")
    with ownership(root):
        raw = read(path(root, "packages/" + identity + ".sqfactory"), MAX_BYTES)
        manifest, entries, snapshot = inspect_bytes(raw, expected=expected)
        if manifest["id"] != identity or target.exists():
            raise ValueError("Restore identity mismatch or destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = Path(tempfile.mkdtemp(dir=target.parent, prefix=".restore-"))
        try:
            for name, source in snapshot.payload["sources"].items():
                write(project_path(temporary, name), source["text"])
            history = temporary / ".superqode/factory-recovery"
            for name, content in entries.items():
                write(project_path(history, name), content)
            write(history / "manifest.json", canonical(manifest))
            recovered = resolve_factory(load_factory(root=temporary))
            if recovered.digest != snapshot.digest:
                raise ValueError("Recovered Factory source resolution differs from the snapshot")
            # Exclusive destination creation also refuses a concurrently created
            # empty directory; rename() alone could overwrite that directory.
            target.mkdir(mode=0o700)
            for child in temporary.iterdir():
                child.rename(target / child.name)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {
        "restored": True,
        "destination": str(target),
        "snapshot_digest": snapshot.digest,
        "inspection_only": True,
        "queue_restored": False,
        "release_authorization": False,
    }


def inventory(root):
    directory = path(root, "packages")
    if not directory.exists():
        return []
    rows = []
    for index, item in enumerate(sorted(directory.iterdir())):
        if index >= 2000:
            raise ValueError("Operations inventory exceeds 2,000 directory entries")
        if not item.name.endswith(".json"):
            continue
        identity = _identity(item.stem)
        receipt = _json(read(path(root, "packages/" + item.name), 64_000))
        if receipt.get("id") != identity or not isinstance(receipt.get("created"), (float, int)):
            raise ValueError("Invalid package inventory receipt")
        verified = False
        try:
            result = inspect(root, identity, expected=receipt.get("sha256"))
            verified = result["created"] == receipt["created"]
        except (ValueError, OSError, KeyError):
            pass
        rows.append({**receipt, "verified": verified})
    return sorted(rows, key=lambda row: (row["created"], row["id"]), reverse=True)


def retention(root, *, keep=2, days=30, cutoff=None):
    if (
        type(keep) is not int
        or not 1 <= keep <= 100
        or type(days) is not int
        or not 1 <= days <= 3650
    ):
        raise ValueError("Keep 1–100 packages for 1–3650 days")
    latest_cutoff = time.time() - days * 86400
    cutoff = latest_cutoff if cutoff is None else cutoff
    if not isinstance(cutoff, (int, float)) or not 0 < cutoff <= latest_cutoff:
        raise ValueError("Invalid retention cutoff")
    rows = inventory(root)
    protected = {r["id"] for r in [r for r in rows if r["verified"]][:keep]}
    candidates = [
        r for r in rows if r["verified"] and r["id"] not in protected and r["created"] < cutoff
    ]
    value = {
        "format": "superqode.factory-retention/1",
        "keep": keep,
        "days": days,
        "cutoff": cutoff,
        "inventory": rows,
        "candidates": candidates,
        "scope": "generated handover archives only",
        "sources_deleted": False,
        "runtime_deleted": False,
    }
    return {**value, "digest": digest(canonical(value))}


def prune(root, review):
    """Delete only reviewed generated archives. Source and live evidence stay put."""
    with ownership(root):
        current = retention(root, keep=review["keep"], days=review["days"], cutoff=review["cutoff"])
        if current != review:
            raise ValueError("Retention inventory changed; preview again")
        deleted = []
        journal = path(root, "retention/" + uuid4().hex + ".json")
        state = {"review": review, "deleted": deleted, "complete": False}
        write(journal, canonical(state))
        for row in current["candidates"]:
            identity = _identity(row["id"])
            inspect(root, identity, expected=row["sha256"])
            path(root, "packages/" + identity + ".sqfactory").unlink()
            path(root, "packages/" + identity + ".json").unlink()
            deleted.append(identity)
            write(journal, canonical(state))
        state["complete"] = True
        write(journal, canonical(state))
        return {
            "deleted": deleted,
            "journal": str(journal),
            "sources_deleted": False,
            "runtime_deleted": False,
        }
