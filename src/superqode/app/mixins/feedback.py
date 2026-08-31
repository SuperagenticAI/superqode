"""Consistent feedback for consequential TUI state transitions."""

from __future__ import annotations

from time import monotonic
from typing import Literal

from superqode.app.outcomes import (
    Outcome,
    OutcomeAction,
    OutcomeSeverity,
    OutcomeStore,
)
from superqode.app.widgets import ConversationLog


TransitionSeverity = Literal["success", "information", "warning", "error"]


class FeedbackMixin:
    """Present important state changes as notifications and transcript receipts."""

    _TRANSITION_TIMEOUTS = {
        "success": 1.5,
        "information": 1.5,
        "warning": 3.0,
        "error": 5.0,
    }
    _TRANSITION_DEDUPE_SECONDS = 3.0

    def _outcome_store(self) -> OutcomeStore:
        """Return the session activity store, creating it lazily."""
        store = getattr(self, "_product_outcomes", None)
        if store is None:
            store = OutcomeStore()
            self._product_outcomes = store
        return store

    def _present_outcome(
        self,
        outcome: Outcome,
        *,
        log: ConversationLog | None = None,
        focus: bool = True,
        receipt: bool = True,
    ) -> Outcome:
        """Present a structured result in focus and preserve it in Activity."""
        self._outcome_store().add(outcome, read=focus)
        if receipt:
            if log is None:
                try:
                    log = self.query_one("#log", ConversationLog)
                except Exception:
                    log = None
            if log is not None:
                writer = {
                    OutcomeSeverity.SUCCESS: "add_success",
                    OutcomeSeverity.INFORMATION: "add_meta",
                    OutcomeSeverity.WARNING: "add_warning",
                    OutcomeSeverity.ERROR: "add_error",
                }[outcome.severity]
                getattr(log, writer)(outcome.receipt)

        if focus:
            try:
                from superqode.widgets.outcome_screen import OutcomeScreen

                self.push_screen(
                    OutcomeScreen(outcome),
                    callback=lambda selection: self._handle_outcome_selection(selection, log),
                )
                return outcome
            except Exception:
                # Mounted lightweight tests and non-Textual callers still get
                # a notification and transcript receipt.
                pass

        try:
            self.notify(
                outcome.summary,
                title=outcome.title,
                severity=(
                    "information"
                    if outcome.severity == OutcomeSeverity.SUCCESS
                    else outcome.severity.value
                ),
                timeout=self._TRANSITION_TIMEOUTS[outcome.severity.value],
                markup=False,
            )
        except Exception:
            pass
        return outcome

    def _handle_outcome_selection(self, selection, log: ConversationLog | None) -> None:
        """Run a command selected from an outcome screen."""
        command = str(getattr(selection, "command", "") or "")
        if not command:
            return
        if log is None:
            try:
                log = self.query_one("#log", ConversationLog)
            except Exception:
                return
        self._handle_command(command, log)

    def _activity_cmd(self, log: ConversationLog) -> None:
        """Open focused session activity instead of searching the transcript."""
        try:
            from superqode.widgets.outcome_screen import ActivityScreen

            outcomes = self._outcome_store().list()
            self.push_screen(
                ActivityScreen(outcomes),
                callback=lambda selection: self._handle_outcome_selection(selection, log),
            )
            for outcome in outcomes:
                self._outcome_store().mark_read(outcome.id)
        except Exception as exc:
            log.add_error(f"Could not open Activity: {exc}")

    def _announce_model_ready(
        self,
        *,
        model_name: str,
        model_id: str,
        source: str,
        log: ConversationLog,
        free: bool = False,
        changed: bool = False,
    ) -> bool:
        """Announce that a model selection is active and ready for input."""
        detail_parts = [f"{source} via ACP"]
        if free:
            detail_parts.append("Free model")
        if model_id and model_id != model_name:
            detail_parts.append(model_id)
        return self._announce_transition(
            title="Model changed" if changed else "Model ready",
            primary=model_name or model_id,
            detail=" · ".join(detail_parts),
            severity="success",
            log=log,
            popup=True,
            dedupe_key=f"model:{source}:{model_id}",
        )

    def _announce_local_model_ready(
        self,
        *,
        provider: str,
        model: str,
        log: ConversationLog,
        detail: str = "Local server validated",
    ) -> bool:
        """Announce that a selected local model passed its readiness check."""
        return self._announce_transition(
            title="Local model ready",
            primary=model,
            detail=f"{provider} · {detail}",
            severity="success",
            log=log,
            persist=False,
            popup=True,
            dedupe_key=f"local-ready:{provider}:{model}",
        )

    def _show_transition_modal(
        self,
        *,
        title: str,
        primary: str,
        detail: str,
        guidance: str,
        severity: str,
    ) -> bool:
        """Acknowledge a finished state change in a modal.

        A toast for "agent connected" was easy to miss and, styled against this
        app's dark panel, hard to read at all. A modal puts the result in the
        middle of the screen and waits for Enter or Esc.

        Returns False when no screen can be pushed, so the caller falls back to
        a notification. That path is what keeps headless and lightweight tests
        working.
        """
        from superqode.app.outcomes import Outcome, OutcomeSeverity
        from superqode.widgets.outcome_screen import OutcomeScreen

        outcome = Outcome(
            title=title,
            summary=primary,
            details=tuple(part for part in (detail, guidance) if part),
            severity=OutcomeSeverity(severity),
            # No source line: "From state change" under "Agent connected" is
            # noise in a modal. Activity still records the source separately.
            source="",
            actions=(
                (OutcomeAction("recover", "Run recovery", guidance),)
                if guidance.startswith(":")
                else ()
            ),
        )

        # A flow that announces twice, such as connecting an agent and then
        # settling its model, must not queue two dismissals.
        try:
            current = self.screen
        except Exception:  # noqa: BLE001 - no screen stack yet
            current = None
        if isinstance(current, OutcomeScreen):
            if current.replace_outcome(outcome):
                return True
            # The newer result needs a different button row, so the screen is
            # swapped rather than stacked: the user still owes one dismissal.
            try:
                self.pop_screen()
            except Exception:  # noqa: BLE001 - fall through to a plain push
                pass

        try:
            self.push_screen(
                OutcomeScreen(outcome),
                callback=lambda selection: self._handle_outcome_selection(selection, None),
            )
        except Exception:  # noqa: BLE001 - fall back to a notification
            return False
        return True

    def _announce_transition(
        self,
        *,
        title: str,
        primary: str,
        detail: str = "",
        severity: TransitionSeverity = "success",
        log: ConversationLog | None = None,
        persist: bool = True,
        guidance: str = "",
        timeout: float | None = None,
        dedupe_key: str = "",
        restore_focus: bool = True,
        popup: bool | None = None,
    ) -> bool:
        """Announce a user-visible state transition.

        Warnings and errors use a short popup because they require attention.
        Routine success and information transitions stay in the transcript and
        status bar unless a caller explicitly requests a popup.
        """
        title = " ".join(str(title).split())
        primary = " ".join(str(primary).split())
        detail = " ".join(str(detail).split())
        guidance = " ".join(str(guidance).split())
        if not title or not primary:
            return False

        key = dedupe_key or f"{severity}:{title}:{primary}:{detail}"
        now = monotonic()
        recent = getattr(self, "_transition_notice_times", None)
        if recent is None:
            recent = {}
            self._transition_notice_times = recent
        previous = recent.get(key)
        if previous is not None and now - previous < self._TRANSITION_DEDUPE_SECONDS:
            return False
        recent[key] = now
        if len(recent) > 64:
            cutoff = now - 30.0
            self._transition_notice_times = {
                item_key: timestamp for item_key, timestamp in recent.items() if timestamp >= cutoff
            }

        # A completed state change must be visible without scrolling.  Routine
        # information may stay quiet, but success, warning and error all get a
        # popup in addition to the persistent status/transcript state.
        show_popup = severity != "information" if popup is None else popup
        # A completed result is acknowledged in a modal; a progress note is not,
        # because nothing has finished yet and demanding a keypress mid-flow is
        # worse than the toast it replaces. ``persist`` is already the difference
        # between the two: only persisted announcements become an Outcome.
        modal_shown = False
        if show_popup and persist:
            modal_shown = self._show_transition_modal(
                title=title,
                primary=primary,
                detail=detail,
                guidance=guidance,
                severity=severity,
            )
        if show_popup and not modal_shown:
            body_parts = [primary]
            if detail:
                body_parts.append(detail)
            if guidance and severity in {"warning", "error"}:
                body_parts.append(guidance)
            try:
                self.notify(
                    "\n".join(body_parts),
                    title=title,
                    severity="information" if severity == "success" else severity,
                    timeout=(
                        timeout if timeout is not None else self._TRANSITION_TIMEOUTS[severity]
                    ),
                    markup=False,
                )
            except Exception:
                # Transcript feedback still works in headless and lightweight tests.
                pass

        if persist:
            if log is None:
                try:
                    log = self.query_one("#log", ConversationLog)
                except Exception:
                    log = None
            if log is not None:
                receipt = f"{title}: {primary}"
                if detail:
                    receipt += f" · {detail}"
                writer_name = {
                    "success": "add_success",
                    "information": "add_info",
                    "warning": "add_warning",
                    "error": "add_error",
                }[severity]
                getattr(log, writer_name)(receipt)
                if guidance:
                    log.add_meta(guidance, icon="→")

            try:
                self._outcome_store().add(
                    Outcome(
                        title=title,
                        summary=primary,
                        details=tuple(part for part in (detail, guidance) if part),
                        severity=OutcomeSeverity(severity),
                        source="state change",
                        actions=(
                            (OutcomeAction("recover", "Run recovery", guidance),)
                            if guidance.startswith(":")
                            else ()
                        ),
                    ),
                    read=show_popup,
                )
            except Exception:
                pass

        if restore_focus:
            try:
                self._ensure_input_focus()
            except Exception:
                pass
        return True
