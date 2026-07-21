"""Discovery for independently installed Harness Protocol adapters.

The smallest package can expose a two-argument function directly::

    [project.entry-points."superqode.harnesses"]
    reviewer = "my_package:run"

Functions are wrapped as :class:`DirectPythonHarnessAdapter` instances.  A
package that needs more lifecycle control may expose a complete adapter object.
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from .protocol import HarnessAdapter, HarnessDescriptor
from .protocol_adapters import CoreHarnessProtocolAdapter, DirectPythonHarnessAdapter

HARNESS_ENTRY_POINT_GROUP = "superqode.harnesses"


@dataclass(frozen=True)
class HarnessAdapterDefinition:
    """One built-in or installed protocol adapter and its load status."""

    id: str
    name: str
    description: str
    source: str
    available: bool
    adapter: HarnessAdapter | None = None
    issue: str = ""
    entry_point: str = ""

    @property
    def descriptor(self) -> HarnessDescriptor | None:
        return self.adapter.descriptor if self.adapter is not None else None

    def to_dict(self) -> dict[str, Any]:
        descriptor = self.descriptor
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "available": self.available,
            "issue": self.issue,
            "entry_point": self.entry_point,
            "protocol_version": descriptor.protocol_version if descriptor else "",
            "capabilities": descriptor.capabilities.to_dict() if descriptor else {},
        }


def discover_harness_adapters(
    *,
    include_builtins: bool = True,
) -> tuple[HarnessAdapterDefinition, ...]:
    """Load installed harness entry points without letting one failure escape."""
    entries: list[HarnessAdapterDefinition] = []
    known: set[str] = set()
    if include_builtins:
        from .catalog import builtin_harnesses
        from .backends.rlm_code import rlm_code_installation_status
        from .rlm_code_adapter import RLMCodeHarnessProtocolAdapter

        for harness in builtin_harnesses():
            adapter = CoreHarnessProtocolAdapter(harness.spec, adapter_id=harness.id)
            entries.append(
                HarnessAdapterDefinition(
                    id=harness.id,
                    name=harness.display_name,
                    description=harness.description,
                    source="built-in",
                    available=True,
                    adapter=adapter,
                )
            )
            known.add(harness.id)

        rlm_available, rlm_issue = rlm_code_installation_status()
        rlm_adapter = RLMCodeHarnessProtocolAdapter() if rlm_available else None
        entries.append(
            HarnessAdapterDefinition(
                id="rlm-code",
                name="RLM Code",
                description=(
                    "Recursive Language Model harness with LID context and trajectory evidence"
                ),
                source="optional:rlm-code",
                available=rlm_available,
                adapter=rlm_adapter,
                issue=rlm_issue,
            )
        )
        known.add("rlm-code")

    for entry_point in _harness_entry_points():
        source = _entry_point_source(entry_point)
        entry_value = str(getattr(entry_point, "value", ""))
        try:
            loaded = entry_point.load()
            adapter = _coerce_harness_adapter(loaded, entry_point.name)
            adapter_id = adapter.descriptor.id
            if adapter_id in known:
                continue
            known.add(adapter_id)
            entries.append(
                HarnessAdapterDefinition(
                    id=adapter_id,
                    name=adapter.descriptor.name,
                    description=adapter.descriptor.description,
                    source=source,
                    available=True,
                    adapter=adapter,
                    entry_point=entry_value,
                )
            )
        except Exception as exc:  # noqa: BLE001 - package failures are isolated.
            adapter_id = str(entry_point.name)
            if adapter_id in known:
                continue
            known.add(adapter_id)
            entries.append(
                HarnessAdapterDefinition(
                    id=adapter_id,
                    name=adapter_id,
                    description="",
                    source=source,
                    available=False,
                    issue=str(exc),
                    entry_point=entry_value,
                )
            )
    return tuple(entries)


def load_harness_adapter(reference: str) -> HarnessAdapter:
    """Resolve a built-in or installed adapter by its descriptor id."""
    normalized = reference.strip().lower()
    for entry in discover_harness_adapters():
        if entry.id.lower() != normalized:
            continue
        if entry.adapter is None:
            raise RuntimeError(f"Harness {entry.id!r} is unavailable: {entry.issue}")
        return entry.adapter
    available = ", ".join(entry.id for entry in discover_harness_adapters() if entry.available)
    raise ValueError(f"Unknown harness {reference!r}. Available harnesses: {available}")


def _harness_entry_points() -> list[Any]:
    points = importlib.metadata.entry_points()
    if hasattr(points, "select"):
        return list(points.select(group=HARNESS_ENTRY_POINT_GROUP))
    return list(points.get(HARNESS_ENTRY_POINT_GROUP, ()))


def _coerce_harness_adapter(value: Any, entry_point_name: str) -> HarnessAdapter:
    if isinstance(value, ModuleType):
        value = getattr(value, "harness", getattr(value, "adapter", None))
    if _is_harness_adapter(value):
        return value
    if callable(value):
        return DirectPythonHarnessAdapter(
            entry_point_name,
            value,
            name=entry_point_name,
            description="Installed Python harness",
        )
    raise TypeError("harness entry point must expose an async handler or HarnessAdapter instance")


def _is_harness_adapter(value: Any) -> bool:
    return value is not None and all(
        hasattr(value, name)
        for name in (
            "descriptor",
            "create",
            "send",
            "resume",
            "steer",
            "cancel",
            "checkpoint",
        )
    )


def _entry_point_source(entry_point: Any) -> str:
    distribution = getattr(entry_point, "dist", None)
    name = getattr(distribution, "name", "") if distribution is not None else ""
    return f"package:{name or entry_point.name}"
