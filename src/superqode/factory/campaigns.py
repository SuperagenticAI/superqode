"""Opted-in, finite experiment campaigns with durable event and budget fencing."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from superqode.desktop_service.ownership import Lease
from . import improvement as imp
from .compiler import repository_revision
from .definition import load_factory, project_path
from .operations import read, write
from .snapshot import canonical, digest, resolve_factory
from .versioning import source_path

PREFIX = ".superqode/factory-campaigns"
FORMAT = "superqode.factory-campaign/1"
METERED = ("max_tokens", "max_cost_usd", "max_tool_calls")


def directory(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"campaign_[0-9a-f]{32}", identity):
        raise ValueError("Choose a Factory experiment campaign")
    return project_path(Path(root).resolve(), PREFIX + "/" + identity)


def _load(root, identity, expected="", *, fresh=False):
    root = Path(root).resolve()
    folder = directory(root, identity)
    manifest = json.loads(read(folder / "manifest.json", 100000))
    token = manifest.pop("digest", "")
    if (
        token != digest(canonical(manifest))
        or (expected and expected != token)
        or manifest.get("format") != FORMAT
        or manifest.get("id") != identity
        or manifest.get("repository") != str(root)
    ):
        raise ValueError("Campaign identity or manifest digest changed")
    manifest["digest"] = token
    state = json.loads(read(folder / "state.json", 2000000))
    if state.get("manifest_digest") != token or not isinstance(state.get("events"), list):
        raise ValueError("Campaign state differs from its pinned manifest")
    if len(state["events"]) > 256 or len({e["id"] for e in state["events"]}) != len(
        state["events"]
    ):
        raise ValueError("Campaign event inventory is invalid")
    reserved = [e for e in state["events"] if e.get("reserved")]
    if len(reserved) > manifest["policy"]["max_experiments"]:
        raise ValueError("Campaign reservation count exceeds its policy")
    for event in reserved:
        if event.get("plan"):
            plan, _ = imp.load(root, event["plan"], event["plan_digest"])
            if any(plan["limits"].get(k) != manifest["reservation"][k] for k in METERED):
                raise ValueError("Child experiment widened its campaign reservation")
            if (
                event.get("usage_digest")
                and imp.budget(root, plan).summary()["digest"] != event["usage_digest"]
            ):
                raise ValueError("Recorded campaign usage changed")
    if fresh:
        current = resolve_factory(load_factory(root=root))
        if (
            current.digest != manifest["factory_digest"]
            or repository_revision(root) != manifest["revision"]
        ):
            raise ValueError("Factory or application changed; prepare a new campaign")
        experiment = manifest["policy"]["experiment"]
        if (
            digest(imp._read(source_path(root, experiment["tasks"]), 250000))
            != manifest["tasks_digest"]
        ):
            raise ValueError("Campaign evaluation criteria changed")
    return manifest, state


def _save(root, identity, state):
    write(directory(root, identity) / "state.json", canonical(state))


def create(root):
    """Pin one saved opt-in policy; creation never makes model requests."""
    root = Path(root).resolve()
    definition = load_factory(root=root)
    optimization = definition.data["improvement"].get("optimization", {})
    if not optimization.get("automatic_experiments"):
        raise ValueError("Save an explicit automatic_experiments opt-in and bounded policy first")
    policy = optimization["experiment_policy"]
    snapshot = resolve_factory(definition)
    revision = repository_revision(root)
    experiment = policy["experiment"]
    tasks_text, _ = imp._suite(source_path(root, experiment["tasks"]))
    reservation = {k: policy[k] / policy["max_experiments"] for k in METERED}
    for key in ("max_tokens", "max_tool_calls"):
        reservation[key] = int(reservation[key])
    identity = "campaign_" + uuid4().hex
    folder = directory(root, identity)
    folder.mkdir(parents=True, mode=0o700)
    manifest = {
        "format": FORMAT,
        "id": identity,
        "repository": str(root),
        "factory_digest": snapshot.digest,
        "revision": revision,
        "policy": policy,
        "reservation": reservation,
        "tasks_digest": digest(tasks_text),
        "created": time.time(),
        "adoption_authorized": False,
        "release_authorized": False,
    }
    manifest["digest"] = digest(canonical(manifest))
    write(folder / "manifest.json", canonical(manifest))
    _save(
        root,
        identity,
        {
            "manifest_digest": manifest["digest"],
            "events": [],
            "started": None,
            "last_started": None,
            "holds": 0,
            "status": "ready",
            "reason": "",
        },
    )
    return inspect(root, identity)


def _source(root, kind, source, expected, policy):
    if kind == "reviewed_failure":
        from .feedback import detail

        issue = detail(root, source)
        reviews = issue["reviews"]
        if (
            issue["review_digest"] != expected
            or not reviews
            or reviews[-1]["status"] != "reviewed"
            or reviews[-1]["category"] not in {"application_defect", "model_protocol"}
            or not any(o["source_valid"] for o in issue["observations"])
        ):
            raise ValueError(
                "Only a current source-verified and reviewed agent failure can trigger tuning"
            )
        return {"source": source, "digest": expected}
    if policy.get("event_sources", {}).get(kind) != source:
        raise ValueError("Event evidence must match the campaign's declared event source")
    raw = imp._read(project_path(Path(root).resolve(), source), 250000)
    if not isinstance(json.loads(raw), dict):
        raise ValueError("Event evidence must be a bounded JSON object")
    if not expected or digest(raw) != expected:
        raise ValueError("Event source changed; supply its exact content digest")
    return {"source": source, "digest": expected}


def enqueue(root, identity, *, expected, kind, key, source, source_digest, parent=""):
    """Admit a verified local event idempotently; no background models start."""
    folder = directory(root, identity)
    with _lease(folder):
        manifest, state = _load(root, identity, expected, fresh=True)
        if kind not in manifest["policy"]["triggers"]:
            raise ValueError("Trigger is not enabled by this campaign policy")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", key):
            raise ValueError("Provide a bounded event idempotency key")
        evidence = _source(root, kind, source, source_digest, manifest["policy"])
        fingerprint = digest(canonical({"kind": kind, **evidence}))
        existing = next(
            (e for e in state["events"] if e["key"] == key or key in e.get("aliases", [])), None
        )
        if existing:
            if existing["fingerprint"] != fingerprint or existing["parent"] != parent:
                raise ValueError("Event key already binds a different source")
            return {"event": existing, "deduplicated": True}
        existing = next((e for e in state["events"] if e["fingerprint"] == fingerprint), None)
        if existing:
            if len(existing.get("aliases", [])) >= 32:
                raise ValueError("Event reached its idempotency alias limit")
            existing.setdefault("aliases", []).append(key)
            _save(root, identity, state)
            return {"event": existing, "deduplicated": True}
        if state["status"] != "ready" or (folder / "stop.request").exists():
            raise ValueError("Campaign is stopped or held; no further triggers are admitted")
        if len(state["events"]) >= 256:
            raise ValueError("Campaign reached its event storage limit")
        depth = 0
        if parent:
            predecessor = next((e for e in state["events"] if e["id"] == parent), None)
            if predecessor is None:
                raise ValueError("Parent event is not part of this campaign")
            depth = predecessor["depth"] + 1
        if depth > manifest["policy"]["max_depth"]:
            raise ValueError("Recursive experiment trigger depth exceeded")
        event = {
            "id": "event_" + uuid4().hex,
            "key": key,
            "kind": kind,
            **evidence,
            "fingerprint": fingerprint,
            "parent": parent,
            "depth": depth,
            "status": "queued",
            "reserved": False,
            "at": time.time(),
        }
        state["events"].append(event)
        _save(root, identity, state)
        return {"event": event, "deduplicated": False}


class _lease:
    def __init__(self, folder):
        self.lease = Lease(folder / "writer.lock")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.lease.close()


def inspect(root, identity):
    manifest, state = _load(root, identity)
    totals = {"tokens": 0, "cost_usd": 0, "tool_calls": 0}
    for event in state["events"]:
        if event.get("plan"):
            plan, _ = imp.load(root, event["plan"], event["plan_digest"])
            summary = imp.budget(root, plan).summary()
            for key in totals:
                totals[key] += summary["accounted"][key]
    return {
        "manifest": manifest,
        "state": state,
        "observed": totals,
        "reserved_experiments": sum(bool(e["reserved"]) for e in state["events"]),
        "stop_requested": (directory(root, identity) / "stop.request").exists(),
        "adoption_authorized": False,
        "release_authorized": False,
    }


def preview_event(root, identity, *, expected, kind, source=""):
    manifest, _ = _load(root, identity, expected, fresh=True)
    policy = manifest["policy"]
    if kind not in policy["triggers"]:
        raise ValueError("Trigger is not enabled")
    if kind == "reviewed_failure":
        from .feedback import detail

        source_digest = detail(root, source)["review_digest"]
    else:
        source = policy.get("event_sources", {}).get(kind, "")
        source_digest = digest(imp._read(project_path(Path(root).resolve(), source), 250000))
    evidence = _source(root, kind, source, source_digest, policy)
    return {
        "kind": kind,
        **evidence,
        "key": "event-" + digest(canonical({"kind": kind, **evidence}))[7:31],
    }


def inventory(root):
    base = project_path(Path(root).resolve(), PREFIX)
    if not base.exists():
        return []
    folders = sorted(base.glob("campaign_*"))
    if len(folders) > 256:
        raise ValueError("Campaign inventory exceeds 256 entries")
    return [inspect(root, folder.name) for folder in folders]


def stop(root, identity, expected):
    """Request draining: active work stays bounded; no next experiment starts."""
    _load(root, identity, expected)
    target = directory(root, identity) / "stop.request"
    write(target, canonical({"manifest_digest": expected, "at": time.time()}))
    return {"id": identity, "stop_requested": True, "mode": "drain-current-action"}


def run_worker(root, identity, expected, *, live=False, poll_interval=1):
    """Automatically consume admitted events until the campaign's finite stop."""
    from .maintenance import execution

    if live is not True:
        raise ValueError("Use --live to enable the bounded campaign worker")
    if (
        type(poll_interval) not in {int, float}
        or not math.isfinite(poll_interval)
        or not 0.05 <= poll_interval <= 30
    ):
        raise ValueError("Choose a polling interval between 0.05 and 30 seconds")
    folder = directory(root, identity)
    worker = Lease(folder / "worker.lock")
    try:
        with execution(root):
            with _lease(folder):
                manifest, state = _load(root, identity, expected, fresh=True)
                if state["started"] is None:
                    state["started"] = time.time()
                    _save(root, identity, state)
                deadline = state["started"] + manifest["policy"]["max_seconds"]
            while time.time() < deadline:
                manifest, state = _load(root, identity, expected, fresh=True)
                if state["status"] != "ready" or (folder / "stop.request").exists():
                    return inspect(root, identity)
                if any(event["status"] == "running" for event in state["events"]):
                    raise ValueError(
                        "Interrupted campaign action is uncertain; worker will not replay it"
                    )
                ready = any(event["status"] == "queued" for event in state["events"])
                cooldown = (
                    state["last_started"] is not None
                    and time.time() - state["last_started"] < manifest["policy"]["cooldown_seconds"]
                )
                if ready and not cooldown:
                    advance(root, identity, expected, live=True)
                else:
                    time.sleep(min(poll_interval, max(0.001, deadline - time.time())))
            with _lease(folder):
                _, state = _load(root, identity, expected)
                state.update(status="exhausted", reason="Campaign worker's shared deadline expired")
                _save(root, identity, state)
            return inspect(root, identity)
    finally:
        worker.close()


def advance(root, identity, expected, *, live=False):
    """Advance one event using existing metered search and comparison only."""
    if live is not True:
        raise ValueError("Use --live to authorize this opted-in campaign's bounded inference")
    folder = directory(root, identity)
    with _lease(folder):
        manifest, state = _load(root, identity, expected, fresh=True)
        policy = manifest["policy"]
        if any(e["status"] == "running" for e in state["events"]):
            raise ValueError(
                "Interrupted campaign action is uncertain; never automatically replay it"
            )
        if state["status"] != "ready" or (folder / "stop.request").exists():
            raise ValueError("Campaign is stopped or held")
        reserved = sum(bool(e["reserved"]) for e in state["events"])
        if reserved >= policy["max_experiments"]:
            raise ValueError("Campaign exhausted its aggregate experiment reservation")
        event = next((e for e in state["events"] if e["status"] == "queued"), None)
        if event is None:
            return inspect(root, identity)
        _source(root, event["kind"], event["source"], event["digest"], policy)
        for previous in state["events"]:
            if previous.get("plan"):
                child, _ = imp.load(root, previous["plan"], previous["plan_digest"])
                summary = imp.budget(root, child).summary()
                if summary["issues"] or summary["pending_operations"]:
                    raise ValueError(
                        "Prior campaign usage is held or uncertain; no further admission"
                    )
        now = time.time()
        if (
            state["last_started"] is not None
            and now - state["last_started"] < policy["cooldown_seconds"]
        ):
            raise ValueError("Campaign trigger cooldown has not elapsed")
        state["started"] = state["started"] or now
        remaining = math.floor(state["started"] + policy["max_seconds"] - now)
        if remaining < 1:
            raise ValueError("Campaign's aggregate wall-time budget expired")
        event.update(status="running", reserved=True)
        state["last_started"] = now
        # Reserve before creating or executing anything; interruption cannot free a slot.
        _save(root, identity, state)
        try:
            options = {
                **policy["experiment"],
                "budget_limits": manifest["reservation"],
                "absolute_deadline": state["started"] + policy["max_seconds"],
            }
            options["max_seconds"] = min(options["max_seconds"], remaining)
            plan = imp.prepare(root, **options)
            event.update(plan=plan["id"], plan_digest=plan["digest"])
            _save(root, identity, state)
            result = imp.optimize(root, plan["id"], plan["digest"])
            event["search"] = result
            if (
                result.get("held")
                or not result.get("candidate")
                or (folder / "stop.request").exists()
            ):
                event.update(status="held", reason="Search held or drain requested")
            else:
                # One automatic final assessment per sealed suite+fixture across campaigns.
                seal = digest(
                    canonical(
                        {"tasks": plan["tasks_digest"], "fixture": plan["source_fixture_digest"]}
                    )
                )[7:]
                claim = project_path(Path(root).resolve(), PREFIX + "/heldout/" + seal + ".json")
                claim.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                try:
                    with claim.open("x") as stream:
                        stream.write(
                            canonical(
                                {
                                    "campaign": identity,
                                    "event": event["id"],
                                    "plan": plan["id"],
                                    "plan_digest": plan["digest"],
                                }
                            )
                        )
                except FileExistsError:
                    event.update(
                        status="held",
                        reason="Automatic held-out assessment already consumed; use fresh criteria",
                    )
                else:
                    comparison = asyncio.run(
                        imp.compare(root, plan["id"], result["candidate"], plan["digest"])
                    )
                    event["comparison"] = comparison
                    event["status"] = "awaiting_review" if comparison["eligible"] else "held"
            summary = imp.budget(root, plan).finalize()
            event["usage_digest"] = summary["digest"]
            if summary["issues"] or summary["pending_operations"]:
                state.update(status="held", reason="Experiment usage is held or uncertain")
        except BaseException:
            # Remain 'running': operator review is required even if no result was written.
            _save(root, identity, state)
            raise
        if event["status"] == "held":
            state["holds"] += 1
        state["status"] = (
            "held"
            if state["status"] == "held"
            else "awaiting_review"
            if event["status"] == "awaiting_review"
            else "held"
            if state["holds"] >= policy["stop_after_holds"]
            else "exhausted"
            if reserved + 1 >= policy["max_experiments"]
            else "ready"
        )
        _save(root, identity, state)
        return inspect(root, identity)
