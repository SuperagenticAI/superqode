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


def tuning_support_available() -> bool:
    """True when GEPA optimize_anything imports in this process."""
    try:
        from gepa.optimize_anything import OptimizeAnythingConfig, optimize_anything  # noqa: F401
    except ImportError:
        return False
    return True


def refresh_tuning_support_import() -> bool:
    """Clear stale import failures so a just-installed GEPA can load without restart."""
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "gepa" or name.startswith("gepa."):
            del sys.modules[name]
    importlib.invalidate_caches()
    return tuning_support_available()


def install_support() -> str:
    """Explicit setup action targeting SuperQode's own Python environment.

    Installs GEPA (and light deps) into the same interpreter SuperQode is running.
    After install we refresh imports so most users can continue without restarting the TUI.
    """
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
    if refresh_tuning_support_import():
        return (
            "Tuning support is ready in this session. You can Prepare examples and Start without restarting. "
            "Your reflection model preference is saved automatically."
        )
    return (
        "Tuning support installed, but this session still cannot import it. "
        "Restart SuperQode once, then open :systemone tune again. "
        "Your reflection model preference is restored automatically; saved judgments can be resumed."
    )


@dataclass
class TuneOptions:
    pack: str = "factory_route"
    spec: str = ""
    reflection_lm: str = ""
    max_evals: int = 120
    max_reflection_cost: float = 2.0
    seed: int = 0
    batch_size: int = 5


def tune_preferences_path() -> Path:
    """User preference file for Tune UI defaults (no secrets)."""
    return Path.home() / ".superqode" / "tune-preferences.json"


def load_tune_preferences() -> dict:
    path = tune_preferences_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_tune_preferences(**updates: str | int | float) -> None:
    """Persist non-secret Tune UI choices when the user directory is writable.

    Preferences improve the next launch, but they must never block preparing,
    labeling, or starting an experiment.
    """
    path = tune_preferences_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        current = load_tune_preferences()
        for key, value in updates.items():
            if value is None or value == "":
                current.pop(key, None)
            else:
                current[key] = value
        temporary = path.with_suffix(".tmp")
        write_json(temporary, current)
        temporary.replace(path)
    except OSError:
        # The experiment manifest remains authoritative and is stored under
        # the workspace. A read-only home should only lose this convenience.
        return


def preferred_reflection_model() -> str:
    """Last Tune reflection model if set; otherwise credential-based default."""
    saved = str(load_tune_preferences().get("reflection_lm") or "").strip()
    return saved or default_reflection_model()


def default_reflection_model() -> str:
    """Select only a provider with configured credentials, never subscription auth."""
    for key, model in (
        ("OPENAI_API_KEY", "openai/gpt-4.1-mini"),
        ("ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-6"),
        ("GEMINI_API_KEY", "gemini/gemini-3.6-flash"),
    ):
        if os.environ.get(key):
            return model
    return ""


def reflection_api_key_env(model: str) -> str | None:
    """Env var required for this reflection model id, when the provider is known."""
    name = (model or "").strip().lower()
    if not name:
        return None
    provider = name.split("/", 1)[0]
    return {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
    }.get(provider)


def missing_tune_credentials(
    *, reflection_lm: str = "", api_key_env: str = "TYPESAFE_API_KEY"
) -> list[str]:
    """Blockers that would make Start do nothing useful without a clear error."""
    missing: list[str] = []
    key_env = str(api_key_env).strip()
    if key_env and not str(os.environ.get(key_env) or "").strip():
        missing.append(
            f"Set {key_env} for live Jev scoring (export {key_env}=... in this shell, then restart SuperQode)."
        )
    model = (reflection_lm or "").strip()
    if not model:
        missing.append(
            "Choose a reflection model (provider/model), or set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY so a default can be chosen."
        )
    else:
        provider_env = reflection_api_key_env(model)
        if provider_env and not str(os.environ.get(provider_env) or "").strip():
            missing.append(
                f"Reflection model {model} needs {provider_env} (export {provider_env}=..., then restart SuperQode)."
            )
    return missing


def format_missing_tune_credentials(missing: list[str]) -> str:
    if not missing:
        return ""
    lines = ["Cannot start the experiment yet:"]
    lines.extend(f"• {item}" for item in missing)
    lines.append("Fix the items above, then click Start experiment again.")
    return "\n".join(lines)


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
        "workflow": "active" if all(row.get("label") is None for row in rows) else "batch",
        "round": 1,
        "history": [],
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
        manifest["options"].setdefault("batch_size", 5)
        manifest.setdefault("workflow", "batch")
        manifest.setdefault("round", 1)
        manifest.setdefault("history", [])
        TuneOptions(**manifest["options"])
        pack = QuestionPack.model_validate(manifest["pack"])
        if (
            pack.id == "tool_gate"
            or len(pack.questions) != 1
            or not isinstance(next(iter(pack.questions.values())), ChoiceQuestion)
        ):
            raise ValueError("Saved experiment must contain one Choice question.")
        if manifest["status"] not in {
            "review",
            "running",
            "decision",
            "completed",
            "cancelled",
            "failed",
        }:
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
    if manifest.get("workflow") == "active" and row.get("selected_round") != int(
        manifest.get("round") or 1
    ):
        raise ValueError("Only examples selected for the current round can be labelled.")
    row.update(label=label, rationale=prepare_decision_state(rationale))
    write_json(output / "run.json", manifest)
    return manifest


def review_batch(manifest: dict) -> list[dict]:
    """Return the current round's selected, still-unlabelled examples."""
    if manifest.get("workflow") != "active":
        return [row for row in manifest["examples"] if row.get("label") is None]
    round_number = int(manifest.get("round") or 1)
    return [
        row
        for row in manifest["examples"]
        if row.get("label") is None and row.get("selected_round") == round_number
    ]


def _choice_ambiguity(answer: dict) -> float:
    """Normalize Choice uncertainty to 0 (clear) through 1 (ambiguous)."""
    probabilities = answer.get("probabilities") or {}
    if isinstance(probabilities, dict) and len(probabilities) >= 2:
        ranked = sorted((float(value) for value in probabilities.values()), reverse=True)
        return max(0.0, min(1.0, 1.0 - (ranked[0] - ranked[1])))
    return max(0.0, min(1.0, 1.0 - float(answer.get("confidence") or 0.0)))


def acquire_review_batch(
    output: Path,
    *,
    client=None,
    progress: Callable[[str], None] = lambda _: None,
) -> list[dict]:
    """Prevent CLI and TUI from scoring the same pool concurrently."""
    lock = output / "acquisition.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("This experiment is already selecting a review batch.") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        return _acquire_review_batch(output, client=client, progress=progress)
    finally:
        lock.unlink(missing_ok=True)


def _acquire_review_batch(
    output: Path,
    *,
    client=None,
    progress: Callable[[str], None] = lambda _: None,
) -> list[dict]:
    """Select uncertain development rows plus a random audit and sealed sample.

    Selection is persisted before any labels are collected, so resume never
    silently changes the batch. Reserved test rows are sampled randomly and
    are not evaluated during acquisition.
    """
    manifest = load_run(output)
    if manifest.get("workflow") != "active":
        return review_batch(manifest)
    if manifest["status"] != "review":
        raise ValueError("Resolve the pending candidate before selecting another review batch.")
    pending = review_batch(manifest)
    if pending:
        return pending
    options = TuneOptions(**manifest["options"])
    round_number = int(manifest.get("round") or 1)
    if not 2 <= options.batch_size <= 20:
        raise ValueError("Review batch size must be between 2 and 20.")
    pack = QuestionPack.model_validate(manifest["pack"])
    candidates = [
        row for row in manifest["examples"] if row["split"] != "test" and row.get("label") is None
    ]
    if not candidates:
        raise ValueError("No unlabelled development examples remain.")
    qid = next(iter(pack.questions))
    cache_path = output / "pool-predictions.json"
    cached_rows: dict[str, dict] = {}
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("pack_hash") == pack.content_hash():
                cached_rows = {row["id"]: row for row in cached.get("rows", [])}
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            cached_rows = {}
    scored = [cached_rows[row["id"]] for row in candidates if row["id"] in cached_rows]
    missing = [row for row in candidates if row["id"] not in cached_rows]
    if missing and client is None:
        preflight_acquisition(manifest)
        client = build_client(_settings(manifest))
    for index, row in enumerate(missing, start=1):
        progress(f"Finding uncertain examples · {index}/{len(missing)}")
        try:
            decision = asyncio.run(evaluate_decision(client, row["state"], pack))
            ambiguity = _choice_ambiguity(decision.answers[qid])
            predicted = decision.outputs[qid]
        except Exception as exc:
            raise ValueError(
                "Jev could not score the review pool. No examples were selected; check the endpoint and try again."
            ) from exc
        scored.append(
            {
                "id": row["id"],
                "ambiguity": ambiguity,
                "predicted": predicted,
                "pack_hash": pack.content_hash(),
            }
        )
    write_json(
        cache_path,
        {"round": manifest.get("round", 1), "pack_hash": pack.content_hash(), "rows": scored},
    )
    by_id = {row["id"]: row for row in manifest["examples"]}
    ranked = sorted(scored, key=lambda row: (-row["ambiguity"], row["id"]))
    count = min(options.batch_size, len(ranked))
    uncertain_count = max(1, count - 1)
    selected = ranked[:uncertain_count]
    selected_ids = {row["id"] for row in selected}
    remainder = [row for row in ranked if row["id"] not in selected_ids]
    audit_id = None
    if remainder and len(selected) < count:
        audit = random.Random(options.seed + int(manifest.get("round") or 1)).sample(remainder, 1)[
            0
        ]
        audit_id = audit["id"]
        selected.append(audit)
    # Keep both optimizer-visible partitions represented whenever possible.
    for split_name in ("train", "validation"):
        if any(by_id[item["id"]]["split"] == split_name for item in selected):
            continue
        replacement = next(
            (item for item in ranked if by_id[item["id"]]["split"] == split_name), None
        )
        if replacement is not None and selected:
            replace_at = next(
                (
                    index
                    for index in range(len(selected) - 1, -1, -1)
                    if selected[index]["id"] != audit_id
                ),
                len(selected) - 1,
            )
            selected[replace_at] = replacement
    # De-duplicate after a partition replacement, then refill by uncertainty.
    selected_by_id = {item["id"]: item for item in selected}
    for item in ranked:
        if len(selected_by_id) >= count:
            break
        selected_by_id.setdefault(item["id"], item)
    selected = list(selected_by_id.values())
    round_number = int(manifest.get("round") or 1)
    most_uncertain = {row["id"] for row in ranked[:uncertain_count]}
    for item in selected:
        row = by_id[item["id"]]
        row.update(
            selected_round=round_number,
            acquired_by="audit" if item["id"] == audit_id else "uncertain",
            ambiguity=item["ambiguity"],
        )
    test_rows = [
        row for row in manifest["examples"] if row["split"] == "test" and row.get("label") is None
    ]
    holdout_count = min(max(1, round(count * 0.2)), len(test_rows))
    if holdout_count:
        rng = random.Random(options.seed + round_number)
        for row in rng.sample(test_rows, holdout_count):
            row.update(selected_round=round_number, acquired_by="holdout")
    write_json(output / "run.json", manifest)
    return review_batch(manifest)


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
        missing = missing_tune_credentials(
            reflection_lm=str((manifest.get("options") or {}).get("reflection_lm") or ""),
            api_key_env=getattr(settings, "api_key_env", "TYPESAFE_API_KEY"),
        )
        if missing:
            raise ValueError(format_missing_tune_credentials(missing))
        raise ValueError(
            "Tune needs live Jev evaluation. Check SystemOne settings and API credentials; stub/replay cannot measure new prompts."
        )
    return settings


def preflight(manifest: dict, *, check_gepa: bool = True) -> dict:
    options = TuneOptions(**manifest["options"])
    if (
        options.max_evals < 1
        or not 0 < options.max_reflection_cost <= 1000
        or not 2 <= options.batch_size <= 20
    ):
        raise ValueError(
            "Set a positive evaluation budget, a reflection limit between $0 and $1000, and a review batch size from 2 to 20."
        )
    reflection = options.reflection_lm.strip()
    # Peek at SystemOne config for the expected live key name without requiring live yet.
    from types import SimpleNamespace
    from superqode.harness.loader import harness_spec_from_dict
    from superqode.systemone.config import resolve_systemone

    spec = harness_spec_from_dict(manifest["harness"]) if manifest.get("harness") else None
    probe = resolve_systemone(
        spec=spec, explicit=None if spec else SimpleNamespace(enabled=True, client="live")
    )
    missing = missing_tune_credentials(
        reflection_lm=reflection, api_key_env=getattr(probe, "api_key_env", "TYPESAFE_API_KEY")
    )
    if missing:
        raise ValueError(format_missing_tune_credentials(missing))
    settings = _settings(manifest)
    if check_gepa:
        try:
            from gepa.optimize_anything import OptimizeAnythingConfig, optimize_anything  # noqa: F401
        except ImportError as exc:
            raise ValueError(
                "Tuning support is not installed. Click Install tuning support in this screen, or run: superqode harness tune --setup."
            ) from exc
    return {
        "endpoint": settings.endpoint,
        "model": settings.model,
        "reflection_model": options.reflection_lm,
        "max_evals": options.max_evals,
        "max_reflection_cost": options.max_reflection_cost,
        "final_test_evals": 2
        * sum(
            row["split"] == "test" and row.get("label") is not None for row in manifest["examples"]
        ),
    }


def preflight_acquisition(manifest: dict) -> dict:
    """Validate only the Jev side needed to rank an unlabeled pool."""
    from types import SimpleNamespace
    from superqode.harness.loader import harness_spec_from_dict

    spec = harness_spec_from_dict(manifest["harness"]) if manifest.get("harness") else None
    probe = resolve_systemone(
        spec=spec, explicit=None if spec else SimpleNamespace(enabled=True, client="live")
    )
    api_key_env = str(getattr(probe, "api_key_env", "TYPESAFE_API_KEY") or "").strip()
    if api_key_env and not str(os.environ.get(api_key_env) or "").strip():
        raise ValueError(
            format_missing_tune_credentials(
                [
                    f"Set {api_key_env} for live Jev scoring (export {api_key_env}=... in this shell, then restart SuperQode)."
                ]
            )
        )
    settings = _settings(manifest)
    return {"endpoint": settings.endpoint, "model": settings.model}


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
    if manifest["status"] == "decision":
        return json.loads((output / "report.json").read_text())
    if manifest["status"] != "review":
        raise ValueError(
            "This experiment already started. Inspect its evidence or start a new bounded experiment."
        )
    if manifest.get("workflow") == "active":
        selected = [
            row
            for row in manifest["examples"]
            if row.get("selected_round") == int(manifest.get("round") or 1)
        ]
        if not selected:
            raise ValueError("Select a review batch before starting optimization.")
        if any(row.get("label") is None for row in selected):
            raise ValueError("Review every selected example before starting optimization.")
    elif any(row.get("label") is None for row in manifest["examples"]):
        raise ValueError("Review every example before starting optimization.")
    options = TuneOptions(**manifest["options"])
    active_workflow = manifest.get("workflow") == "active"
    round_number = int(manifest.get("round") or 1)
    round_output = output / "rounds" / f"round-{round_number:04d}" if active_workflow else output
    round_output.mkdir(parents=True, exist_ok=True)
    pack = QuestionPack.model_validate(manifest["pack"])
    codec = PackCodec(pack)
    # Revalidate persisted inputs and split ownership before any model call.
    partitions = split_examples(normalize_examples(manifest["examples"], pack), options.seed)
    if manifest.get("workflow") == "active":
        partitions = {
            name: [row for row in rows if row.get("label") is not None]
            for name, rows in partitions.items()
        }
        if any(not rows for rows in partitions.values()):
            raise ValueError(
                "This round needs reviewed training, validation, and reserved-test examples. Select another batch or add explicit splits."
            )
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
        write_json(round_output / "evaluations.json", journal)
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
            output=round_output,
            cancel=cancelled,
        )
        check_cancel()
        candidate_pack = codec.decode(result.best_candidate)
        baseline_text = yaml.safe_dump(pack.model_dump(mode="json"), sort_keys=False)
        candidate_text = yaml.safe_dump(candidate_pack.model_dump(mode="json"), sort_keys=False)
        prefix = f"round-{round_number:04d}-" if active_workflow else ""
        baseline_path = output / f"{prefix}baseline-pack.yaml"
        candidate_path = output / f"{prefix}candidate-pack.yaml"
        harness_path = output / f"{prefix}candidate-harness.yaml"
        diff_path = output / f"{prefix}changes.diff"
        baseline_path.write_text(baseline_text)
        candidate_path.write_text(candidate_text)
        diff = "".join(
            difflib.unified_diff(
                baseline_text.splitlines(True),
                candidate_text.splitlines(True),
                fromfile=baseline_path.name,
                tofile=candidate_path.name,
            )
        )
        diff_path.write_text(diff)
        progress("Checking baseline and candidate on sealed examples…")
        baseline, candidate = [], []
        for example in partitions["test"]:
            baseline.append(score(pack, example))
            candidate.append(score(candidate_pack, example))
            write_json(
                round_output / "heldout.json", {"baseline": baseline, "candidate": candidate}
            )
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
        # Training and validation are both optimizer-visible development data.
        # Small runs are useful plumbing, but cannot qualify for adoption.
        development_count = len(partitions["train"]) + len(partitions["validation"])
        pilot = len(partitions["test"]) < 30 or development_count < 30
        harness = deepcopy(manifest.get("harness")) or {
            "version": 1,
            "name": f"{pack.id}-tuned",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "client": "live"},
        }
        harness.pop("inherits", None)
        harness["systemone"]["pack"] = f"./{candidate_path.name}"
        harness_path.write_text(yaml.safe_dump(harness, sort_keys=False))
        from superqode.harness.loader import load_harness_spec

        load_harness_spec(harness_path)
        report = {
            "status": "pending_decision" if active_workflow else "completed",
            "round": round_number,
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
            "candidate_harness": str(harness_path.resolve()),
            "candidate_harness_hash": hashlib.sha256(harness_path.read_bytes()).hexdigest(),
            "diff": diff,
            "cost_note": "Reflection limit excludes Jev evaluation usage; unknown costs remain unknown.",
        }
        write_json(output / "report.json", report)
        if active_workflow:
            write_json(round_output / "report.json", report)
        manifest["status"] = "decision" if active_workflow else "completed"
        progress(
            "Finished. Review and accept or reject the candidate."
            if active_workflow
            else "Finished. Candidate and comparison saved; the active harness was not changed."
        )
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
    decision = ""
    if report.get("status") == "pending_decision":
        decision = "\nDecision pending: accept, reject, or resume later."
    elif report.get("decision"):
        decision = f"\nDecision: {report['decision']}"
    return (
        f"{verdict}\n"
        f"Sealed examples correct: {before['correct']}/{before['total']} → {after['correct']}/{after['total']}\n"
        f"Abstentions: {before['abstentions']} → {after['abstentions']} · errors: {before['errors']} → {after['errors']}\n"
        f"Eligible for adoption: {'yes' if report['eligible'] else 'no'}\n"
        f"Staged harness: {report['candidate_harness']}\n"
        "The active harness is unchanged. Review the saved diff and report before using a candidate."
        + decision
    )


def decide_candidate(
    output: Path,
    decision: str,
    *,
    allow_experimental: bool = False,
) -> dict:
    """Persist a human accept/reject decision and advance an active session."""
    if decision not in {"accept", "reject"}:
        raise ValueError("Decision must be accept or reject.")
    manifest = load_run(output)
    if manifest.get("workflow") != "active" or manifest["status"] != "decision":
        raise ValueError("This experiment has no pending candidate decision.")
    report = json.loads((output / "report.json").read_text())
    adoption = None
    if decision == "accept":
        if not report.get("eligible") and not allow_experimental:
            raise ValueError(
                "This candidate is not verified. Accept it explicitly as experimental or reject it."
            )
        if not report.get("eligible") and report.get("candidate", {}).get("errors"):
            raise ValueError("A candidate with evaluation errors cannot be accepted.")
        from superqode.harness.loader import load_harness_spec

        if (
            hashlib.sha256(Path(report["candidate_harness"]).read_bytes()).hexdigest()
            != report["candidate_harness_hash"]
        ):
            raise ValueError("The staged decision harness has changed since evaluation.")
        spec = load_harness_spec(report["candidate_harness"])
        candidate_pack = load_pack(spec.systemone.pack)
        if candidate_pack.content_hash() != report["candidate_pack_hash"]:
            raise ValueError("The staged question pack has changed since evaluation.")
        manifest["pack"] = candidate_pack.model_dump(mode="json")
        adoption = "verified" if report.get("eligible") else "experimental"
    report.update(
        status="accepted" if decision == "accept" else "rejected",
        decision=decision,
        adoption=adoption,
    )
    manifest.setdefault("history", []).append(
        {
            "round": int(manifest.get("round") or 1),
            "decision": decision,
            "adoption": adoption,
            "candidate_pack_hash": report["candidate_pack_hash"],
            "baseline": report["baseline"],
            "candidate": report["candidate"],
            "candidate_harness": report["candidate_harness"],
        }
    )
    remaining = any(
        row["split"] != "test" and row.get("label") is None for row in manifest["examples"]
    )
    if remaining:
        manifest["round"] = int(manifest.get("round") or 1) + 1
        manifest["status"] = "review"
    else:
        manifest["status"] = "completed"
    write_json(output / "report.json", report)
    round_report = output / "rounds" / f"round-{int(report.get('round') or 1):04d}" / "report.json"
    if round_report.parent.is_dir():
        write_json(round_report, report)
    write_json(output / "run.json", manifest)
    return report


def candidate_use_path(report: dict) -> str:
    """Verify that the pack selected in the UI is the one actually evaluated."""
    from superqode.harness.loader import load_harness_spec

    if not report.get("eligible") and report.get("decision") != "accept":
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
