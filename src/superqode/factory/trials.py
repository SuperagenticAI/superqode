"""Pinned paired Factory trials over the existing durable WorkOrder engine.

Preparation never calls models. Advancement never approves a human gate, signs
or applies a candidate. Scorecards are diagnostic, not promotion authority.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import io
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator

from .compiler import _compile_factory, compile_factory, materialize_snapshot, repository_revision
from .definition import FactoryDefinition, NAME, TEXT, obj, project_path, read_mapping
from .runtime import admit_factory, factory_store, validate_factory_order
from .snapshot import FactorySnapshot, canonical, digest, resolve_factory
from .versioning import source_path, _safe_text
from .verification import evaluator_contract, verify_factory
from superqode.harness.eval_workspace import manifest_digest
from superqode.workorders.models import WorkTaskStatus, COMPLETED_TASK_STATUSES
from superqode.workorders.usage import usage_from_artifacts

PREFIX = ".superqode/factory-trials"
FORMAT = "superqode.factory-trial-plan/1"
BUDGET = obj(
    {
        "max_seconds": {"type": "integer", "minimum": 10, "maximum": 7200},
        "max_tokens": {"type": "integer", "minimum": 1},
        "max_tool_calls": {"type": "integer", "minimum": 1},
        "max_cost_usd": {"type": "number", "exclusiveMinimum": 0},
    },
    ("max_seconds",),
)
SCHEMA = obj(
    {
        "format": {"const": "superqode.factory-trial-suite/1"},
        "name": NAME,
        "baseline": TEXT,
        "candidate": TEXT,
        "budget": BUDGET,
        "cases": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": obj(
                {
                    "id": NAME,
                    "goal": {"type": "string", "minLength": 1, "maxLength": 8000, "pattern": r"\S"},
                    "baseline": TEXT,
                    "candidate": TEXT,
                    "revision": {"type": "string", "pattern": "^([0-9a-f]{40}|[0-9a-f]{64})$"},
                    "split": {"enum": ["held-in", "held-out"]},
                },
                ("id", "goal"),
            ),
        },
    },
    ("format", "name", "baseline", "candidate", "budget", "cases"),
)


def parse_suite(text):
    if not isinstance(text, str):
        raise ValueError("Trial suite source must be YAML text")
    value = read_mapping(text)
    errors = list(Draft202012Validator(SCHEMA).iter_errors(value))
    if errors:
        raise ValueError("Invalid trial suite: " + errors[0].message)
    ids = [c["id"] for c in value["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Trial case identities must be unique")
    for key in ("max_seconds", "max_tokens", "max_tool_calls"):
        if key in value["budget"] and value["budget"][key] < 2 * len(ids):
            raise ValueError("Suite budget must allocate a positive limit to every paired run")
    from superqode.desktop_service.studio import _credentials

    _credentials(value)
    return value


def starter():
    return yaml.safe_dump(
        {
            "format": "superqode.factory-trial-suite/1",
            "name": "reference",
            "baseline": ".superqode/factory.yaml",
            "candidate": ".superqode/factory.yaml",
            "budget": {"max_seconds": 3600, "max_tokens": 120000, "max_tool_calls": 100},
            "cases": [
                {
                    "id": "first-case",
                    "goal": "Replace this with a representative application task and select Factory revisions with protected acceptance probes.",
                }
            ],
        },
        sort_keys=False,
    )


def folder(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"suite_[a-f0-9]{32}", identity):
        raise ValueError("Choose a prepared Factory trial suite")
    return project_path(Path(root).resolve(), PREFIX + "/" + identity)


def _read(path, maximum=8_000_000):
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > maximum
    ):
        raise ValueError("Missing, linked or oversized trial artifact")
    return path.read_text(encoding="utf-8")


def _save(path, value):
    from superqode.desktop_service.studio import _atomic

    _atomic(path, canonical(value))


def _git(root, *args, data=None):
    result = subprocess.run(
        [
            "git",
            "--literal-pathspecs",
            "-C",
            str(root),
            "-c",
            "core.hooksPath=.git/disabled-hooks",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        input=data,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise ValueError(
            "Trial Git operation failed: " + result.stderr.decode(errors="replace")[:1000]
        )
    return result.stdout


def _seed(root, revision):
    """Read bounded committed blobs, without export attributes, links or filters."""
    tree = _git(root, "ls-tree", "-rlz", "--full-tree", revision)
    if len(tree) > 2_000_000:
        raise ValueError("Trial fixture tree is too large")
    entries = []
    for record in tree.split(b"\0"):
        if not record:
            continue
        attributes, raw_path = record.split(b"\t", 1)
        mode, kind, token, size = attributes.decode().split()
        path = raw_path.decode()
        if path.startswith(".superqode/"):
            continue
        source_path(root, path)
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("Trial fixtures require regular committed files, without links")
        entries.append((path, mode, token, int(size)))
    if not entries or len(entries) > 2000 or sum(e[3] for e in entries) > 16_000_000:
        raise ValueError("Use a committed application fixture of at most 2,000 files and 16 MB")
    attrs = (
        _git(
            root,
            "check-attr",
            "-z",
            "--stdin",
            "filter",
            data=b"\0".join(e[0].encode() for e in entries) + b"\0",
        )
        .decode()
        .split("\0")
    )
    if any(v not in {"unspecified", "unset"} for v in attrs[2::3]):
        raise ValueError("Trial fixtures cannot use external Git filters")
    stream = io.BytesIO(
        _git(root, "cat-file", "--batch", data="".join(e[2] + "\n" for e in entries).encode())
    )
    result = {}
    for path, mode, token, size in entries:
        if stream.readline().decode().strip() != f"{token} blob {size}":
            raise ValueError("Committed fixture blob changed during preparation")
        content = stream.read(size)
        if len(content) != size or stream.read(1) != b"\n":
            raise ValueError("Incomplete committed fixture")
        result[path] = (content, 0o755 if mode == "100755" else 0o644)
    return result


def _fixture_manifest(root):
    """Bind every committed seed file, including tracked dependency/cache paths."""
    result = {}
    size = 0
    for path in root.rglob("*"):
        safe = project_path(root, path.relative_to(root).as_posix())
        info = safe.stat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Trial fixtures must contain only regular files")
        size += info.st_size
        if len(result) >= 2000 or size > 16_000_000:
            raise ValueError("Pinned trial fixture exceeds its size bound")
        result[path.relative_to(root).as_posix()] = {
            "sha256": hashlib.sha256(safe.read_bytes()).hexdigest(),
            "mode": stat.S_IMODE(info.st_mode),
        }
    return result


def _snapshot(root, reference):
    archive = re.fullmatch(r"\.superqode/factory-studio/revisions/([a-f0-9]{64})\.yaml", reference)
    pinned = re.fullmatch(r"\.superqode/factory/snapshots/([a-f0-9]{64})/snapshot\.json", reference)
    path = project_path(root, reference) if archive or pinned else source_path(root, reference)
    text = _read(path, 8_000_000 if path.suffix == ".json" else 250000)
    if archive and digest(text)[7:] != archive[1]:
        raise ValueError("Archived Factory revision changed")
    if path.suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Factory snapshot JSON must be an object")
        if data.get("format") == "superqode.factory-snapshot/1":
            snapshot = FactorySnapshot.from_dict(data)
            if pinned and snapshot.digest[7:] != pinned[1]:
                raise ValueError("Pinned Factory snapshot path does not match its digest")
            definition = (
                snapshot.payload["sources"].get(".superqode/factory.yaml", {}).get("text", "")
            )
            if read_mapping(definition) != snapshot.payload["definition"]:
                raise ValueError("Snapshot definition source does not match its contract")
            return snapshot
        if pinned:
            raise ValueError("Expected a resolved Factory snapshot")
    data = read_mapping(text)
    return resolve_factory(
        FactoryDefinition(root, root / ".superqode/factory.yaml", data), source_text=text
    )


def _paired(before, after, root, revision):
    first, second = before.payload, after.payload
    if first["definition"]["governance"] != second["definition"]["governance"]:
        raise ValueError("Paired trials must preserve governance, budgets and release authority")
    for payload in (first, second):
        for path, source in payload["sources"].items():
            source_path(root, path)
            _safe_text(path, source["text"])
        if any(a.get("model") for h in payload["harnesses"].values() for a in h["agents"]):
            raise ValueError("Trial models must be selected through Factory bindings")
    stripped = []
    for payload in (first, second):
        orchestration = deepcopy(payload["definition"]["orchestration"])
        for stage in orchestration["stages"]:
            stage.pop("goal", None)
            stage.pop("title", None)
        stripped.append(orchestration)
    if (
        stripped[0] != stripped[1]
        or first["definition"]["improvement"]["checks"]
        != second["definition"]["improvement"]["checks"]
    ):
        raise ValueError(
            "Paired trials must preserve workflow structure, roles, gates, permissions and acceptance checks"
        )
    plans = [
        _compile_factory(s, root=root, goal="Trial contract", revision=revision)
        for s in (before, after)
    ]
    if evaluator_contract(plans[0])[1] != evaluator_contract(plans[1])[1]:
        raise ValueError("Paired trials must pin identical protected evaluators")


def _narrow(snapshot, limits, count):
    payload = snapshot.payload
    budget = payload["definition"]["governance"]["budget"]
    budget["max_workers"] = 1
    for key, value in limits.items():
        share = (
            value
            if key == "max_seconds"
            else value / count
            if key == "max_cost_usd"
            else value // count
        )
        budget[key] = min(budget.get(key, share), share)
    text = yaml.safe_dump(payload["definition"], sort_keys=False)
    payload["sources"][".superqode/factory.yaml"] = {"text": text, "digest": digest(text)}
    return FactorySnapshot.from_dict({"digest": digest(canonical(payload)), **payload})


def prepare(root, *, suite_text):
    root = Path(root).resolve()
    suite = parse_suite(suite_text)
    revision = repository_revision(root)
    seed = _seed(root, revision)
    seeds = {revision: seed}
    snapshots = []
    for case in suite["cases"]:
        source_revision = case.get("revision", revision)
        if source_revision not in seeds:
            if _git(root, "cat-file", "-t", source_revision).strip() != b"commit":
                raise ValueError("Historical replay requires an available commit object")
            seeds[source_revision] = _seed(root, source_revision)
        pair = [
            _snapshot(root, case.get(variant, suite[variant]))
            for variant in ("baseline", "candidate")
        ]
        _paired(*pair, root, source_revision)
        snapshots.append(pair)
    identity = "suite_" + uuid4().hex
    directory = folder(root, identity)
    directory.mkdir(parents=True)
    try:
        fixture = directory / "fixture"
        fixture.mkdir()
        for path, (content, mode) in seed.items():
            target = project_path(fixture, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
        fixture_digest = manifest_digest(_fixture_manifest(fixture))
        case_fixtures = {}
        for source_revision, source_seed in seeds.items():
            if source_revision == revision:
                continue
            target_fixture = directory / ("fixture-" + source_revision)
            target_fixture.mkdir()
            for path, (content, mode) in source_seed.items():
                target = project_path(target_fixture, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(mode)
            case_fixtures[source_revision] = manifest_digest(_fixture_manifest(target_fixture))
        entries = []
        for case, pair in zip(suite["cases"], snapshots):
            source_revision = case.get("revision", revision)
            case_seed = seeds[source_revision]
            case_fixture = (
                fixture
                if source_revision == revision
                else directory / ("fixture-" + source_revision)
            )
            for variant, original in zip(("baseline", "candidate"), pair):
                snapshot = _narrow(original, suite["budget"], len(suite["cases"]) * 2)
                entry_id = case["id"] + "--" + variant
                project = directory / "projects" / entry_id
                shutil.copytree(case_fixture, project)
                for path, source in snapshot.payload["sources"].items():
                    if not path.startswith(".superqode/") and (
                        path not in case_seed or case_seed[path][0] != source["text"].encode()
                    ):
                        raise ValueError(
                            "Declared sources outside .superqode must match the committed application fixture"
                        )
                    target = project_path(project, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(source["text"], encoding="utf-8")
                _git(project, "init", "-q")
                _git(project, "config", "user.name", "SuperQode Factory Trial")
                _git(project, "config", "user.email", "factory-trial@example.invalid")
                _git(project, "config", "commit.gpgsign", "false")
                _git(project, "config", "core.hooksPath", ".git/disabled-hooks")
                (project / ".git/info/exclude").write_text(".superqode/\n")
                paths = sorted(set(case_seed) | set(snapshot.payload["sources"]))
                _git(
                    project,
                    "add",
                    "-f",
                    "--pathspec-from-file=-",
                    "--pathspec-file-nul",
                    data=b"\0".join(p.encode() for p in paths) + b"\0",
                )
                _git(project, "commit", "-qm", "Pin isolated Factory trial inputs")
                plan = compile_factory(snapshot, root=project, goal=case["goal"])
                materialize_snapshot(plan)
                order = admit_factory(
                    plan, request_id=identity + "-" + entry_id, actor="trial-suite"
                )
                entries.append(
                    {
                        "id": entry_id,
                        "case": case["id"],
                        "variant": variant,
                        "goal": case["goal"],
                        "source_revision": source_revision,
                        "split": case.get("split", "held-out"),
                        "project": project.relative_to(root).as_posix(),
                        "run": order.work_order_id,
                        "snapshot_digest": snapshot.digest,
                        "original_snapshot_digest": original.digest,
                        "budget": order.budget.to_dict(),
                        "revision": order.metadata["factory"]["repository_commit"],
                    }
                )
        plan = {
            "format": FORMAT,
            "id": identity,
            "repository": str(root),
            "suite": suite,
            "suite_digest": digest(suite_text),
            "revision": revision,
            "fixture_digest": fixture_digest,
            "case_fixtures": case_fixtures,
            "created": time.time(),
            "entries": entries,
        }
        plan["digest"] = digest(canonical(plan))
        _save(directory / "plan.json", plan)
        _save(directory / "state.json", {"started": None, "receipts": {}, "inflight": ""})
        return plan
    except BaseException:
        shutil.rmtree(directory)
        raise


def load(root, identity, expected=""):
    root = Path(root).resolve()
    directory = folder(root, identity)
    plan = json.loads(_read(directory / "plan.json"))
    token = plan.pop("digest", "")
    if (
        token != digest(canonical(plan))
        or (expected and expected != token)
        or plan.get("repository") != str(root)
        or plan.get("id") != identity
        or plan.get("format") != FORMAT
    ):
        raise ValueError("Trial plan digest or project mismatch")
    plan["digest"] = token
    parse_suite(yaml.safe_dump(plan["suite"]))
    for path in (directory / "fixture").rglob("*"):
        project_path(root, path.relative_to(root).as_posix())
    if manifest_digest(_fixture_manifest(directory / "fixture")) != plan["fixture_digest"]:
        raise ValueError("Pinned trial application fixture changed")
    for revision, expected_fixture in plan.get("case_fixtures", {}).items():
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
            raise ValueError("Invalid historical fixture revision")
        fixture = directory / ("fixture-" + revision)
        for path in fixture.rglob("*"):
            project_path(root, path.relative_to(root).as_posix())
        if manifest_digest(_fixture_manifest(fixture)) != expected_fixture:
            raise ValueError("Pinned historical application fixture changed")
    return plan


def _order(root, entry):
    project = project_path(Path(root).resolve(), entry["project"])
    store = factory_store(project)
    order = store.get(entry["run"])
    if (
        order.repository != str(project)
        or order.goal != entry["goal"]
        or order.metadata.get("factory", {}).get("snapshot_digest") != entry["snapshot_digest"]
        or order.metadata["factory"]["repository_commit"] != entry["revision"]
    ):
        raise ValueError("Trial WorkOrder differs from its pinned entry")
    plan = validate_factory_order(order, store=store)
    return project, store, order, plan


def _outcome(root, entry, receipt, verification_issue=""):
    project, store, order, compiled = _order(root, entry)
    events = store.events(entry["run"], limit=10000)
    row = {
        **entry,
        "status": "pending",
        "issues": [],
        "gates": [],
        "usage": usage_from_artifacts(order.artifacts).to_dict(),
        "tasks": [
            {"id": t.task_id, "status": t.status.value, "attempts": t.attempts} for t in order.tasks
        ],
        "operator_gate_decisions": sum(
            e.type in {"task.gate_approve", "task.gate_hold"} for e in events
        ),
        "operator_counts_truncated": len(events) == 10000,
    }
    for field, unknown in (
        ("total_tokens", "unknown_token_runs"),
        ("cost_usd", "unknown_cost_runs"),
        ("tool_calls", "unknown_tool_call_runs"),
    ):
        if row["usage"].get(unknown, 0):
            row["usage"][field] = None
    for task in order.tasks:
        if task.status == WorkTaskStatus.WAITING:
            row["gates"].append(
                {"stage": task.task_id, "digest": task.metadata.get("gate_digest", "")}
            )
    if row["gates"]:
        row["status"] = "waiting"
        return row
    if any(
        t.status in {WorkTaskStatus.FAILED, WorkTaskStatus.BLOCKED, WorkTaskStatus.CANCELLED}
        for t in order.tasks
    ):
        row.update(
            status="held",
            issues=[order.error or "A stage failed, was cancelled or requires recovery"],
        )
        return row
    if not receipt:
        if verification_issue:
            row.update(status="held", issues=[verification_issue])
        return row
    if not all(t.status in COMPLETED_TASK_STATUSES for t in order.tasks):
        raise ValueError("Trial receipt precedes completed workflow stages")
    artifact = next((a for a in order.artifacts if a.artifact_id == receipt["artifact"]), None)
    if (
        artifact is None
        or digest(artifact.content) != receipt["digest"]
        or artifact.digest != receipt["digest"]
    ):
        raise ValueError("Trial verification evidence changed")
    report = json.loads(artifact.content)
    binding = report["binding"]
    _, evaluators = evaluator_contract(compiled)
    current = order.metadata.get("factory_verification", {})
    expected_cases = [
        (name, case["id"])
        for name, rows in evaluator_contract(compiled)[0].items()
        for case in rows
    ]
    if (
        current.get("artifact_id") != artifact.artifact_id
        or current.get("binding") != binding
        or binding.get("factory_digest") != entry["snapshot_digest"]
        or binding.get("evaluators") != evaluators
        or [(r.get("check"), r.get("id")) for r in report["results"]] != expected_cases
    ):
        raise ValueError("Trial receipt does not match the pinned candidate and criteria")
    if (
        report.get("missing_evidence")
        or not report.get("isolation_applied")
        or any(r.get("kind") != "completed" for r in report["results"])
    ):
        row.update(
            status="held",
            issues=["Protected verification has missing execution or isolation evidence"],
        )
    else:
        row["status"] = (
            "passed" if all(r["status"] == "passed" for r in report["results"]) else "failed"
        )
    row["verification"] = {
        "artifact": artifact.artifact_id,
        "digest": artifact.digest,
        "passed": sum(r["status"] == "passed" for r in report["results"]),
        "total": len(report["results"]),
        "candidate_digest": binding["candidate_digest"],
    }
    return row


def scorecard(root, identity, expected=""):
    plan = load(root, identity, expected)
    directory = folder(root, identity)
    state = json.loads(_read(directory / "state.json"))
    rows = []
    for entry in plan["entries"]:
        try:
            rows.append(
                _outcome(
                    root,
                    entry,
                    state["receipts"].get(entry["id"]),
                    state.get("verification_errors", {}).get(entry["id"], ""),
                )
            )
        except (ValueError, OSError, KeyError) as exc:
            rows.append({**entry, "status": "held", "issues": [str(exc)], "gates": [], "usage": {}})
    summary = {}
    for variant in ("baseline", "candidate"):
        selected = [r for r in rows if r["variant"] == variant]
        usage = {}
        for field in ("total_tokens", "tool_calls", "cost_usd", "latency_ms"):
            values = [r["usage"].get(field) for r in selected]
            usage[field] = (
                sum(values)
                if all(type(v) in (int, float) and math.isfinite(v) for v in values)
                else None
            )
        summary[variant] = {
            "passed": sum(r["status"] == "passed" for r in selected),
            "total": len(selected),
            "usage": usage,
            "operator_gate_decisions": sum(r.get("operator_gate_decisions", 0) for r in selected),
            "by_split": {
                split: {
                    "passed": sum(
                        r["status"] == "passed"
                        for r in selected
                        if r.get("split", "held-out") == split
                    ),
                    "total": sum(r.get("split", "held-out") == split for r in selected),
                }
                for split in ("held-in", "held-out")
            },
        }
    issues = []
    limits = plan["suite"]["budget"]
    for key, field in (
        ("max_tokens", "total_tokens"),
        ("max_tool_calls", "tool_calls"),
        ("max_cost_usd", "cost_usd"),
    ):
        if key not in limits:
            continue
        values = [r["usage"].get(field) for r in rows]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            issues.append("Required aggregate usage is unknown: " + field)
        elif sum(values) > limits[key]:
            issues.append("Suite exceeded aggregate budget: " + field)
    finished = all(r["status"] in {"passed", "failed"} for r in rows)
    if (
        state.get("started")
        and (state.get("finished") or time.time()) - state["started"] > limits["max_seconds"]
    ):
        issues.append("Suite wall-time budget expired")
    regressions = [
        c["id"]
        for c in plan["suite"]["cases"]
        if next(r for r in rows if r["case"] == c["id"] and r["variant"] == "baseline")["status"]
        == "passed"
        and next(r for r in rows if r["case"] == c["id"] and r["variant"] == "candidate")["status"]
        == "failed"
    ]
    verdict = "incomplete"
    if finished and not issues:
        delta = summary["candidate"]["passed"] - summary["baseline"]["passed"]
        verdict = "regression" if regressions else "improved" if delta > 0 else "tie"
        distinct = any(
            next(
                e for e in plan["entries"] if e["case"] == case["id"] and e["variant"] == "baseline"
            )["original_snapshot_digest"]
            != next(
                e
                for e in plan["entries"]
                if e["case"] == case["id"] and e["variant"] == "candidate"
            )["original_snapshot_digest"]
            for case in plan["suite"]["cases"]
        )
        if not distinct and verdict != "tie":
            verdict = "variation"
    elif issues or any(r["status"] == "held" for r in rows):
        verdict = "hold"
    return {
        "plan": plan,
        "entries": rows,
        "summary": summary,
        "verdict": verdict,
        "issues": issues,
        "regressions": regressions,
        "complete": finished and not issues,
        "started": state.get("started"),
        "elapsed_seconds": max(0, (state.get("finished") or time.time()) - state["started"])
        if state.get("started")
        else 0,
        "promotion_authority": False,
        "release_authorization": False,
        "scope": "Descriptive paired application trials; not statistical reliability, sealed evaluation or production readiness",
    }


async def advance(root, identity, expected="", emit=None):
    from superqode.desktop_service.ownership import Lease
    from superqode.workorders.worker import WorkOrderWorker, WorkOrderWorkerConfig

    root = Path(root).resolve()
    plan = load(root, identity, expected)
    directory = folder(root, identity)
    lease = Lease(directory / "writer.lock")
    try:
        state = json.loads(_read(directory / "state.json"))
        state["started"] = state.get("started") or time.time()
        _save(directory / "state.json", state)
        for entry in plan["entries"]:
            board = scorecard(root, identity, plan["digest"])
            if board["issues"]:
                return board
            row = next(r for r in board["entries"] if r["id"] == entry["id"])
            if row["status"] in {"passed", "failed", "held"}:
                continue
            if row["status"] == "waiting":
                return board
            project, store, order, _ = _order(root, entry)
            if any(t.status == WorkTaskStatus.RUNNING for t in order.tasks):
                raise ValueError(
                    "A previous worker still owns a stage; inspect recovery before continuing"
                )
            state["inflight"] = entry["id"]
            _save(directory / "state.json", state)
            if emit:
                emit("stage", {"message": "Running " + entry["case"] + " / " + entry["variant"]})
            if not all(t.status in COMPLETED_TASK_STATUSES for t in order.tasks):
                worker = WorkOrderWorker(
                    store,
                    WorkOrderWorkerConfig(
                        worker_id="suite-" + uuid4().hex,
                        reference=entry["run"],
                        isolation="worktree",
                        once=True,
                        retry=False,
                    ),
                )
                await worker.run()
            order = store.get(entry["run"])
            if all(t.status in COMPLETED_TASK_STATUSES for t in order.tasks):
                try:
                    await asyncio.to_thread(verify_factory, entry["run"], root=project)
                except (ValueError, OSError) as exc:
                    state.setdefault("verification_errors", {})[entry["id"]] = str(exc)
                    state["inflight"] = ""
                    _save(directory / "state.json", state)
                    continue
                current = store.get(entry["run"])
                artifact_id = current.metadata["factory_verification"]["artifact_id"]
                artifact = next(a for a in current.artifacts if a.artifact_id == artifact_id)
                state["receipts"][entry["id"]] = {
                    "artifact": artifact_id,
                    "digest": digest(artifact.content),
                }
            state["inflight"] = ""
            _save(directory / "state.json", state)
            if any(t.status == WorkTaskStatus.WAITING for t in order.tasks):
                return scorecard(root, identity, plan["digest"])
        final = scorecard(root, identity, plan["digest"])
        if final["complete"] and not state.get("finished"):
            state["finished"] = time.time()
            _save(directory / "state.json", state)
        return final
    finally:
        lease.close()


def gate(root, identity, entry_id, stage, token, decision, reason=""):
    from superqode.desktop_service.ownership import Lease

    root = Path(root).resolve()
    plan = load(root, identity)
    entry = next((e for e in plan["entries"] if e["id"] == entry_id), None)
    if entry is None:
        raise ValueError("Choose an entry in this trial suite")
    lease = Lease(folder(root, identity) / "writer.lock")
    try:
        _, store, order, _ = _order(root, entry)
        store.decide_gate(
            entry["run"],
            stage,
            expected_digest=token,
            decision=decision,
            actor="trial-suite-operator",
            reason=reason,
        )
    finally:
        lease.close()
    return scorecard(root, identity)


def inspect_entry(root, identity, entry_id):
    root = Path(root).resolve()
    plan = load(root, identity)
    entry = next((e for e in plan["entries"] if e["id"] == entry_id), None)
    if entry is None:
        raise ValueError("Choose an entry in this trial suite")
    project, store, order, _ = _order(root, entry)
    workspace = next(
        (
            a
            for a in reversed(order.artifacts)
            if a.kind == "workspace" and a.metadata.get("scope") == "work-order"
        ),
        None,
    )
    patch = ""
    if workspace:
        path = project_path(root, Path(workspace.path).relative_to(root).as_posix())
        patch = _git(path, "diff", "--no-ext-diff", "--no-textconv", entry["revision"]).decode(
            errors="replace"
        )
        if len(patch.encode()) > 200000:
            raise ValueError("Trial patch is too large to review in Studio")
    return {
        "id": entry_id,
        "project": str(project),
        "run": entry["run"],
        "patch": patch,
        "tasks": [t.to_dict() for t in order.tasks],
        "handoffs": [
            {
                "task": a.task_id,
                "artifact": a.artifact_id,
                "digest": a.digest,
                "payload": json.loads(a.content),
            }
            for a in order.artifacts
            if a.kind == "factory_stage_output"
        ],
        "skipped": [
            {"task": t.task_id, "receipt": t.metadata.get("factory_skip_receipt")}
            for t in order.tasks
            if t.status == WorkTaskStatus.SKIPPED
        ],
        "evidence": [
            {
                "id": a.artifact_id,
                "kind": a.kind,
                "task": a.task_id,
                "content": a.content[:8000],
                "truncated": len(a.content) > 8000,
            }
            for a in order.artifacts[-30:]
        ],
        "history": [
            e.to_dict()
            for e in store.events(entry["run"], limit=10000)
            if e.type
            in {
                "task.failed",
                "task.retry_authorized",
                "task.recovery_blocked",
                "task.gate_approve",
                "task.gate_hold",
                "task.succeeded",
                "task.completed",
                "task.skipped",
            }
        ][-100:],
    }


def retry(root, identity, entry_id, stage, attempt, reason=""):
    from superqode.desktop_service.ownership import Lease

    root = Path(root).resolve()
    plan = load(root, identity)
    entry = next((e for e in plan["entries"] if e["id"] == entry_id), None)
    if entry is None:
        raise ValueError("Choose an entry in this trial suite")
    lease = Lease(folder(root, identity) / "writer.lock")
    try:
        board = scorecard(root, identity)
        if board["issues"]:
            raise ValueError("Resolve missing usage or expired suite budgets before retrying")
        _, store, order, _ = _order(root, entry)
        store.retry_failed_task(
            entry["run"],
            stage,
            expected_attempt=attempt,
            actor="trial-suite-operator",
            reason=reason,
        )
        path = folder(root, identity) / "state.json"
        state = json.loads(_read(path))
        state["receipts"].pop(entry_id, None)
        state.pop("finished", None)
        _save(path, state)
    finally:
        lease.close()
    return scorecard(root, identity)
