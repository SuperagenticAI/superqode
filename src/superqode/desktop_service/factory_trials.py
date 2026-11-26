"""Native Trial Suite RPCs; execution remains in the shared Factory engine."""

import json
from pathlib import Path
import time

from superqode.factory import trials
from superqode.factory.versioning import source_path
from .ownership import Lease, project_lease_path
from .ship import assert_idle
from .studio import _atomic, file_digest


def registered(service, params):
    service._write(
        "CREATE TABLE IF NOT EXISTS factory_trial_plans(id TEXT PRIMARY KEY,project TEXT,digest TEXT,payload TEXT,created REAL)"
    )
    rows = service._all(
        "SELECT digest FROM factory_trial_plans WHERE id=? AND project=?",
        (params.get("suite"), params["project"]),
    )
    if not rows:
        raise ValueError("Choose a trial suite prepared for this project")
    return trials.load(service.project(params["project"]), params["suite"], rows[0]["digest"])


def handle(service, root, method, params):
    if method.startswith("factory.suite.history."):
        from superqode.factory import benchmarks

        if method == "factory.suite.history.list":
            return benchmarks.history(root)
        if method == "factory.suite.history.draft":
            return benchmarks.draft(
                root,
                held_in=params.get("held_in", []),
                held_out=params.get("held_out", []),
                candidate=params["candidate"],
            )
        if method == "factory.suite.history.install":
            with service.lock:
                assert_idle(service, params["project"])
                return benchmarks.install(
                    root,
                    params["proposal"],
                    expected=params["digest"],
                    confirmed=params.get("confirmed") is True,
                )
        raise ValueError("Unknown historical workload action")
    service._write(
        "CREATE TABLE IF NOT EXISTS factory_trial_plans(id TEXT PRIMARY KEY,project TEXT,digest TEXT,payload TEXT,created REAL)"
    )
    if method.startswith("factory.suite.feedback."):
        return _feedback(service, root, method.removeprefix("factory.suite.feedback."), params)
    if method in {"factory.suite.source.open", "factory.suite.source.save"}:
        path = params["path"]
        if (
            not isinstance(path, str)
            or not path.startswith(".superqode/trials/")
            or Path(path).suffix not in {".yaml", ".yml"}
        ):
            raise ValueError("Store trial suite sources as YAML under .superqode/trials")
        target = source_path(root, path)
        if method.endswith("open"):
            return {
                "yaml": trials._read(target, 250000) if target.exists() else trials.starter(),
                "expected_file_digest": file_digest(target),
            }
        text = params.get("yaml", "")
        trials.parse_suite(text)
        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                if file_digest(target) != params.get("expected_file_digest", ""):
                    raise ValueError("Suite source changed; reload before saving")
                _atomic(target, text)
                return {"digest": file_digest(target)}
            finally:
                lease.close()
    if method == "factory.suite.list":
        return {
            "suites": [
                json.loads(r["payload"])
                for r in service._all(
                    "SELECT payload FROM factory_trial_plans WHERE project=? ORDER BY created DESC LIMIT 50",
                    (params["project"],),
                )
            ]
        }
    if method == "factory.suite.prepare":
        if params.get("confirmed") is not True:
            raise ValueError(
                "Explicitly prepare the paired suite projects; preparation makes no model calls"
            )
        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                plan = trials.prepare(root, suite_text=params["yaml"])
                service._write(
                    "INSERT INTO factory_trial_plans VALUES(?,?,?,?,?)",
                    (plan["id"], params["project"], plan["digest"], json.dumps(plan), time.time()),
                )
                return trials.scorecard(root, plan["id"], plan["digest"])
            finally:
                lease.close()
    plan = registered(service, params)
    if method == "factory.suite.inspect":
        return trials.scorecard(root, plan["id"], plan["digest"])
    if method == "factory.suite.entry":
        return trials.inspect_entry(root, plan["id"], params["entry"])
    if method == "factory.suite.gate":
        if params.get("confirmed") is not True:
            raise ValueError("Explicitly approve or hold this suite stage")
        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                return trials.gate(
                    root,
                    plan["id"],
                    params["entry"],
                    params["stage"],
                    params["gate_digest"],
                    params["decision"],
                    params.get("reason", ""),
                )
            finally:
                lease.close()
    if method == "factory.suite.retry":
        if params.get("confirmed") is not True:
            raise ValueError("Explicitly authorize retry after reviewing the recorded failure")
        with service.lock:
            assert_idle(service, params["project"])
            lease = Lease(project_lease_path(service.root, root))
            try:
                return trials.retry(
                    root,
                    plan["id"],
                    params["entry"],
                    params["stage"],
                    params["attempt"],
                    params.get("reason", ""),
                )
            finally:
                lease.close()
    raise ValueError("Unknown trial suite operation")


def _feedback(service, root, method, params):
    from superqode.factory import feedback

    if method == "list":
        return feedback.list_issues(root)
    if method == "detail":
        return feedback.detail(root, params["issue"])
    if method == "proposal":
        return feedback.get_proposal(
            root,
            params["issue"],
            params["proposal"],
            for_execution=params.get("for_execution") is True,
        )
    if method not in {"scan", "review", "propose", "attach"}:
        raise ValueError("Unknown Factory feedback operation")
    if params.get("confirmed") is not True:
        raise ValueError("Explicitly request this feedback action")
    secrets = [
        v
        for values in (service.credentials, service.runtime_keys, service.vendor_keys)
        for v in values.values()
        if isinstance(v, str) and v
    ]
    with service.lock:
        assert_idle(service, params["project"])
        lease = Lease(project_lease_path(service.root, root))
        try:
            if method == "scan":
                plan = registered(service, params)
                return feedback.scan(root, plan["id"], plan["digest"], secrets=secrets)
            if method == "review":
                notes = params.get("notes")
                if isinstance(notes, str):
                    notes = feedback._text(notes, root, secrets)
                return feedback.review(
                    root,
                    params["issue"],
                    params["review_digest"],
                    params["category"],
                    params["status"],
                    notes,
                )
            if method == "propose":
                return feedback.propose(
                    root,
                    params["issue"],
                    params["observation"],
                    params["review_digest"],
                    params["kind"],
                    params["value"],
                )
            plan = registered(service, params)
            return feedback.attach_evaluation(
                root, params["issue"], params["proposal"], plan["id"], plan["digest"]
            )
        finally:
            lease.close()
