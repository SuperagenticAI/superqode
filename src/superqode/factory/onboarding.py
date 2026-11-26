"""Read-only first-run guidance shared by CLI, terminal UI and macOS."""

import json
from pathlib import Path

from .definition import (
    FactoryDefinition,
    project_path,
    read_mapping,
    validate_definition,
    relative_path,
)
from .model_setup import inspect_models
from .operations import readiness
from .snapshot import resolve_factory


def verified_trial(order):
    """Validate the receipt rather than treating workflow completion as verification."""
    from superqode.workorders.store import _require_factory_verification

    if "factory" not in order.metadata:
        return False
    candidate = next(
        (a for a in reversed(order.artifacts) if a.kind == "integration_candidate"), None
    )
    if candidate is None:
        return False
    try:
        _require_factory_verification(order, candidate.artifact_id)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    return True


def inspect_setup(root, *, yaml_text=None, drafting_model="", check_connection=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Open an existing project directory")
    path = project_path(root, ".superqode/factory.yaml")
    if path.is_file() and path.stat().st_size > 250000:
        raise ValueError("Factory definition exceeds 250 KB")
    saved_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if yaml_text is None:
        yaml_text = saved_text
    if not isinstance(yaml_text, str):
        raise ValueError("Factory YAML must be text")
    steps = []

    def step(identity, title, status, detail, destination, arguments):
        steps.append(
            {
                "id": identity,
                "title": title,
                "status": status,
                "detail": detail,
                "destination": destination,
                "command": ["sq", "factory", *arguments, "--project", str(root)],
            }
        )

    data = snapshot = None
    legacy = False
    error = "Choose a starter, or describe the outcome to generate a reviewable Factory. Inspection needs no model."
    if yaml_text.strip():
        try:
            data = read_mapping(yaml_text)
            legacy = "apiVersion" not in data and not (set(data) - {"default_route", "routes"})
            validate_definition(data)
            snapshot = resolve_factory(FactoryDefinition(root, path, data), source_text=yaml_text)
        except (ValueError, OSError):
            data = None
            error = (
                "A route policy exists. Choose a workflow starter to keep these routes and create a FactorySpec."
                if legacy
                else "The Factory draft needs attention. Validate it to inspect missing components or schema errors."
            )
    step(
        "definition",
        "Describe an outcome and review the Factory",
        "configured" if data and yaml_text == saved_text else "needs_save" if data else "missing",
        "Factory definition and declared components resolve; this does not run agents."
        if data and yaml_text == saved_text
        else "The draft resolves. Review and save it in Definition before preparing a trial."
        if data
        else error,
        "Definition" if yaml_text.strip() and not legacy else "Stack",
        ["validate"]
        if yaml_text.strip() and not legacy
        else ["init", "--template", "fix-and-verify"],
    )
    models = {}
    if data:
        try:
            models = inspect_models(
                root,
                yaml_text=yaml_text,
                drafting_model=drafting_model,
                check_connection=check_connection,
            )
        except (ValueError, OSError):
            pass
    execution = models.get("execution", [])
    model_ready = bool(execution) and all(row["eligible"] for row in execution)
    step(
        "models",
        "Choose and check execution models",
        "configured" if model_ready else "missing",
        "Drafting and execution models are separate. Connection checks send no inference prompts; a trial supplies execution evidence.",
        "Configuration",
        ["models", "--check-connections"],
    )
    host = readiness(root)
    blocking = [c for c in host["checks"] if c["id"] != "factory" and not c["passed"]]
    step(
        "project",
        "Prepare the project and isolated host",
        "blocked" if blocking else "configured",
        " ".join(c.get("action") or c["detail"] for c in blocking)
        if blocking
        else "Host prerequisites are configured. Run isolation probes and reviewed application commands to test them.",
        "Operations",
        ["operations", "check", "--probe", "--application"],
    )
    protected = False
    if snapshot and data:
        from .probes import parse_probes

        try:
            for name in data["orchestration"]["acceptance_checks"]:
                asset = data["improvement"]["checks"][name]["evaluator"]
                source = relative_path(data["data_context"]["files"][asset]["path"]).as_posix()
                parse_probes(snapshot.payload["sources"][source]["text"])
            protected = bool(data["orchestration"]["acceptance_checks"])
        except (KeyError, ValueError):
            pass
    step(
        "acceptance",
        "Review protected acceptance checks",
        "configured" if protected else "missing",
        "Protected probes are configured. Review their expectations independently before the first trial."
        if protected
        else "Add protected probe expectations before running the trial. A normal test command alone does not establish protected acceptance.",
        "Acceptance",
        ["verifier", "draft", "--help"],
    )
    verified, recent, recent_action = False, "", ""
    database = project_path(root, ".superqode/workorders/store.sqlite3")
    if database.is_file() and snapshot:
        from .runtime import factory_store

        for order in factory_store(root, read_only=True).list(limit=100):
            metadata = order.metadata.get("factory", {})
            if (
                metadata.get("snapshot_digest") != snapshot.digest
                or metadata.get("repository_commit") != host["repository_commit"]
            ):
                continue
            if not recent:
                recent = order.work_order_id
                waiting = any(task.status.value == "waiting_for_human" for task in order.tasks)
                from superqode.workorders.models import COMPLETED_TASK_STATUSES

                candidate = bool(order.tasks) and all(
                    task.status in COMPLETED_TASK_STATUSES for task in order.tasks
                )
                recent_action = (
                    "verify"
                    if candidate
                    else "worker"
                    if order.status.value == "queued" and not waiting
                    else "inspect"
                )
            if verified_trial(order):
                verified = True
                recent = order.work_order_id
                break
    if verified:
        trial_command = ["evidence", "trace", recent]
    elif recent_action == "worker":
        trial_command = ["worker", recent, "--live"]
    elif recent_action == "verify":
        trial_command = ["verify", recent, "--execute"]
    elif recent:
        trial_command = ["inspect", recent]
    else:
        trial_command = ["trial", "Describe one small, verifiable change"]
    step(
        "trial",
        "Run one small trial and inspect evidence",
        "verified" if verified else "prepared" if recent else "not_started",
        "A matching protected trial has verification evidence. Review SuperGauge and human release approval separately."
        if verified
        else "Save the reviewed Factory and commit or isolate source changes. Prepare a trial, explicitly run its worker, resolve human gates, then run protected verification.",
        "Runs",
        trial_command,
    )
    next_step = next((s for s in steps if s["status"] not in {"configured", "verified"}), steps[-1])
    return {
        "format": "superqode.factory-onboarding/1",
        "steps": steps,
        "next_step": next_step,
        "models": models,
        "application": host["application"],
        "host_checks": host["checks"],
        "verified_trial": verified,
        "model_calls": 0,
        "written": False,
        "notice": "This checklist makes no inference calls and runs no project commands. Installation, model downloads, application checks and trial execution remain explicit.",
    }


def lines(value):
    import shlex

    output = ["Factory getting started", value["notice"]]
    output += [
        f"{index}. {step['title']} [{step['status']}]\n   {step['detail']}"
        for index, step in enumerate(value["steps"], 1)
    ]
    output += [
        "Next: " + value["next_step"]["title"],
        "  " + shlex.join(value["next_step"]["command"]),
    ]
    return output
