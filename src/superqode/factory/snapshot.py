"""Content-addressed, self-contained definition and component snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from superqode import __version__
from superqode.harness.loader import (
    _deep_merge_dicts,
    harness_spec_from_dict,
    harness_spec_to_dict,
    validate_harness_data,
)
from superqode.harness.templates import get_harness_template

from .definition import (
    FactoryDefinition,
    MAX_FILE_BYTES,
    project_path,
    read_mapping,
    relative_path,
    validate_definition,
)

SNAPSHOT_FORMAT = "superqode.factory-snapshot/1"
MAX_SOURCES = 256
MAX_SNAPSHOT_BYTES = 8_000_000


def canonical(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class FactorySnapshot:
    """Immutable serialized payload; callers receive independent decoded copies."""

    payload_json: str
    digest: str

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    def to_dict(self) -> dict:
        return {"digest": self.digest, **self.payload}

    @classmethod
    def from_dict(cls, value: dict) -> FactorySnapshot:
        data = dict(value)
        expected = data.pop("digest", None)
        if set(data) != {"format", "engine_version", "definition", "harnesses", "sources"}:
            raise ValueError("Invalid factory snapshot fields")
        text = canonical(data)
        if len(text.encode()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Factory snapshot exceeds 8 MB")
        if expected != digest(text) or data["format"] != SNAPSHOT_FORMAT:
            raise ValueError("Factory snapshot digest or format mismatch")
        validate_definition(data["definition"])
        if not isinstance(data["harnesses"], dict) or not isinstance(data["sources"], dict):
            raise ValueError("Invalid factory snapshot components")
        if len(data["sources"]) > MAX_SOURCES:
            raise ValueError("Too many factory source files")
        for path, source in data["sources"].items():
            # Pure lexical validation; importing a snapshot reads no original files.
            if not relative_path(path).parts:
                raise ValueError("Invalid factory snapshot source path")
            if not isinstance(source, dict) or set(source) != {"text", "digest"}:
                raise ValueError("Invalid factory snapshot source")
            if not isinstance(source["text"], str) or len(source["text"].encode()) > MAX_FILE_BYTES:
                raise ValueError("Invalid factory snapshot source content")
            if source["digest"] != digest(source["text"]):
                raise ValueError("Factory source digest mismatch")
        expected_bindings = set(data["definition"]["inference"]["harnesses"])
        if set(data["harnesses"]) != expected_bindings:
            raise ValueError("Factory snapshot harness bindings mismatch")
        for harness in data["harnesses"].values():
            validate_harness_data(harness)
            spec = harness_spec_from_dict(harness)
            for path in (
                *spec.context.instruction_files,
                spec.context.skills_dir,
                spec.context.roles_dir,
                spec.context.session_storage,
            ):
                if path:
                    relative_path(path)
        from .skills import bound_harness

        for binding in data["harnesses"]:
            bound_harness(data, binding)
        for check in data["definition"]["improvement"]["checks"].values():
            if "evaluator" not in check:
                continue
            from .probes import parse_probes

            asset = data["definition"]["data_context"]["files"][check["evaluator"]]
            source = data["sources"].get(relative_path(asset["path"]).as_posix())
            if source is None:
                raise ValueError("Protected evaluator is missing from the snapshot")
            parse_probes(source["text"])
        return cls(text, expected)


def resolve_factory(
    definition: FactoryDefinition,
    *,
    source_text: str | None = None,
    source_overlays: dict[str, str] | None = None,
) -> FactorySnapshot:
    """Resolve only declared components and harness context, never a user registry."""
    if definition.legacy:
        raise ValueError(
            "Routing-only policy has no workflow; explicitly create a versioned FactorySpec"
        )
    validate_definition(definition.data)
    root = definition.root
    sources = {}
    total_bytes = 0

    def capture(relative):
        nonlocal total_bytes
        path = project_path(root, relative)
        key = path.relative_to(root).as_posix()
        if key in sources:
            return sources[key]["text"]
        overlay = source_text if path == definition.path else (source_overlays or {}).get(key)
        if overlay is None and not path.is_file():
            raise ValueError(f"Factory components must be regular files: {relative}")
        if (
            len(sources) >= MAX_SOURCES
            or (len(overlay.encode()) if overlay is not None else path.stat().st_size)
            > MAX_FILE_BYTES
        ):
            raise ValueError("Factory components exceed the source count or file size limit")
        text = overlay if overlay is not None else path.read_text(encoding="utf-8")
        total_bytes += len(text.encode())
        if total_bytes > MAX_SNAPSHOT_BYTES // 2:
            raise ValueError("Factory source files exceed 4 MB")
        sources[key] = {"text": text, "digest": digest(text)}
        return text

    def harness_data(reference, base=Path("."), chain=()):
        if len(chain) >= 16:
            raise ValueError("Factory harness inheritance exceeds 16 levels")
        relative = (base / reference).as_posix()
        path = project_path(root, relative)
        key = path.relative_to(root).as_posix()
        if not path.exists() and key not in (source_overlays or {}):
            # A simple template identifier may be used by harness inheritance.
            if "/" not in reference and "\\" not in reference and "." not in reference:
                return harness_spec_to_dict(get_harness_template(reference))
            raise ValueError(f"Factory harness file does not exist: {relative}")
        if key in chain:
            raise ValueError("Factory harness inheritance cycle")
        data = read_mapping(capture(key))
        data = data.get("harness", data)
        if not isinstance(data, dict):
            raise ValueError("Harness component must be a mapping")
        parent = data.get("inherits", data.get("extends"))
        if parent:
            if not isinstance(parent, str):
                raise ValueError("Harness inheritance must reference a file or template")
            inherited = harness_data(parent, Path(key).parent, (*chain, key))
            data = _deep_merge_dicts(inherited, data)
        data.pop("inherits", None)
        data.pop("extends", None)
        return data

    def capture_context(spec):
        for relative in spec.context.instruction_files:
            path = project_path(root, relative)
            if path.exists():
                capture(relative)
        for relative in (spec.context.skills_dir, spec.context.roles_dir):
            if not relative:
                continue
            directory = project_path(root, relative)
            if directory.exists():
                # Limit walking as well as reading; links are rejected, not followed.
                count = 0
                for path in directory.rglob("*"):
                    count += 1
                    if count > MAX_SOURCES:
                        raise ValueError("Factory context directory has too many entries")
                    safe = project_path(root, path.relative_to(root).as_posix())
                    if safe.is_file():
                        capture(safe.relative_to(root).as_posix())

    source_text = capture(definition.path.relative_to(root).as_posix())
    if read_mapping(source_text) != definition.data:
        raise ValueError("Factory definition changed during resolution; reload it")
    for asset in definition.data["data_context"].get("files", {}).values():
        capture(asset["path"])
    harnesses = {}
    for name, binding in definition.data["inference"]["harnesses"].items():
        data = (
            harness_data(binding["path"])
            if "path" in binding
            else harness_spec_to_dict(get_harness_template(binding["template"]))
        )
        if "model" in binding:
            data.setdefault("model_policy", {})["primary"] = binding["model"]
        validate_harness_data(data)
        spec = harness_spec_from_dict(data)
        capture_context(spec)
        harnesses[name] = harness_spec_to_dict(spec)
    payload = {
        "format": SNAPSHOT_FORMAT,
        "engine_version": __version__,
        "definition": definition.data,
        "harnesses": harnesses,
        "sources": sources,
    }
    return FactorySnapshot.from_dict({"digest": digest(canonical(payload)), **payload})
