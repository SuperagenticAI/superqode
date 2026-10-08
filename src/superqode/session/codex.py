"""Durable native Codex bindings; credentials stay entirely in Codex."""

import os
import re
from datetime import datetime
from pathlib import Path

from superqode.agent.session_manager import SessionManager


def codex_home():
    return str(Path(os.getenv("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve())


def manager(root):
    return SessionManager(str(Path(root) / ".superqode/sessions"))


def saved_thread(root, sid):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid or ""):
        raise ValueError("Invalid Codex thread id")
    return manager(root).get_session_info(sid)


def record_thread(runtime, thread, *, persisted=False):
    sid = runtime.thread_id
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid or ""):
        raise ValueError("Codex returned an invalid thread id")
    sessions = manager(runtime.config.working_directory)
    sessions.start_session(
        sid,
        provider="openai",
        model=runtime.active_model,
        harness_id="codex",
        harness_source="runtime",
        continuity="exact-resume",
    )
    meta = sessions.get_session_info(sid)
    meta.runtime = "codex-cli"
    meta.backend_session_id = sid
    meta.backend_native_session_id = getattr(runtime, "native_session_id", None) or ""
    meta.backend_forked_from_id = getattr(runtime, "forked_from_id", None) or ""
    meta.backend_home = codex_home()
    meta.backend_resume_ready = meta.backend_resume_ready or persisted
    meta.billing_requested = runtime.billing_requested
    meta.harness_session = True
    meta.harness_display_name = "Codex"
    meta.working_directory = str(runtime.config.working_directory.resolve())
    meta.title = thread.get("name") or meta.title or "Codex session"
    meta.archived = False
    meta.updated_at = datetime.now().isoformat()
    sessions.store._save_metadata(meta)
    sessions.store._record_graph(meta)


def record_prompt(runtime, prompt):
    """Index an attempted turn even if its acknowledgement is lost."""
    sessions = manager(runtime.config.working_directory)
    sessions.start_session(runtime.thread_id)
    sessions.add_user_message(prompt)
    meta = sessions.get_session_info(runtime.thread_id)
    if meta.title == "Codex session":
        meta.title = prompt[:80]
    sessions.store._save_metadata(meta)


def record_turn(runtime, response):
    sessions = manager(runtime.config.working_directory)
    sessions.start_session(runtime.thread_id)
    sessions.add_assistant_message(response)
    meta = sessions.get_session_info(runtime.thread_id)
    meta.backend_usage = runtime.token_usage
    meta.backend_resume_ready = True
    sessions.store._save_metadata(meta)


def archive_thread(runtime, sid, *, archived):
    sessions = manager(runtime.config.working_directory)
    meta = sessions.get_session_info(sid)
    if meta is not None and meta.runtime == "codex-cli":
        meta.archived = archived
        sessions.store._save_metadata(meta)


def latest_thread(root, billing):
    return next(
        (
            m
            for m in manager(root).list_all_sessions()
            if m.runtime == "codex-cli"
            and (m.backend_resume_ready or m.message_count > 0)
            and not m.archived
            and m.backend_home == codex_home()
            and m.billing_requested == billing
        ),
        None,
    )
