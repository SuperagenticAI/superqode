"""Agent memory providers for SuperQode."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Protocol

from .config import MemoryProviderConfig
from .types import MemoryProviderStatus, MemoryRecord, MemorySearchResult, now_iso


class AgentMemoryProvider(Protocol):
    """Common interface for agent memory backends."""

    name: str

    def status(self) -> MemoryProviderStatus: ...

    def search(self, query: str, *, limit: int = 8) -> list[MemorySearchResult]: ...

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        scope: str = "project",
        tags: tuple[str, ...] = (),
    ) -> MemoryRecord: ...

    def forget(self, memory_id: str) -> bool: ...

    def export(self) -> dict: ...


def project_hash(project_root: str | Path = ".") -> str:
    """Stable project hash for user-local memory files."""
    return hashlib.sha256(str(Path(project_root).expanduser().resolve()).encode()).hexdigest()[:16]


def default_local_memory_path(project_root: str | Path = ".") -> Path:
    """Default user-local memory file for a project."""
    return Path.home() / ".superqode" / "memory" / f"agent-{project_hash(project_root)}.json"


class LocalAgentMemoryProvider:
    """Simple local JSON memory provider."""

    name = "local"

    def __init__(self, project_root: str | Path = ".", path: str | Path | None = None):
        self.project_root = Path(project_root).expanduser().resolve()
        self.path = Path(path).expanduser() if path else default_local_memory_path(self.project_root)

    def _load(self) -> dict:
        if not self.path.exists():
            return {
                "version": 1,
                "provider": self.name,
                "project": str(self.project_root),
                "records": [],
            }
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        records = data.get("records", [])
        if not isinstance(records, list):
            records = []
        return {
            "version": 1,
            "provider": self.name,
            "project": str(self.project_root),
            "records": records,
        }

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _records(self) -> list[MemoryRecord]:
        return [
            MemoryRecord.from_dict(item)
            for item in self._load().get("records", [])
            if isinstance(item, dict)
        ]

    def status(self) -> MemoryProviderStatus:
        records = self._records()
        return MemoryProviderStatus(
            provider=self.name,
            available=True,
            detail="local user memory",
            record_count=len(records),
            path=str(self.path),
            capabilities=("search", "remember", "forget", "export"),
        )

    def search(self, query: str, *, limit: int = 8) -> list[MemorySearchResult]:
        terms = [term.lower() for term in query.split() if term.strip()]
        results: list[MemorySearchResult] = []
        for record in self._records():
            haystack = " ".join([record.content, record.kind, " ".join(record.tags)]).lower()
            if not terms:
                score = 0.1
            else:
                hits = sum(1 for term in terms if term in haystack)
                if hits == 0:
                    continue
                score = hits / max(1, len(terms))
            results.append(MemorySearchResult(record=record, score=score, provider=self.name))
        results.sort(key=lambda item: (item.score, item.record.updated_at), reverse=True)
        return results[:limit]

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        scope: str = "project",
        tags: tuple[str, ...] = (),
    ) -> MemoryRecord:
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        data = self._load()
        now = now_iso()
        memory_id = hashlib.sha256(f"{content}:{now}".encode()).hexdigest()[:12]
        record = MemoryRecord(
            id=memory_id,
            content=content,
            kind=kind,
            scope=scope,
            source="user",
            tags=tags,
            created_at=now,
            updated_at=now,
            metadata={"project": str(self.project_root)},
        )
        data["records"].append(record.to_dict())
        self._save(data)
        return record

    def forget(self, memory_id: str) -> bool:
        data = self._load()
        records = [item for item in data.get("records", []) if isinstance(item, dict)]
        kept = [item for item in records if not str(item.get("id", "")).startswith(memory_id)]
        if len(kept) == len(records):
            return False
        data["records"] = kept
        self._save(data)
        return True

    def export(self) -> dict:
        return self._load()


class SpecMemProvider:
    """SpecMem-aware read provider.

    This provider is intentionally lightweight: it detects the local SpecMem
    workspace and searches the Agent Experience Pack files directly. If the
    `specmem` CLI is installed, status reports it, but SuperQode does not require
    SpecMem as a dependency.
    """

    name = "specmem"

    def __init__(
        self,
        project_root: str | Path = ".",
        root: str | Path = ".specmem",
        config: MemoryProviderConfig | None = None,
    ):
        self.project_root = Path(project_root).expanduser().resolve()
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            self.root = self.project_root / self.root
        self.config = config or MemoryProviderConfig(name=self.name, enabled=False)

    def _candidate_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        preferred = [
            "agent_memory.json",
            "agent_context.md",
            "knowledge_index.json",
            "impact_graph.json",
        ]
        files = [self.root / name for name in preferred if (self.root / name).is_file()]
        files.extend(
            path
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in {".md", ".json", ".txt"}
            and path not in files
            and "vectordb" not in path.parts
        )
        return files

    def status(self) -> MemoryProviderStatus:
        files = self._candidate_files()
        cli = shutil.which("specmem")
        detail = "SpecMem workspace found" if self.root.exists() else "No .specmem directory"
        if cli:
            detail += f"; CLI: {cli}"
        return MemoryProviderStatus(
            provider=self.name,
            available=self.root.exists(),
            detail=detail,
            record_count=len(files),
            path=str(self.root),
            capabilities=("search", "export", "context") if self.root.exists() else (),
            enabled=self.config.enabled,
            installed=bool(cli),
        )

    def search(self, query: str, *, limit: int = 8) -> list[MemorySearchResult]:
        terms = [term.lower() for term in query.split() if term.strip()]
        results: list[MemorySearchResult] = []
        for path in self._candidate_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            haystack = text.lower()
            hits = sum(1 for term in terms if term in haystack) if terms else 1
            if hits <= 0:
                continue
            snippet = _snippet(text, terms)
            record = MemoryRecord(
                id=hashlib.sha256(str(path).encode()).hexdigest()[:12],
                content=snippet,
                kind="spec",
                scope="project",
                source=self.name,
                tags=("specmem", path.name),
                metadata={"path": str(path.relative_to(self.project_root)) if path.is_relative_to(self.project_root) else str(path)},
            )
            results.append(
                MemorySearchResult(record=record, score=hits / max(1, len(terms)), provider=self.name)
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        scope: str = "project",
        tags: tuple[str, ...] = (),
    ) -> MemoryRecord:
        raise NotImplementedError("SpecMem provider is read-only from SuperQode; use `specmem` to write.")

    def forget(self, memory_id: str) -> bool:
        raise NotImplementedError("SpecMem provider is read-only from SuperQode; use `specmem` to edit.")

    def export(self) -> dict:
        return {
            "version": 1,
            "provider": self.name,
            "root": str(self.root),
            "files": [str(path) for path in self._candidate_files()],
        }


class Mem0Provider:
    """Optional Mem0 provider.

    Supports Mem0 hosted API through `mem0ai`'s `MemoryClient`. It is disabled
    until configured in `superqode.yaml`.
    """

    name = "mem0"

    def __init__(self, project_root: str | Path = ".", config: MemoryProviderConfig | None = None):
        self.project_root = Path(project_root).expanduser().resolve()
        self.config = config or MemoryProviderConfig(name=self.name, enabled=False)
        self.user_id = str(self.config.get("user_id") or project_hash(self.project_root))
        self.api_key_env = str(self.config.get("api_key_env") or "MEM0_API_KEY")

    def _api_key(self) -> str:
        return str(self.config.get("api_key") or os.environ.get(self.api_key_env) or "")

    def _client(self) -> Any:
        _ensure_enabled(self.config)
        try:
            from mem0 import MemoryClient
        except Exception as exc:  # pragma: no cover - exercised via status in unit tests
            raise RuntimeError("Install `superqode[mem0]` to use the mem0 memory provider.") from exc
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError(f"Set {self.api_key_env} or memory.providers.mem0.api_key.")
        return MemoryClient(api_key=api_key)

    def status(self) -> MemoryProviderStatus:
        installed = _module_installed("mem0")
        api_key = self._api_key()
        if not self.config.enabled:
            detail = "disabled; enable memory.providers.mem0.enabled in superqode.yaml"
        elif not installed:
            detail = "not installed; install superqode[mem0]"
        elif not api_key:
            detail = f"missing API key; set {self.api_key_env}"
        else:
            detail = "configured for Mem0 hosted memory"
        return MemoryProviderStatus(
            provider=self.name,
            available=self.config.enabled and installed and bool(api_key),
            detail=detail,
            capabilities=("search", "remember", "forget") if self.config.enabled else (),
            enabled=self.config.enabled,
            installed=installed,
        )

    def search(self, query: str, *, limit: int = 8) -> list[MemorySearchResult]:
        response = self._client().search(query, user_id=self.user_id, limit=limit)
        return _results_from_payload(response, provider=self.name, default_kind="memory")[:limit]

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        scope: str = "project",
        tags: tuple[str, ...] = (),
    ) -> MemoryRecord:
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        metadata = {"kind": kind, "scope": scope, "tags": list(tags), "project": str(self.project_root)}
        response = self._client().add(
            [{"role": "user", "content": content}],
            user_id=self.user_id,
            metadata=metadata,
        )
        return _record_from_write_response(
            response,
            provider=self.name,
            content=content,
            kind=kind,
            scope=scope,
            tags=tags,
            metadata=metadata,
        )

    def forget(self, memory_id: str) -> bool:
        self._client().delete(memory_id=memory_id)
        return True

    def export(self) -> dict:
        return {"version": 1, "provider": self.name, "status": self.status().to_dict()}


class CogneeProvider:
    """Optional Cognee provider using SDK calls or the Cognee CLI."""

    name = "cognee"

    def __init__(self, project_root: str | Path = ".", config: MemoryProviderConfig | None = None):
        self.project_root = Path(project_root).expanduser().resolve()
        self.config = config or MemoryProviderConfig(name=self.name, enabled=False)
        self.session_id = self.config.get("session_id")

    def _module(self) -> Any:
        _ensure_enabled(self.config)
        try:
            import cognee
        except Exception as exc:  # pragma: no cover - exercised via status in unit tests
            raise RuntimeError(
                "Install Cognee separately to use the Cognee SDK provider. "
                "Cognee 1.1.2 currently conflicts with SuperQode's rich>=15 dependency, "
                "so SuperQode does not expose a bundled cognee extra."
            ) from exc
        return cognee

    def status(self) -> MemoryProviderStatus:
        installed = _module_installed("cognee") or bool(shutil.which("cognee-cli"))
        if not self.config.enabled:
            detail = "disabled; enable memory.providers.cognee.enabled in superqode.yaml"
        elif not installed:
            detail = "not installed; install Cognee separately or provide cognee-cli"
        else:
            detail = "configured for Cognee remember/recall"
            if os.environ.get("COGNEE_SERVICE_URL"):
                detail += "; cloud service URL set"
        return MemoryProviderStatus(
            provider=self.name,
            available=self.config.enabled and installed,
            detail=detail,
            capabilities=("search", "remember", "forget") if self.config.enabled else (),
            enabled=self.config.enabled,
            installed=installed,
        )

    def search(self, query: str, *, limit: int = 8) -> list[MemorySearchResult]:
        _ensure_enabled(self.config)
        if _module_installed("cognee"):
            kwargs = {"session_id": self.session_id} if self.session_id else {}
            response = _run_coro_sync(self._module().recall(query, **kwargs))
        elif shutil.which("cognee-cli"):
            response = _run_cognee_cli("recall", query)
        else:
            self._module()
            response = None
        return _results_from_payload(response, provider=self.name, default_kind="memory")[:limit]

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        scope: str = "project",
        tags: tuple[str, ...] = (),
    ) -> MemoryRecord:
        _ensure_enabled(self.config)
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        if _module_installed("cognee"):
            kwargs = {"session_id": self.session_id} if self.session_id else {}
            response = _run_coro_sync(self._module().remember(content, **kwargs))
        elif shutil.which("cognee-cli"):
            response = _run_cognee_cli("remember", content)
        else:
            self._module()
            response = None
        return _record_from_write_response(
            response,
            provider=self.name,
            content=content,
            kind=kind,
            scope=scope,
            tags=tags,
            metadata={"project": str(self.project_root)},
        )

    def forget(self, memory_id: str) -> bool:
        _ensure_enabled(self.config)
        if not _module_installed("cognee"):
            raise RuntimeError("Cognee forget requires the Cognee Python SDK.")
        kwargs = {"dataset": memory_id} if memory_id else {}
        _run_coro_sync(self._module().forget(**kwargs))
        return True

    def export(self) -> dict:
        return {"version": 1, "provider": self.name, "status": self.status().to_dict()}


class SupermemoryProvider:
    """Optional Supermemory hosted provider."""

    name = "supermemory"

    def __init__(self, project_root: str | Path = ".", config: MemoryProviderConfig | None = None):
        self.project_root = Path(project_root).expanduser().resolve()
        self.config = config or MemoryProviderConfig(name=self.name, enabled=False)
        self.api_key_env = str(self.config.get("api_key_env") or "SUPERMEMORY_API_KEY")
        self.container_tags = tuple(self.config.get("container_tags") or ())

    def _api_key(self) -> str:
        return str(self.config.get("api_key") or os.environ.get(self.api_key_env) or "")

    def _client(self) -> Any:
        _ensure_enabled(self.config)
        try:
            from supermemory import Supermemory
        except Exception as exc:  # pragma: no cover - exercised via status in unit tests
            raise RuntimeError(
                "Install `superqode[supermemory]` to use the Supermemory provider."
            ) from exc
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError(f"Set {self.api_key_env} or memory.providers.supermemory.api_key.")
        return Supermemory(api_key=api_key)

    def status(self) -> MemoryProviderStatus:
        installed = _module_installed("supermemory")
        api_key = self._api_key()
        if not self.config.enabled:
            detail = "disabled; enable memory.providers.supermemory.enabled in superqode.yaml"
        elif not installed:
            detail = "not installed; install superqode[supermemory]"
        elif not api_key:
            detail = f"missing API key; set {self.api_key_env}"
        else:
            detail = "configured for Supermemory hosted search"
        return MemoryProviderStatus(
            provider=self.name,
            available=self.config.enabled and installed and bool(api_key),
            detail=detail,
            capabilities=("search", "remember", "forget") if self.config.enabled else (),
            enabled=self.config.enabled,
            installed=installed,
        )

    def search(self, query: str, *, limit: int = 8) -> list[MemorySearchResult]:
        response = self._client().search.memories(q=query, limit=limit)
        return _results_from_payload(response, provider=self.name, default_kind="memory")[:limit]

    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        scope: str = "project",
        tags: tuple[str, ...] = (),
    ) -> MemoryRecord:
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        container_tags = list(self.container_tags or tags or ("superqode",))
        response = self._client().add(
            content=content,
            container_tags=container_tags,
            metadata={"kind": kind, "scope": scope, "tags": list(tags), "project": str(self.project_root)},
        )
        return _record_from_write_response(
            response,
            provider=self.name,
            content=content,
            kind=kind,
            scope=scope,
            tags=tags,
            metadata={"project": str(self.project_root), "container_tags": container_tags},
        )

    def forget(self, memory_id: str) -> bool:
        self._client().memories.forget(ids=[memory_id])
        return True

    def export(self) -> dict:
        return {"version": 1, "provider": self.name, "status": self.status().to_dict()}


def _snippet(text: str, terms: list[str], max_chars: int = 700) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    lower = collapsed.lower()
    positions = [lower.find(term) for term in terms if term and lower.find(term) >= 0]
    start = max(0, min(positions) - 160) if positions else 0
    snippet = collapsed[start : start + max_chars]
    if start > 0:
        snippet = "..." + snippet
    if start + max_chars < len(collapsed):
        snippet += "..."
    return snippet


def _module_installed(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _ensure_enabled(config: MemoryProviderConfig) -> None:
    if not config.enabled:
        raise RuntimeError(
            f"Memory provider '{config.name}' is disabled. "
            f"Enable memory.providers.{config.name}.enabled in superqode.yaml."
        )


def _run_cognee_cli(command: str, value: str) -> list[dict[str, Any]]:
    executable = shutil.which("cognee-cli")
    if not executable:
        raise RuntimeError("cognee-cli is not installed.")
    completed = subprocess.run(
        [executable, command, value],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = completed.stdout.strip()
    if not output:
        return []
    try:
        parsed = json.loads(output)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    return [{"id": hashlib.sha256(output.encode()).hexdigest()[:12], "content": output}]


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "dict"):
        try:
            dumped = value.dict()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    data: dict[str, Any] = {}
    for key in ("id", "memory", "content", "text", "score", "metadata"):
        if hasattr(value, key):
            data[key] = getattr(value, key)
    return data


def _extract_items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    data = _as_dict(payload)
    for key in ("results", "memories", "documents", "data", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
            return list(value)
    return [payload]


def _results_from_payload(
    payload: Any,
    *,
    provider: str,
    default_kind: str,
) -> list[MemorySearchResult]:
    results: list[MemorySearchResult] = []
    for index, item in enumerate(_extract_items(payload)):
        data = _as_dict(item)
        content = (
            data.get("memory")
            or data.get("content")
            or data.get("text")
            or data.get("document")
            or data.get("summary")
            or str(item)
        )
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        record = MemoryRecord(
            id=str(data.get("id") or data.get("memory_id") or hashlib.sha256(str(content).encode()).hexdigest()[:12]),
            content=str(content),
            kind=str(metadata.get("kind") or data.get("kind") or default_kind),
            scope=str(metadata.get("scope") or data.get("scope") or "project"),
            source=provider,
            tags=tuple(str(tag) for tag in metadata.get("tags") or data.get("tags") or ()),
            metadata={key: value for key, value in data.items() if key not in {"memory", "content", "text"}},
        )
        raw_score = data.get("score") or data.get("relevance") or data.get("similarity") or 1.0
        try:
            score = float(raw_score)
        except Exception:
            score = 1.0 / (index + 1)
        results.append(MemorySearchResult(record=record, score=score, provider=provider))
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def _record_from_write_response(
    payload: Any,
    *,
    provider: str,
    content: str,
    kind: str,
    scope: str,
    tags: tuple[str, ...],
    metadata: dict[str, Any],
) -> MemoryRecord:
    data = _as_dict(payload)
    memory_id = (
        data.get("id")
        or data.get("memory_id")
        or data.get("document_id")
        or hashlib.sha256(f"{provider}:{content}:{now_iso()}".encode()).hexdigest()[:12]
    )
    now = now_iso()
    return MemoryRecord(
        id=str(memory_id),
        content=content,
        kind=kind,
        scope=scope,
        source=provider,
        tags=tags,
        created_at=now,
        updated_at=now,
        metadata=metadata | {"response": data},
    )


def _run_coro_sync(coro: Any) -> Any:
    try:
        import asyncio

        asyncio.get_running_loop()
    except RuntimeError:
        import asyncio

        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        import asyncio

        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
