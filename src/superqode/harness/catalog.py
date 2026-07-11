"""User-facing harness catalogue and name/path resolution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..agent.loop_policy import (
    NativeLoopPolicy,
    core_loop_policy,
    workbench_loop_policy,
)
from .loader import harness_spec_to_dict, load_harness_spec
from .registry import list_registry_specs
from .spec import HarnessSpec
from .templates import core_template, no_tool_template, workbench_template


DEFAULT_HARNESS_ID = "core"


@dataclass(frozen=True)
class HarnessDefinition:
    """One selectable harness entry."""

    id: str
    display_name: str
    description: str
    runtime: str
    source: str
    spec: HarnessSpec
    loop_policy: NativeLoopPolicy
    aliases: tuple[str, ...] = ()
    path: Path | None = None
    available: bool = True
    issue: str = ""
    default: bool = False

    @property
    def tools(self) -> tuple[str, ...]:
        profile = str(self.spec.model_policy.config.get("tool_profile") or "").strip()
        if self.source == "built-in" and self.runtime == "builtin" and profile:
            from ..tools.base import ToolRegistry

            return tuple(tool.name for tool in ToolRegistry.for_profile(profile).list())
        return self.spec.agents[0].tools if self.spec.agents else ()

    @property
    def digest(self) -> str:
        payload = json.dumps(harness_spec_to_dict(self.spec), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "runtime": self.runtime,
            "source": self.source,
            "aliases": list(self.aliases),
            "path": str(self.path) if self.path else None,
            "available": self.available,
            "issue": self.issue,
            "default": self.default,
            "tools": list(self.tools),
            "tool_count": len(self.tools),
            "digest": self.digest,
        }


def builtin_harnesses() -> tuple[HarnessDefinition, ...]:
    """Return selectable harnesses shipped with SuperQode."""
    core = core_template()
    workbench = workbench_template()
    no_tool = no_tool_template(name="no-tool")
    return (
        HarnessDefinition(
            id="core",
            display_name="Core",
            description=core.description,
            runtime=core.runtime.backend,
            source="built-in",
            spec=core,
            loop_policy=core_loop_policy(),
            aliases=("minimal",),
            default=True,
        ),
        HarnessDefinition(
            id="workbench",
            display_name="Workbench",
            description=workbench.description,
            runtime=workbench.runtime.backend,
            source="built-in",
            spec=workbench,
            loop_policy=workbench_loop_policy(),
            aliases=("coding", "native", "build"),
        ),
        HarnessDefinition(
            id="no-tool",
            display_name="No Tool",
            description=no_tool.description,
            runtime=no_tool.runtime.backend,
            source="built-in",
            spec=no_tool,
            loop_policy=core_loop_policy(),
            aliases=("no_tool",),
        ),
    )


def _candidate_paths(root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    direct = (root / "harness.yaml", root / "harness.yml", root / "harness.json")
    directories = (root / ".superqode" / "harnesses", Path.home() / ".superqode" / "harnesses")
    for path in direct:
        if path.is_file() and path.resolve() not in seen:
            seen.add(path.resolve())
            yield path
    for directory in directories:
        if not directory.is_dir():
            continue
        for pattern in ("*.yaml", "*.yml", "*.json"):
            for path in sorted(directory.glob(pattern)):
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield path
    for item in list_registry_specs():
        raw = item.get("spec")
        if raw:
            path = Path(str(raw)).expanduser()
            if path.is_file() and path.resolve() not in seen:
                seen.add(path.resolve())
                yield path


def list_harnesses(root: str | Path = ".") -> list[HarnessDefinition]:
    """List built-in and discoverable HarnessSpec entries."""
    entries = list(builtin_harnesses())
    known = {entry.id for entry in entries}
    for path in _candidate_paths(Path(root).expanduser().resolve()):
        try:
            spec = load_harness_spec(path)
            entry_id = spec.name.strip().lower()
            if not entry_id or entry_id in known:
                continue
            known.add(entry_id)
            entries.append(
                HarnessDefinition(
                    id=entry_id,
                    display_name=spec.name,
                    description=spec.description,
                    runtime=spec.runtime.backend,
                    source="registry" if "harness-registry" in str(path) else "file",
                    spec=spec,
                    loop_policy=workbench_loop_policy(),
                    path=path.resolve(),
                )
            )
        except Exception:
            # Listing should remain useful when one unrelated spec is broken.
            continue
    return entries


def resolve_harness(reference: str | Path | None = None, *, root: str | Path = ".") -> HarnessDefinition:
    """Resolve a built-in/discovered harness name or an explicit spec path."""
    raw = str(reference or DEFAULT_HARNESS_ID).strip()
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        spec = load_harness_spec(candidate)
        return HarnessDefinition(
            id=spec.name.strip().lower(),
            display_name=spec.name,
            description=spec.description,
            runtime=spec.runtime.backend,
            source="file",
            spec=spec,
            loop_policy=workbench_loop_policy(),
            path=candidate.resolve(),
        )

    normalized = raw.lower()
    for entry in list_harnesses(root):
        if normalized == entry.id or normalized in entry.aliases:
            return entry
    available = ", ".join(entry.id for entry in list_harnesses(root))
    raise ValueError(f"Unknown harness {raw!r}. Available harnesses: {available}")


__all__ = [
    "DEFAULT_HARNESS_ID",
    "HarnessDefinition",
    "builtin_harnesses",
    "list_harnesses",
    "resolve_harness",
]
