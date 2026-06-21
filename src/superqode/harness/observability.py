"""Optional observability exports for harness runs.

The local harness store is the source of truth. Exporters mirror stored runs to
portable JSON/JSONL artifacts and optional external sinks without changing run
execution semantics.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .events import HarnessEvent
from .spec import HarnessSpec, ObservabilitySpec
from .store import FileHarnessStore, HarnessRunRecord

logger = logging.getLogger(__name__)

TRACE_SCHEMA_VERSION = "superqode.harness.observability.v1"


class HarnessStoreReader(Protocol):
    """Read-only subset of harness stores needed for observability export."""

    def get_run(self, run_id: str) -> HarnessRunRecord | None:
        """Return one run by id."""
        ...

    def list_runs(self, *, session_id: str | None = None) -> list[HarnessRunRecord]:
        """Return known runs."""
        ...


class HarnessObservabilitySink(Protocol):
    """External sink contract for exported harness traces."""

    name: str

    def status(self) -> dict[str, Any]:
        """Return enabled/available/configuration details."""
        ...

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
        """Mirror a normalized trace. Sink failures should not break callers."""
        ...


@dataclass(slots=True)
class LocalArtifactSink:
    """Local artifact sink for the always-written trace files."""

    enabled: bool = True
    name: str = "local-jsonl"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "available": True,
            "configured": True,
            "detail": "local trace.json, JSONL, and OTEL-shaped JSONL artifacts",
        }

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
        if not self.enabled:
            return {"name": self.name, "status": "disabled"}
        return {"name": self.name, "status": "exported", "detail": str(output_dir)}


@dataclass(slots=True)
class MLflowArtifactSink:
    """Optional MLflow artifact sink for exported harness traces."""

    enabled: bool
    experiment: str = "superqode-harness"
    tracking_uri: str | None = None
    name: str = "mlflow"
    _mlflow: Any = None
    _available: bool = False
    _detail: str = "disabled"
    _configured: bool = False

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        try:
            import mlflow  # type: ignore[import-not-found]

            self._mlflow = mlflow
            self._available = True
            self._detail = self.tracking_uri or "default-tracking-uri"
        except Exception as exc:
            self._available = False
            self._detail = f"unavailable: {exc}"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "available": self._available,
            "detail": self._detail,
            "experiment": self.experiment,
        }

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
        if not self.enabled:
            return {"name": self.name, "status": "disabled"}
        if not self._available:
            return {"name": self.name, "status": "unavailable", "detail": self._detail}
        run_id = str(trace.get("root_run_id") or trace.get("run_id") or "superqode-run")
        try:
            if not self._configured:
                if self.tracking_uri:
                    self._mlflow.set_tracking_uri(self.tracking_uri)
                self._mlflow.set_experiment(self.experiment)
                self._configured = True
            with self._mlflow.start_run(run_name=run_id):
                self._mlflow.set_tags(
                    {
                        "component": "superqode-harness",
                        "schema_version": str(trace.get("schema_version") or ""),
                        "root_run_id": run_id,
                    }
                )
                self._mlflow.log_params(
                    {
                        "run_count": len(trace.get("runs") or []),
                        "span_count": len(trace.get("spans") or []),
                        "event_count": len(trace.get("events") or []),
                    }
                )
                self._mlflow.log_metrics(
                    {
                        "superqode.run_count": float(len(trace.get("runs") or [])),
                        "superqode.span_count": float(len(trace.get("spans") or [])),
                        "superqode.event_count": float(len(trace.get("events") or [])),
                    }
                )
                self._mlflow.log_artifacts(str(output_dir))
            return {"name": self.name, "status": "exported", "detail": self._detail}
        except Exception as exc:
            logger.warning("MLflow observability export failed: %s", exc)
            return {"name": self.name, "status": "failed", "detail": str(exc)}


@dataclass(slots=True)
class OpenTelemetryLiveSink:
    """Optional OpenTelemetry exporter for live harness trace mirroring."""

    enabled: bool
    endpoint: str | None = None
    service_name: str = "superqode-harness"
    name: str = "opentelemetry"
    _available: bool = False
    _detail: str = "disabled"
    _trace: Any = None
    _tracer: Any = None

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        try:
            from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
                BatchSpanProcessor,
            )

            resource = Resource.create({SERVICE_NAME: self.service_name})
            provider = TracerProvider(resource=resource)
            if self.endpoint:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(endpoint=self.endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                self._detail = self.endpoint
            else:
                self._detail = "sdk-ready; no OTLP endpoint configured"
            try:
                otel_trace.set_tracer_provider(provider)
            except Exception:
                # A process can only set the global provider once. Reuse the
                # existing provider if another runtime configured it first.
                pass
            self._trace = otel_trace
            self._tracer = otel_trace.get_tracer(self.service_name)
            self._available = True
        except Exception as exc:
            self._available = False
            self._detail = f"unavailable: {exc}"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "available": self._available,
            "configured": bool(self.endpoint),
            "detail": self._detail,
            "service_name": self.service_name,
        }

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
        if not self.enabled:
            return {"name": self.name, "status": "disabled"}
        if not self._available or self._tracer is None:
            return {"name": self.name, "status": "unavailable", "detail": self._detail}
        try:
            spans = list(trace.get("spans") or [])
            root_span = next(
                (span for span in spans if not span.get("parent_span_id")),
                spans[0] if spans else None,
            )
            if root_span is None:
                return {"name": self.name, "status": "skipped", "detail": "no spans"}
            children = [span for span in spans if span is not root_span]
            with self._start_span(root_span):
                for span in children:
                    with self._start_span(span):
                        pass
            return {
                "name": self.name,
                "status": "exported" if self.endpoint else "sdk-ready",
                "detail": self._detail,
                "artifact": str(output_dir / "otel_spans.jsonl"),
            }
        except Exception as exc:
            logger.warning("OpenTelemetry observability export failed: %s", exc)
            return {"name": self.name, "status": "failed", "detail": str(exc)}

    def _start_span(self, span: dict[str, Any]) -> Any:
        attrs = _clean_otel_attributes(span.get("attributes") or {})
        started = span.get("start_time_unix_nano")
        ctx = self._tracer.start_as_current_span(
            str(span.get("name") or "superqode.harness.run"),
            attributes=attrs,
            start_time=started if isinstance(started, int) else None,
            end_on_exit=False,
        )
        return _OpenTelemetrySpanContext(ctx, span)


@dataclass(slots=True)
class ArizePhoenixLiveSink(OpenTelemetryLiveSink):
    """Arize Phoenix sink through the Phoenix/OTEL collector path."""

    name: str = "arize"

    def __post_init__(self) -> None:
        if not self.endpoint:
            self.endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv(
                "ARIZE_PHOENIX_COLLECTOR_ENDPOINT"
            )
        OpenTelemetryLiveSink.__post_init__(self)
        if self.enabled and self._available:
            self._detail = self.endpoint or "sdk-ready; set PHOENIX_COLLECTOR_ENDPOINT"


@dataclass(slots=True)
class LangSmithLiveSink:
    """Optional LangSmith run tree sink."""

    enabled: bool
    project: str = "superqode-harness"
    api_key: str | None = None
    name: str = "langsmith"
    _available: bool = False
    _detail: str = "disabled"
    _run_tree: Any = None
    _client: Any = None

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        try:
            from langsmith import Client  # type: ignore[import-not-found]
            from langsmith.run_trees import RunTree  # type: ignore[import-not-found]

            client_kwargs = {"api_key": self.api_key} if self.api_key else {}
            self._client = Client(**client_kwargs)
            self._run_tree = RunTree
            self._available = True
            self._detail = self.project
        except Exception as exc:
            self._available = False
            self._detail = f"unavailable: {exc}"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "available": self._available,
            "configured": bool(self.api_key or os.getenv("LANGSMITH_API_KEY")),
            "detail": self._detail,
            "project": self.project,
        }

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
        if not self.enabled:
            return {"name": self.name, "status": "disabled"}
        if not self._available or self._run_tree is None:
            return {"name": self.name, "status": "unavailable", "detail": self._detail}
        try:
            runs = list(trace.get("runs") or [])
            if not runs:
                return {"name": self.name, "status": "skipped", "detail": "no runs"}
            root = next((run for run in runs if not run.get("parent_run_id")), runs[0])
            root_tree = self._make_run_tree(root, trace, output_dir)
            by_id = {root.get("run_id"): root_tree}
            for run in runs:
                run_id = run.get("run_id")
                if run_id == root.get("run_id"):
                    continue
                parent = by_id.get(run.get("parent_run_id")) or root_tree
                child = parent.create_child(
                    name=f"superqode child {run_id}",
                    run_type="chain",
                    inputs={"prompt_preview": run.get("prompt_preview")},
                    outputs=_langsmith_outputs(run),
                    extra={"metadata": run.get("metadata") or {}},
                )
                child.end(outputs=_langsmith_outputs(run))
                by_id[run_id] = child
            root_tree.end(
                outputs={"summary": _trace_summary(trace), "artifact_dir": str(output_dir)}
            )
            root_tree.post()
            return {"name": self.name, "status": "exported", "detail": self.project}
        except Exception as exc:
            logger.warning("LangSmith observability export failed: %s", exc)
            return {"name": self.name, "status": "failed", "detail": str(exc)}

    def _make_run_tree(self, run: dict[str, Any], trace: dict[str, Any], output_dir: Path) -> Any:
        return self._run_tree(
            name=f"superqode harness {run.get('run_id')}",
            run_type="chain",
            inputs={
                "root_run_id": trace.get("root_run_id"),
                "prompt_preview": run.get("prompt_preview"),
            },
            extra={
                "metadata": {
                    "schema_version": trace.get("schema_version"),
                    "artifact_dir": str(output_dir),
                    **(run.get("metadata") or {}),
                }
            },
            project_name=self.project,
            client=self._client,
        )


@dataclass(slots=True)
class LogfireLiveSink:
    """Optional Logfire sink for harness run summaries and events."""

    enabled: bool
    token: str | None = None
    service_name: str = "superqode-harness"
    name: str = "logfire"
    _available: bool = False
    _detail: str = "disabled"
    _logfire: Any = None

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        try:
            import logfire  # type: ignore[import-not-found]

            configure_kwargs: dict[str, Any] = {
                "service_name": self.service_name,
                "send_to_logfire": "if-token-present",
                "console": False,
            }
            if self.token:
                configure_kwargs["token"] = self.token
            try:
                logfire.configure(**configure_kwargs)
            except Exception:
                # Logfire may already be configured by the host application.
                pass
            self._logfire = logfire
            self._available = True
            self._detail = self.service_name
        except Exception as exc:
            self._available = False
            self._detail = f"unavailable: {exc}"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "available": self._available,
            "configured": bool(self.token or os.getenv("LOGFIRE_TOKEN")),
            "detail": self._detail,
            "service_name": self.service_name,
        }

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
        if not self.enabled:
            return {"name": self.name, "status": "disabled"}
        if not self._available or self._logfire is None:
            return {"name": self.name, "status": "unavailable", "detail": self._detail}
        try:
            summary = _trace_summary(trace)
            with self._logfire.span(
                "superqode harness run {run_id}",
                run_id=str(trace.get("root_run_id") or trace.get("run_id") or ""),
                artifact_dir=str(output_dir),
                **summary,
            ):
                for run in trace.get("runs") or []:
                    self._logfire.info(
                        "superqode harness child run",
                        run_id=run.get("run_id"),
                        parent_run_id=run.get("parent_run_id"),
                        status=run.get("status"),
                        provider=run.get("provider"),
                        model=run.get("model"),
                    )
            return {"name": self.name, "status": "exported", "detail": self._detail}
        except Exception as exc:
            logger.warning("Logfire observability export failed: %s", exc)
            return {"name": self.name, "status": "failed", "detail": str(exc)}


@dataclass(slots=True)
class HarnessObservability:
    """Coordinator for configured harness observability sinks."""

    sinks: list[HarnessObservabilitySink] = field(default_factory=list)

    @classmethod
    def from_spec(
        cls, spec: HarnessSpec | ObservabilitySpec | None = None
    ) -> "HarnessObservability":
        obs = spec.observability if isinstance(spec, HarnessSpec) else spec
        obs = obs or ObservabilitySpec()
        return cls(sinks=build_observability_sinks(obs))

    def status(self) -> list[dict[str, Any]]:
        return [sink.status() for sink in self.sinks]

    def export_trace(self, trace: dict[str, Any], *, output_dir: Path) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for sink in self.sinks:
            try:
                results.append(sink.export_trace(trace, output_dir=output_dir))
            except Exception as exc:
                logger.warning("Observability sink '%s' failed: %s", sink.name, exc)
                results.append({"name": sink.name, "status": "failed", "detail": str(exc)})
        return results


def build_observability_sinks(
    spec: ObservabilitySpec | None = None,
) -> list[HarnessObservabilitySink]:
    """Build optional sinks from spec and environment variables."""
    spec = spec or ObservabilitySpec()
    config = dict(spec.config or {})
    exporters = _exporter_config(spec.exporters)
    sinks: list[HarnessObservabilitySink] = []
    sinks.append(LocalArtifactSink(enabled=spec.local))
    otel_service_name = str(
        _value("opentelemetry", exporters, "service_name")
        or _value("otel", exporters, "service_name")
        or config.get("service_name")
        or os.getenv("OTEL_SERVICE_NAME")
        or "superqode-harness"
    )
    otel_endpoint = (
        str(
            _value("opentelemetry", exporters, "endpoint")
            or _value("otel", exporters, "endpoint")
            or config.get("otel_endpoint")
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            or ""
        )
        or None
    )
    sinks.append(
        OpenTelemetryLiveSink(
            enabled=_enabled("opentelemetry", exporters, "SUPERQODE_OBS_OTEL_ENABLED")
            or _enabled("otel", exporters, "SUPERQODE_OBS_OTEL_ENABLED"),
            endpoint=otel_endpoint,
            service_name=otel_service_name,
        )
    )
    sinks.append(
        MLflowArtifactSink(
            enabled=_enabled("mlflow", exporters, "SUPERQODE_OBS_MLFLOW_ENABLED"),
            experiment=str(
                _value("mlflow", exporters, "experiment")
                or config.get("mlflow_experiment")
                or os.getenv("SUPERQODE_OBS_MLFLOW_EXPERIMENT")
                or "superqode-harness"
            ),
            tracking_uri=str(
                _value("mlflow", exporters, "tracking_uri")
                or config.get("mlflow_tracking_uri")
                or os.getenv("MLFLOW_TRACKING_URI")
                or ""
            )
            or None,
        )
    )
    sinks.append(
        LangSmithLiveSink(
            enabled=_enabled("langsmith", exporters, "SUPERQODE_OBS_LANGSMITH_ENABLED"),
            project=str(
                _value("langsmith", exporters, "project")
                or config.get("langsmith_project")
                or os.getenv("LANGSMITH_PROJECT")
                or os.getenv("LANGCHAIN_PROJECT")
                or "superqode-harness"
            ),
            api_key=str(
                _value("langsmith", exporters, "api_key")
                or config.get("langsmith_api_key")
                or os.getenv("LANGSMITH_API_KEY")
                or os.getenv("LANGCHAIN_API_KEY")
                or ""
            )
            or None,
        )
    )
    sinks.append(
        LogfireLiveSink(
            enabled=_enabled("logfire", exporters, "SUPERQODE_OBS_LOGFIRE_ENABLED"),
            token=str(
                _value("logfire", exporters, "token")
                or config.get("logfire_token")
                or os.getenv("LOGFIRE_TOKEN")
                or ""
            )
            or None,
            service_name=str(
                _value("logfire", exporters, "service_name")
                or config.get("service_name")
                or os.getenv("LOGFIRE_SERVICE_NAME")
                or "superqode-harness"
            ),
        )
    )
    sinks.append(
        ArizePhoenixLiveSink(
            enabled=_enabled("arize", exporters, "SUPERQODE_OBS_ARIZE_ENABLED")
            or _enabled("phoenix", exporters, "SUPERQODE_OBS_ARIZE_ENABLED"),
            endpoint=str(
                _value("arize", exporters, "endpoint")
                or _value("phoenix", exporters, "endpoint")
                or config.get("phoenix_collector_endpoint")
                or os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
                or os.getenv("ARIZE_PHOENIX_COLLECTOR_ENDPOINT")
                or ""
            )
            or None,
            service_name=str(
                _value("arize", exporters, "service_name")
                or _value("phoenix", exporters, "service_name")
                or config.get("service_name")
                or "superqode-harness"
            ),
        )
    )
    return sinks


def observability_status(
    spec: HarnessSpec | ObservabilitySpec | None = None,
) -> list[dict[str, Any]]:
    """Return status rows for all known observability sinks."""
    return HarnessObservability.from_spec(spec).status()


def export_harness_observability(
    store: HarnessStoreReader,
    run_id: str,
    *,
    output_dir: str | Path | None = None,
    spec: HarnessSpec | ObservabilitySpec | None = None,
) -> dict[str, Any]:
    """Export a stored run tree to local artifacts and optional sinks."""
    trace = normalize_harness_trace(store, run_id)
    target = Path(output_dir or Path(".superqode/harness/observability") / run_id)
    target.mkdir(parents=True, exist_ok=True)
    _write_trace_artifacts(trace, target)
    sink_results = HarnessObservability.from_spec(spec).export_trace(trace, output_dir=target)
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": run_id,
        "root_run_id": trace["root_run_id"],
        "output_dir": str(target),
        "files": {
            "trace": str(target / "trace.json"),
            "runs": str(target / "runs.jsonl"),
            "events": str(target / "events.jsonl"),
            "otel_spans": str(target / "otel_spans.jsonl"),
            "overview": str(target / "overview.md"),
        },
        "run_count": len(trace["runs"]),
        "event_count": len(trace["events"]),
        "span_count": len(trace["spans"]),
        "sinks": sink_results,
    }


def normalize_harness_trace(store: HarnessStoreReader, run_id: str) -> dict[str, Any]:
    """Return a normalized trace containing the run and its descendant runs."""
    root = store.get_run(run_id)
    if root is None:
        raise KeyError(f"Unknown harness run: {run_id}")
    all_runs = store.list_runs()
    descendants = _descendant_runs(root, all_runs)
    descendants.sort(key=lambda item: item.started_at)
    events = _flatten_events(descendants)
    spans = [_run_to_otel_span(run, root) for run in descendants]
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "generated_at": time.time(),
        "run_id": run_id,
        "root_run_id": root.root_run_id or root.run_id,
        "runs": [_run_summary(run) for run in descendants],
        "events": events,
        "spans": spans,
    }


def create_file_store_for_observability(path: str | Path) -> FileHarnessStore:
    """Create the file store used by observability CLI commands."""
    return FileHarnessStore(path)


def render_observability_status(rows: Iterable[dict[str, Any]]) -> str:
    lines = ["Harness observability sinks:"]
    for row in rows:
        enabled = "enabled" if row.get("enabled") else "disabled"
        available = "available" if row.get("available") else "unavailable"
        detail = row.get("detail") or ""
        lines.append(f"- {row.get('name')}: {enabled}, {available} ({detail})")
    return "\n".join(lines)


def render_observability_export(payload: dict[str, Any]) -> str:
    lines = [
        f"Exported harness observability: {payload['run_id']}",
        f"Output: {payload['output_dir']}",
        f"Runs: {payload['run_count']}  Events: {payload['event_count']}  Spans: {payload['span_count']}",
    ]
    for sink in payload.get("sinks") or []:
        lines.append(f"Sink {sink.get('name')}: {sink.get('status')}")
    return "\n".join(lines)


class _OpenTelemetrySpanContext:
    """Attach stored events/status to an OpenTelemetry span context manager."""

    def __init__(self, ctx: Any, span_record: dict[str, Any]) -> None:
        self._ctx = ctx
        self._span_record = span_record
        self._span: Any = None

    def __enter__(self) -> Any:
        self._span = self._ctx.__enter__()
        for event in self._span_record.get("events") or []:
            self._span.add_event(
                str(event.get("name") or "event"),
                attributes=_clean_otel_attributes(event.get("attributes") or {}),
            )
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        ended = self._span_record.get("end_time_unix_nano")
        if exc_type is None:
            status_code = (self._span_record.get("status") or {}).get("code")
            if status_code == "ERROR":
                try:
                    from opentelemetry.trace import Status, StatusCode  # type: ignore[import-not-found]

                    self._span.set_status(Status(StatusCode.ERROR))
                except Exception:
                    pass
        try:
            self._span.end(end_time=ended if isinstance(ended, int) else None)
        finally:
            return self._ctx.__exit__(exc_type, exc, tb)


def _write_trace_artifacts(trace: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "runs.jsonl", trace["runs"])
    _write_jsonl(output_dir / "events.jsonl", trace["events"])
    _write_jsonl(output_dir / "otel_spans.jsonl", trace["spans"])
    (output_dir / "overview.md").write_text(_overview_markdown(trace), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def _overview_markdown(trace: dict[str, Any]) -> str:
    lines = [
        "# SuperQode Harness Observability Export",
        "",
        f"- schema: `{trace['schema_version']}`",
        f"- root run: `{trace['root_run_id']}`",
        f"- runs: {len(trace['runs'])}",
        f"- events: {len(trace['events'])}",
        f"- spans: {len(trace['spans'])}",
        "",
        "## Runs",
    ]
    for run in trace["runs"]:
        parent = f" parent=`{run['parent_run_id']}`" if run.get("parent_run_id") else ""
        lines.append(
            f"- `{run['run_id']}` {run['status']} {run['provider']}/{run['model']} "
            f"runtime={run['runtime']}{parent}"
        )
    return "\n".join(lines) + "\n"


def _descendant_runs(
    root: HarnessRunRecord, runs: list[HarnessRunRecord]
) -> list[HarnessRunRecord]:
    selected = {root.run_id}
    changed = True
    while changed:
        changed = False
        for run in runs:
            if run.run_id in selected:
                continue
            if run.parent_run_id in selected or (run.root_run_id and run.root_run_id in selected):
                selected.add(run.run_id)
                changed = True
    by_id = {run.run_id: run for run in runs}
    by_id[root.run_id] = root
    return [by_id[item] for item in selected if item in by_id]


def _flatten_events(runs: list[HarnessRunRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        for index, event in enumerate(run.events):
            rows.append(_event_summary(run, event, index))
    rows.sort(key=lambda item: (item["timestamp"], item["run_id"], item["event_index"]))
    return rows


def _event_summary(run: HarnessRunRecord, event: HarnessEvent, index: int) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "session_id": event.session_id or run.session_id,
        "parent_run_id": run.parent_run_id,
        "root_run_id": run.root_run_id or run.run_id,
        "event_index": index,
        "timestamp": event.timestamp,
        "type": event.type,
        "data": _safe_json(event.data),
    }


def _run_summary(run: HarnessRunRecord) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "harness": run.harness,
        "flavor": run.flavor,
        "provider": run.provider,
        "model": run.model,
        "runtime": run.runtime,
        "status": run.status,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "parent_run_id": run.parent_run_id,
        "root_run_id": run.root_run_id or run.run_id,
        "prompt_preview": run.prompt_preview,
        "event_count": len(run.events),
        "metadata": _safe_json(run.metadata),
    }


def _run_to_otel_span(run: HarnessRunRecord, root: HarnessRunRecord) -> dict[str, Any]:
    span_id = _span_id(run.run_id)
    parent_span_id = _span_id(run.parent_run_id) if run.parent_run_id else ""
    status_code = "OK" if run.status in {"completed", "complete", "done"} else "ERROR"
    if run.status in {"running", "pending"}:
        status_code = "UNSET"
    return {
        "trace_id": _trace_id(root.root_run_id or root.run_id),
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "name": "superqode.harness.run",
        "kind": "INTERNAL",
        "start_time_unix_nano": int(run.started_at * 1_000_000_000),
        "end_time_unix_nano": int((run.ended_at or run.started_at) * 1_000_000_000),
        "status": {"code": status_code},
        "attributes": {
            "superqode.run_id": run.run_id,
            "superqode.session_id": run.session_id,
            "superqode.parent_run_id": run.parent_run_id,
            "superqode.root_run_id": run.root_run_id or run.run_id,
            "superqode.harness": run.harness,
            "superqode.flavor": run.flavor,
            "superqode.provider": run.provider,
            "superqode.model": run.model,
            "superqode.runtime": run.runtime,
            "superqode.status": run.status,
            "superqode.event_count": len(run.events),
        },
        "events": [
            {
                "name": event.type,
                "time_unix_nano": int(event.timestamp * 1_000_000_000),
                "attributes": _event_attributes(event),
            }
            for event in run.events
        ],
    }


def _event_attributes(event: HarnessEvent) -> dict[str, Any]:
    attrs: dict[str, Any] = {"superqode.event_type": event.type}
    for key, value in (event.data or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            attrs[f"superqode.event.{key}"] = value
        else:
            attrs[f"superqode.event.{key}"] = json.dumps(
                _safe_json(value), ensure_ascii=True, sort_keys=True
            )[:4000]
    return attrs


def _span_id(value: str) -> str:
    return _hex_id(value, length=16)


def _trace_id(value: str) -> str:
    return _hex_id(value, length=32)


def _hex_id(value: str, *, length: int) -> str:
    import hashlib

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:length]


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _safe_json(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_safe_json(item) for item in value]
        return str(value)


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "root_run_id": trace.get("root_run_id"),
        "schema_version": trace.get("schema_version"),
        "run_count": len(trace.get("runs") or []),
        "span_count": len(trace.get("spans") or []),
        "event_count": len(trace.get("events") or []),
    }


def _langsmith_outputs(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": run.get("status"),
        "provider": run.get("provider"),
        "model": run.get("model"),
        "runtime": run.get("runtime"),
        "event_count": run.get("event_count"),
    }


def _clean_otel_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if isinstance(value, (str, bool, int, float)) or value is None:
            out[str(key)] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (str, bool, int, float)) for item in value
        ):
            out[str(key)] = list(value)
        else:
            out[str(key)] = json.dumps(_safe_json(value), ensure_ascii=True, sort_keys=True)[:4000]
    return out


def _exporter_config(exporters: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in exporters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("type") or item.get("name") or "").strip().lower()
        if name:
            out[name] = dict(item)
    return out


def _enabled(name: str, exporters: dict[str, dict[str, Any]], env_name: str) -> bool:
    if name in exporters:
        return _bool(exporters[name].get("enabled"), default=True)
    return _bool(os.getenv(env_name), default=False)


def _value(name: str, exporters: dict[str, dict[str, Any]], key: str) -> Any:
    return exporters.get(name, {}).get(key)


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = [
    "ArizePhoenixLiveSink",
    "HarnessObservability",
    "HarnessObservabilitySink",
    "LangSmithLiveSink",
    "LocalArtifactSink",
    "LogfireLiveSink",
    "MLflowArtifactSink",
    "OpenTelemetryLiveSink",
    "TRACE_SCHEMA_VERSION",
    "build_observability_sinks",
    "create_file_store_for_observability",
    "export_harness_observability",
    "normalize_harness_trace",
    "observability_status",
    "render_observability_export",
    "render_observability_status",
]
