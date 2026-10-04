"""Host-owned A2A execution for the RLM's sole Python tool.

Admission is durable before network dispatch. Unknown sends are never replayed.
A handle carries only a local ID; credentials and results remain on the host.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import os
import math
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from .delegation_policy import DelegationPolicy
from .delegation_store import DelegationStore, TERMINAL


class DelegationManager:
    def __init__(
        self,
        *,
        root: str,
        store: DelegationStore,
        policy: DelegationPolicy,
        client_factory=None,
        source_root: str | Path | None = None,
    ):
        self.root, self.store, self.policy = root, store, policy
        self.client_factory = client_factory
        self.source_root = str(source_root or "")
        self.source_revision = ""
        if self.source_root:
            import subprocess

            try:
                revision = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=self.source_root,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if revision.returncode == 0:
                    self.source_revision = revision.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._trackers: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def inventory(self):
        return self.policy.inventory()

    def _client(self, peer):
        token = os.environ.get(peer.credential_env, "") if peer.credential_env else ""
        if peer.credential_env and not token:
            raise PermissionError("Configured A2A credential is unavailable on this host")
        if self.client_factory:
            return self.client_factory(peer)
        from superqode.a2a.client import A2AClient

        return A2AClient(
            peer.url,
            bearer_token=token or None,
            strict_origin=True,
            timeout=self.policy.request_timeout,
            max_response_bytes=self.policy.max_result_bytes,
            subscription_method=peer.subscription_method,
        )

    def _peer_for(self, record):
        peer = self.policy.peer(record["peer"])
        if peer.url != record["endpoint"] or peer.credential_env != record["credential_ref"]:
            raise PermissionError("A2A route changed since admission; reconcile the original peer")
        return peer

    def snapshot(self, owner, identifier):
        value = self.store.get(self.root, owner, identifier)
        self._peer_for(value)
        return self._public_record(value)

    @staticmethod
    def _public_record(value):
        return {k: v for k, v in value.items() if k not in {"result", "credential_ref", "endpoint"}}

    async def recover(self, owner):
        for record in self.store.records(self.root, None if owner == "root" else owner):
            if record["state"] == "admitting" and record["owner"] == owner:
                self.store.update(
                    record,
                    "unknown",
                    state="unknown",
                    error="Interrupted send; remote acceptance must be reconciled",
                )
            elif record.get("task_id") and record["state"] not in TERMINAL:
                self._track(record["owner"], record["id"])
        if owner == "root" and self.policy.enabled:
            self._trackers["<root-scan>"] = asyncio.create_task(self._scan())

    async def start(
        self,
        owner,
        *,
        peer,
        task,
        context="",
        required=True,
        deadline_seconds=None,
        request_id=None,
        context_id=None,
    ):
        selected = self.policy.peer(str(peer))
        if not isinstance(required, bool) or not isinstance(task, str) or not task.strip():
            raise ValueError("A2A task must be nonempty text and required must be a boolean")
        if not isinstance(context, (str, dict, list)):
            raise ValueError("Export context as bounded text or JSON with source provenance")
        bundle = context if isinstance(context, str) else json.dumps(context, sort_keys=True)
        body = f"{task}\n\nSelected context:\n{bundle}" if bundle else task
        if len(body.encode()) > self.policy.max_payload_bytes:
            raise ValueError("A2A context bundle exceeds the payload allowance")
        seconds = self.policy.deadline_seconds if deadline_seconds is None else deadline_seconds
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or not 0 < seconds <= self.policy.deadline_seconds
        ):
            raise ValueError("A2A deadline exceeds host policy")
        # Resolve credentials and discover before intent: neither executes work.
        client = self._client(selected)
        try:
            card = await asyncio.wait_for(client.get_agent_card(), self.policy.request_timeout)
            if selected.skill and selected.skill not in {s.id for s in card.skills}:
                raise PermissionError("Configured A2A skill is not advertised by this peer")
            identity = request_id or uuid4().hex
            if not isinstance(identity, str) or not identity or len(identity) > 512:
                raise ValueError("A2A request_id must contain 1–512 characters")
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "task": task,
                        "context": context,
                        "peer": asdict(selected),
                        "required": required,
                        "deadline": seconds,
                        "context_id": context_id,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            from .capabilities import check_admission

            check_admission()
            record, admitted = self.store.admit(
                self.root,
                owner,
                identity,
                fingerprint,
                self.policy,
                selected,
                {
                    "peer": selected.name,
                    "endpoint": selected.url,
                    "credential_ref": selected.credential_env,
                    "binding": getattr(client, "_binding", None),
                    "version": getattr(client, "_protocol_version", None),
                    "interface_url": getattr(client, "_interface_url", None) or selected.url,
                    "required": required,
                    "deadline": time.time() + seconds,
                    "bundle_sha256": hashlib.sha256(bundle.encode()).hexdigest(),
                    "source_root": self.source_root,
                    "source_revision": self.source_revision,
                    "task_id": None,
                    "context_id": context_id,
                },
            )
            if admitted:
                try:
                    result = await asyncio.wait_for(
                        client.send_message(
                            body,
                            session_id=context_id,
                            message_id=record["message_id"],
                            nonblocking=True,
                            metadata={
                                "superqodeSkill": selected.skill,
                                "superqodeDelegationId": record["id"],
                                "superqodeRootId": hashlib.sha256(self.root.encode()).hexdigest(),
                                "superqodeRequired": required,
                                **(
                                    {
                                        "superqodeBudgetVersion": 1,
                                        "superqodeMaxCredits": selected.credits,
                                    }
                                    if selected.hosted
                                    else {}
                                ),
                            },
                        ),
                        min(seconds, self.policy.request_timeout),
                    )
                    record = self._save_result(record, result)
                except BaseException as error:
                    self.store.update(
                        record,
                        "unknown",
                        state="unknown",
                        error="Send outcome unknown; do not resubmit without reconciliation",
                    )
                    # Caller cancellation does not imply a remote cancellation.
                    if isinstance(error, asyncio.CancelledError):
                        raise
            if record.get("task_id") and record["state"] not in TERMINAL:
                self._track(owner, record["id"])
            return {
                "__rlm__": "delegation",
                "id": record["id"],
                "status": self.snapshot(owner, record["id"]),
            }
        finally:
            await client.close()

    def _save_result(self, record, result):
        from superqode.a2a.types import Message

        data = asdict(result)
        if len(json.dumps(data).encode()) > self.policy.max_result_bytes:
            raise ValueError("A2A result exceeds the result allowance")
        direct = isinstance(result, Message)
        state = "completed" if direct else result.status.state.value
        return self.store.update(
            record,
            "observed",
            state=state,
            task_id=record.get("task_id") if direct else result.task_id,
            context_id=result.context_id or record.get("context_id"),
            response_kind="message" if direct else "task",
            result=data,
            result_sha256=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            error="",
            usage=record.get("usage"),
            usage_source="unknown",
        )

    async def poll(self, owner, identifier):
        async with self._locks.setdefault(identifier, asyncio.Lock()):
            record = self.store.get(self.root, owner, identifier)
            if record["state"] in TERMINAL or not record.get("task_id"):
                return self.snapshot(owner, identifier)
            peer = self._peer_for(record)
            client = self._client(peer)
            try:
                await self._pin_interface(client, record)
                result = await asyncio.wait_for(
                    client.get_task(record["task_id"]), self.policy.request_timeout
                )
                self._save_result(record, result)
            finally:
                await client.close()
        return self.snapshot(owner, identifier)

    @staticmethod
    async def _pin_interface(client, record):
        # Reopening a handle never trusts a newly advertised interface. Saved
        # binding/version/URL are transport identity, not card display names.
        client._interface_url = record.get("interface_url") or record["endpoint"]
        client._binding = record.get("binding") or "JSONRPC"
        client._protocol_version = record.get("version") or "1.0"

    async def wait(self, owner, identifier, timeout=20):
        if (
            not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 <= timeout <= 300
        ):
            raise ValueError("A2A wait timeout must be between 0 and 300 seconds")
        end = time.monotonic() + timeout
        while True:
            snapshot = self.snapshot(owner, identifier)
            if (
                snapshot["state"] in TERMINAL
                or time.monotonic() >= end
                or snapshot["state"] in {"unknown", "input_required", "auth_required"}
            ):
                return snapshot
            try:
                await asyncio.wait_for(
                    self.poll(owner, identifier), max(0.001, end - time.monotonic())
                )
            except TimeoutError:
                return self.snapshot(owner, identifier)
            await asyncio.sleep(min(self.policy.poll_seconds, max(0, end - time.monotonic())))

    async def cancel(self, owner, identifier):
        async with self._locks.setdefault(identifier, asyncio.Lock()):
            record = self.store.get(self.root, owner, identifier)
            if record["state"] in TERMINAL:
                return self.snapshot(owner, identifier)
            peer = self._peer_for(record)
            record = self.store.update(record, "cancel_requested", state="cancel_requested")
            if not record.get("task_id"):
                return self.snapshot(owner, identifier)
            client = self._client(peer)
            try:
                await self._pin_interface(client, record)
                result = await asyncio.wait_for(
                    client.cancel_task(record["task_id"]), self.policy.request_timeout
                )
                self._save_result(record, result)
            except Exception:
                self.store.update(
                    record, "cancel_unconfirmed", error="Remote cancellation is unconfirmed"
                )
            finally:
                await client.close()
            return self.snapshot(owner, identifier)

    async def reply(self, owner, identifier, message):
        async with self._locks.setdefault(identifier, asyncio.Lock()):
            record = self.store.get(self.root, owner, identifier)
            if record["state"] != "input_required" or not record.get("task_id"):
                raise ValueError(
                    "Reply requires an active task awaiting input; use follow_up after completion"
                )
            if (
                not isinstance(message, str)
                or not message.strip()
                or len(message.encode()) > self.policy.max_payload_bytes
            ):
                raise ValueError("A2A reply exceeds payload policy or is empty")
            if time.time() >= record["deadline"]:
                raise PermissionError("A2A task admission deadline expired")
            client = self._client(self._peer_for(record))
            record = self.store.update(
                record, "reply_intent", state="admitting", message_id=uuid4().hex
            )
            try:
                await self._pin_interface(client, record)
                result = await asyncio.wait_for(
                    client.send_message(
                        message,
                        session_id=record["context_id"],
                        task_id=record["task_id"],
                        message_id=record["message_id"],
                        nonblocking=True,
                    ),
                    self.policy.request_timeout,
                )
                self._save_result(record, result)
            except BaseException:
                self.store.update(
                    record,
                    "unknown",
                    state="unknown",
                    error="Reply outcome unknown; reconcile before retry",
                )
                raise
            finally:
                await client.close()
            return self.snapshot(owner, identifier)

    async def follow_up(self, owner, identifier, task, **kwargs):
        record = self.store.get(self.root, owner, identifier)
        if record["state"] not in TERMINAL:
            raise ValueError("Follow-up work requires a terminal task")
        return await self.start(
            owner, peer=record["peer"], task=task, context_id=record.get("context_id"), **kwargs
        )

    def read(self, owner, identifier, artifact=None, start=0, size=4000):
        record = self.store.get(self.root, owner, identifier)
        self._peer_for(record)
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start < 0
            or not isinstance(size, int)
            or not 0 <= size <= 20000
        ):
            raise ValueError(
                "Artifact slices require a nonnegative offset and at most 20,000 characters"
            )
        result = record.get("result") or {}
        if artifact is not None:
            matches = [
                a
                for a in result.get("artifacts", [])
                if artifact in {a.get("artifact_id"), a.get("name")}
            ]
            if not matches:
                raise KeyError("Unknown A2A artifact")
            parts = [p for a in matches for p in a.get("parts", [])]
        else:
            parts = result.get("parts", []) or [
                p for a in result.get("artifacts", []) for p in a.get("parts", [])
            ]
            if not parts:
                parts = [
                    p
                    for m in result.get("history", [])
                    if m.get("role") == "agent"
                    for p in m.get("parts", [])
                ]
        text = "\n".join(
            p.get("text")
            or (json.dumps(p["data"], sort_keys=True) if p.get("data") is not None else "")
            for p in parts
        )
        if not text:
            text = str((result.get("status") or {}).get("message") or "")
        return text[start : start + size]

    async def dispatch(self, owner, name, payload):
        if name == "a2a.peers":
            return self.inventory()
        if name == "a2a.start":
            return await self.start(owner, **payload)
        if name == "a2a.tasks":
            return [self.snapshot(owner, r["id"]) for r in self.store.records(self.root, owner)]
        identifier = str(payload.get("id") or "")
        if name == "a2a.status":
            return self.snapshot(owner, identifier)
        if name == "a2a.read":
            return self.read(
                owner,
                identifier,
                payload.get("artifact"),
                payload.get("start", 0),
                payload.get("size", 4000),
            )
        if name == "a2a.poll":
            return await self.poll(owner, identifier)
        if name == "a2a.wait":
            return await self.wait(owner, identifier, payload.get("timeout", 20))
        if name == "a2a.cancel":
            return await self.cancel(owner, identifier)
        if name == "a2a.reply":
            return await self.reply(owner, identifier, payload.get("message"))
        if name == "a2a.follow_up":
            return await self.follow_up(
                owner, identifier, payload["task"], request_id=payload.get("request_id")
            )
        raise ValueError(f"Unsupported A2A host operation: {name}")

    def completion_errors(self, owner=None):
        return [
            f"Required A2A task {r['id']} is {r['state']}"
            for r in self.store.records(self.root, owner)
            if r.get("required", True) and r["state"] != "completed"
        ]

    def evidence(self):
        return [
            {
                **self._public_record(r),
                "artifacts": (r.get("result") or {}).get("artifacts", []),
                "response": r.get("result"),
                "verification": "remote_unverified",
            }
            for r in self.store.records(self.root)
        ]

    def _track(self, owner, identifier):
        if identifier not in self._trackers or self._trackers[identifier].done():
            self._trackers[identifier] = asyncio.create_task(self._tracking(owner, identifier))

    async def _scan(self):
        while True:
            for record in self.store.records(self.root):
                if (
                    record.get("task_id")
                    and record["state"] not in TERMINAL
                    and record["state"] != "unknown"
                    and time.time() < record["deadline"]
                ):
                    self._track(record["owner"], record["id"])
            await asyncio.sleep(self.policy.poll_seconds)

    async def _tracking(self, owner, identifier):
        while True:
            record = self.store.get(self.root, owner, identifier)
            if record["state"] in TERMINAL or record["state"] == "unknown":
                return
            if time.time() >= record["deadline"]:
                self.store.update(
                    record, "deadline", error="Local deadline expired; remote work may still run"
                )
                return
            try:
                await self.poll(owner, identifier)
            except Exception:
                # Tracking never resubmits. A temporary read failure preserves
                # the last observation and the admitted reservation.
                pass
            await asyncio.sleep(self.policy.poll_seconds)

    async def close(self):
        for task in self._trackers.values():
            task.cancel()
        await asyncio.gather(*self._trackers.values(), return_exceptions=True)
        self._trackers.clear()

    async def cancel_required(self):
        for record in self.store.records(self.root):
            if record.get("required", True) and record["state"] not in TERMINAL:
                await self.cancel(record["owner"], record["id"])

    def reconcile(self, owner, identifier, *, task_id, reason):
        """Operator attaches a verified remote ID; never performs a resend."""
        record = self.store.get(self.root, owner, identifier)
        if record["state"] not in {"admitting", "unknown", "cancel_requested"}:
            raise ValueError("Only an uncertain submission can be reconciled")
        if not isinstance(task_id, str) or not task_id.strip() or not str(reason).strip():
            raise ValueError("A verified task ID and reconciliation reason are required")
        return self.store.update(
            record,
            "reconciled",
            task_id=task_id,
            state="submitted",
            reconciliation_reason=reason,
            error="",
        )
