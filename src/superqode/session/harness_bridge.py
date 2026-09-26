"""Bridge FileHarnessStore / PiPy sessions into SessionManager listings.

`:sessions` and `:resume` only read SessionManager (`*.meta.json`). HarnessSpec
backends (PiPy, Prime, Tau, and other non-builtin runtimes) persist under
FileHarnessStore and, for PiPy, under `~/.superqode/pipy/sessions/`. This
module dual-writes SessionManager metadata so those sessions appear, and can
be resumed, after disconnect.

Resumed sessions restore provider, model, harness, working directory, and the
external transcript id. Listings prefer human labels such as
``PiPy · gpt-4.1 · refactor auth · 2h ago`` over opaque hashes alone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from superqode.agent.session_manager import SessionManager, SessionMetadata


DEFAULT_SESSION_DIR = ".superqode/sessions"
# FileHarnessStore class default plus the HarnessSpec context default.
HARNESS_STORE_ROOTS = (".superqode/sessions", ".superqode/harness")

_HARNESS_DISPLAY = {
    "pipy": "PiPy",
    "prime-agent": "Prime Agent",
    "rlm": "RLM",
    "core": "Core",
    "workbench": "Workbench",
    "no-tool": "No Tool",
    "systemone": "SystemOne",
    "tau": "Tau",
    "uhp": "UHP",
    "deepagents": "DeepAgents",
}


class SessionResumeError(RuntimeError):
    """Raised when a known session cannot be restored safely."""


def harness_display_name(harness_id: str, *, explicit: str = "") -> str:
    """Return a human harness label for lists and resume receipts."""
    if explicit and explicit.strip():
        return explicit.strip()
    text = str(harness_id or "").strip()
    if not text:
        return "Workbench"
    return _HARNESS_DISPLAY.get(text.lower(), text[:1].upper() + text[1:])


def model_short_name(model: str) -> str:
    """Prefer the bare model id over a provider/model path for labels."""
    text = str(model or "").strip()
    if not text:
        return "model?"
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text


def relative_age(updated_at: str, *, now: datetime | None = None) -> str:
    """Format an ISO timestamp as a short relative age (``2h ago``)."""
    if not updated_at:
        return "unknown"
    try:
        stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return updated_at[:19]
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    current = now or datetime.now()
    seconds = max(0, int((current - stamp).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def topic_from_preview(preview: str, *, fallback: str = "") -> str:
    """Derive a short human topic from the first user prompt."""
    text = " ".join(str(preview or "").strip().split())
    if not text:
        return fallback
    if len(text) > 48:
        text = text[:45].rstrip() + "..."
    return text


def format_session_label(metadata: SessionMetadata) -> str:
    """Build ``PiPy · gpt-4.1 · refactor auth · 2h ago`` style labels."""
    harness = harness_display_name(
        metadata.harness_id,
        explicit=metadata.harness_display_name,
    )
    return f"{harness} · {format_session_row_label(metadata)}"


def format_session_row_label(metadata: SessionMetadata) -> str:
    """Build ``gpt-4.1 · refactor auth · 2h ago`` for rows under a harness header."""
    model = model_short_name(metadata.model) if metadata.model else (metadata.provider or "model?")
    harness = harness_display_name(
        metadata.harness_id,
        explicit=metadata.harness_display_name,
    )
    topic = (metadata.title or "").strip()
    if not topic or topic.lower() in {
        harness.lower(),
        metadata.harness_id.lower(),
        metadata.session_id,
        f"{harness.lower()} session",
    }:
        topic = "untitled"
    age = relative_age(metadata.updated_at)
    return f"{model} · {topic} · {age}"


def session_short_label(metadata: SessionMetadata, *, max_len: int = 28) -> str:
    """Compact title or id for the status bar session chip."""
    title = (metadata.title or "").strip()
    harness = harness_display_name(
        metadata.harness_id,
        explicit=metadata.harness_display_name,
    )
    if title and title.lower() not in {
        harness.lower(),
        metadata.harness_id.lower(),
        "untitled",
        f"{harness.lower()} session",
    }:
        text = title
    else:
        text = metadata.session_id[:8]
    if len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def group_sessions_by_harness(
    sessions: Iterable[SessionMetadata],
) -> list[tuple[str, list[SessionMetadata]]]:
    """Group sessions under harness headers.

    Within each group, sort by ``updated_at`` newest first. Groups themselves
    are ordered by the most recent activity in that group.
    """
    buckets: dict[str, list[SessionMetadata]] = {}
    latest: dict[str, str] = {}
    for item in sessions:
        key = harness_display_name(
            item.harness_id,
            explicit=item.harness_display_name,
        )
        buckets.setdefault(key, []).append(item)
        stamp = str(item.updated_at or "")
        if stamp >= latest.get(key, ""):
            latest[key] = stamp
    for key, rows in buckets.items():
        rows.sort(key=lambda row: str(row.updated_at or ""), reverse=True)
    ordered = sorted(
        buckets.items(),
        key=lambda pair: latest.get(pair[0], ""),
        reverse=True,
    )
    return ordered


def rename_session_title(
    session_id: str,
    title: str,
    *,
    storage_dir: str | Path = DEFAULT_SESSION_DIR,
) -> SessionMetadata:
    """Persist a human title into SessionManager meta for list/picker labels."""
    sid = (session_id or "").strip()
    new_title = " ".join(str(title or "").strip().split())
    if not sid:
        raise ValueError("session_id is required")
    if not new_title:
        raise ValueError("title is required")
    manager = SessionManager(storage_dir=str(storage_dir))
    metadata = manager.get_session_info(sid)
    if metadata is None:
        raise LookupError(f"Session not found: {sid}")
    metadata.title = new_title
    metadata.updated_at = datetime.now().isoformat()
    manager.store._save_metadata(metadata)
    manager.store._record_graph(
        metadata,
        last_result_preview=new_title[:240],
        status="idle",
    )
    return metadata


def session_last_user_preview(
    metadata: SessionMetadata,
    *,
    storage_dir: str | Path = DEFAULT_SESSION_DIR,
    max_len: int = 72,
) -> str:
    """Best-effort one-line preview of the last user turn for picker highlight."""
    try:
        messages = SessionManager(storage_dir=str(storage_dir)).store.get_messages(
            metadata.session_id,
            limit=40,
        )
    except Exception:
        messages = []
    for message in reversed(messages):
        if str(getattr(message, "role", "")).lower() == "user":
            text = " ".join(str(getattr(message, "content", "") or "").split())
            if text:
                return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."
    if metadata.backend_session_path:
        for item in reversed(load_external_transcript_messages(metadata.backend_session_path)):
            if item.get("role") == "user":
                text = " ".join(str(item.get("content") or "").split())
                if text:
                    return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."
    topic = (metadata.title or "").strip()
    if topic and topic.lower() not in {"untitled", metadata.harness_id.lower()}:
        return topic if len(topic) <= max_len else topic[: max_len - 3].rstrip() + "..."
    return ""


def load_external_transcript_messages(backend_session_path: str | Path) -> list[dict[str, str]]:
    """Best-effort load of user/assistant turns from an external transcript file."""
    path = Path(backend_session_path).expanduser()
    if not path.is_file():
        return []
    # PiPy JSONL tree first.
    try:
        from superqode.pipy.messages import content_text
        from superqode.pipy.session.entries import MessageEntry
        from superqode.pipy.session.jsonl import JsonlSessionStorage

        storage = JsonlSessionStorage.open(path)
        out: list[dict[str, str]] = []
        for entry in getattr(storage, "_entries", []):
            if not isinstance(entry, MessageEntry):
                continue
            message = entry.message
            role = str(getattr(message, "role", "") or "").lower()
            if role not in {"user", "assistant"}:
                continue
            extract = getattr(message, "extract_text", None)
            if callable(extract):
                content = str(extract() or "")
            else:
                content = str(content_text(getattr(message, "content", "")) or "")
            content = content.strip()
            if content:
                out.append({"role": role, "content": content})
        if out:
            return out
    except Exception:
        pass

    # Plain SessionManager-style JSONL fallback (role/content lines).
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            role = str(payload.get("role") or "").lower()
            if role not in {"user", "assistant"}:
                continue
            content = payload.get("content")
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(str(block["text"]))
                    elif isinstance(block, str):
                        parts.append(block)
                content = "".join(parts)
            text = str(content or "").strip()
            if text:
                out.append({"role": role, "content": text})
    except OSError:
        return []
    return out


def enrich_resume_messages(
    messages: list[dict[str, Any]] | None,
    metadata: SessionMetadata,
) -> tuple[list[dict[str, str]], str]:
    """Return display turns plus a short receipt when falling back to external JSONL.

    Returns ``(turns, receipt)`` where ``receipt`` is empty when SessionManager
    JSONL already had usable history.
    """
    turns: list[dict[str, str]] = []
    for item in messages or []:
        role = str(item.get("role") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            turns.append({"role": role, "content": content})
    if turns:
        return turns, ""
    path = str(metadata.backend_session_path or "").strip()
    if not path:
        return [], ""
    external = load_external_transcript_messages(path)
    if not external:
        return [], "No chat turns found in SessionManager or external transcript"
    return external, f"Loaded {len(external)} turns from external transcript"


def missing_provider_credentials(provider: str) -> str:
    """Return a human hint when a BYOK provider key is absent, else ``\"\"``."""
    provider_id = str(provider or "").strip().lower()
    if not provider_id:
        return ""
    # Local / keyless routes do not need cloud credentials.
    if provider_id in {"ollama", "lmstudio", "llamacpp", "vllm", "local", "synthetic", "ds4"}:
        return ""
    try:
        from superqode.providers.registry import PROVIDERS

        definition = PROVIDERS.get(provider_id)
    except Exception:
        definition = None
    env_vars = list(getattr(definition, "env_vars", None) or [])
    if not env_vars:
        return ""
    import os

    if any(os.environ.get(name) for name in env_vars):
        return ""
    return " or ".join(env_vars)


def upsert_harness_session_meta(
    session_id: str,
    *,
    provider: str = "",
    model: str = "",
    harness_id: str = "",
    harness_source: str = "harness-spec",
    harness_path: str | None = None,
    harness_digest: str = "",
    harness_display: str = "",
    title: str = "",
    backend_session_path: str = "",
    working_directory: str | Path = "",
    storage_dir: str | Path = DEFAULT_SESSION_DIR,
    message_count: int | None = None,
    preview: str = "",
) -> SessionMetadata:
    """Create or refresh SessionManager metadata for a harness-backed session."""
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")

    manager = SessionManager(storage_dir=str(storage_dir))
    existing = manager.get_session_info(sid)
    if existing is None:
        manager.start_session(
            session_id=sid,
            provider=provider,
            model=model,
            harness_id=harness_id,
            harness_source=harness_source or "harness-spec",
            harness_digest=harness_digest,
        )
    else:
        manager.store.update_execution_binding(
            sid,
            provider=provider or existing.provider,
            model=model or existing.model,
            harness_id=harness_id or existing.harness_id,
            harness_source=harness_source or existing.harness_source or "harness-spec",
            harness_digest=harness_digest or existing.harness_digest,
            continuity="harness-resume",
        )

    metadata = manager.get_session_info(sid)
    if metadata is None:
        raise RuntimeError(f"Failed to upsert session metadata for {sid}")

    metadata.harness_session = True
    display = harness_display_name(
        harness_id or metadata.harness_id,
        explicit=harness_display or metadata.harness_display_name,
    )
    metadata.harness_display_name = display

    topic = (title or "").strip()
    if not topic:
        topic = topic_from_preview(preview, fallback="")
    if topic:
        # Keep an earlier human title unless the caller supplies a better one.
        prior = (metadata.title or "").strip()
        if not prior or prior.lower() in {"untitled", metadata.harness_id.lower(), display.lower()}:
            metadata.title = topic
        elif title:
            metadata.title = topic
    elif not metadata.title:
        metadata.title = f"{display} session"

    if backend_session_path:
        metadata.backend_session_path = str(backend_session_path)
    if harness_path is not None:
        metadata.harness_path = (
            str(Path(harness_path).expanduser().resolve()) if harness_path else ""
        )
    wd = str(working_directory or metadata.working_directory or Path.cwd()).strip()
    if wd:
        try:
            metadata.working_directory = str(Path(wd).expanduser().resolve())
        except OSError:
            metadata.working_directory = wd
    if message_count is not None:
        metadata.message_count = max(0, int(message_count))
    metadata.updated_at = datetime.now().isoformat()
    manager.store._save_metadata(metadata)
    manager.store._record_graph(
        metadata,
        last_result_preview=(preview or metadata.title or "")[:240],
        status="idle",
    )
    manager._current_session_id = sid
    return metadata


def discover_external_sessions(
    *,
    cwd: str | Path | None = None,
    storage_dir: str | Path = DEFAULT_SESSION_DIR,
    register: bool = True,
    only_session_id: str = "",
    include_known: bool = False,
) -> list[SessionMetadata]:
    """Find external sessions and optionally register one or more of them.

    Listing callers should use ``register=False``. Registration is intentionally
    targetable so choosing one old backend session cannot flood SessionManager
    with every historical run for the repository.
    """
    working = Path(cwd or Path.cwd()).expanduser().resolve()
    manager = SessionManager(storage_dir=str(storage_dir))
    known = {item.session_id for item in manager.list_all_sessions()}
    discovered: list[SessionMetadata] = []

    for root in _harness_store_roots(working, storage_dir):
        run_details = _file_harness_run_details(root)
        for record in _list_file_harness_sessions(root):
            sid = str(record.session_id)
            if not sid or (only_session_id and sid != only_session_id):
                continue
            refresh_known = register and only_session_id == sid
            if sid in known and not include_known and not refresh_known:
                continue
            run = run_details.get(sid, {})
            provider = str(record.metadata.get("provider") or run.get("provider") or "")
            model = str(record.metadata.get("model") or run.get("model") or "")
            harness_id = str(record.harness or "")
            title = str(
                record.metadata.get("title")
                or record.metadata.get("preview")
                or run.get("title")
                or ""
            )
            message_count = int(
                record.metadata.get("message_count") or run.get("message_count") or 0
            )
            backend_path = str(record.metadata.get("session_path") or "")
            # Opening a harness can create a record before any conversation.
            # Empty records are not useful resume targets and previously made
            # test/connect probes dominate the picker.
            if not title and message_count == 0 and not backend_path:
                continue
            if register:
                meta = upsert_harness_session_meta(
                    sid,
                    provider=provider,
                    model=model,
                    harness_id=harness_id,
                    harness_source="harness-store",
                    harness_display=harness_display_name(harness_id),
                    title=title or f"{harness_display_name(harness_id)} session",
                    backend_session_path=backend_path,
                    working_directory=working,
                    storage_dir=storage_dir,
                    message_count=message_count,
                )
                if record.updated_at:
                    try:
                        meta.created_at = _ts_iso(record.created_at)
                        meta.updated_at = datetime.fromtimestamp(
                            float(run.get("updated_at") or record.updated_at)
                        ).isoformat()
                        manager.store._save_metadata(meta)
                    except (OSError, ValueError, TypeError):
                        pass
                discovered.append(meta)
            else:
                discovered.append(
                    SessionMetadata(
                        session_id=sid,
                        created_at=_ts_iso(record.created_at),
                        updated_at=_ts_iso(run.get("updated_at") or record.updated_at),
                        provider=provider,
                        model=model,
                        harness_id=harness_id,
                        harness_source="harness-store",
                        harness_display_name=harness_display_name(harness_id),
                        title=title or f"{harness_display_name(harness_id)} session",
                        harness_session=True,
                        message_count=message_count,
                        backend_session_path=backend_path,
                        working_directory=str(working),
                    )
                )
            known.add(sid)

    for record in _list_pipy_sessions(working):
        sid = f"pipy-{record.id}"
        if only_session_id and sid != only_session_id:
            continue
        details = _pipy_session_details(record)
        title = details["title"] or "PiPy session"
        if sid in known:
            if register and record.path.is_file() and only_session_id == sid:
                existing = manager.get_session_info(sid)
                meta = upsert_harness_session_meta(
                    sid,
                    provider=details["provider"] or (existing.provider if existing else ""),
                    model=details["model"] or (existing.model if existing else ""),
                    harness_id="pipy",
                    harness_source="pipy",
                    harness_display="PiPy",
                    title=details["title"] or (existing.title if existing else "") or title,
                    backend_session_path=str(record.path),
                    working_directory=working,
                    storage_dir=storage_dir,
                    message_count=max(
                        int(details["message_count"]),
                        existing.message_count if existing else 0,
                    ),
                )
                meta.created_at = str(details["created_at"])
                meta.updated_at = str(details["updated_at"])
                manager.store._save_metadata(meta)
                discovered.append(meta)
                _index_pipy_path(sid, record.path, working)
            elif include_known:
                discovered.append(
                    _merge_external_metadata(
                        manager.get_session_info(sid),
                        _pipy_metadata(sid, record, working, details),
                    )
                )
            continue
        if register:
            meta = upsert_harness_session_meta(
                sid,
                provider=str(details["provider"]),
                model=str(details["model"]),
                harness_id="pipy",
                harness_source="pipy",
                harness_display="PiPy",
                title=title,
                backend_session_path=str(record.path),
                working_directory=working,
                storage_dir=storage_dir,
                message_count=int(details["message_count"]),
            )
            meta.created_at = str(details["created_at"])
            meta.updated_at = str(details["updated_at"])
            manager.store._save_metadata(meta)
            discovered.append(meta)
        else:
            discovered.append(_pipy_metadata(sid, record, working, details))
        known.add(sid)
        if register and record.path.is_file():
            _index_pipy_path(sid, record.path, working)

    discovered.sort(key=lambda item: item.updated_at, reverse=True)
    return discovered


def ensure_sessions_listed(
    *,
    cwd: str | Path | None = None,
    storage_dir: str | Path = DEFAULT_SESSION_DIR,
) -> list[SessionMetadata]:
    """Return stored and external sessions without mutating the session store."""
    working = Path(cwd or Path.cwd()).expanduser().resolve()
    sessions = SessionManager(storage_dir=str(storage_dir)).list_all_sessions()
    external = discover_external_sessions(
        cwd=working,
        storage_dir=storage_dir,
        register=False,
        include_known=True,
    )
    merged = {item.session_id: item for item in sessions}
    for item in external:
        merged[item.session_id] = _merge_external_metadata(merged.get(item.session_id), item)
    external_ids = {item.session_id for item in external}
    sessions = [
        item for item in merged.values() if not _orphaned_import_placeholder(item, external_ids)
    ]
    sessions.sort(key=lambda item: item.updated_at, reverse=True)
    # Prefer rows that belong to this cwd when working_directory was recorded.
    scoped: list[SessionMetadata] = []
    unscoped: list[SessionMetadata] = []
    for item in sessions:
        recorded = str(item.working_directory or "").strip()
        if not recorded:
            unscoped.append(item)
            continue
        try:
            if Path(recorded).expanduser().resolve() == working:
                scoped.append(item)
            # Different cwd: keep out of the default list for this project.
        except OSError:
            unscoped.append(item)
    # Legacy rows without working_directory stay visible (project-local store).
    return scoped + unscoped if scoped else sessions


def _ts_iso(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value)).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now().isoformat()


def _normalise_iso(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback or datetime.now().isoformat()
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone().replace(tzinfo=None)
        return stamp.isoformat()
    except ValueError:
        return fallback or text


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text") or block.get("content")
            if isinstance(text, str):
                parts.append(text)
    return " ".join(parts)


def _pipy_session_details(record: Any) -> dict[str, Any]:
    """Read enough of a PiPy transcript to produce an honest picker row."""
    metadata = getattr(getattr(record, "metadata", None), "metadata", {}) or {}
    provider = str(metadata.get("provider") or "")
    model = str(metadata.get("model") or "")
    title = str(metadata.get("name") or metadata.get("title") or metadata.get("preview") or "")
    message_count = 0
    path = Path(record.path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if payload.get("type") != "message":
                    continue
                message = payload.get("message") or {}
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "").lower()
                if role in {"user", "assistant"}:
                    message_count += 1
                if role == "user" and not title:
                    title = topic_from_preview(_message_text(message.get("content")))
                if role == "assistant":
                    provider = provider or str(message.get("provider") or "")
                    model = model or str(message.get("model") or "")
    except OSError:
        pass
    created_at = _normalise_iso(getattr(record, "created_at", ""))
    try:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        updated_at = created_at
    return {
        "provider": provider,
        "model": model,
        "title": title,
        "message_count": message_count,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _pipy_metadata(
    session_id: str,
    record: Any,
    working: Path,
    details: dict[str, Any],
) -> SessionMetadata:
    return SessionMetadata(
        session_id=session_id,
        created_at=str(details["created_at"]),
        updated_at=str(details["updated_at"]),
        provider=str(details["provider"]),
        model=str(details["model"]),
        message_count=int(details["message_count"]),
        harness_id="pipy",
        harness_source="pipy",
        harness_display_name="PiPy",
        title=str(details["title"] or "PiPy session"),
        harness_session=True,
        backend_session_path=str(record.path),
        working_directory=str(working),
    )


def _merge_external_metadata(
    stored: SessionMetadata | None,
    external: SessionMetadata,
) -> SessionMetadata:
    """Overlay incomplete auto-imported rows with authoritative backend data."""
    if stored is None:
        return external
    generic_titles = {
        "",
        "untitled",
        f"{harness_display_name(stored.harness_id).lower()} session",
    }
    stored.provider = external.provider or stored.provider
    stored.model = external.model or stored.model
    stored.harness_id = external.harness_id or stored.harness_id
    stored.harness_source = external.harness_source or stored.harness_source
    stored.harness_display_name = external.harness_display_name or stored.harness_display_name
    if stored.title.strip().lower() in generic_titles and external.title:
        stored.title = external.title
    stored.message_count = max(stored.message_count, external.message_count)
    stored.backend_session_path = external.backend_session_path or stored.backend_session_path
    stored.working_directory = external.working_directory or stored.working_directory
    if external.created_at:
        stored.created_at = external.created_at
    if external.updated_at:
        stored.updated_at = external.updated_at
    return stored


def _harness_store_roots(cwd: Path, storage_dir: str | Path) -> list[Path]:
    roots: list[Path] = []
    candidates: Iterable[str | Path] = (storage_dir, *HARNESS_STORE_ROOTS)
    for raw in candidates:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = cwd / path
        try:
            path = path.resolve()
        except OSError:
            continue
        if path not in roots:
            roots.append(path)
    return roots


def _list_file_harness_sessions(root: Path) -> list[Any]:
    sessions_dir = root / "sessions"
    if not sessions_dir.is_dir():
        return []
    try:
        from superqode.harness.store import FileHarnessStore

        return FileHarnessStore(root).list_sessions()
    except Exception:
        return []


def _file_harness_run_details(root: Path) -> dict[str, dict[str, Any]]:
    """Summarise stored runs once so session rows have useful topics."""
    try:
        from superqode.harness.store import FileHarnessStore

        runs = FileHarnessStore(root).list_runs()
    except Exception:
        return {}
    details: dict[str, dict[str, Any]] = {}
    for run in runs:
        item = details.setdefault(
            str(run.session_id),
            {
                "provider": str(run.provider or ""),
                "model": str(run.model or ""),
                "title": topic_from_preview(run.prompt_preview),
                "message_count": 0,
                "updated_at": 0.0,
            },
        )
        item["message_count"] = int(item["message_count"]) + 2
        updated = float(run.ended_at or run.started_at or 0.0)
        if updated >= float(item["updated_at"]):
            item["provider"] = str(run.provider or item["provider"])
            item["model"] = str(run.model or item["model"])
            item["title"] = topic_from_preview(run.prompt_preview) or item["title"]
            item["updated_at"] = updated
    return details


def _orphaned_import_placeholder(
    metadata: SessionMetadata,
    external_ids: set[str],
) -> bool:
    """Hide obsolete indexes created for empty external harness sessions."""
    if metadata.session_id in external_ids or metadata.harness_source != "harness-store":
        return False
    title = (metadata.title or "").strip().lower()
    generic = title in {
        "",
        "untitled",
        f"{harness_display_name(metadata.harness_id).lower()} session",
    }
    return bool(
        metadata.harness_session
        and generic
        and metadata.message_count == 0
        and not metadata.backend_session_path
    )


def _list_pipy_sessions(cwd: Path) -> list[Any]:
    try:
        from superqode.pipy.session.repository import SessionRepository

        return SessionRepository().list(cwd)
    except Exception:
        return []


def _index_pipy_path(session_id: str, session_path: Path, working_directory: Path) -> None:
    try:
        from superqode.harness.pipy_adapter import _record_session_path

        _record_session_path(session_id, session_path)
    except Exception:
        return


__all__ = [
    "DEFAULT_SESSION_DIR",
    "HARNESS_STORE_ROOTS",
    "SessionResumeError",
    "discover_external_sessions",
    "enrich_resume_messages",
    "ensure_sessions_listed",
    "format_session_label",
    "format_session_row_label",
    "group_sessions_by_harness",
    "harness_display_name",
    "load_external_transcript_messages",
    "missing_provider_credentials",
    "model_short_name",
    "relative_age",
    "rename_session_title",
    "session_last_user_preview",
    "session_short_label",
    "topic_from_preview",
    "upsert_harness_session_meta",
]
