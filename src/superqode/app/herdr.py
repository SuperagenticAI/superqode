"""Bridge the interactive app's shared lifecycle to Herdr."""

from __future__ import annotations

from pathlib import Path

from superqode.herdr import HerdrReporter, launch_prefix, valid_resume_argv


def resume_command(app) -> tuple[str, tuple[str, ...]]:
    """Advertise only a durable active session, never a recent-session fallback."""
    approval = getattr(app, "approval_mode", "ask")
    mode = "plan" if getattr(app, "_plan_mode_enabled", False) else "build"
    base = (*launch_prefix(), "--tui", "--approval-mode", approval, "--interaction-mode", mode)
    # Replacing a previous restore command with a fresh launch prevents Herdr
    # from reopening the old conversation after disconnecting or changing to
    # a backend without durable SuperQode session storage.
    fresh = base if valid_resume_argv(base) else ("superqode", "--tui")
    pure = getattr(app, "_pure_mode", None)
    if pure is None or not getattr(getattr(pure, "session", None), "connected", False):
        return "", fresh
    if getattr(app, "current_agent", "") or getattr(app, "_chat_mode", False):
        return "", fresh
    try:
        sid = pure.get_current_session_id()
        manager = getattr(pure, "_session_manager", None)
        meta = manager.get_session_info(sid) if sid and manager else None
        if meta is None or not meta.provider or not meta.model:
            return "", fresh
        # Session storage and Herdr's restored pane both belong to this cwd.
        if (
            meta.working_directory
            and Path(meta.working_directory).resolve() != Path.cwd().resolve()
        ):
            return "", fresh
        harness = meta.harness_path or meta.harness_id or "core"
        if not meta.harness_session and getattr(pure, "_agent", None) is None:
            return "", fresh
        argv = (
            *base,
            "--resume",
            sid,
            "--provider",
            meta.provider,
            "--model",
            meta.model,
            "--harness",
            harness,
            "--runtime",
            pure.runtime_name,
        )
        if valid_resume_argv(argv):
            return sid, argv
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return "", fresh


def start(app) -> None:
    app._herdr_reporter = HerdrReporter.from_env()
    sync(app)


def sync(app) -> None:
    reporter = getattr(app, "_herdr_reporter", None)
    if reporter is None:
        return
    pending = []
    pure = getattr(app, "_pure_mode", None)
    try:
        pending = pure.get_pending_approvals() if pure is not None else []
    except Exception:
        pass
    if getattr(app, "_herdr_restore_error", "") and not getattr(
        getattr(pure, "session", None), "connected", False
    ):
        state, message = "blocked", "Session restore failed"
    elif getattr(app, "_awaiting_agent_question", False):
        state, message = "blocked", "Answer needed"
    elif getattr(app, "_permission_pending", False) or pending:
        state, message = "blocked", "Approval needed"
    else:
        state = "working" if getattr(app, "is_busy", False) else "idle"
        message = ""
    harness = getattr(app, "current_agent", "") or getattr(app, "current_mode", "")
    model = getattr(app, "current_model", "")
    try:
        status = app.query_one("#status-bar")
        harness = getattr(status, "active_harness", "") or harness
        model = getattr(status, "active_model", "") or model
    except Exception:
        pass
    sid, argv = resume_command(app)
    reporter.report(
        state,
        message=message,
        harness=harness,
        model=model,
        session_id=sid,
        resume_argv=argv,
    )


def close(app) -> None:
    reporter = getattr(app, "_herdr_reporter", None)
    if reporter is not None:
        app._herdr_reporter = None
        reporter.close()
