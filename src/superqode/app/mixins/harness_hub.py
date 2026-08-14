"""Application integration for the dedicated Harness Hub screen."""

from __future__ import annotations

from pathlib import Path

from superqode.app.harness_picker import HarnessPickerItem, harness_picker_items
from superqode.app.outcomes import Outcome, OutcomeAction, OutcomeSeverity
from superqode.app.widgets import ConversationLog
from superqode.harness.hub import (
    REFERENCE_ONLY_KINDS,
    hub_ecosystem_picker_items,
    hub_record,
    readiness_label,
)


class HarnessHubMixin:
    """Open the Hub and route its actions through existing harness machinery."""

    def _hub_cmd(self, args: str, log: ConversationLog) -> None:
        """Open Harness Hub.

        The historical model-search mode is available during migration through
        ``:hub model <query>``.  ``:local search`` remains its canonical name.
        """
        raw = (args or "").strip()
        lowered = raw.casefold()
        if lowered == "list":
            raw = ""
            lowered = ""
        elif lowered.startswith("show "):
            item_id = raw[5:].strip()
            try:
                item = next(
                    (
                        candidate
                        for candidate in self._harness_hub_items()
                        if candidate.id.casefold() == item_id.casefold()
                    ),
                    None,
                )
            except Exception as exc:
                self._present_outcome(
                    Outcome(
                        title="Harness Hub unavailable",
                        summary="The catalog could not be loaded",
                        details=(str(exc),),
                        severity=OutcomeSeverity.ERROR,
                        source=":hub show",
                    ),
                    log=log,
                )
                return
            if item is None:
                self._present_outcome(
                    Outcome(
                        title="Harness not found",
                        summary=item_id,
                        details=("Use :hub to browse or :hub list to see every entry.",),
                        severity=OutcomeSeverity.WARNING,
                        source=":hub show",
                    ),
                    log=log,
                )
                return
            self._present_harness_hub_detail(item, log)
            return
        for prefix in ("model ", "models ", "--model "):
            if lowered.startswith(prefix):
                query = raw[len(prefix) :].strip()
                if not query:
                    self._present_outcome(
                        Outcome(
                            title="Model search",
                            summary="Enter a model name",
                            details=("Use :local search <model> or :hub model <model>.",),
                            severity=OutcomeSeverity.INFORMATION,
                        ),
                        log=log,
                    )
                    return
                self.run_worker(self._local_search(query, log))
                return

        if lowered in {"off", "stop", "exit"}:
            # These used to toggle model-search mode off. They now land here so
            # muscle memory opens the Hub instead of reporting an unknown flag.
            self._present_outcome(
                Outcome(
                    title="Harness Hub",
                    summary="Model-search mode has moved",
                    details=("Use :local search <model>. Opening Harness Hub now.",),
                    severity=OutcomeSeverity.INFORMATION,
                ),
                log=log,
                focus=False,
            )
            raw = ""
            lowered = ""

        filters = {"all", "ready", "setup", "custom", "coming"}
        initial_filter = lowered if lowered in filters else "all"
        query = "" if lowered in {"", *filters, "on", "start"} else raw
        self._open_harness_hub(log, query=query, initial_filter=initial_filter)

    @staticmethod
    def _harness_hub_items() -> list[HarnessPickerItem]:
        """Return runnable entries plus read-only ecosystem discovery records."""
        return [
            *harness_picker_items(
                Path.cwd(),
                include_all=True,
                expand_protocol_catalog=True,
            ),
            *hub_ecosystem_picker_items(),
        ]

    def _open_harness_hub(
        self,
        log: ConversationLog,
        *,
        query: str = "",
        initial_filter: str = "all",
    ) -> None:
        from superqode.widgets.harness_hub import HarnessHubScreen

        try:
            items = self._harness_hub_items()
        except Exception as exc:
            self._present_outcome(
                Outcome(
                    title="Harness Hub unavailable",
                    summary="The catalog could not be loaded",
                    details=(str(exc), "Run :doctor or reopen the Hub."),
                    severity=OutcomeSeverity.ERROR,
                    source=":hub",
                ),
                log=log,
            )
            return

        current_id = next(
            (item.id for item in items if self._harness_picker_item_is_current(item)),
            "",
        )
        self._record_milestone("explored")
        self.push_screen(
            HarnessHubScreen(
                items,
                current_id=current_id,
                query=query,
                initial_filter=initial_filter,
            ),
            callback=lambda result: self._handle_harness_hub_result(result, items, log),
        )

    def _handle_harness_hub_result(
        self,
        result,
        items: list[HarnessPickerItem],
        log: ConversationLog,
    ) -> None:
        if result is None:
            self._ensure_input_focus()
            return
        action = str(getattr(result, "action", "") or "")
        if action == "build":
            self._handle_command(":connect build", log)
            return
        item_id = str(getattr(result, "item_id", "") or "")
        item = next((candidate for candidate in items if candidate.id == item_id), None)
        if item is None:
            self._present_outcome(
                Outcome(
                    title="Harness Hub",
                    summary="That catalog entry is no longer available",
                    severity=OutcomeSeverity.WARNING,
                    source=":hub",
                ),
                log=log,
            )
            return
        if action == "inspect":
            self._present_harness_hub_detail(item, log)
            return
        if action == "use":
            self._activate_harness_hub_item(item, log)

    def _present_harness_hub_detail(
        self,
        item: HarnessPickerItem,
        log: ConversationLog,
    ) -> None:
        record = hub_record(item, include_local_paths=True)
        status = readiness_label(record.readiness)
        details = [
            item.description,
            f"Status: {status}",
            f"Category: {item.group}",
            f"Runtime: {item.runtime or 'defined by harness'}",
            f"Continuity: {item.continuity.replace('-', ' ')}",
            f"Source: {item.source}",
        ]
        if item.provider or item.model:
            details.append(f"Model route: {item.provider}/{item.model}")
        if item.issue and not item.available:
            details.append(f"Setup: {item.issue}")
        if item.warning:
            details.append(f"Important: {item.warning}")
        if record.based_on:
            details.append(f"Based on: {record.based_on}")
        if record.tools:
            details.append(f"Tools: {', '.join(record.tools)}")
        if record.capabilities:
            details.append(f"Capabilities: {', '.join(record.capabilities)}")
        if record.support_note:
            details.append(f"SuperQode support: {record.support_note}")
        if record.docs_url:
            details.append(f"Documentation: {record.docs_url}")
        if record.homepage and record.homepage != record.docs_url:
            details.append(f"Official site: {record.homepage}")
        details.extend(f"Policy: {policy}" for policy in record.policies)
        if record.setup_steps:
            for index, step in enumerate(record.setup_steps, 1):
                instruction = f"{index}. {step.title}"
                if step.command:
                    instruction += f": {step.command}"
                if step.description:
                    instruction += f" — {step.description}"
                details.append(f"Setup: {instruction}")
        elif record.install_command:
            details.append(f"Setup: {record.install_command}")
        if record.tui_commands:
            details.append(f"TUI: {' · '.join(record.tui_commands)}")
        if record.cli_commands:
            details.append(f"CLI: {' · '.join(record.cli_commands)}")
        if record.eval_commands:
            details.append(f"Evaluate: {' · '.join(record.eval_commands)}")
        if record.optimize_commands:
            details.append(f"Optimize: {' · '.join(record.optimize_commands)}")
        unsupported = record.readiness == "not-supported"
        primary_command = record.tui_commands[0] if record.tui_commands else ""
        self._present_outcome(
            Outcome(
                title=item.display_name,
                summary="Harness Hub details",
                details=tuple(details),
                severity=(OutcomeSeverity.SUCCESS if item.available else OutcomeSeverity.WARNING),
                actions=(
                    ()
                    if unsupported or not primary_command
                    else (
                        OutcomeAction(
                            "use",
                            "Use" if item.available else "Set up",
                            primary_command,
                            primary=True,
                        ),
                    )
                ),
                source="Harness Hub",
            ),
            log=log,
            receipt=False,
        )

    def _activate_harness_hub_item(
        self,
        item: HarnessPickerItem,
        log: ConversationLog,
    ) -> None:
        """Reuse the proven picker activation and setup paths."""
        if item.kind in REFERENCE_ONLY_KINDS:
            self._present_harness_hub_detail(item, log)
            return
        self._harness_selection_list = [item]
        self._harness_highlighted_index = 0
        self._harness_include_all = True
        self._awaiting_harness_selection = True
        self.action_select_highlighted_harness()


__all__ = ["HarnessHubMixin"]
