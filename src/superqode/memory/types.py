"""Provider-neutral agent memory types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MemoryRecord:
    """One explicit agent memory item."""

    id: str
    content: str
    kind: str = "note"
    scope: str = "project"
    source: str = "user"
    tags: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        return cls(
            id=str(data.get("id") or ""),
            content=str(data.get("content") or ""),
            kind=str(data.get("kind") or "note"),
            scope=str(data.get("scope") or "project"),
            source=str(data.get("source") or "user"),
            tags=tuple(str(tag) for tag in data.get("tags") or ()),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MemorySearchResult:
    """A ranked memory search result."""

    record: MemoryRecord
    score: float = 0.0
    provider: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "score": self.score,
            "record": self.record.to_dict(),
        }


@dataclass(frozen=True)
class MemoryProviderStatus:
    """Provider readiness and storage summary."""

    provider: str
    available: bool
    detail: str = ""
    record_count: int = 0
    path: str = ""
    capabilities: tuple[str, ...] = ()
    enabled: bool = True
    installed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "detail": self.detail,
            "record_count": self.record_count,
            "path": self.path,
            "capabilities": list(self.capabilities),
            "enabled": self.enabled,
            "installed": self.installed,
        }


def now_iso() -> str:
    """Current timestamp for memory records."""
    return datetime.now().isoformat(timespec="seconds")
