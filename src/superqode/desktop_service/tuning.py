"""Project-owned native tuning rounds using the shared TUI tuning service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

from superqode.systemone import tune


def directory(state: Path, project: str, identity: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Choose a saved tuning experiment")
    root = (state / "tuning" / project).resolve()
    if not root.is_relative_to(state.resolve()):
        raise ValueError("Tuning storage points outside app state")
    target = (root / identity).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Tuning experiment is outside this project")
    return target


def review(output: Path) -> dict:
    manifest = tune.load_run(output)
    rows = tune.review_batch(manifest)
    labels = list(next(iter(manifest["pack"]["questions"].values()))["criteria"])
    counts = {
        split: sum(row["split"] == split for row in manifest["examples"])
        for split in ("train", "validation", "test")
    }
    report_path = output / "report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    return {
        "id": output.name,
        "status": manifest["status"],
        "round": manifest["round"],
        "workflow": manifest["workflow"],
        "labels": labels,
        "review": rows,
        "counts": counts,
        "options": manifest["options"],
        "report": report,
        "revision": hashlib.sha256((output / "run.json").read_bytes()).hexdigest(),
        "needs_acquisition": manifest["workflow"] == "active"
        and manifest["status"] == "review"
        and not rows
        and not any(row.get("selected_round") == manifest["round"] for row in manifest["examples"]),
    }


def handle(service, method, params):
    project = params["project"]
    root = service.project(project)
    if method == "tuning.list":
        folder = directory(service.root, project, "0" * 32).parent
        entries = sorted(folder.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"id": p.parent.name, "updated": p.stat().st_mtime} for p in entries[:100]]
    if method == "tuning.prepare":
        options = tune.TuneOptions(
            pack=str(params.get("pack") or "factory_route"),
            reflection_lm=str(params.get("reflection_model") or ""),
            max_evals=int(params.get("max_evals", 30)),
            max_reflection_cost=float(params.get("max_cost", 2)),
            batch_size=int(params.get("batch_size", 5)),
            seed=int(params.get("seed", 0)),
        )
        if not 1 <= options.max_evals <= 1000 or not 0 < options.max_reflection_cost <= 100:
            raise ValueError("Use 1–1000 evaluations and a positive cost limit up to $100")
        if not 2 <= options.batch_size <= 20:
            raise ValueError("Review batch size must be between 2 and 20")
        source = Path(str(params.get("data") or "")).expanduser()
        source = source if source.is_absolute() else root / source
        rows = tune.read_examples(source)
        output = directory(service.root, project, uuid.uuid4().hex)
        tune.prepare_run(options, rows, output)
        return review(output)
    output = directory(service.root, project, str(params.get("id") or ""))
    current = review(output)
    if method == "tuning.get":
        return current
    if params.get("revision") != current["revision"]:
        raise ValueError("This tuning round changed. Refresh before editing or running it")
    if method == "tuning.label":
        if (output / "acquisition.lock").exists():
            raise ValueError("Wait until example selection finishes before labeling")
        identity = str(params.get("example") or "")
        if not any(row["id"] == identity for row in current["review"]):
            raise ValueError("Choose an example in the current review batch")
        rationale = str(params.get("rationale") or "")
        if len(rationale) > 4000:
            raise ValueError("Use a rationale of at most 4000 characters")
        tune.save_label(output, identity, str(params.get("label") or ""), rationale)
        return review(output)
    if method == "tuning.decide":
        # The native flow never enables the experimental acceptance override.
        tune.decide_candidate(output, str(params.get("decision") or ""))
        return review(output)
    if method == "tuning.start":
        if params.get("live") is not True:
            raise ValueError("Explicit live consent is required for model calls")
        stage = params.get("stage")
        if stage not in {"acquire", "optimize"}:
            raise ValueError("Choose example selection or optimization")
        if current["status"] != "review":
            raise ValueError("This experiment is not ready for another run")
        if stage == "acquire" and not current["needs_acquisition"]:
            raise ValueError("Review the current batch before selecting another")
        if stage == "optimize" and (current["needs_acquisition"] or current["review"]):
            raise ValueError("Label the current review batch before optimizing")
        options = current["options"]
        return service.start(
            project,
            "tuning",
            {
                "project": project,
                "id": output.name,
                "stage": stage,
                "live": True,
                "harness": "systemone",
                "reflection_model": options["reflection_lm"],
                "command_id": params.get("command_id"),
            },
        )
    raise ValueError("Unknown native tuning action")


def run(request, emit, *, client=None, optimizer=None):
    import signal
    import threading

    output = directory(Path(request["state_root"]), request["project"], request["id"])
    cancelled = threading.Event()
    previous = signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
    try:

        def progress(message):
            if cancelled.is_set():
                raise tune.TuneCancelled("Stopped in SuperQode Desktop")
            emit("stage", {"message": message})

        if request["stage"] == "acquire":
            tune.acquire_review_batch(output, client=client, progress=progress)
        else:
            tune.run_tune(
                output, client=client, optimizer=optimizer, progress=progress, cancel=cancelled
            )
        emit("result", {"tuning_id": output.name, "round": review(output)["round"]})
    finally:
        signal.signal(signal.SIGTERM, previous)
