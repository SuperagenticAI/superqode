"""Reproducible HarnessBench manifests, raw runs, and public scorecards."""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from superqode import __version__

from .eval import run_harness_eval


HARNESS_BENCH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HarnessBenchManifest:
    """One fixed tasks × model × harnesses benchmark contract."""

    bench_id: str
    tasks: str
    specs: tuple[str, ...]
    provider: str
    model: str
    runtime: str | None = None
    working_dir: str = "."
    sandbox: str = "local"
    split: str = "all"
    repetitions: int = 1
    live: bool = False
    schema_version: int = HARNESS_BENCH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "specs": list(self.specs)}


def load_harness_bench_manifest(path: str | Path) -> HarnessBenchManifest:
    manifest_path = Path(path).expanduser().resolve()
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("HarnessBench manifest must be a mapping")
    version = int(payload.get("schema_version") or 1)
    if version != HARNESS_BENCH_SCHEMA_VERSION:
        raise ValueError(f"unsupported HarnessBench schema version: {version}")
    root = manifest_path.parent
    tasks = _resolve_existing(root, payload.get("tasks"), "tasks")
    raw_specs = payload.get("specs") or payload.get("harnesses") or ()
    if not isinstance(raw_specs, (list, tuple)) or len(raw_specs) < 2:
        raise ValueError("HarnessBench requires at least two harness specs")
    specs = tuple(_resolve_existing(root, value, "spec") for value in raw_specs)
    repetitions = int(payload.get("repetitions") or 1)
    if repetitions < 1 or repetitions > 100:
        raise ValueError("HarnessBench repetitions must be between 1 and 100")
    split = str(payload.get("split") or "all")
    if split not in {"all", "held-in", "held-out"}:
        raise ValueError("HarnessBench split must be all, held-in, or held-out")
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not provider or not model:
        raise ValueError("HarnessBench requires one fixed provider and model")
    working = Path(str(payload.get("working_dir") or ".")).expanduser()
    if not working.is_absolute():
        working = (root / working).resolve()
    if not working.is_dir():
        raise ValueError(f"HarnessBench working_dir does not exist: {working}")
    return HarnessBenchManifest(
        bench_id=str(payload.get("id") or payload.get("bench_id") or manifest_path.stem),
        tasks=tasks,
        specs=specs,
        provider=provider,
        model=model,
        runtime=str(payload.get("runtime") or "") or None,
        working_dir=str(working),
        sandbox=str(payload.get("sandbox") or "local"),
        split=split,
        repetitions=repetitions,
        live=bool(payload.get("live", False)),
    )


async def run_harness_bench(
    manifest: HarnessBenchManifest,
    *,
    output_dir: str | Path,
    live: bool | None = None,
    eval_runner: Callable[..., Awaitable[dict[str, Any]]] = run_harness_eval,
) -> dict[str, Any]:
    """Execute a manifest and write raw traces plus a reproducible scorecard."""
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"HarnessBench output directory is not empty: {root}")
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    effective_live = manifest.live if live is None else live
    source_digests = {
        "tasks": _sha256_file(Path(manifest.tasks)),
        "specs": {path: _sha256_file(Path(path)) for path in manifest.specs},
    }
    normalized_manifest = {**manifest.to_dict(), "live": effective_live}
    fingerprint = _sha256_json({"manifest": normalized_manifest, "sources": source_digests})
    started_at = datetime.now(timezone.utc).isoformat()
    runs: list[dict[str, Any]] = []
    for repetition in range(1, manifest.repetitions + 1):
        result = await eval_runner(
            spec_paths=list(manifest.specs),
            tasks_path=manifest.tasks,
            provider=manifest.provider,
            model=manifest.model,
            runtime=manifest.runtime,
            working_dir=manifest.working_dir,
            sandbox_backend=manifest.sandbox,
            live=effective_live,
            eval_split=manifest.split,
        )
        envelope = {
            "schema_version": HARNESS_BENCH_SCHEMA_VERSION,
            "bench_id": manifest.bench_id,
            "fingerprint": fingerprint,
            "repetition": repetition,
            "provider": manifest.provider,
            "model": manifest.model,
            "runtime": manifest.runtime,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
        }
        raw_path = raw_dir / f"run-{repetition:03d}.json"
        _write_json(raw_path, envelope)
        runs.append(envelope)
    scorecard = build_harness_bench_scorecard(
        manifest,
        runs,
        fingerprint=fingerprint,
        source_digests=source_digests,
        started_at=started_at,
        live=effective_live,
    )
    manifest_path = root / "manifest.json"
    scorecard_path = root / "scorecard.json"
    report_path = root / "scorecard.md"
    _write_json(manifest_path, normalized_manifest)
    _write_json(scorecard_path, scorecard)
    report_path.write_text(render_harness_bench_scorecard(scorecard), encoding="utf-8")
    indexed_paths = [manifest_path, scorecard_path, report_path, *sorted(raw_dir.glob("*.json"))]
    index = {
        "schema_version": HARNESS_BENCH_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "artifacts": {str(path.relative_to(root)): _sha256_file(path) for path in indexed_paths},
    }
    _write_json(root / "artifacts.json", index)
    return {
        "output_dir": str(root),
        "manifest": str(manifest_path),
        "scorecard": str(scorecard_path),
        "report": str(report_path),
        "artifacts": str(root / "artifacts.json"),
        "fingerprint": fingerprint,
        "status": scorecard["status"],
        "winner": scorecard["winner"],
    }


def build_harness_bench_scorecard(
    manifest: HarnessBenchManifest,
    runs: list[dict[str, Any]],
    *,
    fingerprint: str,
    source_digests: dict[str, Any],
    started_at: str,
    live: bool,
) -> dict[str, Any]:
    variants: dict[str, list[dict[str, Any]]] = {}
    for envelope in runs:
        result = envelope.get("result") or {}
        result_variants = list(result.get("variants") or ())
        name_counts: dict[str, int] = {}
        for variant in result_variants:
            name = str(variant.get("harness") or "unknown")
            name_counts[name] = name_counts.get(name, 0) + 1
        for variant in result_variants:
            name = str(variant.get("harness") or "unknown")
            key = name
            if name_counts[name] > 1:
                key = f"{name}@{Path(str(variant.get('spec') or 'variant')).stem}"
            variants.setdefault(key, []).append(variant)
    summaries = [_variant_summary(name, rows) for name, rows in variants.items()]
    for summary in summaries:
        summary["pareto"] = _is_pareto(summary, summaries)
    ranked = sorted(
        summaries,
        key=lambda item: (
            -float(item["score"]["mean"]),
            _sortable_metric(item["cost_usd"]["mean"]),
            _sortable_metric(item["latency_ms"]["mean"]),
            item["harness"],
        ),
    )
    all_runs_passed = all(
        (envelope.get("result") or {}).get("status") == "passed" for envelope in runs
    )
    return {
        "schema_version": HARNESS_BENCH_SCHEMA_VERSION,
        "bench_id": manifest.bench_id,
        "fingerprint": fingerprint,
        "status": "passed" if all_runs_passed else "failed",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "live": live,
        "provider": manifest.provider,
        "model": manifest.model,
        "runtime": manifest.runtime,
        "split": manifest.split,
        "repetitions": manifest.repetitions,
        "task_count": (runs[0].get("result") or {}).get("task_count", 0) if runs else 0,
        "winner": ranked[0]["harness"] if ranked else "",
        "ranking": [item["harness"] for item in ranked],
        "variants": ranked,
        "sources": source_digests,
        "environment": {
            "superqode": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "methodology": {
            "same_tasks": True,
            "same_provider": True,
            "same_model": True,
            "raw_runs_preserved": True,
            "artifact_checksums": True,
            "ranking": "quality desc, then observed cost asc, then latency asc",
        },
    }


def verify_harness_bench(output_dir: str | Path) -> dict[str, Any]:
    """Verify checksums and cross-file fingerprints without calling a model."""
    root = Path(output_dir).expanduser().resolve()
    index_path = root / "artifacts.json"
    if not index_path.is_file():
        raise ValueError(f"HarnessBench artifact index is missing: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    for relative, expected in (index.get("artifacts") or {}).items():
        path = root / relative
        if not path.is_file():
            failures.append({"path": relative, "error": "missing"})
            continue
        actual = _sha256_file(path)
        if actual != expected:
            failures.append(
                {
                    "path": relative,
                    "error": "digest_mismatch",
                    "expected": expected,
                    "actual": actual,
                }
            )
    scorecard_path = root / "scorecard.json"
    if scorecard_path.is_file():
        scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        if scorecard.get("fingerprint") != index.get("fingerprint"):
            failures.append({"path": "scorecard.json", "error": "fingerprint_mismatch"})
    return {
        "output_dir": str(root),
        "fingerprint": str(index.get("fingerprint") or ""),
        "valid": not failures,
        "checked": len(index.get("artifacts") or {}),
        "failures": failures,
    }


def render_harness_bench_scorecard(scorecard: dict[str, Any]) -> str:
    lines = [
        f"# HarnessBench: {scorecard['bench_id']}",
        "",
        f"Fingerprint: `{scorecard['fingerprint']}`",
        "",
        f"Fixed model: `{scorecard['provider']}/{scorecard['model']}`",
        "",
        f"Tasks: {scorecard['task_count']} · repetitions: {scorecard['repetitions']} · split: {scorecard['split']}",
        "",
        "| Rank | Harness | Success | Cost (USD) | Latency (ms) | Pareto |",
        "| ---: | --- | ---: | ---: | ---: | :---: |",
    ]
    for index, variant in enumerate(scorecard.get("variants") or (), 1):
        lines.append(
            f"| {index} | {variant['harness']} | {_metric_text(variant['score']['mean'])} "
            f"| {_metric_text(variant['cost_usd']['mean'])} "
            f"| {_metric_text(variant['latency_ms']['mean'])} "
            f"| {'yes' if variant['pareto'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "Raw repetition results and source digests are preserved beside this scorecard. ",
            "Run `sq harness bench-verify <directory>` before publishing or comparing it.",
            "",
        ]
    )
    return "\n".join(lines)


def _variant_summary(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "harness": name,
        "spec": str(rows[0].get("spec") or "") if rows else "",
        "runs": len(rows),
        "score": _stats([item.get("score") for item in rows]),
        "cost_usd": _stats([item.get("cost_usd") for item in rows]),
        "total_tokens": _stats([item.get("total_tokens") for item in rows]),
        "latency_ms": _stats(
            [
                float(item.get("duration_seconds") or 0) * 1000
                if item.get("duration_seconds") is not None
                else None
                for item in rows
            ]
        ),
        "regression_runs": sum(bool(item.get("regressed")) for item in rows),
        "task_outcomes": _task_outcomes(rows),
    }


def _stats(values: list[Any]) -> dict[str, Any]:
    observed = [float(value) for value in values if value is not None]
    if not observed:
        return {"mean": None, "stdev": None, "min": None, "max": None, "reports": 0}
    return {
        "mean": round(statistics.fmean(observed), 8),
        "stdev": round(statistics.pstdev(observed), 8),
        "min": round(min(observed), 8),
        "max": round(max(observed), 8),
        "reports": len(observed),
    }


def _task_outcomes(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    outcomes: dict[str, dict[str, int]] = {}
    for row in rows:
        for task in row.get("tasks") or ():
            task_id = str(task.get("id") or "unknown")
            status = str(task.get("status") or "unknown")
            bucket = outcomes.setdefault(task_id, {})
            bucket[status] = bucket.get(status, 0) + 1
    return outcomes


def _is_pareto(candidate: dict[str, Any], variants: list[dict[str, Any]]) -> bool:
    quality = candidate["score"]["mean"]
    cost = candidate["cost_usd"]["mean"]
    latency = candidate["latency_ms"]["mean"]
    if quality is None:
        return False
    for other in variants:
        if other is candidate or other["score"]["mean"] is None:
            continue
        other_cost = other["cost_usd"]["mean"]
        other_latency = other["latency_ms"]["mean"]
        no_worse = (
            other["score"]["mean"] >= quality
            and _sortable_metric(other_cost) <= _sortable_metric(cost)
            and _sortable_metric(other_latency) <= _sortable_metric(latency)
        )
        strictly_better = (
            other["score"]["mean"] > quality
            or _sortable_metric(other_cost) < _sortable_metric(cost)
            or _sortable_metric(other_latency) < _sortable_metric(latency)
        )
        if no_worse and strictly_better:
            return False
    return True


def _resolve_existing(root: Path, value: Any, label: str) -> str:
    if not str(value or "").strip():
        raise ValueError(f"HarnessBench manifest requires {label}")
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"HarnessBench {label} does not exist: {path}")
    return str(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sortable_metric(value: Any) -> float:
    return float("inf") if value is None else float(value)


def _metric_text(value: Any) -> str:
    return "unreported" if value is None else f"{float(value):.4f}"


def default_harness_bench_output(bench_id: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    safe = re_sub_nonword(bench_id)
    return Path(".superqode") / "harnessbench" / f"{safe}-{stamp}"


def re_sub_nonword(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-") or "bench"


__all__ = [
    "HARNESS_BENCH_SCHEMA_VERSION",
    "HarnessBenchManifest",
    "build_harness_bench_scorecard",
    "default_harness_bench_output",
    "load_harness_bench_manifest",
    "render_harness_bench_scorecard",
    "run_harness_bench",
    "verify_harness_bench",
]
