"""Import optimizer artifacts as proposals, never as evaluation authority."""

from __future__ import annotations

import json
from pathlib import Path
import re

from . import improvement
from .definition import project_path, relative_path
from .snapshot import canonical, digest
from .versioning import SECRET_PARTS


def techniques():
    """Factory capability, distinct from the broader CLI engine catalog."""
    return [
        {
            "id": "native",
            "name": "Native evaluator–optimizer",
            "mode": "Metered Factory search",
            "search": True,
        },
        {
            "id": "gepa",
            "name": "GEPA",
            "mode": "Metered Factory search; optional dependency",
            "search": True,
        },
        {
            "id": "skills",
            "name": "Bound skills",
            "mode": "Instruction proposals and metered comparison",
            "search": True,
        },
        {
            "id": "metaharness",
            "name": "MetaHarness",
            "mode": "Optional metered kernel with Factory-owned gateway; external import also supported",
            "search": True,
        },
        {
            "id": "omni-search",
            "name": "Omni portfolio",
            "mode": "Metered composition of native, GEPA and MetaHarness; not opaque external-agent execution",
            "search": True,
        },
        {
            "id": "omni",
            "name": "GEPA Omni",
            "mode": "External candidate import; separate harness engine",
            "search": False,
        },
    ]


def _path(root, value):
    relative = relative_path(value)
    if value != relative.as_posix() or any(
        p in SECRET_PARTS or p.startswith((".env", ".superqode-")) or any(ord(c) < 32 for c in p)
        for p in relative.parts
    ):
        raise ValueError("Use a canonical project-relative optimizer artifact path")
    return project_path(root, value)


def _json(path):
    value = json.loads(improvement._read(path, 250000))
    if not isinstance(value, dict):
        raise ValueError("Optimizer metadata must be a JSON object")
    return value


def _workspace(root, base, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Optimizer artifact must name its candidate workspace")
    incoming = Path(value)
    candidate = incoming if incoming.is_absolute() else base / incoming
    # Lexical containment is checked before accessing any provided path.
    if not candidate.is_relative_to(base) or not candidate.is_relative_to(root):
        raise ValueError("Optimizer candidate must stay inside its run/report directory")
    return _path(root, candidate.relative_to(root).as_posix())


def import_candidate(root, identity, *, engine, artifact):
    """Read only known artifact files; no subprocess, dependency install or model."""
    if engine not in {"metaharness", "omni"}:
        raise ValueError("Choose MetaHarness or GEPA Omni")
    root = Path(root).resolve()
    plan, _ = improvement.load(root, identity, fresh=True)
    if plan.get("target_kind", "harness") != "harness":
        raise ValueError("External optimizer imports currently require a harness-instructions plan")
    base = _path(root, artifact)
    with improvement.budget(root, plan).action():
        if engine == "metaharness":
            leaderboard = _json(_path(root, artifact + "/indexes/leaderboard.json"))
            selected = leaderboard.get("best_candidate_id")
            if not isinstance(selected, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", selected
            ):
                raise ValueError("MetaHarness leaderboard must name a safe best candidate id")
            manifest = _json(_path(root, artifact + "/candidates/" + selected + "/manifest.json"))
            if manifest.get("candidate_id") != selected:
                raise ValueError("MetaHarness candidate identity differs from its leaderboard")
            workspace = _workspace(root, base, manifest.get("workspace_dir"))
            source = _path(root, (workspace / "harness.yaml").relative_to(root).as_posix())
            metadata = {"leaderboard": leaderboard, "manifest": manifest}
        else:
            if base.suffix != ".json":
                raise ValueError("Choose the GEPA Omni result JSON file")
            metadata = _json(base)
            source = _workspace(root, base.parent, metadata.get("staged_spec_path"))
            if source.suffix not in {".yaml", ".yml"}:
                raise ValueError("GEPA Omni must name a YAML candidate HarnessSpec")
        text = improvement._read(source, 250000)
        metadata_digest = digest(canonical(metadata))
        # The normal Factory surface audit rejects changed tools, context,
        # permissions, graders, model routes and workflow before staging.
        result = improvement.stage(root, identity, text)
        origin = {
            "format": "superqode.factory-external-proposal/1",
            "engine": engine,
            "plan_digest": plan["digest"],
            "candidate": result["candidate"],
            "artifact": artifact,
            "source": source.relative_to(root).as_posix(),
            "source_digest": digest(text),
            "metadata_digest": metadata_digest,
            "external_scores_authoritative": False,
            "external_usage_included": False,
            "adoption_authorized": False,
            "execution_started": False,
        }
        directory = improvement.folder(root, identity)
        origin_id = digest(canonical(origin))[7:23]
        target = project_path(
            root,
            (
                directory
                / "origins"
                / (result["candidate"] + "-" + engine + "-" + origin_id + ".json")
            )
            .relative_to(root)
            .as_posix(),
        )
        improvement._write(target, canonical(origin))
        return {
            **result,
            "origin": origin,
            "notice": "Proposal imported. External scores and spending do not count as Factory evidence; run a separate metered held-out comparison.",
        }
