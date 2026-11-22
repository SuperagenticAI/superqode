"""One authoring engine for the macOS app, CLI and TUI.

Opening, validating, saving, templating and AI drafting of
``.superqode/factory.yaml`` live here. Interfaces add their own review and
locking, then call these functions so every surface writes the same revisions.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import re
import time

import yaml

from .definition import FactoryDefinition, LAYERS, project_path, read_mapping, validate_definition
from .snapshot import resolve_factory
from .templates import factory_template

TARGET = ".superqode/factory.yaml"
REVISIONS = ".superqode/factory-studio/revisions"
DRAFTS = ".superqode/factory-studio/drafts"
TEMPLATES = ("fix-and-verify", "continuous-outcomes")


def _helpers():
    from superqode.desktop_service.studio import _atomic, _credentials, file_digest, sha

    return _atomic, _credentials, file_digest, sha


def target(root):
    return project_path(Path(root).resolve(), TARGET)


def read_text(path):
    if path.stat().st_size > 250000:
        raise ValueError("Factory definition exceeds 250 KB")
    return path.read_text(encoding="utf-8")


def parse(root, text):
    _, credentials, _, _ = _helpers()
    root = Path(root).resolve()
    data = read_mapping(text)
    validate_definition(data)
    credentials(data)
    return data, resolve_factory(FactoryDefinition(root, target(root), data), source_text=text)


def template_text(root, name="fix-and-verify"):
    """A full FactorySpec from a template, keeping any existing route policy."""
    data = factory_template(name)
    path = target(root)
    if path.is_file():
        existing = read_mapping(read_text(path))
        for key in ("default_route", "routes"):
            if key in existing:
                data[key] = existing[key]
    return yaml.safe_dump(data, sort_keys=False)


def open_definition(root, *, template="", revision=""):
    _, _, file_digest, _ = _helpers()
    root = Path(root).resolve()
    path = target(root)
    current = read_text(path) if path.is_file() else ""
    if template:
        current = template_text(root, template)
    elif revision:
        if not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise ValueError("Invalid factory revision")
        current = read_text(project_path(root, f"{REVISIONS}/{revision}.yaml"))
    return {
        "yaml": current,
        "expected_file_digest": file_digest(path),
        "legacy": bool(current and "apiVersion" not in read_mapping(current)),
    }


def inspect_definition(root, text):
    """Validate a proposed definition and describe it. Makes no model calls."""
    _, _, file_digest, sha = _helpers()
    root = Path(root).resolve()
    data, snapshot = parse(root, text)
    path = target(root)
    old = read_text(path) if path.is_file() else ""
    warnings = []
    for name in data["orchestration"]["acceptance_checks"]:
        if "evaluator" not in data["improvement"]["checks"][name]:
            warnings.append(
                f"{name}: add protected evaluator probes before acceptance verification."
            )
    if not data["governance"].get("release_authority"):
        warnings.append("No release signing authority is configured; delivery remains on hold.")
    warnings.append(
        "Definition validation makes no model calls and does not establish execution quality."
    )
    return {
        "yaml": text,
        "name": data["metadata"]["name"],
        "digest": sha(text),
        "snapshot_digest": snapshot.digest,
        "expected_file_digest": file_digest(path),
        "warnings": warnings,
        "stages": data["orchestration"]["stages"],
        "requirements": data["data_context"].get("requirements", {}),
        "application_checks": data["improvement"]["checks"],
        "acceptance_checks": data["orchestration"]["acceptance_checks"],
        "revision_loop": data["orchestration"].get("revision_loop", {}),
        "layers": list(LAYERS),
        "bindings": data["inference"]["harnesses"],
        "binding_models": {
            name: harness.get("model_policy", {}).get("primary", "")
            for name, harness in snapshot.payload["harnesses"].items()
        },
        "governance": data["governance"],
        "diff": "".join(
            difflib.unified_diff(
                old.splitlines(True),
                text.splitlines(True),
                fromfile="Current factory",
                tofile="Proposed factory",
            )
        ),
    }


def save_definition(root, text, *, expected_file_digest, reason, expected_snapshot_digest=""):
    """Write a reviewed revision. Callers hold their interface's project lock."""
    atomic, _, file_digest, sha = _helpers()
    root = Path(root).resolve()
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("Describe why this factory revision is being saved")
    path = target(root)
    current = file_digest(path)
    if current != expected_file_digest:
        raise ValueError("Project factory changed; reload before saving")
    _, snapshot = parse(root, text)
    if expected_snapshot_digest and snapshot.digest != expected_snapshot_digest:
        raise ValueError("Factory components changed since validation; validate again")
    token = sha(text)
    folder = project_path(root, REVISIONS)
    versions = [(token, text)]
    if current:
        versions.append((current, read_text(path)))
    for name, body in versions:
        stored = project_path(root, (folder.relative_to(root) / (name + ".yaml")).as_posix())
        if stored.exists() and read_text(stored) != body:
            raise ValueError("Stored factory revision was modified")
        if not stored.exists():
            atomic(stored, body)
    metadata = project_path(root, (folder.relative_to(root) / (token + ".json")).as_posix())
    if not metadata.exists():
        atomic(metadata, json.dumps({"reason": reason, "parent": current, "created": time.time()}))
    atomic(path, text)
    return {"digest": token, "snapshot_digest": snapshot.digest, "path": str(path)}


def init_from_template(root, name="fix-and-verify", *, force=False):
    """Create a full FactorySpec. Existing route policy is kept; nothing else is overwritten."""
    _, _, file_digest, _ = _helpers()
    if name not in TEMPLATES:
        raise ValueError("Choose fix-and-verify or continuous-outcomes")
    root = Path(root).resolve()
    path = target(root)
    upgraded = False
    if path.is_file():
        existing = read_mapping(read_text(path))
        upgraded = "apiVersion" not in existing
        if not upgraded and not force:
            raise ValueError(
                f"{TARGET} already holds a FactorySpec; pass --force to replace it from the template"
            )
    text = template_text(root, name)
    result = save_definition(
        root,
        text,
        expected_file_digest=file_digest(path),
        reason=f"Created from the {name} template",
    )
    return {**result, "template": name, "upgraded_route_policy": upgraded}


async def draft(root, description, *, provider, model, gateway=None):
    """Ask a model for a FactorySpec draft. Stores a draft for review, never the definition."""
    from .generation import generate_factory

    atomic, _, _, sha = _helpers()
    root = Path(root).resolve()
    path = target(root)
    base = read_text(path) if path.is_file() else ""
    if not base or "apiVersion" not in read_mapping(base):
        base = template_text(root, "fix-and-verify")
    proposal = await generate_factory(
        description=description, yaml_text=base, provider=provider, model=model, gateway=gateway
    )
    review = inspect_definition(root, proposal["yaml"])
    folder = project_path(root, DRAFTS)
    stored = {
        "yaml": proposal["yaml"],
        "assumptions": proposal["assumptions"],
        "missing_capabilities": proposal["missing_capabilities"],
        "expected_file_digest": review["expected_file_digest"],
        "snapshot_digest": review["snapshot_digest"],
        "created": time.time(),
    }
    atomic(
        project_path(root, (folder.relative_to(root) / (review["digest"] + ".json")).as_posix()),
        json.dumps(stored),
    )
    return {
        **review,
        "assumptions": proposal["assumptions"],
        "missing_capabilities": proposal["missing_capabilities"],
        "usage": proposal.get("usage"),
        "cost": proposal.get("cost"),
        "proposal_only": True,
        "written": False,
    }


def apply_draft(root, digest_value, *, reason, confirmed):
    """Save a reviewed AI draft. Requires explicit confirmation and an unchanged base."""
    if confirmed is not True:
        raise ValueError("Confirm saving the reviewed Factory draft")
    if not isinstance(digest_value, str) or not re.fullmatch(r"[0-9a-f]{64}", digest_value):
        raise ValueError("Choose a Factory draft by its digest")
    root = Path(root).resolve()
    path = project_path(root, f"{DRAFTS}/{digest_value}.json")
    if not path.is_file():
        raise ValueError("Factory draft not found; run describe again")
    stored = json.loads(read_text(path))
    if time.time() - stored["created"] > 86400:
        raise ValueError("Factory draft expired; run describe again")
    _, _, _, sha = _helpers()
    if sha(stored["yaml"]) != digest_value:
        raise ValueError("Factory draft changed after review")
    return save_definition(
        root,
        stored["yaml"],
        expected_file_digest=stored["expected_file_digest"],
        reason=reason,
        expected_snapshot_digest=stored["snapshot_digest"],
    )
