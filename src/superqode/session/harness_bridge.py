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
    model = model_short_name(metadata.model) if metadata.model else (
        metadata.provider or "model?"
    )
    topic = (metadata.title or "").strip()
    # Avoid repeating harness/model when title already encodes them.
    if not topic or topic.lower() in {harness.lower(), metadata.harness_id.lower(), metadata.session_id}:
        topic = "untitled"
    age = relative_age(metadata.updated_at)
    return f"{harness} · {model} · {topic} · {age}"


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
) -> list[SessionMetadata]:
    """Find FileHarnessStore and PiPy sessions for this cwd and optionally register them."""
    working = Path(cwd or Path.cwd()).expanduser().resolve()
    manager = SessionManager(storage_dir=str(storage_dir))
    known = {item.session_id for item in manager.list_all_sessions()}
    discovered: list[SessionMetadata] = []

    for root in _harness_store_roots(working, storage_dir):
        for record in _list_file_harness_sessions(root):
            sid = str(record.session_id)
            if not sid or sid in known:
                continue
            provider = str(record.metadata.get("provider") or "")
            model = str(record.metadata.get("model") or "")
            harness_id = str(record.harness or "")
            title = str(
                record.metadata.get("title")
                or record.metadata.get("preview")
                or ""
            )
            if register:
                meta = upsert_harness_session_meta(
                    sid,
                    provider=provider,
                    model=model,
                    harness_id=harness_id,
                    harness_source="harness-store",
                    harness_display=harness_display_name(harness_id),
                    title=title or f"{harness_display_name(harness_id)} session",
                    backend_session_path=str(record.metadata.get("session_path") or ""),
                    working_directory=working,
                    storage_dir=storage_dir,
                    message_count=int(record.metadata.get("message_count") or 0),
                )
                if record.updated_at:
                    try:
                        meta.updated_at = datetime.fromtimestamp(
                            float(record.updated_at)
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
                        updated_at=_ts_iso(record.updated_at),
                        provider=provider,
                        model=model,
                        harness_id=harness_id,
                        harness_source="harness-store",
                        harness_display_name=harness_display_name(harness_id),
                        title=title or f"{harness_display_name(harness_id)} session",
                        harness_session=True,
                        backend_session_path=str(record.metadata.get("session_path") or ""),
                        working_directory=str(working),
                    )
                )
            known.add(sid)

    for record in _list_pipy_sessions(working):
        sid = f"pipy-{record.id}"
        title = ""
        try:
            title = str(getattr(record.metadata, "name", "") or "")
        except Exception:
            title = ""
        if not title:
            title = "PiPy session"
        if sid in known:
            if register and record.path.is_file():
                existing = manager.get_session_info(sid)
                if existing and existing.backend_session_path != str(record.path):
                    upsert_harness_session_meta(
                        sid,
                        provider=existing.provider if existing else "",
                        model=existing.model if existing else "",
                        harness_id="pipy",
                        harness_source="pipy",
                        harness_display="PiPy",
                        title=existing.title if existing and existing.title else title,
                        backend_session_path=str(record.path),
                        working_directory=working,
                        storage_dir=storage_dir,
                        message_count=existing.message_count if existing else 0,
                    )
            continue
        if register:
            meta = upsert_harness_session_meta(
                sid,
                harness_id="pipy",
                harness_source="pipy",
                harness_display="PiPy",
                title=title,
                backend_session_path=str(record.path),
                working_directory=working,
                storage_dir=storage_dir,
            )
            discovered.append(meta)
        else:
            discovered.append(
                SessionMetadata(
                    session_id=sid,
                    created_at=str(getattr(record, "created_at", "") or datetime.now().isoformat()),
                    updated_at=str(getattr(record, "created_at", "") or datetime.now().isoformat()),
                    harness_id="pipy",
                    harness_source="pipy",
                    harness_display_name="PiPy",
                    title=title,
                    harness_session=True,
                    backend_session_path=str(record.path),
                    working_directory=str(working),
                )
            )
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
    """Return SessionManager sessions, discovering harness/PiPy entries first."""
    working = Path(cwd or Path.cwd()).expanduser().resolve()
    discover_external_sessions(cwd=working, storage_dir=storage_dir, register=True)
    sessions = SessionManager(storage_dir=str(storage_dir)).list_all_sessions()
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
    "ensure_sessions_listed",
    "format_session_label",
    "harness_display_name",
    "missing_provider_credentials",
    "model_short_name",
    "relative_age",
    "topic_from_preview",
    "upsert_harness_session_meta",
]
