"""Shared, staged decision tuning for the CLI and Textual UI.

Only text leaves of a single Choice question may evolve. Labels, schema,
transport and decision policy stay frozen; sealed examples never reach GEPA.
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import hashlib
import json
import os
import random
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .config import build_client, resolve_systemone
from .decision import evaluate_decision, parse_state
from .pack import QuestionPack, load_pack
from .state import prepare_decision_state
from .types import ChoiceQuestion

GEPA_REQUIREMENT = (
    "gepa @ git+https://github.com/gepa-ai/gepa.git@15ee314f9c7d34ec153b809d401f42f55c4dcd76"
)


class TuneCancelled(Exception):
    """A user stopped a tuning experiment."""


def install_support() -> str:
    """Explicit setup action targeting SuperQode's own Python environment."""
    import shlex
    import subprocess
    from superqode.providers.env_introspect import python_package_install_command

    command = shlex.split(python_package_install_command(GEPA_REQUIREMENT))
    command.extend(["cloudpickle>=3", "tqdm>=4.66.1"])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "Tuning support installation failed. Check your network and Python package installer."
        ) from exc
    if result.returncode:
        raise ValueError(
            "Tuning support installation failed. Check Git access to github.com/gepa-ai/gepa and package-index access."
        )
    return (
        "Tuning support installed. Restart SuperQode before tuning; saved judgments can be resumed."
    )


@dataclass
class TuneOptions:
    pack: str = "factory_route"
    spec: str = ""
    reflection_lm: str = ""
    max_evals: int = 120
    max_reflection_cost: float = 2.0
    seed: int = 0


def default_reflection_model() -> str:
    """Select only a provider with configured credentials, never subscription auth."""
    for key, model in (
        ("OPENAI_API_KEY", "openai/gpt-4.1-mini"),
        ("ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-6"),
        ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
    ):
        if os.environ.get(key):
            return model
    return ""


def load_tune_pack(options: TuneOptions) -> tuple[QuestionPack, Any]:
    from superqode.harness.loader import load_harness_spec

    spec = load_harness_spec(options.spec) if options.spec else None
    if spec and spec.runtime.backend != "systemone":
        raise ValueError(
            "Choose a SystemOne decision harness; coding-harness tuning uses harness optimize."
        )
    pack = load_pack(spec.systemone.pack if spec else options.pack)
    if pack.id == "tool_gate" or len(pack.questions) != 1:
        raise ValueError("Tune currently supports one Choice question, such as factory_route.")
    if not isinstance(next(iter(pack.questions.values())), ChoiceQuestion):
        raise ValueError("Tune currently supports Choice decisions with fixed labels.")
    return pack, spec


class PackCodec:
    """Expose string leaves without letting the optimizer change structure."""

    def __init__(self, pack: QuestionPack):
        self.baseline = pack.model_dump(mode="json")
        self.paths: dict[str, tuple] = {}
        self.seed: dict[str, str] = {}
        qid = next(iter(pack.questions))

        def walk(value, path):
            if isinstance(value, str):
                key = json.dumps(path, separators=(",", ":"))
                self.paths[key] = path
                self.seed[key] = value
            elif isinstance(value, dict):
                for key, child in value.items():
                    walk(child, (*path, key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, (*path, index))

        for field in ("instructions", "criteria"):
            walk(self.baseline["questions"][qid][field], ("questions", qid, field))

    def decode(self, candidate: dict[str, str]) -> QuestionPack:
        if not isinstance(candidate, dict) or candidate.keys() != self.seed.keys():
            raise ValueError("Candidate must preserve every question component.")
        result = deepcopy(self.baseline)
        for key, path in self.paths.items():
            text = candidate[key]
            if not isinstance(text, str) or not text.strip() or len(text) > 8000:
                raise ValueError("Each candidate component must contain 1–8000 characters.")
            target = result
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = text
        return QuestionPack.model_validate(result)


def read_examples(
    path: str | Path, *, input_column: str = "state", label_column: str = "label"
) -> list[dict]:
    """Import CSV, JSONL, JSON or YAML, including existing decision eval tasks."""
    path = Path(path).expanduser()
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Use an example file smaller than 10 MiB.")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        import io

        rows = list(csv.DictReader(io.StringIO(text)))
    elif path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        rows = yaml.safe_load(text)
        if isinstance(rows, dict):
            rows = rows.get("tasks", rows.get("examples"))
    if not isinstance(rows, list) or not rows or len(rows) > 5000:
        raise ValueError("Supply 1–5000 example rows.")
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Row {index + 1} must be an object.")
        state = row.get(input_column, row.get("prompt"))
        if state is None:
            raise ValueError(f"Row {index + 1} has no {input_column!r} input.")
        label = row.get(label_column)
        if label is None and isinstance(row.get("evaluator"), dict):
            expected = row["evaluator"].get("expected", {})
            if len(expected) == 1:
                label = next(iter(expected.values()))
        result.append(
            {
                "id": str(row.get("id") or index + 1),
                "state": state,
                "label": label if label != "" else None,
                "rationale": str(row.get("rationale") or ""),
                "split": str(row.get("split") or ""),
                "group": str(row.get("group") or ""),
            }
        )
    return result


def normalize_examples(rows: list[dict], pack: QuestionPack) -> list[dict]:
    options = next(iter(pack.questions.values())).criteria
    normalized, seen, ids = [], set(), set()
    for row in rows:
        row = dict(row)
        state = row["state"]
        if isinstance(state, str):
            state = parse_state(state, pack)
        row["state"] = prepare_decision_state(state, pack.state_schema)
        fingerprint = hashlib.sha256(json.dumps(row["state"], sort_keys=True).encode()).hexdigest()
        if fingerprint in seen or row["id"] in ids:
            raise ValueError("Duplicate inputs or IDs must be removed before splitting examples.")
        seen.add(fingerprint)
        ids.add(row["id"])
        row["fingerprint"] = fingerprint
        row["rationale"] = prepare_decision_state(str(row.get("rationale") or ""))
        label = row.get("label")
        if label is not None and (not isinstance(label, str) or label not in options):
            raise ValueError(
                f"Unknown label in example {row['id']!r}; choose from {', '.join(options)}."
            )
        normalized.append(row)
    return normalized


def split_examples(rows: list[dict], seed: int = 0) -> dict[str, list[dict]]:
    """Partition whole groups before annotation; preserve explicit sealed splits."""
    if len(rows) < 6:
        raise ValueError("Provide at least six distinct examples for train, validation and test.")
    aliases = {
        "held-in": "train",
        "held-out": "test",
        "validation": "validation",
        "train": "train",
        "test": "test",
    }
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("group") or row["fingerprint"], []).append(dict(row))
    explicit = any(row.get("split") for row in rows)
    partitions: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    if explicit:
        for members in groups.values():
            names = {aliases.get(row.get("split", "")) for row in members}
            if None in names or len(names) != 1:
                raise ValueError(
                    "Use explicit train/validation/test splits for every row; groups cannot cross splits."
                )
            partitions[names.pop()].extend(members)
        # Existing held-in/held-out eval packs have no validation partition.
        if not partitions["validation"]:
            train_groups = {}
            for row in partitions["train"]:
                train_groups.setdefault(row.get("group") or row["fingerprint"], []).append(row)
            keys = sorted(train_groups)
            random.Random(seed).shuffle(keys)
            if len(keys) < 2:
                raise ValueError("At least two independent held-in groups are required.")
            validation_keys = set(keys[: max(1, len(keys) // 4)])
            partitions["train"] = []
            for key, members in train_groups.items():
                partitions["validation" if key in validation_keys else "train"].extend(members)
    else:
        keys = sorted(groups)
        random.Random(seed).shuffle(keys)
        if len(keys) < 3:
            raise ValueError("Provide at least three independent groups.")
        n = max(1, len(keys) // 5)
        for index, key in enumerate(keys):
            name = "test" if index < n else "validation" if index < 2 * n else "train"
            partitions[name].extend(groups[key])
    if any(not part for part in partitions.values()):
        raise ValueError("Training, validation and sealed test must each contain examples.")
    for name, members in partitions.items():
        for row in members:
            row["split"] = name
    return partitions


def write_json(path: Path, value: Any) -> None:
    """Atomic, private experiment state; no provider credentials are persisted."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
    temporary.replace(path)


def prepare_run(options: TuneOptions, rows: list[dict], output: Path) -> dict:
    pack, spec = load_tune_pack(options)
    codec = PackCodec(pack)
    codec.decode(codec.seed)
    partitions = split_examples(normalize_examples(rows, pack), options.seed)
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Choose an empty output directory; existing experiments are never overwritten."
        )
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    from superqode.harness.loader import harness_spec_to_dict

    manifest = {
        "version": 1,
        "status": "review",
        "options": asdict(options),
        "pack": pack.model_dump(mode="json"),
        "harness": harness_spec_to_dict(spec) if spec else None,
        "examples": [row for part in partitions.values() for row in part],
    }
    write_json(output / "run.json", manifest)
    return manifest


def load_run(output: Path) -> dict:
    manifest = json.loads((output / "run.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("Unsupported Tune experiment version.")
    try:
        TuneOptions(**manifest["options"])
        pack = QuestionPack.model_validate(manifest["pack"])
        if (
            pack.id == "tool_gate"
            or len(pack.questions) != 1
            or not isinstance(next(iter(pack.questions.values())), ChoiceQuestion)
        ):
            raise ValueError("Saved experiment must contain one Choice question.")
        if manifest["status"] not in {"review", "running", "completed", "cancelled", "failed"}:
            raise ValueError("Invalid experiment status.")
        if not isinstance(manifest["examples"], list) or not manifest["examples"]:
            raise ValueError("Saved experiment has no examples.")
        for row in manifest["examples"]:
            if not isinstance(row, dict) or not {"id", "state", "split"} <= row.keys():
                raise ValueError("Invalid saved example.")
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid saved Tune experiment.") from exc
    return manifest


def save_label(output: Path, example_id: str, label: str, rationale: str = "") -> dict:
    if (output / "active.lock").exists():
        raise ValueError("An experiment is running; labels are frozen.")
    manifest = load_run(output)
    if manifest["status"] != "review":
        raise ValueError("Labels are frozen once an experiment starts.")
    pack = QuestionPack.model_validate(manifest["pack"])
    if label not in next(iter(pack.questions.values())).criteria:
        raise ValueError("Choose one of the decision's existing labels.")
    row = next(row for row in manifest["examples"] if row["id"] == example_id)
    row.update(label=label, rationale=prepare_decision_state(rationale))
    write_json(output / "run.json", manifest)
    return manifest


def new_output() -> Path:
    from uuid import uuid4

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path(".superqode/tuning") / f"{stamp}-{uuid4().hex[:6]}"


def demo_examples() -> list[dict]:
    """Synthetic routing examples, explicitly too small to qualify for adoption."""
    examples = {
        "private": [
            "Keep all code on this laptop; do not send it to cloud services.",
            "Analyze this confidential file using local OSS models only.",
            "No network or cloud handoff is permitted for this task.",
            "Work offline on the proprietary repository.",
        ],
        "cheap": [
            "Use a low-cost model to rename a variable.",
            "Add a straightforward unit test on the cheapest suitable model.",
            "Fix this spelling mistake cheaply.",
            "Use a budget model for this routine doc edit.",
        ],
        "review": [
            "Review this patch for security issues.",
            "Critique the proposed implementation.",
            "Review the pull request before merging.",
            "Check this code for correctness as a reviewer.",
        ],
    }
    return [
        {
            "id": f"demo-{label}-{i}",
            "state": text,
            "label": label,
            "rationale": "Synthetic starter example; replace with reviewed project cases.",
            "split": "",
            "group": "",
        }
        for label, texts in examples.items()
        for i, text in enumerate(texts)
    ]


def _settings(manifest: dict):
    from types import SimpleNamespace
    from superqode.harness.loader import harness_spec_from_dict

    spec = harness_spec_from_dict(manifest["harness"]) if manifest.get("harness") else None
    settings = resolve_systemone(
        spec=spec, explicit=None if spec else SimpleNamespace(enabled=True, client="live")
    )
    if settings.skip_client or not settings.enabled or settings.client != "live":
        raise ValueError(
            "Tune needs live Jev evaluation. Check SystemOne settings and API credentials; stub/replay cannot measure new prompts."
        )
    return settings


def preflight(manifest: dict, *, check_gepa: bool = True) -> dict:
    options = TuneOptions(**manifest["options"])
    if options.max_evals < 1 or not 0 < options.max_reflection_cost <= 1000:
        raise ValueError(
            "Set a positive evaluation budget and a reflection limit between $0 and $1000."
        )
    if not options.reflection_lm.strip():
        raise ValueError(
            "Choose a reflection model (provider/model) or configure OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY."
        )
    settings = _settings(manifest)
    if check_gepa:
        try:
            from gepa.optimize_anything import OptimizeAnythingConfig, optimize_anything  # noqa: F401
        except ImportError as exc:
            raise ValueError(
                "Tuning support is not installed or is out of date. Run: superqode harness tune --setup, then restart SuperQode."
            ) from exc
    return {
        "endpoint": settings.endpoint,
        "model": settings.model,
        "reflection_model": options.reflection_lm,
        "max_evals": options.max_evals,
        "max_reflection_cost": options.max_reflection_cost,
        "final_test_evals": 2 * sum(row["split"] == "test" for row in manifest["examples"]),
    }


def summarize(rows: list[dict]) -> dict:
    count = len(rows)
    decided = sum(row["status"] == "decided" for row in rows)
    correct = sum(row["correct"] for row in rows)
    labels = sorted({row["expected"] for row in rows})
    per_class = {}
    for label in labels:
        tp = sum(row["correct"] and row["expected"] == label for row in rows)
        actual = sum(row["expected"] == label for row in rows)
        predicted = sum(row.get("predicted") == label for row in rows)
        per_class[label] = {
            "recall": tp / actual if actual else 0,
            "f1": 2 * tp / (actual + predicted) if actual + predicted else 0,
        }
    return {
        "total": count,
        "correct": correct,
        "score": correct / count if count else 0,
        "coverage": decided / count if count else 0,
        "accuracy_when_decided": correct / decided if decided else None,
        "abstentions": sum(row["status"] == "abstain" for row in rows),
        "errors": sum(row["status"] == "error" for row in rows),
        "macro_f1": sum(item["f1"] for item in per_class.values()) / len(labels) if labels else 0,
        "per_class": per_class,
    }


def run_tune(output: Path, **kwargs) -> dict:
    """Prevent simultaneous CLI/TUI experiments from spending the same budget."""
    lock = output / "active.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "This experiment is already active. Inspect active.lock before recovering a terminated process."
        ) from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        return _run_tune_locked(output, **kwargs)
    finally:
        lock.unlink(missing_ok=True)


def _run_tune_locked(
    output: Path,
    *,
    progress: Callable[[str], None] = lambda _: None,
    cancel: threading.Event | None = None,
    client=None,
    optimizer=None,
) -> dict:
    """Run synchronously in a worker; sealed data stays outside optimizer scope.

    Client/optimizer injection is exclusively for deterministic offline tests.
    An interrupted optimization is not silently resumed with a fresh budget.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise ValueError("Run Tune in a worker thread, outside the active event loop.")
    manifest = load_run(output)
    if manifest["status"] == "completed":
        return json.loads((output / "report.json").read_text())
    if manifest["status"] != "review":
        raise ValueError(
            "This experiment already started. Inspect its evidence or start a new bounded experiment."
        )
    if any(row.get("label") is None for row in manifest["examples"]):
        raise ValueError("Review every example before starting optimization.")
    options = TuneOptions(**manifest["options"])
    pack = QuestionPack.model_validate(manifest["pack"])
    codec = PackCodec(pack)
    # Revalidate persisted inputs and split ownership before any model call.
    partitions = split_examples(normalize_examples(manifest["examples"], pack), options.seed)
    if client is None:
        preflight(manifest)
        client = build_client(_settings(manifest))
    if options.max_evals < len(partitions["validation"]):
        raise ValueError("Evaluation budget must cover at least the validation baseline.")
    if optimizer is None:
        optimizer = _gepa_optimize
    cancelled = cancel or threading.Event()
    count = 0
    journal: list[dict] = []

    def check_cancel():
        if cancelled.is_set():
            raise TuneCancelled("Stopped. Completed evaluations and reviewed labels were saved.")

    def evaluate(candidate, example):
        nonlocal count
        check_cancel()
        if count >= options.max_evals:
            raise ValueError("Tune evaluation budget exhausted.")
        count += 1
        candidate_pack = codec.decode(candidate)
        row = score(candidate_pack, example)
        journal.append({"phase": "optimization", "pack_hash": candidate_pack.content_hash(), **row})
        write_json(output / "evaluations.json", journal)
        progress(f"Improving decisions · evaluation {count}/{options.max_evals}")
        return float(row["correct"]), {
            "state": example["state"],
            "expected": example["label"],
            "predicted": row["predicted"],
            "status": row["status"],
            "human_rationale": example.get("rationale", ""),
            "answers": row.get("answers", {}),
        }

    def score(candidate_pack, example):
        check_cancel()
        try:
            decision = asyncio.run(evaluate_decision(client, example["state"], candidate_pack))
            predicted = next(iter(decision.outputs.values()))
            return {
                "id": example["id"],
                "expected": example["label"],
                "predicted": predicted,
                "status": decision.status,
                "correct": decision.status == "decided" and predicted == example["label"],
                "answers": decision.answers,
                "metadata": decision.metadata,
            }
        except TuneCancelled:
            raise
        except Exception:
            return {
                "id": example["id"],
                "expected": example["label"],
                "predicted": None,
                "status": "error",
                "correct": False,
            }

    manifest["status"] = "running"
    write_json(output / "run.json", manifest)
    try:
        progress("Testing question variants against reviewed examples…")
        result = optimizer(
            seed_candidate=codec.seed,
            evaluator=evaluate,
            dataset=partitions["train"],
            valset=partitions["validation"],
            options=options,
            output=output,
            cancel=cancelled,
        )
        check_cancel()
        candidate_pack = codec.decode(result.best_candidate)
        baseline_text = yaml.safe_dump(pack.model_dump(mode="json"), sort_keys=False)
        candidate_text = yaml.safe_dump(candidate_pack.model_dump(mode="json"), sort_keys=False)
        (output / "baseline-pack.yaml").write_text(baseline_text)
        (output / "candidate-pack.yaml").write_text(candidate_text)
        diff = "".join(
            difflib.unified_diff(
                baseline_text.splitlines(True),
                candidate_text.splitlines(True),
                fromfile="baseline-pack.yaml",
                tofile="candidate-pack.yaml",
            )
        )
        (output / "changes.diff").write_text(diff)
        progress("Checking baseline and candidate on sealed examples…")
        baseline, candidate = [], []
        for example in partitions["test"]:
            baseline.append(score(pack, example))
            candidate.append(score(candidate_pack, example))
            write_json(output / "heldout.json", {"baseline": baseline, "candidate": candidate})
        check_cancel()
        before, after = summarize(baseline), summarize(candidate)
        regressions = [
            a["id"] for a, b in zip(baseline, candidate) if a["correct"] and not b["correct"]
        ]
        improved = (
            candidate_pack.content_hash() != pack.content_hash()
            and after["score"] > before["score"]
        )
        gate_passed = improved and not regressions and not before["errors"] and not after["errors"]
        # Small runs are useful plumbing, but cannot qualify for adoption.
        pilot = len(partitions["test"]) < 30 or len(partitions["train"]) < 30
        harness = deepcopy(manifest.get("harness")) or {
            "version": 1,
            "name": f"{pack.id}-tuned",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "client": "live"},
        }
        harness.pop("inherits", None)
        harness["systemone"]["pack"] = "./candidate-pack.yaml"
        (output / "candidate-harness.yaml").write_text(yaml.safe_dump(harness, sort_keys=False))
        from superqode.harness.loader import load_harness_spec

        load_harness_spec(output / "candidate-harness.yaml")
        report = {
            "status": "completed",
            "baseline": before,
            "candidate": after,
            "regressions": regressions,
            "improved": improved,
            "gate_passed": gate_passed,
            "pilot": pilot,
            "eligible": gate_passed and not pilot,
            "optimization_evals": count,
            "heldout_evals": 2 * len(baseline),
            "reflection_model": options.reflection_lm,
            "max_reflection_cost": options.max_reflection_cost,
            "baseline_pack_hash": pack.content_hash(),
            "candidate_pack_hash": candidate_pack.content_hash(),
            "dataset_hash": hashlib.sha256(
                json.dumps(manifest["examples"], sort_keys=True).encode()
            ).hexdigest(),
            "split_counts": {name: len(rows) for name, rows in partitions.items()},
            "optimizer": "gepa",
            "optimizer_source": GEPA_REQUIREMENT,
            "reflection_cost_usd": (getattr(result, "metadata", {}) or {}).get("adapter_cost"),
            "candidate_harness": str((output / "candidate-harness.yaml").resolve()),
            "candidate_harness_hash": hashlib.sha256(
                (output / "candidate-harness.yaml").read_bytes()
            ).hexdigest(),
            "diff": diff,
            "cost_note": "Reflection limit excludes Jev evaluation usage; unknown costs remain unknown.",
        }
        write_json(output / "report.json", report)
        manifest["status"] = "completed"
        progress("Finished. Candidate and comparison saved; the active harness was not changed.")
        return report
    except BaseException as exc:
        manifest["status"] = (
            "cancelled" if isinstance(exc, (TuneCancelled, KeyboardInterrupt)) else "failed"
        )
        raise
    finally:
        write_json(output / "run.json", manifest)


class _TuneLogger:
    """Keep GEPA diagnostics out of CLI JSON and the active TUI terminal."""

    def __init__(self, path: Path):
        self.path = path

    def log(self, message):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(str(message) + "\n")


def _gepa_optimize(*, seed_candidate, evaluator, dataset, valset, options, output, cancel=None):
    from gepa.optimize_anything import OptimizeAnythingConfig, optimize_anything

    return optimize_anything(
        seed_candidate=seed_candidate,
        evaluator=evaluator,
        dataset=dataset,
        valset=valset,
        objective="Improve exact decision correctness against human-reviewed labels. Abstention is unresolved, not correct.",
        background="Only improve supplied instruction and criterion text. Preserve the meaning of labels. Use rationales to clarify boundaries; do not memorize individual examples.",
        config=OptimizeAnythingConfig(
            engine="gepa",
            max_evals=options.max_evals,
            max_token_cost=options.max_reflection_cost,
            max_concurrency=1,
            stop_at_score=1.0,
            output_dir=output / "gepa",
            run_dir=str(output / "gepa" / "engine"),
            engine_config={
                "tracking": {"logger": _TuneLogger(output / "optimizer.log")},
                "stop_callbacks": [lambda state: cancel.is_set()] if cancel else [],
                "engine": {
                    "seed": options.seed,
                    "parallel": False,
                    "max_workers": 1,
                    "cache_evaluation": False,
                    "display_progress_bar": False,
                },
                "reflection": {
                    "reflection_lm": options.reflection_lm,
                    "module_selector": "round_robin",
                },
            },
        ),
    )


def render_report(report: dict) -> str:
    before, after = report["baseline"], report["candidate"]
    verdict = "Improved" if report["improved"] else "No demonstrated improvement"
    if report["regressions"]:
        verdict += " · regressions found"
    if report["pilot"]:
        verdict += " · small pilot, more independent examples needed before adoption"
    return (
        f"{verdict}\n"
        f"Sealed examples correct: {before['correct']}/{before['total']} → {after['correct']}/{after['total']}\n"
        f"Abstentions: {before['abstentions']} → {after['abstentions']} · errors: {before['errors']} → {after['errors']}\n"
        f"Eligible for adoption: {'yes' if report['eligible'] else 'no'}\n"
        f"Staged harness: {report['candidate_harness']}\n"
        "The active harness is unchanged. Review changes.diff and report.json before using a candidate."
    )


def candidate_use_path(report: dict) -> str:
    """Verify that the pack selected in the UI is the one actually evaluated."""
    from superqode.harness.loader import load_harness_spec

    if not report.get("eligible"):
        raise ValueError("This candidate did not qualify for adoption.")
    path = report["candidate_harness"]
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != report["candidate_harness_hash"]:
        raise ValueError("The staged decision harness has changed since evaluation.")
    spec = load_harness_spec(path)
    if not spec.is_decision or spec.runtime.backend != "systemone":
        raise ValueError("The staged decision harness has changed since evaluation.")
    if load_pack(spec.systemone.pack).content_hash() != report["candidate_pack_hash"]:
        raise ValueError(
            "The staged question pack has changed since evaluation. Run a new comparison."
        )
    return path
