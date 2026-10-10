"""Guided first tasks and local, reviewed developer feedback."""

from __future__ import annotations

from superqode.app.developer_trial import DeveloperTrial
from superqode.app.widgets import ConversationLog


class DeveloperExperienceMixin:
    def _trial_state(self) -> DeveloperTrial:
        state = getattr(self, "_developer_trial", None)
        if state is None:
            state = self._developer_trial = DeveloperTrial()
        return state

    def _trial_setup_pending(self) -> bool:
        prompts = getattr(self, "_prompts", None)
        return bool(
            (prompts and prompts.active is not None)
            or getattr(self, "_permission_pending", False)
            or getattr(self, "_awaiting_agent_question", False)
            or getattr(self, "_install_in_progress", False)
            or any(
                getattr(self, flag, False)
                for flag in (
                    "_awaiting_connect_type",
                    "_awaiting_subscription_login",
                    "_awaiting_runtime_selection",
                    "_awaiting_byok_provider",
                    "_awaiting_byok_model",
                    "_awaiting_acp_agent_selection",
                    "_awaiting_local_provider",
                    "_awaiting_local_model",
                    "_awaiting_codex_model",
                    "_awaiting_codex_effort",
                    "_awaiting_harness_selection",
                    "_awaiting_harness_confirmation",
                    "_awaiting_harness_install",
                    "_awaiting_harness_wizard",
                    "_awaiting_dependency_install",
                    "_awaiting_local_server_start",
                    "_awaiting_local_dep_install",
                    "_awaiting_local_connect_start",
                    "_awaiting_session_resume",
                    "_awaiting_mode_selection",
                    "_awaiting_model_selection",
                )
            )
        )

    def _trial_cmd(self, log) -> None:
        from superqode.widgets.developer_trial import DeveloperTrialScreen

        if self.is_busy:
            log.add_info(
                "The task is running. Esc or Ctrl+C cancels it; use :trial after it finishes to review."
            )
            return
        if self._trial_setup_pending():
            log.add_info(
                "Finish the connection or approval prompt first, then use :trial to continue."
            )
            return
        self.push_screen(
            DeveloperTrialScreen(self._trial_state()), callback=lambda _: self._ensure_input_focus()
        )

    def _feedback_cmd(self, log) -> None:
        from superqode.widgets.feedback_export import FeedbackExportScreen

        self.push_screen(FeedbackExportScreen(), callback=lambda _: self._ensure_input_focus())

    def _trial_connection_ready(self) -> None:
        state = getattr(self, "_developer_trial", None)
        if not state or not state.awaiting_connection:
            return
        state.awaiting_connection = False

        def resume():
            from superqode.app.widgets import ConversationLog

            if (
                self.screen is self.default_screen
                and not self.is_busy
                and not self._trial_setup_pending()
            ):
                self._trial_cmd(self.query_one("#log", ConversationLog))

        self.set_timer(0.2, resume)

    def _trial_route_identity(self) -> tuple:
        fingerprint = self._connection_fingerprint()
        # ACP and SDK clients may start lazily on the first prompt. Their
        # object identities are appropriate for diagnostic freshness, but not
        # for detecting a user route switch during that first task.
        return (
            (fingerprint[0], fingerprint[1], fingerprint[2], *fingerprint[7:])
            if len(fingerprint) >= 10
            else fingerprint
        )

    def _trial_same_route(self, expected: tuple | None) -> bool:
        actual = self._trial_route_identity()
        if (
            expected
            and len(expected) == 6
            and isinstance(expected[0], tuple)
            and not expected[0][2]
        ):
            actual = ((actual[0][0], actual[0][1], ""), *actual[1:])
        return expected == actual

    def _bind_trial_task(self, task_id: str) -> None:
        state = getattr(self, "_developer_trial", None)
        if state and state.pending:
            if not state.task_id and self._trial_same_route(state.submitted_route):
                state.task_id = task_id
            elif state.task_id != task_id:
                state.pending = False
                state.result = (
                    "The guided run stopped before a successful answer. Validate and try again."
                )

    def _record_trial_completion(self, summary: dict, response: str) -> None:
        state = getattr(self, "_developer_trial", None)
        task = getattr(self, "_task_changes_current", None)
        if not (state and state.pending and state.task_id and task and state.task_id == task.id):
            return
        if not self._trial_same_route(state.submitted_route):
            state.pending = False
            state.result = (
                "The connection changed during the task. Validate the new route and try again."
            )
            return
        state.pending = False
        state.completed = bool(response.strip()) and not getattr(self, "_cancel_requested", False)
        if state.completed:
            count = len(summary.get("files_modified") or [])
            state.result = f"Answer received · {count} changed file(s). Review the answer and recorded changes."
            if self._run_hit_an_error(summary):
                state.result += " Some tools failed; inspect Activity before continuing."
            from dataclasses import replace
            from superqode.app.task_review import task_review

            calls = getattr(self.query_one("#log", ConversationLog), "_tool_calls", [])
            outcome = task_review({**summary, "task_id": task.id}, calls)
            state.outcome = replace(
                outcome,
                title="Guided task result",
                source="First task",
                details=("Answer\n" + response[:16000], *outcome.details),
            )
            self._outcome_store().add(state.outcome)
        else:
            state.result = "The guided run stopped without an answer. Check Activity and try again."
