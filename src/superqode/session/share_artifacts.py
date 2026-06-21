"""Portable local share artifacts for stored SuperQode sessions."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from superqode.agent.session_manager import SessionManager, SessionMessage
from superqode.headless import export_session, resolve_session_id


SHARE_SUFFIX = ".superqode-share.json"


@dataclass(frozen=True)
class ShareArtifactInfo:
    """Metadata for one local share artifact."""

    path: Path
    source_session_id: str = ""
    created_at: str = ""


def default_shares_dir() -> Path:
    return Path(".superqode") / "shares"


def _safe_id(session_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id)


def share_output_path(session_id: str, output: str | Path | None = None) -> Path:
    """Resolve an artifact output path."""
    if output:
        path = Path(output).expanduser()
        if not path.name.lower().endswith(SHARE_SUFFIX):
            path = path.with_suffix(SHARE_SUFFIX)
        return path
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return default_shares_dir() / f"share-{_safe_id(session_id)}-{stamp}{SHARE_SUFFIX}"


def create_share_artifact(
    session_id_or_prefix: str,
    *,
    output: str | Path | None = None,
    storage_dir: str = ".superqode/sessions",
    include_tree: bool = False,
) -> Path:
    """Create a portable share artifact for a stored session or session tree."""
    session_id = resolve_session_id(session_id_or_prefix, storage_dir)
    if include_tree:
        return create_share_tree_artifact(session_id, output=output, storage_dir=storage_dir)
    exported = json.loads(export_session(session_id, fmt="json", storage_dir=storage_dir))
    payload = {
        "format": "superqode-share-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_session_id": session_id,
        "session": exported,
    }
    path = share_output_path(session_id, output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def create_share_tree_artifact(
    session_id_or_prefix: str,
    *,
    output: str | Path | None = None,
    storage_dir: str = ".superqode/sessions",
) -> Path:
    """Create a portable ``superqode-share-v2`` artifact for a session subtree."""
    from superqode.session.switchboard import SessionSwitchboard

    session_id = resolve_session_id(session_id_or_prefix, storage_dir)
    switchboard = SessionSwitchboard(storage_dir=storage_dir)
    stack = [session_id]
    seen: set[str] = set()
    records: list[dict] = []
    while stack:
        current_id = stack.pop()
        if current_id in seen:
            continue
        seen.add(current_id)
        node = switchboard.info(current_id)
        records.append(node)
        stack.extend(
            reversed([str(child["session_id"]) for child in switchboard.children(current_id)])
        )
    session_ids = [str(record["session_id"]) for record in records]
    sessions = {
        sid: json.loads(export_session(sid, fmt="json", storage_dir=storage_dir))
        for sid in session_ids
        if SessionManager(storage_dir=storage_dir).get_session_info(sid)
    }
    payload = {
        "format": "superqode-share-v2",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_session_id": session_id,
        "graph": {
            "root_session_id": session_id,
            "records": records,
        },
        "sessions": sessions,
    }
    path = share_output_path(session_id, output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export_session_file(
    session_id_or_prefix: str,
    *,
    fmt: str = "markdown",
    output: str | Path,
    storage_dir: str = ".superqode/sessions",
) -> Path:
    """Export a stored session to Markdown or JSON file."""
    if fmt not in {"markdown", "json"}:
        raise ValueError("format must be markdown or json")
    session_id = resolve_session_id(session_id_or_prefix, storage_dir)
    content = export_session(session_id, fmt=fmt, storage_dir=storage_dir)
    path = Path(output).expanduser()
    suffix = ".json" if fmt == "json" else ".md"
    if path.suffix.lower() not in {".json", ".md", ".markdown"}:
        path = path.with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def import_share_artifact(
    path: str | Path,
    *,
    new_session_id: str = "",
    storage_dir: str = ".superqode/sessions",
) -> str:
    """Import a portable share artifact into the JSONL session store."""
    artifact_path = Path(path).expanduser()
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if payload.get("format") == "superqode-share-v2":
        return _import_share_tree_artifact(payload, artifact_path, new_session_id, storage_dir)
    if payload.get("format") != "superqode-share-v1":
        raise ValueError("not a superqode-share-v1 or superqode-share-v2 artifact")
    session_data = payload.get("session") or {}
    source_id = str(session_data.get("session_id") or payload.get("source_session_id") or "")
    new_id = new_session_id or f"{source_id or 'import'}-import-{str(uuid.uuid4())[:4]}"
    manager = SessionManager(storage_dir=storage_dir)
    if manager.get_session_info(new_id):
        raise ValueError(f"session already exists: {new_id}")
    metadata = manager.store.create_session(
        new_id,
        provider=str(session_data.get("provider") or ""),
        model=str(session_data.get("model") or ""),
        parent_session_id=source_id or None,
        title=str(session_data.get("title") or f"Import of {source_id or artifact_path.stem}"),
    )
    for raw in session_data.get("messages") or []:
        if not isinstance(raw, dict):
            continue
        message = SessionMessage(
            role=str(raw.get("role") or "user"),
            content=str(raw.get("content") or ""),
            timestamp=str(raw.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%S")),
            tool_calls=raw.get("tool_calls"),
            tool_name=raw.get("tool_name"),
            tool_result=raw.get("tool_result"),
        )
        manager.store.append_message(metadata.session_id, message)
    return metadata.session_id


def _import_share_tree_artifact(
    payload: dict,
    artifact_path: Path,
    new_session_id: str,
    storage_dir: str,
) -> str:
    from superqode.session.switchboard import SessionGraphStore

    sessions = payload.get("sessions") or {}
    graph = payload.get("graph") or {}
    records = graph.get("records") or []
    source_root = str(graph.get("root_session_id") or payload.get("source_session_id") or "")
    if not isinstance(sessions, dict) or not source_root:
        raise ValueError("invalid superqode-share-v2 artifact")

    manager = SessionManager(storage_dir=storage_dir)
    id_map: dict[str, str] = {}
    for source_id in sessions:
        mapped = new_session_id if source_id == source_root and new_session_id else source_id
        if manager.get_session_info(mapped):
            mapped = f"{mapped}-import-{str(uuid.uuid4())[:4]}"
        id_map[source_id] = mapped

    for source_id, session_data in sessions.items():
        if not isinstance(session_data, dict):
            continue
        target_id = id_map[source_id]
        parent = session_data.get("parent_session_id")
        parent_id = id_map.get(str(parent), str(parent)) if parent else None
        metadata = manager.store.create_session(
            target_id,
            provider=str(session_data.get("provider") or ""),
            model=str(session_data.get("model") or ""),
            parent_session_id=parent_id,
            title=str(session_data.get("title") or f"Import of {source_id or artifact_path.stem}"),
        )
        for raw in session_data.get("messages") or []:
            if not isinstance(raw, dict):
                continue
            manager.store.append_message(
                metadata.session_id,
                SessionMessage(
                    role=str(raw.get("role") or "user"),
                    content=str(raw.get("content") or ""),
                    timestamp=str(raw.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%S")),
                    tool_calls=raw.get("tool_calls"),
                    tool_name=raw.get("tool_name"),
                    tool_result=raw.get("tool_result"),
                ),
            )

    graph_store = SessionGraphStore(storage_dir)
    for record in records:
        if not isinstance(record, dict):
            continue
        source_id = str(record.get("session_id") or "")
        target_id = id_map.get(source_id)
        if not target_id:
            continue
        parent = record.get("parent_session_id")
        graph_store.upsert(
            target_id,
            parent_session_id=id_map.get(str(parent), str(parent)) if parent else None,
            root_session_id=id_map.get(str(record.get("root_session_id") or ""), target_id),
            kind=str(record.get("kind") or "import"),
            agent_id=str(record.get("agent_id") or ""),
            agent_name=str(record.get("agent_name") or ""),
            title=str(record.get("title") or ""),
            status="idle",
            closed=False,
            record_metadata={"imported_from": source_id, "share_artifact": str(artifact_path)},
        )
    return id_map.get(source_root, new_session_id or source_root)


def list_share_artifacts(shares_dir: str | Path | None = None) -> list[ShareArtifactInfo]:
    """List managed local share artifacts."""
    directory = Path(shares_dir).expanduser() if shares_dir else default_shares_dir()
    infos: list[ShareArtifactInfo] = []
    for path in sorted(directory.glob(f"*{SHARE_SUFFIX}"), reverse=True):
        source = ""
        created_at = ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source = str(payload.get("source_session_id") or "")
            created_at = str(payload.get("created_at") or "")
        except Exception:
            pass
        infos.append(ShareArtifactInfo(path=path, source_session_id=source, created_at=created_at))
    return infos


def revoke_share_artifact(target: str | Path, shares_dir: str | Path | None = None) -> Path:
    """Delete a managed share artifact by name or path."""
    path = Path(target).expanduser()
    if not path.is_absolute() and not path.exists():
        directory = Path(shares_dir).expanduser() if shares_dir else default_shares_dir()
        path = directory / path.name
    path.unlink()
    return path
