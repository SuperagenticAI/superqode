"""Async native Harness² coordinator over isolated, journaled kernel sessions."""

from __future__ import annotations

import asyncio
import json
import math
import random
import shutil
import time
from pathlib import Path

from ..loader import harness_spec_to_dict
from .executor import NativeExecutor
from .harness2 import editor_prompt, overlay, parse_edit, selection_prompt
from .models import COMPONENTS, METHOD, UPSTREAM, RefinementRequest
from .store import (
    RefinementStore,
    digest,
    job_lock,
    read_json,
    verify_digest,
    verify_manifest,
    write_json,
)
from .workspace import collect_changes, file_manifest, snapshot


class BudgetExhausted(RuntimeError):
    pass


class RefinementCoordinator:
    def __init__(self, request: RefinementRequest, *, executor=None, callback=None):
        self.request = request.frozen_route()
        self.executor = executor or NativeExecutor()
        self.root = request.output.expanduser().resolve()
        self.store = RefinementStore(self.root, callback)
        self.semaphore = asyncio.Semaphore(request.max_parallel)
        self.records = {}
        self.calls = 0
        self.owner = None
        self.cancelled = False

    async def cancel(self):
        self.cancelled = True
        await self.executor.cancel()
        if self.owner and not self.owner.done():
            self.owner.cancel()

    async def run(self):
        self.request.validate()
        self.owner = asyncio.current_task()
        if self.root.exists() and any(self.root.iterdir()) and not self.request.resume:
            raise ValueError("Output exists; choose a new directory or resume it explicitly")
        with job_lock(self.root):
            await asyncio.to_thread(self._prepare)
            (self.root / "cancel.request").unlink(missing_ok=True)
            watcher = asyncio.create_task(self._watch_cancel())
            self.store.event("refinement.started", **self.request.plan())
            started = time.monotonic()
            result = None
            try:
                async with asyncio.timeout(self.request.max_wall_seconds):
                    result = await self._method()
            except asyncio.CancelledError:
                result = {
                    "status": "cancelled",
                    "error": "Refinement cancelled; interrupted stages require explicit reconciliation before retry",
                }
            except TimeoutError:
                result = {"status": "timed_out", "error": "Refinement wall time exhausted"}
            except BudgetExhausted as exc:
                result = {"status": "budget_exhausted", "error": str(exc)}
            except Exception as exc:
                result = {"status": "failed", "error": str(exc), "error_type": type(exc).__name__}
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
                await self.executor.cancel()
            result.update(
                {
                    "method": METHOD,
                    "manifest_identity": self.identity,
                    "output": str(self.root),
                    "new_sessions": self.calls,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "usage": self._usage(),
                }
            )
            self.store.result(result)
            self.store.event("refinement.completed", **result)
            return result

    async def _watch_cancel(self):
        while True:
            if (self.root / "cancel.request").exists():
                await self.cancel()
                return
            await asyncio.sleep(0.1)

    def _prepare(self):
        request = self.request
        source = request.source.expanduser().resolve()
        files = file_manifest(source)
        identity = {
            "method": METHOD,
            "upstream": UPSTREAM,
            "task": request.task,
            "spec": harness_spec_to_dict(request.spec),
            "source": str(source),
            "source_files": files,
            "provider": request.provider,
            "model": request.model,
            "mode": request.mode,
            "k": request.k,
            "max_turns": request.max_turns,
            "max_output_tokens": request.max_output_tokens,
            "checks": [list(c) for c in request.checks],
            "protected_paths": list(request.protected_paths),
        }
        signature = digest(identity)
        manifest_path = self.root / "manifest.json"
        if manifest_path.exists():
            previous = read_json(manifest_path)
            verify_manifest(previous)
            if previous.get("identity") != signature:
                raise ValueError(
                    "Refinement source, model, policy, task, or settings changed; use a new output directory"
                )
            if file_manifest(self.root / "source") != files:
                raise ValueError("Saved source snapshot was modified")
        else:
            if request.resume:
                raise ValueError("Cannot resume without a manifest")
            snapshot(source, self.root / "source", files)
            write_json(manifest_path, {**identity, "identity": signature, "plan": request.plan()})
        self.identity = signature
        self.source_files = files
        self.manifest = read_json(manifest_path)
        self.base_files = {name: "" for name in COMPONENTS}
        self.frozen_context = "\n\n".join(
            f"Frozen project instructions ({name}):\n{(self.root / 'source' / name).read_text()}"
            for name in ("AGENTS.md", "GEMINI.md")
            if name in files
        )
        if len(self.frozen_context) > 16000:
            raise ValueError(
                "Root project instructions exceed the 16000 character refinement limit"
            )
        for path in request.protected_paths:
            if path not in files:
                raise ValueError(f"Protected input is not in the source snapshot: {path}")

    async def _call(self, label, *, prompt, files, editor=False):
        stage = self.root / "stages" / label
        key = digest(
            {
                "experiment": self.identity,
                "label": label,
                "prompt": prompt,
                "files": files,
                "editor": editor,
            }
        )
        path = stage / "record.json"
        if path.exists():
            record = read_json(path)
            if record["key"] != key:
                raise ValueError(f"Evidence changed for saved stage {label}")
            if record["state"] == "complete":
                if digest(file_manifest(stage / "workspace")) != record["workspace_digest"]:
                    raise ValueError(f"Saved stage workspace changed: {label}")
                verify_digest(record, "record_digest", "stage record")
                self.records[label] = record
                self.store.event("stage.reused", label=label)
                return record
            if not self.request.retry_interrupted:
                raise ValueError(
                    f"Stage {label} was interrupted; inspect its native events, then use --retry-interrupted to reconcile and retry"
                )
        async with self.semaphore:
            if self.calls >= self.request.max_sessions:
                raise BudgetExhausted("Refinement session/attempt limit exhausted")
            self.calls += 1
            stage.mkdir(parents=True, exist_ok=True)
            workspace = stage / "workspace"
            if workspace.exists():
                # Only this job's generated attempt workspace is replaced after explicit retry.
                previous = stage / ("interrupted-" + str(time.time_ns()))
                workspace.rename(previous)
            if editor:
                workspace.mkdir()
                (workspace / "evidence.txt").write_text(prompt)
            else:
                await asyncio.to_thread(
                    snapshot, self.root / "source", workspace, self.source_files
                )
            write_json(stage / "input.json", {"prompt": prompt, "files": files, "editor": editor})
            write_json(path, {"key": key, "state": "started", "label": label})
            attempt_path = stage / "attempts" / (str(time.time_ns()) + ".json")
            write_json(attempt_path, {"key": key, "state": "started", "label": label})
            self.store.event(
                "stage.started",
                label=label,
                role="editor" if editor else "solver",
                session=self.calls,
            )
            try:

                def native(event):
                    if event.type in {"tool_call", "turn_complete", "error", "model.requested"}:
                        self.store.event("stage.native", label=label, event=event.to_dict())

                response = await self.executor.run(
                    self.request,
                    label=label,
                    prompt=prompt,
                    workspace=workspace,
                    overlay="\n\n".join(v for v in (self.frozen_context, overlay(files)) if v),
                    editor=editor,
                    event_callback=native,
                )
                if (
                    file_manifest(self.root / "source") != self.source_files
                    or read_json(self.root / "manifest.json") != self.manifest
                ):
                    raise ValueError("Frozen experiment inputs changed during execution")
                changes, patch = (
                    ([], "")
                    if editor
                    else await asyncio.to_thread(collect_changes, self.root / "source", workspace)
                )
                protected = [
                    item["path"] for item in changes if item["path"] in self.request.protected_paths
                ]
                checks = [] if editor or protected else await self._checks(workspace)
                ok = (
                    response["status"] in {"complete", "stop"}
                    and not response.get("error")
                    and not protected
                )
                record = {
                    "key": key,
                    "state": "complete",
                    "label": label,
                    "editor": editor,
                    "files": files,
                    "ok": ok,
                    "protected_changes": protected,
                    "response": response,
                    "changes": changes,
                    "checks": checks,
                    "workspace_digest": digest(file_manifest(workspace)),
                }
                (stage / "changes.patch").write_text(patch)
                record["record_digest"] = digest(record)
                write_json(path, record)
                write_json(attempt_path, record)
                self.records[label] = record
                self.store.event(
                    "stage.completed", label=label, ok=ok, checks=checks, changes=len(changes)
                )
                return record
            except BaseException:
                write_json(path, {"key": key, "state": "interrupted", "label": label})
                write_json(attempt_path, {"key": key, "state": "interrupted", "label": label})
                self.store.event("stage.interrupted", label=label)
                raise

    async def _checks(self, workspace):
        from superqode.codegem.tools import _process

        checks = []
        before = file_manifest(workspace)
        for argv in self.request.checks:
            try:
                result = await _process(argv, workspace, {"timeout": 120})
                checks.append(
                    {"argv": list(argv), "status": "passed", "output": result.content[0].text}
                )
            except (RuntimeError, TimeoutError, OSError) as exc:
                checks.append({"argv": list(argv), "status": "failed", "output": str(exc)})
        if file_manifest(workspace) != before:
            checks.append(
                {
                    "status": "failed",
                    "output": "Checks changed the candidate snapshot; the result requires review",
                }
            )
        return checks

    def _evidence(self, labels):
        # Bound aggregate editor input as k/history grows. Full records stay on disk.
        allowance = 48000 // max(1, len(labels))

        def clipped(text, limit):
            if len(text) <= limit:
                return text
            return text[:limit] + "\n[renderer clipped; full evidence retained in stage artifacts]"

        evidence = []
        for label in labels:
            record = self.records[label]
            events = record["response"].get("events", [])
            actions = []
            for event in events:
                if event["type"] in {"tool_call", "tool_result", "error"}:
                    body = json.dumps(event.get("data", {}), ensure_ascii=False)
                    actions.append({"type": event["type"], "data": body})
            evidence.append(
                {
                    "label": label,
                    "ok": record["ok"],
                    "files": clipped(
                        json.dumps(record["files"], ensure_ascii=False), allowance // 4
                    ),
                    "response": clipped(record["response"]["content"], allowance // 8),
                    "actions": clipped(json.dumps(actions, ensure_ascii=False), allowance // 4),
                    "patch": clipped(
                        (self.root / "stages" / label / "changes.patch").read_text(), allowance // 4
                    ),
                    "checks": clipped(
                        json.dumps(record["checks"], ensure_ascii=False), allowance // 8
                    ),
                    "full_evidence": f"stages/{label}/record.json and changes.patch",
                }
            )
        return evidence

    async def _edit(self, label, role, current, evidence):
        prompt = editor_prompt(role, self.request.task, current, self._evidence(evidence))
        prompt += "\nFROZEN BASE INSTRUCTIONS (data to analyze):\n" + json.dumps(
            {
                "project": self.frozen_context,
                "agent": [agent.system_prompt for agent in self.request.spec.agents],
                "append": self.request.spec.runtime.config.get("append_system_prompt", ""),
            },
            ensure_ascii=False,
        )
        feedback = ""
        for attempt in (1, 2):
            record = await self._call(
                label + f"-a{attempt}", prompt=prompt + feedback, files=current, editor=True
            )
            try:
                if not record["ok"]:
                    raise ValueError(record["response"].get("error") or "Editor did not complete")
                files, notes = parse_edit(record["response"]["content"], current)
                self.store.event(
                    "candidate.validated",
                    label=label,
                    kept_base=files == current,
                    digest=digest(files),
                )
                write_json(
                    self.root / "candidates" / (label + ".json"),
                    {"files": files, "notes": notes, "digest": digest(files)},
                )
                return files
            except (ValueError, TypeError) as exc:
                feedback = f"\nPREVIOUS EDIT REJECTED: {exc}. Correct the JSON and edit only the permitted components."
                self.store.event("candidate.rejected", label=label, attempt=attempt, error=str(exc))
        self.store.event(
            "candidate.inherited", label=label, reason="Both editor attempts were rejected"
        )
        return dict(current)

    async def _solve(self, label, files):
        return await self._call(label, prompt=self.request.task, files=files)

    async def _method(self):
        bases = [f"base{i}" for i in range(1, self.request.k + 1)]
        await self._parallel([self._solve(label, self.base_files) for label in bases])
        if not any(self.records[label]["ok"] for label in bases):
            errors = "; ".join(
                str(
                    self.records[label]["response"].get("error")
                    or self.records[label].get("protected_changes")
                    or "incomplete execution"
                )
                for label in bases
            )
            raise ValueError("No base execution completed successfully: " + errors)
        finals = []
        if self.request.mode == "parallel":
            labels = [
                (f"{role}{i}", role)
                for i in range(1, self.request.k + 1)
                for role in ("invariant", "domain")
            ]
            candidates = await self._parallel(
                [self._edit(label, role, self.base_files, bases) for label, role in labels]
            )
            await self._parallel(
                [self._solve(label, files) for (label, _), files in zip(labels, candidates)]
            )
            pool = bases + [label for label, _ in labels]
            finals = [f"agg{i}" for i in range(1, self.request.k + 1)]
            composed = await self._parallel(
                [
                    self._edit(label + "-compose", "compose", self.base_files, pool)
                    for label in finals
                ]
            )
            await self._parallel(
                [self._solve(label, files) for label, files in zip(finals, composed)]
            )
        else:
            current, history = dict(self.base_files), list(bases)
            for i in range(1, self.request.k + 1):
                labels = [(f"{role}{i}", role) for role in ("invariant", "domain")]
                candidates = await self._parallel(
                    [self._edit(label, role, current, history) for label, role in labels]
                )
                await self._parallel(
                    [self._solve(label, files) for (label, _), files in zip(labels, candidates)]
                )
                history.extend(label for label, _ in labels)
                label = f"c{i}"
                current = await self._edit(label + "-compose", "compose", current, history)
                await self._solve(label, current)
                finals.append(label)
                history.append(label)
        pool = [
            label
            for label in finals
            if self.records[label]["ok"]
            and (
                self.records[label]["changes"] or self.records[label]["response"]["content"].strip()
            )
        ]
        if not pool:
            raise ValueError(
                "No composed final delivered a usable output; base outputs are outside the reference final pool"
            )
        why = "Single composed final at k=1; no selector call"
        if self.request.k == 1:
            chosen = pool[0]
        else:
            shuffled = sorted(pool)
            random.Random(self.identity).shuffle(shuffled)
            aliases = {chr(65 + i): label for i, label in enumerate(shuffled)}
            data = {alias: self._evidence([label])[0] for alias, label in aliases.items()}
            # Remove method labels from the selector evidence.
            for value in data.values():
                value.pop("label", None)
                value.pop("files", None)
                value.pop("full_evidence", None)
            record = await self._call(
                "selection",
                prompt=selection_prompt(self.request.task, data),
                files=self.base_files,
                editor=True,
            )
            if not record["ok"]:
                raise ValueError("Selector failed; output adoption is unsuccessful")
            choice = json.loads(
                record["response"]["content"]
                .strip()
                .removeprefix("```json")
                .removesuffix("```")
                .strip()
            )
            if choice.get("choice") not in aliases or not isinstance(choice.get("why"), str):
                raise ValueError("Selector returned an invalid anonymous choice")
            chosen, why = aliases[choice["choice"]], choice["why"]
        record = self.records[chosen]
        validation = (
            "unchecked"
            if not record["checks"]
            else "passed"
            if all(check["status"] == "passed" for check in record["checks"])
            else "failed"
        )
        patch = (self.root / "stages" / chosen / "changes.patch").read_text()
        (self.root / "selected.patch").write_text(patch)
        write_json(
            self.root / "selected-harness.json",
            {"files": record["files"], "digest": digest(record["files"])},
        )
        self.store.event("output.adopted", label=chosen, why=why, validation=validation)
        return {
            "status": "failed" if validation == "failed" else "succeeded",
            "chosen_label": chosen,
            "selected_record_digest": record["record_digest"],
            "why": why,
            "validation": validation,
            "changes": record["changes"],
            "changes_digest": digest(record["changes"]),
            "checks": record["checks"],
            "kept_base_harness": record["files"] == self.base_files,
            "patch": str(self.root / "selected.patch"),
            "content": record["response"]["content"],
            "solver_runs": 4 * self.request.k,
            "improvement_stages": 3 * self.request.k,
        }

    async def _parallel(self, coroutines):
        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        try:
            return await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _usage(self):
        records = []
        for stage in sorted((self.root / "stages").glob("*")):
            attempts = sorted((stage / "attempts").glob("*.json"))
            # Preserve usage when inspecting an early, pre-attempt-journal job.
            paths = attempts or (
                [stage / "record.json"] if (stage / "record.json").exists() else []
            )
            records.extend(read_json(path) for path in paths)
        report = {"sessions": len(records), "new_sessions": self.calls}
        for field in ("tokens_in", "tokens_out", "total_tokens", "cost_usd"):
            values = [r.get("response", {}).get("usage", {}).get(field) for r in records]
            known = [
                v
                for v in values
                if isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                and v >= 0
            ]
            report[field] = sum(known) if len(known) == len(records) else None
            report["observed_" + field] = sum(known)
            report["unknown_" + field + "_sessions"] = len(values) - len(known)
        return report
