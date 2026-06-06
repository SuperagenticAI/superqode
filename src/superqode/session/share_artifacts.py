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
) -> Path:
    """Create a portable ``superqode-share-v1`` artifact for a stored session."""
    session_id = resolve_session_id(session_id_or_prefix, storage_dir)
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
    if payload.get("format") != "superqode-share-v1":
        raise ValueError("not a superqode-share-v1 artifact")
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
