"""Wire live supervision to existing runtime, approval and delivery contracts."""

from __future__ import annotations

import asyncio
import shlex
import sqlite3
import time
from pathlib import Path

from textual import on
from textual.widgets import Button

from superqode.app.supervision import (
    SupervisionEntry,
    SupervisionSnapshot,
    approval_entry,
    display_state,
    evidence_text,
    request_identity,
)
from superqode.app.widgets import ConversationLog


class SupervisionMixin:
    def _supervision_loop(self):
        pure = getattr(self, "_pure_mode", None)
        loop = getattr(pure, "_agent", None)
        if loop is None:
            loop = getattr(getattr(pure, "_runtime", None), "loop", None)
        if loop is None:
            session = getattr(pure, "_harness_session", None)
            loop = getattr(getattr(session, "_pending_runtime", None), "loop", None)
        return loop

    def _live_supervision(self):
        pure = getattr(self, "_pure_mode", None)
        loop = self._supervision_loop()
        manager = getattr(loop, "_peer_manager", None)
        peers = manager.list_agents() if manager is not None else []
        runs, approvals = [], []
        sid = ""
        if pure is not None:
            try:
                sid = pure.get_current_session_id() or ""
            except (AttributeError, RuntimeError):
                pass
            try:
                requests = pure.get_pending_approvals()
            except (AttributeError, RuntimeError):
                requests = []
            for request in requests:
                owner = f"{sid}:{id(pure)}:{id(getattr(pure, '_runtime', None))}:{id(getattr(pure, '_harness_session', None))}"
                approvals.append(approval_entry("pure", owner, "Main agent", request))
        if getattr(self, "_permission_pending", False):
            request = {
                "tool_name": getattr(self, "_pending_tool_name", "unknown"),
                "arguments": dict(getattr(self, "_pending_tool_input", {}) or {}),
                "approval_id": getattr(self, "_inline_approval_id", ""),
            }
            approvals.append(approval_entry("inline", sid, "Main agent", request))
        connected = bool(
            getattr(getattr(pure, "session", None), "connected", False)
            or getattr(self, "current_agent", "")
            or getattr(self, "is_busy", False)
        )
        if connected:
            state = "Waiting for approval" if approvals else "Running" if self.is_busy else "Idle"
            runtime = getattr(pure, "_runtime", None)
            codex_status = (
                getattr(runtime, "run_status", {})
                if getattr(runtime, "name", "") == "codex-cli"
                else {}
            )
            if codex_status:
                state = {
                    "active": "Running",
                    "idle": "Idle",
                    "systemError": "Failed",
                    "notLoaded": "Not loaded",
                }.get(codex_status.get("type"), state)
                if "waitingOnApproval" in codex_status.get("activeFlags", []):
                    state = "Waiting for approval"
            if getattr(self, "_awaiting_agent_question", False):
                state = "Waiting for answer"
            model = getattr(self, "current_model", "") or "Not reported"
            runtime = (
                getattr(pure, "runtime_name", "") or getattr(self, "current_agent", "") or "Core"
            )
            elapsed = (
                f"{max(0, time.time() - self._thinking_start):.1f}s"
                if self.is_busy and getattr(self, "_thinking_start", None)
                else "Not running"
            )
            runs.append(
                SupervisionEntry(
                    f"main:{sid}",
                    "◆ Main agent",
                    state,
                    f"Main agent\nState: {state}\nSession: {sid or 'Not reported'}\n"
                    f"Runtime: {runtime}\nModel: {model}\nElapsed: {elapsed}\n"
                    f"Queued messages: {len(getattr(self, '_typeahead_queue', []))}\n"
                    f"Current operation: {getattr(loop, '_supervision_operation', '') or 'Not reported'}\n"
                    f"Last activity: {getattr(loop, '_supervision_last_event', '') or 'Not reported'}\n\n"
                    "Use Activity for recorded outcomes and the transcript for the full conversation.\n"
                    "External routes expose only the telemetry they report.",
                    command=":activity",
                )
            )
        for peer in peers:
            target = str(peer["agent_id"])
            name = str(peer["task_name"])
            agent = manager.resolve(target)
            child_loop = getattr(agent, "loop", None)
            messages = getattr(child_loop, "_current_messages", []) or []
            transcript = "\n\n".join(
                f"{getattr(m, 'role', 'message')}: {getattr(m, 'content', '')}"
                for m in messages[-12:]
                if getattr(m, "role", "") in {"user", "assistant"}
            )
            config = getattr(child_loop, "config", None)
            runs.append(
                SupervisionEntry(
                    f"peer:{target}",
                    f"  ↳ {name}",
                    display_state(peer["status"]),
                    f"Child of main agent\nAgent: {name}\nSession: {peer['session_id']}\n"
                    f"State: {display_state(peer['status'])}\n"
                    f"Model: {getattr(config, 'model', '') or 'Not reported'}\n"
                    f"Queued messages: {peer['queued_inputs']}\n\n"
                    f"Current operation: {getattr(child_loop, '_supervision_operation', '') or 'Not reported'}\n"
                    f"Last activity: {getattr(child_loop, '_supervision_last_event', '') or 'Not reported'}\n\n"
                    + evidence_text(peer.get("last_result_preview") or "No completed result yet")
                    + "\n\nRecent user/assistant messages\n"
                    + evidence_text(transcript or "Not reported"),
                    source="peer",
                    target=target,
                )
            )
            for request in peer.get("pending_approvals", []):
                approvals.append(approval_entry("peer", target, name, request))
        return runs, approvals

    async def _load_supervision(self, store=None):
        runs, approvals = self._live_supervision()
        delivery = []
        for outcome in self._outcome_store().list():
            if outcome.source != "task":
                continue
            action = next((a.command for a in outcome.actions if a.command), "")
            delivery.append(
                SupervisionEntry(
                    outcome.id,
                    outcome.summary,
                    "Task finished · review evidence",
                    "Recorded task outcome\n"
                    + evidence_text("\n\n".join(outcome.details))
                    + "\n\nThis task outcome is not an approved WorkOrder integration candidate.",
                    command=action,
                )
            )
        from superqode.commands.work import DEFAULT_WORK_STORE

        path = Path(store or DEFAULT_WORK_STORE).expanduser().resolve()
        project = Path.cwd().resolve()
        notice = (
            "Live state refreshes every 2 seconds. Usage remains unavailable when not reported."
        )
        try:
            work_runs, work_delivery = await asyncio.to_thread(
                self._work_supervision, path, project
            )
            runs.extend(work_runs)
            delivery.extend(work_delivery)
            approvals.extend(
                row
                for row in work_delivery
                if row.state == "Ready for review" and row.request.get("needs_review")
            )
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            notice = f"WorkOrder state unavailable: {exc}"
        return SupervisionSnapshot(tuple(runs), tuple(approvals), tuple(delivery), notice)

    def _work_supervision(self, path, project):
        if not path.is_file():
            return [], []
        from superqode.workorders.store import WorkOrderStore
        from superqode.workorders.cockpit import build_cockpit_snapshot

        stat = path.stat()
        key = (path, stat.st_dev, stat.st_ino)
        cached = getattr(self, "_supervision_read_store", None)
        if cached is None or cached[0] != key:
            cached = (key, WorkOrderStore.read_only(path))
            self._supervision_read_store = cached
        store = cached[1]
        runs, delivery = [], []
        for order in store.list(limit=100):
            if Path(order.repository).resolve() != project:
                continue
            snapshot = build_cockpit_snapshot(store, order.work_order_id)
            target = order.work_order_id
            usage = snapshot["usage"]
            cost = (
                f"Reported subtotal ${usage['cost_usd']:.4f}; {usage['unknown_cost_runs']} run(s) unavailable"
                if usage.get("cost_reports")
                else "Not reported"
            )
            gates = snapshot["gates"]
            review = gates.get("decision") or {}
            detail = (
                f"WorkOrder: {target}\nGoal: {order.goal}\nState: {display_state(order.status.value)}\n"
                f"Candidate: {gates.get('candidate_id') or 'Not recorded'}\n"
                f"Checks: {gates.get('check_results', 0)} recorded\n"
                f"Review: {review.get('verdict') or 'Not recorded'}\n"
                f"Cost: {cost}\n\nRecorded evidence\n"
                + evidence_text(snapshot)
                + "\n\nOpen delivery to inspect candidate changes, checks and human review."
            )
            row = SupervisionEntry(
                f"work:{path}:{target}",
                f"◇ {target} · {order.goal}",
                display_state(order.status.value),
                detail,
                "workorder",
                target,
                store=str(path),
                request={"needs_review": not bool(snapshot["gates"].get("decision"))},
            )
            runs.append(row)
            delivery.append(row)
            for task in snapshot["tasks"]:
                runs.append(
                    SupervisionEntry(
                        f"{row.id}:{task['task_id']}",
                        f"  ↳ {task['title']}",
                        display_state(task["status"]),
                        f"WorkOrder: {target}\n" + evidence_text(task),
                        "workorder",
                        target,
                        store=str(path),
                    )
                )
        return runs, delivery

    def _open_supervision(self, section="runs", args=""):
        from superqode.widgets.run_overview import RunOverviewScreen

        tokens = shlex.split(args)
        store, reference = None, ""
        if "--store" in tokens:
            index = tokens.index("--store")
            if index + 1 >= len(tokens):
                raise ValueError("--store requires a path")
            store = tokens[index + 1]
            del tokens[index : index + 2]
        if len(tokens) > 1 or (tokens and tokens[0].startswith("--")):
            raise ValueError("Usage: :runs | :approvals | :delivery [WORK_ID] [--store PATH]")
        if tokens:
            reference = tokens[0]
        self.push_screen(
            RunOverviewScreen(
                lambda: self._load_supervision(store),
                self._supervision_action,
                section=section,
                reference=reference,
            ),
            callback=lambda _: self._ensure_input_focus(),
        )

    def action_run_overview(self):
        self._open_supervision()

    def _refresh_supervision_bar(self):
        from superqode.widgets.run_overview import SupervisionBar

        if not self.is_running:
            return
        runs, approvals = self._live_supervision()
        self.query_one(SupervisionBar).update_counts(
            len(runs) + len(getattr(self, "_supervision_work_runs", ())),
            len(approvals) + len(getattr(self, "_supervision_work_approvals", ())),
            len(getattr(self, "_typeahead_queue", [])),
        )

    async def _refresh_work_supervision_cache(self):
        if getattr(self, "_supervision_cache_loading", False):
            return
        self._supervision_cache_loading = True
        try:
            from superqode.commands.work import DEFAULT_WORK_STORE

            path = Path(DEFAULT_WORK_STORE).expanduser().resolve()
            runs, delivery = await asyncio.to_thread(
                self._work_supervision, path, Path.cwd().resolve()
            )
            self._supervision_work_runs = runs
            self._supervision_work_approvals = [
                row
                for row in delivery
                if row.state == "Ready for review" and row.request.get("needs_review")
            ]
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self._supervision_work_runs = ()
            self._supervision_work_approvals = ()
        finally:
            self._supervision_cache_loading = False
        if self.is_running:
            self._refresh_supervision_bar()

    @on(Button.Pressed, "SupervisionBar Button")
    def supervision_navigation(self, event):
        event.stop()
        section = event.button.id.removeprefix("supervision-")
        if section == "queue":
            self._handle_command(":queue", self.query_one("#log", ConversationLog))
        else:
            self._open_supervision(section)

    async def _supervision_action(self, action, row):
        log = self.query_one("#log", ConversationLog)
        if action == "open":
            if row.source == "workorder":
                self._open_work_inspector(
                    f"view {shlex.quote(row.target)} --store {shlex.quote(row.store)}",
                    log,
                    section="delivery",
                )
            elif row.command:
                self._handle_command(row.command, log)
            return "Opened recorded evidence."
        if action not in {"approve", "reject"}:
            raise ValueError("Unknown supervision action")
        _, current = self._live_supervision()
        match = next((item for item in current if item.id == row.id), None)
        if match is None:
            return "This request expired or changed. Inspect the current request before deciding."
        if row.id in getattr(self, "_supervision_resolving", set()):
            return "This request is already being resolved."
        if not hasattr(self, "_supervision_resolving"):
            self._supervision_resolving = set()
        self._supervision_resolving.add(row.id)
        root_resolution = row.source == "pure"
        was_busy = getattr(self, "is_busy", False)
        if root_resolution and was_busy:
            self._supervision_resolving.discard(row.id)
            return "The main agent is running. Wait for it to pause before resolving this request."
        try:
            pure = getattr(self, "_pure_mode", None)
            if row.source == "inline":
                self._handle_permission_input("y" if action == "approve" else "n")
                result = "Allowed once" if action == "approve" else "Rejected"
            elif row.source == "peer":
                manager = self._supervision_loop()._peer_manager
                requests = manager.resolve(row.target).pending_approvals
                index = self._request_index(row, requests)
                response = await (
                    manager.approve(row.target, index=index, always=False)
                    if action == "approve"
                    else manager.reject(row.target, index=index, always=False)
                )
                result = evidence_text(response.get("result") or response.get("status"))
            else:
                index = self._request_index(row, pure.get_pending_approvals())
                self.is_busy = True
                response = await (
                    pure.approve_and_resume(index=index, always=False)
                    if action == "approve"
                    else pure.reject_and_resume(index=index, always=False)
                )
                result = evidence_text(
                    response.error or response.content or response.stopped_reason
                )
                if response.stopped_reason == "needs_approval":
                    self._announce_pending_approvals(pure, log)
            log.add_info(f"{action.capitalize()} · {row.label}: {result}")
            from superqode.app.outcomes import Outcome

            self._outcome_store().add(
                Outcome(
                    "Approval decision",
                    f"{action.capitalize()} · {row.label}",
                    (f"Scope: once · Request: {row.id}", result),
                    source="approval",
                )
            )
            self._refresh_supervision_bar()
            return result
        finally:
            if root_resolution:
                self.is_busy = was_busy
            self._supervision_resolving.discard(row.id)

    @staticmethod
    def _request_index(row, requests):
        for index, request in enumerate(requests):
            if request_identity(row.source, row.target, request) == row.id:
                return index
        raise RuntimeError("Request changed before approval. Inspect it again.")
