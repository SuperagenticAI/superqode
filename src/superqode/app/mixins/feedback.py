"""Consistent feedback for consequential TUI state transitions."""

from __future__ import annotations

from time import monotonic
from typing import Literal

from superqode.app.widgets import ConversationLog


TransitionSeverity = Literal["success", "information", "warning", "error"]


class FeedbackMixin:
    """Present important state changes as notifications and transcript receipts."""

    _TRANSITION_TIMEOUTS = {
        "success": 4.0,
        "information": 3.0,
        "warning": 7.0,
        "error": 10.0,
    }

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
            dedupe_key=f"local-ready:{provider}:{model}",
        )

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
    ) -> bool:
        """Announce a user-visible state transition.

        The toast provides immediate feedback. The transcript receipt preserves
        the result after the toast expires. Callers remain responsible for
        updating the persistent status bar with the new active state.
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
        if previous is not None and now - previous < 1.25:
            return False
        recent[key] = now
        if len(recent) > 64:
            cutoff = now - 30.0
            self._transition_notice_times = {
                item_key: timestamp for item_key, timestamp in recent.items() if timestamp >= cutoff
            }

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
                timeout=timeout or self._TRANSITION_TIMEOUTS[severity],
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

        if restore_focus:
            try:
                self._ensure_input_focus()
            except Exception:
                pass
        return True
