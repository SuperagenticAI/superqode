"""Live WorkOrder evidence/recovery inspection over the existing local store."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Select, Static, TextArea
from textual.widgets.option_list import Option

from superqode.workorders.inspection import (
    inspect_work_order,
    read_inspected_evidence,
    inspected_diff,
)
from .panel_shortcuts import PanelShortcutMixin, PanelShortcuts


class WorkOrderInspector(PanelShortcutMixin, ModalScreen[list[str] | None]):
    BINDINGS = [
        Binding("escape", "close", "Back", priority=True),
        Binding("r", "reload", "Refresh"),
    ]
    CSS = """
    WorkOrderInspector { align: center middle; }
    #work-inspector { width: 96%; height: 94%; background: #0a0a0a; border: round #7c3aed; padding: 0 1; }
    #work-title { height: 1; color: #a855f7; text-style: bold; }
    #work-selectors { height: 3; }
    #work-selectors Select { width: 1fr; }
    #work-rows { height: 6; max-height: 30%; }
    #work-detail { height: 1fr; }
    #work-notice { height: 2; color: #a1a1aa; }
    #work-reason { height: 3; display: none; }
    #work-actions { height: 6; }
    #work-controls, #work-navigation { height: 3; }
    #work-controls Button { width: 14; min-width: 14; }
    #work-navigation Button { min-width: 12; width: 1fr; }
    #work-operation { width: 1fr; min-width: 12; }
    """

    def __init__(
        self, path: Path, reference: str, *, on_action=None, worker_running=None, lease_seconds=300
    ):
        super().__init__()
        self.path, self.reference = path, reference
        self.lease_seconds = lease_seconds
        self.on_action = on_action
        self.worker_running = worker_running or (lambda: False)
        self.snapshot = {}
        self.rows = []
        self._loading = False
        self._page = None
        self._reading = False
        self._generation = 0
        self._inspected_digest = ""
        self._inspected_id = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="work-inspector"):
            yield Static("WorkOrder · loading…", id="work-title")
            with Horizontal(id="work-selectors"):
                yield Select(
                    [(v, v.lower()) for v in ("Overview", "Evidence", "Recovery", "Review")],
                    value="overview",
                    allow_blank=False,
                    id="work-section",
                )
                yield Select([], prompt="Task", id="work-task")
            yield OptionList(id="work-rows")
            yield TextArea("Loading committed state…", read_only=True, id="work-detail")
            yield Static(
                "Recovery and context settings are unchanged by inspection.", id="work-notice"
            )
            yield Input(placeholder="Reason for approving this exact candidate", id="work-reason")
            with Vertical(id="work-actions"):
                with Horizontal(id="work-controls"):
                    yield Select(
                        [
                            (label, action)
                            for label, action in (
                                ("Queue work", "queue"),
                                ("Run ready tasks", "run"),
                                ("Recover stale leases", "recover"),
                                ("Resume blocked work", "resume"),
                                ("Prepare candidate", "prepare"),
                                ("Acceptance checks", "check"),
                            )
                        ],
                        value="run",
                        allow_blank=False,
                        id="work-operation",
                    )
                    yield Button("Execute", id="work-execute")
                    yield Button("Interrupt", id="work-interrupt", disabled=True)
                with Horizontal(id="work-navigation"):
                    yield Button("Refresh", id="work-refresh")
                    yield Button("Open", id="work-open", disabled=True)
                    yield Button("Next page", id="work-next", disabled=True)
                    yield Button("Approve…", id="work-approve", disabled=True)
                    yield Button("Back", id="work-back")
            yield PanelShortcuts(
                {
                    "work-rows": "↑↓ Select · Enter Inspect · Tab Actions · Esc Back",
                    "work-detail": "↑↓ Scroll · Tab Actions · Esc Back",
                },
                "Tab Next control · Esc Back",
            )

    def on_mount(self):
        self.call_after_refresh(self.reload)
        self.set_interval(2, self.reload)
        self.query_one("#work-rows", OptionList).focus()

    def on_resize(self, event):
        if self.is_mounted:
            self.query_one("#work-rows", OptionList).styles.height = (
                3 if event.size.height < 30 else 6
            )

    def _notice(self, text):
        self.query_one("#work-notice", Static).update(Text(text))

    async def reload(self):
        if self._loading or not self.is_mounted:
            return
        self._loading = True
        try:
            task = self.query_one("#work-task", Select).value
            snapshot = await asyncio.to_thread(
                inspect_work_order,
                self.path,
                self.reference,
                task_id=str(task) if task is not Select.BLANK else "",
            )
            if not self.is_mounted:
                return
            previous_tasks = [(t["title"], t["task_id"]) for t in self.snapshot.get("tasks", [])]
            if snapshot["gates"].get("candidate_id") != self.snapshot.get("gates", {}).get(
                "candidate_id"
            ):
                self._inspected_digest = ""
                self.query_one("#work-reason", Input).value = ""
                self.query_one("#work-reason", Input).display = False
                self.query_one("#work-rows", OptionList).display = True
            self.snapshot = snapshot
            options = [(t["title"], t["task_id"]) for t in snapshot["tasks"]]
            selector = self.query_one("#work-task", Select)
            if options != previous_tasks:
                selector.set_options(options)
                selector.value = snapshot["selected_task"] or Select.BLANK
            self.query_one("#work-title", Static).update(
                Text(
                    f"{snapshot['work_order_id']} · {snapshot['status'].upper()} · {snapshot['goal']}",
                    no_wrap=True,
                    overflow="ellipsis",
                )
            )
            self._render_rows()
        except Exception:
            self._notice("WorkOrder unavailable. Check the store path and current project policy.")
        finally:
            self._loading = False

    def _render_rows(self):
        section = self.query_one("#work-section", Select).value
        s = self.snapshot
        if not s:
            return
        old_row = self._selected()
        old_key = (
            self._row_key(old_row) if getattr(self, "_rendered_section", None) == section else None
        )
        self._rendered_section = section
        if section == "overview":
            self.rows = [
                (f"{t['task_id']} · {t['status']} · after {', '.join(t['dependencies']) or '—'}", t)
                for t in s["tasks"]
            ]
            self.rows.append(("Acceptance and approval", s["gates"]))
            self.rows.append(
                (
                    "Budget and usage",
                    {"budget": s["budget"], "usage": s["usage"], "policy": s["policy"]},
                )
            )
            self.rows.extend((f"Event · {e['type']}", e) for e in s["events"])
        elif section == "evidence":
            self.rows = [
                (
                    f"{e['task_id']} → {s['selected_task']} · {e['freshness']} · {e['verification']}",
                    e,
                )
                for e in s["evidence"]
            ]
        elif section == "recovery":
            self.rows = [
                (f"{r['state']} · {r['task_id']} · {r['operation']}", r) for r in s["recovery"]
            ]
        else:
            self.rows = [
                (f"{a['kind']} · {a.get('task_id') or 'WorkOrder'}", a) for a in s["review"]
            ]
        listing = self.query_one("#work-rows", OptionList)
        old = listing.highlighted or 0
        # Avoid replacing the selected page or resetting scroll on every tick.
        signature = json.dumps(
            [
                (label, {k: v for k, v in row.items() if k != "lease_remaining_seconds"})
                for label, row in self.rows
            ],
            sort_keys=True,
        )
        if signature != getattr(self, "_row_signature", ""):
            self._row_signature = signature
            listing.clear_options()
            listing.add_options(
                Option(Text(label), id=str(i)) for i, (label, _) in enumerate(self.rows)
            )
            restored = next(
                (
                    i
                    for i, (_, row) in enumerate(self.rows)
                    if old_key and self._row_key(row) == old_key
                ),
                min(old, len(self.rows) - 1),
            )
            listing.highlighted = restored if self.rows else None
            self._show_selected()
        approved = s["gates"].get("decision")
        can_approve = bool(
            self._inspected_digest
            and self._inspected_digest == s["gates"].get("candidate_digest")
            and self._inspected_id == s["gates"].get("candidate_id")
            and not approved
            and s["status"] == "ready_to_merge"
        )
        self.query_one("#work-approve", Button).disabled = not can_approve
        operation = self.query_one("#work-operation", Select).value
        permitted = {
            "queue": s["status"] == "draft",
            "run": s["status"] in {"queued", "running"},
            "recover": any(t["status"] == "running" for t in s["tasks"]),
            "resume": s["status"] == "blocked",
            "prepare": bool(s["tasks"]) and all(t["status"] == "succeeded" for t in s["tasks"]),
            "check": s["status"] in {"reviewing", "checking", "ready_to_merge", "blocked"},
        }
        running = self.worker_running()
        self.query_one("#work-execute", Button).disabled = running or not permitted.get(
            operation, False
        )
        self.query_one("#work-interrupt", Button).disabled = not running
        if running:
            self._notice(
                "Worker running. Interrupt stops this process; unknown side effects require reconciliation."
            )

    @staticmethod
    def _row_key(row):
        if row:
            for key in ("artifact_id", "reference", "invocation_id", "sequence", "task_id"):
                if row.get(key):
                    return key, row[key]
        return None

    def _selected(self):
        index = self.query_one("#work-rows", OptionList).highlighted
        return self.rows[index][1] if index is not None and index < len(self.rows) else None

    def _show_selected(self):
        self._generation += 1
        self._page = None
        row = self._selected()
        section = getattr(self, "_rendered_section", "overview")
        description = {
            "evidence": "Freshness describes sources. Reported findings still need verification.\n\n",
            "recovery": "Committed ≠ reused. Retry eligibility still requires current policy, workspace and ownership checks. Private outcomes are not displayed.\n\n",
            "review": "Acceptance checks and human approval apply to the current candidate.\n\n",
        }.get(section, "")
        detail = description + self._detail(row, section)
        self.query_one("#work-detail", TextArea).load_text(detail)
        self.query_one("#work-open", Button).disabled = not bool(
            row and (row.get("reference") or row.get("kind") == "integration_candidate")
        )
        self.query_one("#work-next", Button).disabled = True

    def _detail(self, row, section):
        if not row:
            return "No records for this section/task."
        if section == "overview" and "task_id" in row and "title" in row:
            return (
                f"{row['title']} ({row['task_id']})\n"
                f"State: {row['status']} · role: {row['role']}\n"
                f"Depends on: {', '.join(row['dependencies']) or 'none'}\n"
                f"Attempts: {row['attempts']}/{row['max_attempts']} · worker: {row['worker_id'] or 'unclaimed'}\n"
                f"Run: {row['run_id'] or 'none'}\n"
                f"{row['error'] or ''}"
            )
        if section == "overview" and "acceptance_tests" in row:
            return (
                "Acceptance commands\n"
                + "\n".join(row["acceptance_tests"])
                + f"\n\nLast checks: {'passed' if row['last_check_passed'] else 'not passed'}\n"
                f"Candidate: {row['candidate_id'] or 'not prepared'}\n"
                f"Human decision: {row['decision'] or 'pending'}"
            )
        if section == "evidence":
            return (
                f"Predecessor: {row['task_id']} → {self.snapshot['selected_task']}\n"
                f"Sources: {row['freshness']}\nVerification: {row['verification']}\n"
                f"Reference: {row['reference']}\n\n"
                "Open retrieves a bounded page under current policy.\n"
                + str(row.get("preview") or row.get("summary") or "")[:4000]
            )
        if section == "recovery":
            detail = (
                f"{row['state'].upper()}\n{row['operation']}\n"
                f"Task: {row['task_id']} · invocation: {row['invocation_id']}\n"
                f"Attempt: {row['attempt']} · worker: {row['worker_id']}\n"
                f"Reuse admissions: {row['reuse_count']}\n"
                f"Declared replay safe: {bool(row['replay_safe'])}\n"
            )
            if row["state"] == "reconcile needed":
                detail += "\nStop the old worker and verify the external effect. Record its verified result or explicitly authorize retry with :work reconcile; then resume."
            elif row["state"] == "retry eligible":
                detail += "\nRecover the stale lease, then run ready work. Current ownership, workspace, configuration and policy are rechecked."
            return detail
        if section == "review":
            if row["kind"] == "check_result":
                try:
                    results = json.loads(row["content"])
                    return "\n\n".join(
                        f"{r.get('status', 'unknown').upper()} · {r.get('command', '')}\n{r.get('stdout', '')}\n{r.get('stderr', '')}"
                        for r in results
                    )[:16000]
                except (ValueError, TypeError, AttributeError):
                    pass
            return (
                f"{row['kind']} · {row['artifact_id']}\n"
                f"Digest: {row['digest'] or 'none'}\n\n{row['content']}\n"
                + (
                    "Preview truncated. Open the complete candidate before approval."
                    if row.get("content_truncated")
                    else ""
                )
            )
        return json.dumps(row, indent=2, ensure_ascii=False)[:16000]

    @on(Select.Changed)
    async def selection_changed(self, event):
        if not self.snapshot:
            return
        if event.select.id == "work-task":
            await self.reload()
        else:
            self._row_signature = ""
            self._render_rows()

    @on(OptionList.OptionHighlighted, "#work-rows")
    def highlighted(self):
        self._show_selected()

    @on(OptionList.OptionSelected, "#work-rows")
    def inspect_selected(self):
        self.query_one("#work-detail", TextArea).focus()

    async def _open(self, *, next_page=False):
        row = self._selected()
        if not row or self._reading:
            return
        self._reading = True
        generation = self._generation
        try:
            if row.get("reference"):
                offset = self._page.next_offset if next_page and self._page else 0
                page = await asyncio.to_thread(
                    read_inspected_evidence,
                    self.path,
                    self.reference,
                    self.snapshot["selected_task"],
                    row["reference"],
                    offset=offset,
                )
                detail = f"Characters {page.offset}–{page.next_offset} of {page.total_chars}\n\n{page.text}"
            else:
                page = None
                detail, digest, candidate_id, complete = await asyncio.to_thread(
                    inspected_diff, self.path, self.reference
                )
            if generation != self._generation or not self.is_mounted:
                return
            self._page = page
            if page is None:
                self._inspected_digest = digest if complete else ""
                self._inspected_id = candidate_id if complete else ""
                self._render_rows()
                self._notice(
                    "Candidate opened. Run acceptance checks before approving."
                    if complete
                    else "Candidate exceeds the preview limit; use the CLI to review and approve it."
                )
            self.query_one("#work-detail", TextArea).load_text(detail)
            self.query_one("#work-next", Button).disabled = page is None or page.eof
        except Exception:
            self._page = None
            self.query_one("#work-next", Button).disabled = True
            self.query_one("#work-detail", TextArea).load_text(
                "Evidence unavailable or denied under current policy."
            )
        finally:
            self._reading = False

    @on(Button.Pressed)
    async def button_pressed(self, event):
        event.stop()
        action = event.button.id.removeprefix("work-")
        if action == "back":
            self.dismiss(None)
        elif action == "refresh":
            await self.reload()
        elif action in {"open", "next"}:
            await self._open(next_page=action == "next")
        elif action == "approve":
            if (
                not self._inspected_digest
                or self._inspected_digest != self.snapshot["gates"].get("candidate_digest")
                or self._inspected_id != self.snapshot["gates"].get("candidate_id")
            ):
                self._notice("Open the current candidate diff before approving.")
                return
            reason = self.query_one("#work-reason", Input)
            if not reason.display:
                reason.display = True
                self.query_one("#work-rows", OptionList).display = False
                reason.focus()
                self._notice(
                    "Enter your review reason, then click Approve again. Approval does not merge."
                )
                return
            if not reason.value.strip():
                self._notice("A human review reason is required.")
                return
            digest = self._inspected_digest
            self._dispatch(
                [
                    "work",
                    "--store",
                    str(self.path),
                    "approve",
                    self.reference,
                    "--actor",
                    "tui-human",
                    "--reason",
                    reason.value.strip(),
                    "--candidate-digest",
                    digest,
                    "--candidate-id",
                    self._inspected_id,
                ]
            )
        elif action == "execute":
            operation = self.query_one("#work-operation", Select).value
            parts = ["work", "--store", str(self.path), str(operation), self.reference]
            if operation == "run":
                parts.extend(["--lease", str(self.lease_seconds)])
            self._dispatch(parts)
        elif action == "interrupt":
            self._dispatch(["interrupt"])

    def _dispatch(self, parts):
        if self.on_action:
            self.on_action(parts)
        else:
            self.dismiss(parts)

    async def action_reload(self):
        await self.reload()

    def action_close(self):
        self.dismiss(None)


def parse_inspector_args(args, default_store):
    tokens = shlex.split(args)
    if not tokens or tokens[0] != "view":
        return None
    usage = "Usage: :work view WORK_ID [--store PATH] [--lease SECONDS]"
    if len(tokens) < 2 or len(tokens) % 2:
        raise ValueError(usage)
    options = {}
    for flag, value in zip(tokens[2::2], tokens[3::2]):
        if flag not in {"--store", "--lease"} or flag in options:
            raise ValueError(usage)
        options[flag] = value
    try:
        lease = int(options.get("--lease", "300"))
        if lease < 1:
            raise ValueError(usage)
    except ValueError as exc:
        raise ValueError(usage) from exc
    return Path(options.get("--store", default_store)).expanduser().resolve(), tokens[1], lease
