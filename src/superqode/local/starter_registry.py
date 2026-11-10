"""Curated tags plus explicit, machine-scoped local evaluation evidence."""

import json
import math
from urllib.parse import urlsplit
from pathlib import Path

from .context_contract import choose_contract

SUITE_VERSION = "local-coding-v1"
TASK_IDS = ("edit_file", "run_test", "fix_test", "multi_step", "json_tool_call")


def registry():
    """Shipped entries are catalog verified, never claimed to be model tested."""
    return json.loads((Path(__file__).parent / "data/starter_models.json").read_text())["models"]


def evidence_path():
    return Path.home() / ".superqode/local-model-evals.json"


def memory_tier(memory):
    for threshold in (128, 96, 64, 48, 32, 24, 16, 8):
        if memory >= threshold:
            return str(threshold)
    return "below-8"


def validate_report(report):
    """Validate complete local-run evidence, not a certification of model quality."""
    if not isinstance(report, dict) or report.get("suite") != SUITE_VERSION:
        raise ValueError("Unrecognized local evaluation suite.")
    if report.get("execution_mode") != "local-model" or report.get("completed") is not True:
        raise ValueError("Only a completed real local endpoint run can be promoted.")
    entry = next((m for m in registry() if m["id"] == report.get("registry_model")), None)
    engine = report.get("engine")
    if not entry or engine not in {"ollama", "lmstudio"}:
        raise ValueError("Unknown registry model or engine.")
    if report.get("catalog_tag") != entry["engines"][engine]:
        raise ValueError("The engine catalog tag does not match the registry.")
    artifact = report.get("artifact")
    if report.get("identity_verified") is not True or not isinstance(artifact, dict):
        raise ValueError("The endpoint did not identify the selected catalog model artifact.")
    if engine == "ollama" and not isinstance(artifact.get("digest"), str):
        raise ValueError("Ollama artifact digest is missing.")
    if engine == "ollama" and not artifact["digest"]:
        raise ValueError("Ollama artifact digest is missing.")
    if engine == "lmstudio" and artifact.get("key") != report["catalog_tag"]:
        raise ValueError("LM Studio artifact key is not the curated catalog key.")
    if not isinstance(report.get("runtime_model"), str) or not report["runtime_model"]:
        raise ValueError("Runtime model identity is missing.")
    if not isinstance(report.get("endpoint"), str):
        raise ValueError("Loopback endpoint evidence is missing.")
    endpoint = urlsplit(report["endpoint"])
    if (
        endpoint.scheme not in {"http", "https"}
        or endpoint.hostname not in {"127.0.0.1", "::1"}
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("Only loopback endpoint evidence may be promoted.")
    fit = report.get("fit")
    if not isinstance(fit, dict) or report.get("passed") is not True or fit.get("rating") != "Fits":
        raise ValueError("A passing run and a fitting model are required before promotion.")

    hardware = report.get("hardware")
    if not isinstance(hardware, dict):
        raise ValueError("Mac hardware evidence is missing.")
    memory = hardware.get("unified_memory_gb")
    if hardware.get("is_apple_silicon") is not True or type(memory) is not int or memory < 8:
        raise ValueError("Mac starter promotion requires Apple Silicon memory information.")
    if report.get("memory_tier") != memory_tier(memory):
        raise ValueError("Evaluation memory tier does not match its hardware.")
    context = report.get("context")
    if type(context) is not int or not 512 <= context <= 262144:
        raise ValueError("Evaluation context is missing or invalid.")
    tasks = report.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(TASK_IDS):
        raise ValueError("All five fixed tasks must have run.")
    if {t.get("id") for t in tasks if isinstance(t, dict)} != set(TASK_IDS):
        raise ValueError("The fixed task list does not match this suite.")
    for task in tasks:
        if task.get("passed") is not True or task.get("tool_calls_valid") is not True:
            raise ValueError("Every task must pass with valid tool calls before promotion.")
        if type(task.get("tool_calls")) is not int or task["tool_calls"] < 1:
            raise ValueError("A task without actual tool use is not a passing evaluation.")
        if task.get("invalid_calls", 0) != 0:
            raise ValueError("Tool-call validity conflicts with recorded invalid calls.")
        tokens = task.get("completion_tokens")
        speed = task.get("tokens_per_second")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError("Reported completion token usage is invalid.")
        if speed is not None and (
            type(speed) not in {int, float} or not math.isfinite(speed) or speed < 0
        ):
            raise ValueError("Reported throughput is invalid.")
        if (
            type(task.get("elapsed_seconds")) not in {int, float}
            or not math.isfinite(task["elapsed_seconds"])
            or not task["elapsed_seconds"] > 0
        ):
            raise ValueError("Evaluation task timing is missing.")
    return report


def load_evidence(path=None):
    try:
        reports = json.loads((path or evidence_path()).read_text())["reports"]
        valid = []
        for report in reports:
            try:
                valid.append(validate_report(report))
            except (ValueError, TypeError, KeyError):
                continue
        return valid
    except (OSError, ValueError, TypeError, KeyError):
        return []


def promote(report_file, path=None):
    """Explicit opt-in import. Never modifies the shipped catalog or uploads data."""
    report = validate_report(json.loads(Path(report_file).read_text()))
    path = path or evidence_path()
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    key = (
        report["registry_model"],
        report["engine"],
        report["memory_tier"],
        report["runtime_model"],
    )
    with path.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        text = stream.read()
        payload = json.loads(text) if text.strip() else {"schema_version": 1, "reports": []}
        reports = payload.get("reports")
        if not isinstance(reports, list):
            raise ValueError("Existing evaluation registry is invalid; it was left unchanged.")
        reports = [
            r
            for r in reports
            if not isinstance(r, dict)
            or (
                r.get("registry_model"),
                r.get("engine"),
                r.get("memory_tier"),
                r.get("runtime_model"),
            )
            != key
        ]
        payload["reports"] = reports + [report]
        encoded = json.dumps(payload, indent=2, allow_nan=False) + "\n"
        stream.seek(0)
        stream.truncate()
        stream.write(encoded)
    return report


def suggestions(hardware, path=None):
    """Prefer fitting, tested entries per engine and this memory tier only.

    Untested installed models remain available in the caller. Evidence from a
    larger Mac, shorter context or another engine cannot upgrade these choices.
    """
    memory = hardware.available_memory_gb
    if not memory or memory < 8:
        return []
    reports = load_evidence(path)
    rows = []
    for entry in reversed(registry()):
        if memory < entry["minimum_memory_gb"]:
            continue
        for engine, tag in entry["engines"].items():
            contract = choose_contract(tag, hardware, provider=engine)
            if contract.fit["rating"] != "Fits":
                continue
            tested = any(
                r["registry_model"] == entry["id"]
                and r["engine"] == engine
                and r["memory_tier"] == memory_tier(memory)
                and r["hardware"]["unified_memory_gb"] <= memory
                and r["context"] >= contract.context
                for r in reports
            )
            rows.append(
                {
                    "engine": engine,
                    "model": tag,
                    "context": contract.context,
                    "status": "tested" if tested else "catalog-verified",
                }
            )
    tested_engines = {r["engine"] for r in rows if r["status"] == "tested"}
    return [r for r in rows if r["engine"] not in tested_engines or r["status"] == "tested"]
