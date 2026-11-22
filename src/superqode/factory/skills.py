"""Explicit, snapshot-owned skill instructions for Factory harness bindings.

A binding applies Markdown instructions. Skill metadata never installs tools,
executes scripts, discovers user directories or changes runtime permissions.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from .definition import read_mapping, relative_path

MAX_SKILL_BYTES = 50_000
MAX_BOUND_PROMPT_BYTES = 100_000


def parse_skill(text):
    if not isinstance(text, str) or len(text.encode()) > MAX_SKILL_BYTES or "\0" in text:
        raise ValueError("Use a Markdown skill smaller than 50 KB without NUL characters")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("Factory skills require YAML frontmatter with a stable name")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValueError("Skill frontmatter needs a closing --- line")
    metadata = read_mapping("".join(lines[1:end]))
    name = metadata.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("Skill frontmatter needs a stable name of up to 64 characters")
    if metadata.get("enabled", True) is not True:
        raise ValueError("A disabled skill cannot be bound to a Factory harness")
    if "description" in metadata and not isinstance(metadata["description"], str):
        raise ValueError("Skill description must be text")
    body = "".join(lines[end + 1 :]).strip()
    if not body:
        raise ValueError("Skill instructions cannot be empty")
    return metadata, body


def check_candidate(baseline, candidate):
    from superqode.skillopt import _check_skill_text

    before, _ = parse_skill(baseline)
    after, _ = parse_skill(candidate)
    if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
        raise ValueError(
            "Skill candidates may edit instructions only; frontmatter metadata is protected"
        )
    result = _check_skill_text(
        baseline_text=baseline, candidate_text=candidate, max_edits=8, max_bytes=MAX_SKILL_BYTES
    )
    if not result["ok"]:
        raise ValueError("Skill edit rejected: " + "; ".join(result["errors"]))
    return result


def bound_harness(payload, binding, *, harness=None, skill_overrides=None):
    """Apply declared assets from immutable source text; perform no file I/O."""
    definition = payload["definition"]
    assets = definition["data_context"].get("files", {})
    selected = definition["inference"]["harnesses"][binding].get("skills", [])
    overrides = skill_overrides or {}
    if set(overrides) - set(selected):
        raise ValueError("Skill override is not bound to this Factory harness")
    data = deepcopy(payload["harnesses"][binding] if harness is None else harness)
    if not selected:
        return data
    if len(data.get("agents", [])) != 1:
        raise ValueError("Factory skill bindings currently require one native agent")
    evaluator_paths = {
        relative_path(v["path"]).as_posix() for v in assets.values() if v["purpose"] == "evaluator"
    }
    applied = []
    for identity in selected:
        asset = assets.get(identity, {})
        if (
            asset.get("purpose") != "skill"
            or relative_path(asset["path"]).as_posix() in evaluator_paths
        ):
            raise ValueError("Bind only declared skill assets, never evaluator files")
        path = relative_path(asset["path"]).as_posix()
        if not path.endswith(".md"):
            raise ValueError("Factory skill assets must be Markdown files")
        source = payload["sources"].get(path)
        if source is None:
            raise ValueError("Bound skill is missing from the Factory snapshot")
        original = source["text"]
        text = overrides.get(identity, original)
        if identity in overrides:
            check_candidate(original, text)
        metadata, instructions = parse_skill(text)
        previous = data["agents"][0].get("system_prompt") or ""
        prompt = (
            previous.rstrip() + f"\n\n## Skill: {metadata['name']}\n\n{instructions}\n"
        ).strip()
        if len(prompt.encode()) > MAX_BOUND_PROMPT_BYTES:
            raise ValueError("Bound skill instructions exceed the 100 KB prompt limit")
        data["agents"][0]["system_prompt"] = prompt
        applied.append(
            {
                "asset": identity,
                "name": metadata["name"],
                "digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    data.setdefault("metadata", {})["factory_skill_bindings"] = applied
    return data
