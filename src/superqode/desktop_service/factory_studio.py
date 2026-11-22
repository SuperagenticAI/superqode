"""Native Factory Studio RPCs over shared definitions and durable WorkOrders."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import time

import yaml

from superqode.factory import (
    load_factory,
    resolve_factory,
    compile_factory,
    materialize_snapshot,
    admit_factory,
)
from superqode.factory.definition import (
    FactoryDefinition,
    LAYERS,
    read_mapping,
    validate_definition,
    project_path,
)
from superqode.factory.templates import factory_template
from superqode.factory.runtime import factory_store, validate_factory_order
from superqode.factory.snapshot import canonical, digest
from .studio import sha, file_digest, _credentials, _atomic


def _target(root):
    return project_path(root, ".superqode/factory.yaml")


def _text(path):
    if path.stat().st_size > 250000:
        raise ValueError("Factory definition exceeds 250 KB")
    return path.read_text(encoding="utf-8")


def _parse(root, text):
    data = read_mapping(text)
    validate_definition(data)
    _credentials(data)
    return data, resolve_factory(FactoryDefinition(root, _target(root), data), source_text=text)


def _ensure(service):
    service._write(
        "CREATE TABLE IF NOT EXISTS factory_studio_reviews(id TEXT PRIMARY KEY,project TEXT,payload TEXT,created REAL)"
    )


def _source_review(service, params):
    rows = service._all(
        "SELECT payload,created FROM factory_source_reviews WHERE id=? AND project=?",
        (params.get("source_review"), params["project"]),
    )
    if not rows or time.time() - rows[0]["created"] > 1800:
        raise ValueError("Refresh the Factory source review; it is missing or expired")
    value = json.loads(rows[0]["payload"])
    if value["digest"] != params.get("source_digest"):
        raise ValueError("Factory source review changed; refresh before committing")
    return value


def _review(service, params):
    rows = service._all(
        "SELECT payload,created FROM factory_studio_reviews WHERE id=? AND project=?",
        (params.get("review"), params["project"]),
    )
    if not rows or time.time() - rows[0]["created"] > 1800:
        raise ValueError("Validate this factory again; its review is missing or expired")
    value = json.loads(rows[0]["payload"])
    if value["digest"] != params.get("digest"):
        raise ValueError("Factory changed after validation")
    return value


def handle(service, method, params):
    root = service.project(params["project"])
    _ensure(service)
    target = _target(root)
    if method.startswith("factory.export."):
        from superqode.factory import portable

        if method == "factory.export.preview":
            return portable.preview(root)
        if method != "factory.export.create":
            raise ValueError("Unknown Factory export action")
        if params.get("confirmed") is not True:
            raise ValueError("Confirm exporting the reviewed Factory sources")
        from .ownership import Lease, project_lease_path
        from .ship import assert_idle

        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                return portable.create(root, expected=params["digest"])
            finally:
                lease.close()
    if method == "factory.evidence.trace":
        from superqode.factory.evidence import trace

        return trace(root, params["run"])
    if method == "factory.evidence.outcomes":
        from superqode.factory.evidence import outcomes

        return outcomes(root)
    if method == "factory.intake.receipts":
        from superqode.factory.intake import receipts

        return receipts(root)
    if method == "factory.evidence.record-outcome":
        from superqode.factory.evidence import record_outcome

        if params.get("confirmed") is not True:
            raise ValueError("Confirm recording the attributed outcome")
        return record_outcome(
            root,
            params["run"],
            observation=params["observation"],
            outcome=params["outcome"],
            human_minutes=params.get("human_minutes"),
            actor="desktop",
        )
    if method == "factory.verifier.draft":
        from superqode.factory.verifiers import draft

        return draft(root, params["checks"], yaml_text=params.get("yaml"))
    if method == "factory.verifier.install":
        from superqode.factory.verifiers import install
        from .ship import assert_idle

        with service.lock:
            assert_idle(service, params["project"])
            return install(
                root,
                params["proposal"],
                expected=params["digest"],
                confirmed=params.get("confirmed"),
            )
    if method.startswith("factory.operations."):
        from .factory_operations import handle as handle_operations

        return handle_operations(service, root, method, params)
    if method.startswith("factory.campaign."):
        from .factory_campaigns import handle as handle_campaigns

        return handle_campaigns(service, root, method, params)
    if method == "factory.workflow.experiment":
        if params.get("confirmed") is not True:
            raise ValueError("Explicitly create the unmeasured workflow experiment")
        from .ship import assert_idle
        from .ownership import Lease, project_lease_path
        from superqode.factory.workflow import experiment

        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                return experiment(
                    root,
                    stage=params["stage"],
                    goal=params["goal"],
                    work_goal=params["work_goal"],
                    expected_snapshot=params["snapshot_digest"],
                )
            finally:
                lease.close()
    if method.startswith("factory.suite."):
        from .factory_trials import handle as handle_trials

        return handle_trials(service, root, method, params)
    if method.startswith("factory.improvement."):
        return _improvement(service, root, method, params)
    if method == "factory.source.inspect":
        from superqode.factory.versioning import inspect_sources

        value = inspect_sources(root)
        created = time.time()
        service._write("DELETE FROM factory_source_reviews WHERE created<?", (created - 1800,))
        identity = sha(params["project"] + value["digest"] + str(created))
        service._write(
            "INSERT INTO factory_source_reviews VALUES(?,?,?,?)",
            (identity, params["project"], json.dumps(value), created),
        )
        return {**value, "review": identity}
    if method == "factory.open":
        current = _text(target) if target.is_file() else ""
        if params.get("template"):
            data = factory_template(params["template"])
            if current:
                existing = read_mapping(current)
                for key in ("default_route", "routes"):
                    if key in existing:
                        data[key] = existing[key]
            current = yaml.safe_dump(data, sort_keys=False)
        elif params.get("revision"):
            revision = params["revision"]
            if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
                raise ValueError("Invalid factory revision")
            current = _text(
                project_path(root, f".superqode/factory-studio/revisions/{revision}.yaml")
            )
        return {
            "yaml": current,
            "expected_file_digest": file_digest(target),
            "legacy": bool(current and "apiVersion" not in read_mapping(current)),
        }
    if method == "factory.edit":
        data = read_mapping(params["yaml"])
        controls = params.get("controls", {})
        if "name" in controls:
            data["metadata"]["name"] = controls["name"]
        if "model" in controls:
            binding = controls.get("binding", next(iter(data["inference"]["harnesses"])))
            if binding not in data["inference"]["harnesses"]:
                raise ValueError("Choose an existing factory harness binding")
            data["inference"]["harnesses"][binding]["model"] = controls["model"]
        for key in ("max_workers", "max_seconds"):
            if key in controls:
                data["governance"]["budget"][key] = controls[key]
        if "allow_network" in controls:
            data["governance"]["permissions"]["allow_network"] = controls["allow_network"]
        if "requirements" in controls:
            data["data_context"]["requirements"] = controls["requirements"]
        if "check_categories" in controls:
            categories = controls["check_categories"]
            if not isinstance(categories, dict) or set(categories) - set(
                data["improvement"]["checks"]
            ):
                raise ValueError("Choose existing acceptance checks for category edits")
            for name, category in categories.items():
                data["improvement"]["checks"][name]["category"] = category
        if "public_key" in controls:
            authority = data["governance"].setdefault(
                "release_authority",
                {"method": "p256-signature", "keys": {}, "challenge_ttl_seconds": 120},
            )
            authority["keys"][controls.get("key_id", "this-mac")] = {
                "public_key": controls["public_key"]
            }
        validate_definition(data)
        return {"yaml": yaml.safe_dump(data, sort_keys=False)}
    if method == "factory.inspect":
        text = params.get("yaml", "")
        data, snapshot = _parse(root, text)
        old = _text(target) if target.is_file() else ""
        warnings = []
        for name in data["orchestration"]["acceptance_checks"]:
            if "evaluator" not in data["improvement"]["checks"][name]:
                warnings.append(
                    f"{name}: add protected evaluator probes before acceptance verification."
                )
        if not data["governance"].get("release_authority"):
            warnings.append("No release signing authority is configured; delivery remains on hold.")
        warnings.append(
            "Definition validation makes no model calls and does not establish execution quality."
        )
        value = {
            "yaml": text,
            "name": data["metadata"]["name"],
            "digest": sha(text),
            "snapshot_digest": snapshot.digest,
            "expected_file_digest": file_digest(target),
            "warnings": warnings,
            "stages": data["orchestration"]["stages"],
            "requirements": data["data_context"].get("requirements", {}),
            "application_checks": data["improvement"]["checks"],
            "acceptance_checks": data["orchestration"]["acceptance_checks"],
            "revision_loop": data["orchestration"].get("revision_loop", {}),
            "layers": list(LAYERS),
            "bindings": data["inference"]["harnesses"],
            "binding_models": {
                name: harness.get("model_policy", {}).get("primary", "")
                for name, harness in snapshot.payload["harnesses"].items()
            },
            "governance": data["governance"],
            "diff": "".join(
                difflib.unified_diff(
                    old.splitlines(True),
                    text.splitlines(True),
                    fromfile="Current factory",
                    tofile="Proposed factory",
                )
            ),
        }
        identity = sha(json.dumps(value, sort_keys=True))
        service._write(
            "INSERT OR REPLACE INTO factory_studio_reviews VALUES(?,?,?,?)",
            (identity, params["project"], json.dumps(value), time.time()),
        )
        return {**value, "review": identity}
    if method == "factory.save":
        from .ownership import Lease, project_lease_path

        review = _review(service, params)
        reason = params.get("reason", "")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError("Describe why this factory revision is being saved")
        with service.lock:
            if service._all(
                "SELECT id FROM jobs WHERE project=? AND status IN ('running','queued','needs_approval','cancelling')",
                (params["project"],),
            ):
                raise ValueError("Finish active project work before changing the factory")
            lease = Lease(project_lease_path(service.root, root))
            try:
                current = file_digest(target)
                if (
                    current != params.get("expected_file_digest", "")
                    or current != review["expected_file_digest"]
                ):
                    raise ValueError("Project factory changed; reload before saving")
                _, snapshot = _parse(root, review["yaml"])
                if snapshot.digest != review["snapshot_digest"]:
                    raise ValueError("Factory components changed since validation; validate again")
                folder = project_path(root, ".superqode/factory-studio/revisions")
                versions = [(review["digest"], review["yaml"])]
                if current:
                    versions.append((current, _text(target)))
                for token, text in versions:
                    path = project_path(
                        root, (folder.relative_to(root) / (token + ".yaml")).as_posix()
                    )
                    if path.exists() and _text(path) != text:
                        raise ValueError("Stored factory revision was modified")
                    if not path.exists():
                        _atomic(path, text)
                metadata_path = project_path(
                    root, (folder.relative_to(root) / (review["digest"] + ".json")).as_posix()
                )
                if not metadata_path.exists():
                    _atomic(
                        metadata_path,
                        json.dumps({"reason": reason, "parent": current, "created": time.time()}),
                    )
                _atomic(target, review["yaml"])
            finally:
                lease.close()
        return {"digest": review["digest"], "snapshot_digest": snapshot.digest}
    if method == "factory.list":
        folder = project_path(root, ".superqode/factory-studio/revisions")
        revisions = []
        if folder.exists():
            paths = [
                project_path(root, path.relative_to(root).as_posix())
                for path in folder.glob("*.yaml")
            ]
            for safe in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                revisions.append({"digest": safe.stem, "intact": file_digest(safe) == safe.stem})
        store_path = project_path(root, ".superqode/workorders/store.sqlite3")
        runs = []
        if store_path.exists():
            for order in factory_store(root, read_only=True).list(limit=100):
                if "factory" in order.metadata:
                    runs.append(
                        {
                            "id": order.work_order_id,
                            "goal": order.goal,
                            "status": order.status.value,
                            "factory_digest": order.metadata["factory"]["snapshot_digest"],
                        }
                    )
        return {"revisions": revisions, "runs": runs}
    if method == "factory.trial":
        if params.get("confirmed") is not True:
            raise ValueError("Explicitly confirm preparation of this factory trial")
        review = _review(service, params)
        if file_digest(target) != review["digest"]:
            raise ValueError("Save the reviewed factory revision before preparing a trial")
        plan = compile_factory(
            resolve_factory(load_factory(root=root)), root=root, goal=params["goal"]
        )
        if plan.snapshot.digest != review["snapshot_digest"]:
            raise ValueError("Factory components changed; validate again")
        materialize_snapshot(plan)
        order = admit_factory(plan, request_id=params["request_id"], actor="desktop")
        return {
            "work_order": {"work_order_id": order.work_order_id, "status": order.status.value},
            "execution_started": False,
        }
    if method == "factory.run.inspect":
        from superqode.workorders.cockpit import build_cockpit_snapshot

        store = factory_store(root, read_only=True)
        order = store.get(params["run"])
        if "factory" not in order.metadata:
            raise ValueError("Choose a factory run")
        data = order.to_dict()
        data["artifacts"] = [
            {key: row[key] for key in ("artifact_id", "kind", "task_id", "digest")}
            for row in data["artifacts"]
        ]
        for task in data["tasks"]:
            task["metadata"] = {
                key: task["metadata"].get(key)
                for key in ("human_gate", "gate_digest", "gate_approval")
            }
        candidate = next(
            (a for a in reversed(order.artifacts) if a.kind == "integration_candidate"), None
        )
        return {
            "work_order": data,
            "evidence": [
                {
                    "id": a.artifact_id,
                    "kind": a.kind,
                    "task_id": a.task_id,
                    "content": a.content[:16000],
                    "truncated": len(a.content) > 16000,
                }
                for a in order.artifacts[-50:]
                if a.content and a.kind != "integration_candidate"
            ],
            "cockpit": build_cockpit_snapshot(store, order.work_order_id),
            "candidate_diff": candidate.content[:200000] if candidate else "",
            "diff_truncated": bool(candidate and len(candidate.content) > 200000),
            "candidate_id": candidate.artifact_id if candidate else "",
            "candidate_digest": candidate.digest if candidate else "",
        }
    if method == "factory.gate":
        store = factory_store(root)
        validate_factory_order(store.get(params["run"]), store=store)
        order = store.decide_gate(
            params["run"],
            params["stage"],
            expected_digest=params["gate_digest"],
            decision=params["decision"],
            actor="desktop",
            reason=params.get("reason", ""),
        )
        return {"id": order.work_order_id, "status": order.status.value}
    if method == "factory.cancel":
        order = factory_store(root).cancel(
            params["run"], actor="desktop", reason="Stopped from Factory Studio"
        )
        return {"id": order.work_order_id, "status": order.status.value}
    if method == "factory.release.status":
        from superqode.factory.release import release_status

        return release_status(params["run"], root=root)
    if method == "factory.release.challenge":
        from superqode.factory.release import issue_challenge

        return issue_challenge(params["run"], root=root, key_id=params["key_id"])
    if method == "factory.release.authorize":
        from superqode.factory.release import authorize_release

        order = authorize_release(params["run"], params["proof"], root=root)
        return {
            "id": order.work_order_id,
            "status": order.status.value,
            "actor": order.decision.actor,
        }
    if method == "factory.action.start":
        return service.start(params["project"], "factory", params)
    raise ValueError("Unknown Factory Studio operation")


def _improvement_plan(service, params, *, fresh=True):
    from superqode.factory.improvement import load

    rows = service._all(
        "SELECT payload FROM factory_improvement_plans WHERE id=? AND project=?",
        (params.get("plan"), params["project"]),
    )
    if not rows:
        plan, _ = load(service.project(params["project"]), params.get("plan"), fresh=fresh)
        return plan
    saved = json.loads(rows[0]["payload"])
    plan, _ = load(service.project(params["project"]), saved["id"], saved["digest"], fresh=fresh)
    return plan


def _completed_comparison(service, params):
    rows = service._all(
        "SELECT request,result,status FROM jobs WHERE id=? AND project=? AND kind='factory'",
        (params.get("comparison_job"), params["project"]),
    )
    if not rows or rows[0]["status"] != "completed":
        raise ValueError("A completed native comparison job is required before adoption")
    request = json.loads(rows[0]["request"])
    result = _comparison_from_job(
        request, json.loads(rows[0]["result"] or "{}"), params.get("plan"), params.get("candidate")
    )
    if (
        not result
        or result.get("plan") != params.get("plan")
        or result.get("candidate") != params.get("candidate")
        or result.get("eligible") is not True
    ):
        raise ValueError("Comparison does not authorize this exact improvement candidate")
    return result


def _comparison_from_job(request, result, plan, candidate=""):
    if not isinstance(request, dict) or not isinstance(result, dict):
        return {}
    if request.get("factory_action") == "improvement-compare":
        if request.get("plan") == plan and (not candidate or request.get("candidate") == candidate):
            return result
    if request.get("factory_action") in {"campaign-run", "campaign-worker"}:
        manifest = result.get("manifest", {})
        state = result.get("state", {})
        if (
            not isinstance(manifest, dict)
            or not isinstance(state, dict)
            or not isinstance(state.get("events"), list)
        ):
            return {}
        if manifest.get("id") != request.get("campaign") or manifest.get("digest") != request.get(
            "campaign_digest"
        ):
            return {}
        matches = [
            event["comparison"]
            for event in state["events"]
            if isinstance(event, dict)
            and event.get("plan") == plan
            and isinstance(event.get("comparison"), dict)
            and (not candidate or event["comparison"].get("candidate") == candidate)
        ]
        if len(matches) == 1:
            return matches[0]
    return {}


def _improvement(service, root, method, params):
    from superqode.factory import improvement

    if method == "factory.improvement.capabilities":
        definition = load_factory(root=root)
        resolved_harnesses = (
            resolve_factory(definition).payload["harnesses"] if not definition.legacy else {}
        )
        return {
            **improvement.capabilities(),
            "bindings": list(definition.data.get("inference", {}).get("harnesses", {})),
            "bound_skills": {
                key: value.get("skills", [])
                for key, value in definition.data.get("inference", {}).get("harnesses", {}).items()
            },
            "workflow_stages": [
                {"id": s["id"], "harness": s["harness"], "role": s["role"]}
                for s in definition.data.get("orchestration", {}).get("stages", [])
                if not s.get("depends_on") and not s.get("human_gate")
            ],
            "route_models": {
                key: list(
                    dict.fromkeys(
                        [
                            *(
                                [resolved_harnesses[key]["model_policy"]["primary"]]
                                if resolved_harnesses.get(key, {})
                                .get("model_policy", {})
                                .get("primary")
                                else []
                            ),
                            *definition.data.get("routes", {})
                            .get(definition.data.get("default_route"), {})
                            .get("prefer", []),
                        ]
                    )
                )
                for key, value in definition.data.get("inference", {}).get("harnesses", {}).items()
            },
        }
    if method == "factory.improvement.skill.create":
        from .ownership import Lease, project_lease_path
        from .ship import assert_idle
        from superqode.factory.skills import parse_skill
        from superqode.factory.versioning import source_path, _safe_text
        import re

        if params.get("confirmed") is not True:
            raise ValueError("Explicitly create and bind this skill into a draft")
        identity = params.get("skill", "")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identity):
            raise ValueError("Use a skill ID of lowercase letters, digits and hyphens")
        text = params.get("markdown", "")
        metadata, _ = parse_skill(text)
        _credentials(metadata)
        data = read_mapping(params["yaml"])
        validate_definition(data)
        _credentials(data)
        binding = data["inference"]["harnesses"].get(params.get("binding"))
        if binding is None:
            raise ValueError("Choose a declared harness binding")
        assets = data["data_context"].setdefault("files", {})
        path = f".superqode/skills/{identity}/SKILL.md"
        _safe_text(path, text)
        target = source_path(root, path)
        if identity in assets or any(v["path"] == path for v in assets.values()):
            raise ValueError("Skill ID or path is already declared; choose a new ID")
        assets[identity] = {"path": path, "purpose": "skill"}
        binding.setdefault("skills", []).append(identity)
        proposed = yaml.safe_dump(data, sort_keys=False)
        snapshot = resolve_factory(
            FactoryDefinition(root, _target(root), data),
            source_text=proposed,
            source_overlays={path: text},
        )
        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                if target.exists():
                    raise ValueError("Skill file already exists; choose a new ID")
                _atomic(target, text)
            finally:
                lease.close()
        return {
            "yaml": proposed,
            "component": path,
            "snapshot_digest": snapshot.digest,
            "notice": "Skill created and bound in the draft. Review and save the definition explicitly before preparing an experiment.",
        }
    if method in {"factory.improvement.suite.open", "factory.improvement.suite.save"}:
        from superqode.factory.versioning import source_path

        path = source_path(root, params["path"])
        if not params["path"].startswith(".superqode/evals/") or path.suffix not in {
            ".yaml",
            ".yml",
            ".json",
        }:
            raise ValueError("Keep improvement suites under .superqode/evals as YAML or JSON")
        if method.endswith("open"):
            starter = "tasks:\n  - id: train\n    split: held-in\n    prompt: Say ready\n    expect_contains: ready\n  - id: heldout\n    split: held-out\n    prompt: Respond with the word ready\n    expect_contains: ready\n"
            return {
                "yaml": _text(path) if path.is_file() else starter,
                "expected_file_digest": file_digest(path),
            }
        from .ownership import Lease, project_lease_path
        from .ship import assert_idle
        import tempfile

        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                if file_digest(path) != params.get("expected_file_digest", ""):
                    raise ValueError("Suite changed; reload before saving")
                text = params.get("yaml", "")
                if not isinstance(text, str) or len(text.encode()) > 250000:
                    raise ValueError("Use a suite smaller than 250 KB")
                _credentials(read_mapping(text))
                temporary = project_path(root, ".superqode/factory-improvements/suite-validation")
                temporary.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=temporary) as directory:
                    proposed = Path(directory) / "tasks.yaml"
                    proposed.write_text(text, encoding="utf-8")
                    improvement._suite(proposed)
                _atomic(path, text)
                return {"digest": file_digest(path)}
            finally:
                lease.close()
    if method == "factory.improvement.list":
        values = {
            row["id"]: json.loads(row["payload"])
            for row in service._all(
                "SELECT id,payload FROM factory_improvement_plans WHERE project=? ORDER BY created DESC LIMIT 50",
                (params["project"],),
            )
        }
        base = project_path(root, improvement.PREFIX)
        if base.exists():
            for folder in sorted(base.glob("improve_*"), key=lambda p: p.name)[-50:]:
                location = project_path(root, (folder / "plan.json").relative_to(root).as_posix())
                value = json.loads(improvement._read(location))
                token = value.pop("digest", "")
                if (
                    value.get("repository") != str(root)
                    or value.get("id") != folder.name
                    or digest(canonical(value)) != token
                ):
                    raise ValueError("Headless experiment identity or digest changed")
                values.setdefault(folder.name, {**value, "digest": token})
        return {"plans": list(values.values())[-100:]}
    if method == "factory.improvement.prepare":
        # The same writer ownership boundary as definition saves; no models execute.
        from .ownership import Lease, project_lease_path
        from .ship import assert_idle

        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                plan = improvement.prepare(
                    root,
                    **{
                        k: params[k]
                        for k in (
                            "binding",
                            "tasks",
                            "fixture",
                            "max_evals",
                            "max_seconds",
                            "reflection_model",
                        )
                    },
                    target_kind=params.get("target_kind", "harness"),
                    skill=params.get("skill", ""),
                    stage=params.get("stage", ""),
                    route_models=params.get("route_models"),
                    optimizer_engine=params.get("optimizer_engine", "gepa"),
                )
                service._write(
                    "INSERT INTO factory_improvement_plans VALUES(?,?,?,?)",
                    (plan["id"], params["project"], json.dumps(plan), time.time()),
                )
                return {
                    **plan,
                    "baseline_yaml": improvement.baseline_proposal(root, plan),
                }
            finally:
                lease.close()
    plan = _improvement_plan(
        service,
        params,
        fresh=method
        not in {
            "factory.improvement.open",
            "factory.improvement.preview",
            "factory.improvement.budget",
        },
    )
    if method == "factory.improvement.open":
        directory = improvement.folder(root, plan["id"])
        candidates = []
        if (directory / "candidates").is_dir():
            for path in sorted(
                (directory / "candidates").glob("*" + improvement.proposal_suffix(plan))
            )[:50]:
                improvement.get_candidate(root, plan, path.stem)
                candidates.append(path.stem)
        comparison = {}
        comparison_job = ""
        fresh = True
        try:
            improvement.load(root, plan["id"], plan["digest"], fresh=True)
        except ValueError:
            fresh = False
        for row in service._all(
            "SELECT id,request,result FROM jobs WHERE project=? AND kind='factory' AND status='completed' ORDER BY created DESC LIMIT 100",
            (params["project"],),
        ):
            request = json.loads(row["request"])
            value = _comparison_from_job(request, json.loads(row["result"] or "{}"), plan["id"])
            if value.get("plan") != plan["id"] or value.get("candidate") not in candidates:
                continue
            comparison = value
            comparison_job = row["id"]
            if fresh and value.get("eligible"):
                try:
                    improvement.evidence(
                        root, plan["id"], value["candidate"], value.get("receipt_digest", "")
                    )
                except ValueError:
                    comparison = {
                        **value,
                        "eligible": False,
                        "issues": [
                            *value.get("issues", []),
                            "Recorded evidence changed; adoption is on hold",
                        ],
                    }
            elif not fresh:
                comparison = {
                    **value,
                    "eligible": False,
                    "issues": [
                        *value.get("issues", []),
                        "This is historical evidence; prepare a fresh experiment for the current Factory",
                    ],
                }
            break
        return {
            **plan,
            "baseline_yaml": improvement.baseline_proposal(root, plan),
            "candidates": candidates,
            "fresh": fresh,
            "comparison": comparison,
            "comparison_job": comparison_job,
            "compared": (directory / "comparison.claim").exists(),
            "budget": improvement.budget_summary(root, plan, detail=True),
        }
    if method == "factory.improvement.budget":
        return improvement.budget_summary(root, plan, detail=True)
    if method == "factory.improvement.propose":
        return improvement.stage(root, plan["id"], params["yaml"])
    if method == "factory.improvement.import":
        from superqode.factory.versioning import source_path

        return improvement.stage(root, plan["id"], _text(source_path(root, params["path"])))
    if method == "factory.improvement.external.import":
        if params.get("confirmed") is not True:
            raise ValueError("Explicitly import an external optimizer proposal")
        from superqode.factory.external import import_candidate
        from .ownership import Lease, project_lease_path
        from .ship import assert_idle

        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                return import_candidate(
                    root, plan["id"], engine=params["engine"], artifact=params["path"]
                )
            finally:
                lease.close()
    if method == "factory.improvement.preview":
        return improvement.preview(root, plan["id"], params["candidate"])
    if method == "factory.improvement.adopt":
        if params.get("confirmed") is not True:
            raise ValueError("Explicitly adopt this candidate into a draft")
        comparison = _completed_comparison(service, params)
        from .ownership import Lease, project_lease_path
        from .ship import assert_idle

        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                return improvement.adoption(
                    root, plan["id"], params["candidate"], comparison["receipt_digest"]
                )
            finally:
                lease.close()
    raise ValueError("Unknown improvement operation")


def validate_request(root, params, *, service=None):
    action = params.get("factory_action")
    if params.get("confirmed") is not True:
        raise ValueError("Explicitly confirm factory execution")
    common = {"factory_action": action, "confirmed": True}
    if "command_id" in params:
        common["command_id"] = params["command_id"]
    if action in {"campaign-run", "campaign-worker"}:
        from superqode.factory import campaigns
        from superqode.providers.model_specs import split_provider_model_ref

        manifest, state = campaigns._load(
            root, params["campaign"], params["campaign_digest"], fresh=True
        )
        experiment = manifest["policy"]["experiment"]
        snapshot = resolve_factory(load_factory(root=root))
        routes = [
            snapshot.payload["harnesses"][experiment["binding"]]["model_policy"]["primary"],
            experiment["reflection_model"],
            *experiment.get("route_models", []),
        ]
        providers = {split_provider_model_ref(model).provider for model in routes}
        remaining = manifest["policy"]["max_seconds"] - (
            time.time() - state["started"] if state["started"] else 0
        )
        if remaining < 1 or state["status"] != "ready":
            raise ValueError("Campaign is held or its wall-time budget expired")
        return {
            **common,
            "campaign": manifest["id"],
            "campaign_digest": manifest["digest"],
            "factory_providers": sorted(providers),
            "provider": "",
            "model": "",
            "factory_deadline_seconds": max(
                1,
                int(
                    remaining
                    if action == "campaign-worker"
                    else min(remaining, experiment["max_seconds"])
                ),
            ),
        }
    if action == "suite-run":
        if service is None:
            raise ValueError("Suite execution requires a registered native plan")
        from .factory_trials import registered
        from superqode.factory import trials
        from superqode.providers.model_specs import split_provider_model_ref

        plan = registered(service, params)
        providers = set()
        for entry in plan["entries"]:
            _, _, _, compiled = trials._order(root, entry)
            for harness in compiled.snapshot.payload["harnesses"].values():
                policy = harness["model_policy"]
                for model in (policy["primary"], *policy.get("fallbacks", [])):
                    route = split_provider_model_ref(model)
                    if route.provider in {"synthetic", "acp"}:
                        raise ValueError("Trial suites require direct model providers")
                    providers.add(route.provider)
        started = trials.scorecard(root, plan["id"], plan["digest"])["started"]
        remaining = plan["suite"]["budget"]["max_seconds"] - (
            time.time() - started if started else 0
        )
        if remaining <= 0:
            raise ValueError("Suite wall-time budget expired; prepare a new suite")
        return {
            **common,
            "suite": plan["id"],
            "suite_digest": plan["digest"],
            "factory_providers": sorted(providers),
            "provider": "",
            "model": "",
            "factory_deadline_seconds": max(1, int(remaining)),
        }
    if action in {"improvement-search", "improvement-compare"}:
        from superqode.factory import improvement

        if service is None:
            raise ValueError("Factory improvement requires a prepared native plan")
        plan = _improvement_plan(service, params)
        improvement.budget(root, plan).check_admission()
        if (improvement.folder(root, plan["id"]) / "comparison.claim").exists():
            raise ValueError("This plan already exposed a held-out comparison; prepare a new plan")
        if action == "improvement-search" and (
            not plan["reflection_model"]
            or not any(
                row["id"] == plan.get("optimizer_engine", "gepa") and row["available"]
                for row in improvement.capabilities()["optimizer_engines"]
            )
        ):
            raise ValueError(
                "Select an available optimizer engine and an explicit reflection model; no dependencies are installed automatically"
            )
        candidate = params.get("candidate", "")
        candidate_text = ""
        if action == "improvement-compare":
            _, candidate_text = improvement.get_candidate(root, plan, candidate)
        from superqode.providers.model_specs import split_provider_model_ref

        providers = {plan["provider"]}
        if plan.get("target_kind") == "route":
            models = (
                plan["route_models"]
                if action == "improvement-search"
                else [read_mapping(candidate_text)["model"]]
            )
            providers.update(split_provider_model_ref(model).provider for model in models)
        if action == "improvement-search":
            providers.add(split_provider_model_ref(plan["reflection_model"]).provider)
        return {
            **common,
            "plan": plan["id"],
            "plan_digest": plan["digest"],
            "candidate": candidate,
            "factory_providers": sorted(providers),
            "provider": "",
            "model": "",
            "factory_deadline_seconds": max(
                0.01,
                plan["max_seconds"] - improvement.budget(root, plan).summary()["elapsed_seconds"],
            ),
        }
    if action == "source-commit":
        from superqode.factory.versioning import selected_review

        if service is None:
            raise ValueError("Factory source commits require a reviewed desktop operation")
        review = _source_review(service, params)
        selected_review(review, params.get("paths"))
        message = params.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 5000:
            raise ValueError("Enter a Factory commit message of up to 5,000 characters")
        return {
            **common,
            "source_plan": review,
            "paths": params["paths"],
            "message": message,
            "factory_providers": [],
            "provider": "",
            "model": "",
        }
    if action in {"generate", "verifier-generate"}:
        from superqode.providers.registry import PROVIDERS

        data = read_mapping(params["yaml"])
        validate_definition(data)
        if action == "verifier-generate" and data != load_factory(root=root).data:
            raise ValueError("Save the Factory draft before proposing its verifiers")
        _credentials(data)
        from superqode.factory.generation import check_generation_route

        check_generation_route(data, str(params.get("provider", "")), str(params.get("model", "")))
        if (
            params.get("provider") not in PROVIDERS
            or PROVIDERS[params["provider"]].harness_only
            or not params.get("model")
            or not isinstance(params.get("description"), str)
            or not 0 < len(params["description"]) <= 8000
        ):
            raise ValueError("Choose a model provider and describe the factory")
        return {
            **common,
            **{key: params[key] for key in ("yaml", "description", "provider", "model")},
            "factory_providers": [params["provider"]],
        }
    if action not in {"worker", "verify", "apply"}:
        raise ValueError("Unsupported factory action")
    store = factory_store(root)
    plan = validate_factory_order(store.get(params["run"]), store=store)
    if action == "verify":
        from superqode.factory.verification import evaluator_contract

        evaluator_contract(plan)
    if action == "apply":
        from superqode.factory.release import require_authorization

        order = store.get(params["run"])
        require_authorization(order)
        payload = order.metadata["factory_release"]["payload"]
        if (
            params.get("candidate_id") != payload["candidate_id"]
            or params.get("candidate_digest") != payload["candidate_digest"]
        ):
            raise ValueError("Inspected candidate changed before applying")
    from superqode.providers.model_specs import split_provider_model_ref

    providers = set()
    if action == "worker":
        for harness in plan.snapshot.payload["harnesses"].values():
            policy = harness["model_policy"]
            providers.update(
                split_provider_model_ref(model).provider
                for model in (policy["primary"], *policy.get("fallbacks", []))
            )
    safe = {
        **common,
        "run": params["run"],
        "factory_providers": sorted(providers),
        "provider": "",
        "model": "",
    }
    if action == "apply":
        safe.update({key: params[key] for key in ("candidate_id", "candidate_digest")})
    return safe


async def run(request, emit):
    from superqode.factory.runtime import factory_store

    action, root = request["factory_action"], request["cwd"]
    if action in {"campaign-run", "campaign-worker"}:
        import asyncio
        from superqode.factory import campaigns

        operation = campaigns.run_worker if action == "campaign-worker" else campaigns.advance
        result = await asyncio.to_thread(
            operation, root, request["campaign"], request["campaign_digest"], live=True
        )
    elif action == "suite-run":
        from superqode.factory import trials

        result = await trials.advance(root, request["suite"], request["suite_digest"], emit=emit)
    elif action in {"improvement-search", "improvement-compare"}:
        from superqode.factory import improvement

        improvement.load(root, request["plan"], request["plan_digest"], fresh=True)
        if action == "improvement-compare":
            result = await improvement.compare(
                root, request["plan"], request["candidate"], request["plan_digest"]
            )
        else:
            # This is already a dedicated existing desktop worker process.
            import asyncio

            result = await asyncio.to_thread(
                improvement.optimize, root, request["plan"], request["plan_digest"]
            )
    elif action == "source-commit":
        from superqode.factory.versioning import commit_sources

        result = commit_sources(root, request["source_plan"], request["paths"], request["message"])
    elif action in {"generate", "verifier-generate"}:
        from superqode.factory.generation import generate_factory
        from superqode.factory.verifiers import generate as generate_verifiers

        result = await (
            generate_factory(
                description=request["description"],
                yaml_text=request["yaml"],
                provider=request["provider"],
                model=request["model"],
            )
            if action == "generate"
            else generate_verifiers(
                root,
                description=request["description"],
                provider=request["provider"],
                model=request["model"],
            )
        )
    elif action == "worker":
        from superqode.workorders.worker import WorkOrderWorker, WorkOrderWorkerConfig

        worker = WorkOrderWorker(
            factory_store(root),
            WorkOrderWorkerConfig(
                worker_id="studio-" + request["job_id"],
                reference=request["run"],
                isolation="worktree",
                once=True,
            ),
        )
        stats = await worker.run()
        order = factory_store(root).get(request["run"])
        result = {
            "stats": stats.to_dict(),
            "run": order.work_order_id,
            "factory_state": order.status.value,
        }
    elif action == "verify":
        from superqode.factory.verification import verify_factory

        # A dedicated worker process owns the bounded native verifier.
        verified = verify_factory(request["run"], root=root)
        result = {
            "run": request["run"],
            "verification_status": verified["report"]["status"],
            "record": verified["record"],
            "missing_evidence": verified["report"]["missing_evidence"],
            "gauge": {
                "verdict": verified["record"]["decision"]["verdict"],
                "reasons": verified["record"]["decision"]["reasons"],
                "factory_digest": verified["record"]["subject"]["factory_digest"],
                "candidate": verified["record"]["subject"]["candidate"],
            },
            "traceability": verified["traceability"],
        }
    else:
        from superqode.factory.release import apply_approved

        result = apply_approved(
            request["run"],
            root=root,
            candidate_id=request["candidate_id"],
            candidate_digest=request["candidate_digest"],
        )
        result = {"run": result.work_order_id, "factory_state": result.status.value}
    emit("result", {"status": "completed", "factory_action": action, **result})
