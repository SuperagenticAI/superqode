import json

import pytest

from superqode.harness import (
    FileHarnessStore,
    HarnessEvent,
    LangSmithLiveSink,
    LogfireLiveSink,
    ObservabilitySpec,
    build_observability_sinks,
    export_harness_observability,
    get_harness_template,
    normalize_harness_trace,
    observability_status,
)


def _store_with_child_run(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("coding")
    root = store.start_run(
        session_id="session-obs",
        spec=spec,
        provider="ollama",
        model="qwen3:8b",
        runtime="builtin",
        prompt="root task",
    )
    store.append_event(
        root.run_id,
        HarnessEvent(
            type="tool_call",
            data={"tool_name": "context_handle", "ok": True},
            session_id="session-obs",
            run_id=root.run_id,
        ),
    )
    child = store.start_run(
        session_id="session-obs",
        spec=spec,
        provider="ollama",
        model="qwen3:8b",
        runtime="builtin",
        prompt="child task",
        metadata={"parent_run_id": root.run_id, "root_run_id": root.run_id},
    )
    store.append_event(
        child.run_id,
        HarnessEvent(
            type="sandbox_command",
            data={"command": "pytest -q", "exit_code": 0},
            session_id="session-obs",
            run_id=child.run_id,
        ),
    )
    store.end_run(child.run_id, status="succeeded")
    store.end_run(root.run_id, status="succeeded")
    return store, root, child


def test_normalize_harness_trace_preserves_child_lineage(tmp_path):
    store, root, child = _store_with_child_run(tmp_path)

    trace = normalize_harness_trace(store, root.run_id)

    assert trace["schema_version"] == "superqode.harness.observability.v1"
    assert {run["run_id"] for run in trace["runs"]} == {root.run_id, child.run_id}
    child_span = next(
        span
        for span in trace["spans"]
        if span["attributes"]["superqode.run_id"] == child.run_id
    )
    root_span = next(
        span for span in trace["spans"] if span["attributes"]["superqode.run_id"] == root.run_id
    )
    assert child_span["parent_span_id"] == root_span["span_id"]
    assert {event["type"] for event in trace["events"]} == {"tool_call", "sandbox_command"}


def test_export_harness_observability_writes_artifacts(tmp_path):
    store, root, _child = _store_with_child_run(tmp_path)

    payload = export_harness_observability(
        store,
        root.run_id,
        output_dir=tmp_path / "obs",
        spec=ObservabilitySpec(local=True),
    )

    assert payload["run_count"] == 2
    assert payload["event_count"] == 2
    assert (tmp_path / "obs" / "trace.json").exists()
    assert (tmp_path / "obs" / "runs.jsonl").exists()
    assert (tmp_path / "obs" / "events.jsonl").exists()
    assert (tmp_path / "obs" / "otel_spans.jsonl").exists()
    trace = json.loads((tmp_path / "obs" / "trace.json").read_text(encoding="utf-8"))
    assert trace["root_run_id"] == root.run_id


def test_observability_status_is_graceful_without_optional_packages(monkeypatch):
    monkeypatch.delenv("SUPERQODE_OBS_MLFLOW_ENABLED", raising=False)
    rows = observability_status(
        ObservabilitySpec(
            exporters=(
                {"type": "mlflow", "enabled": True},
                {"type": "langsmith", "enabled": True},
            )
        )
    )

    names = {row["name"] for row in rows}
    assert {"local-jsonl", "mlflow", "langsmith"} <= names
    assert all("enabled" in row and "available" in row for row in rows)


def test_build_observability_sinks_uses_live_platform_sinks(monkeypatch):
    monkeypatch.delenv("SUPERQODE_OBS_OTEL_ENABLED", raising=False)
    sinks = build_observability_sinks(
        ObservabilitySpec(
            exporters=(
                {"type": "opentelemetry", "enabled": True, "endpoint": "http://otel:4317"},
                {"type": "langsmith", "enabled": True, "project": "sq-tests"},
                {"type": "logfire", "enabled": True, "service_name": "sq-tests"},
                {"type": "arize", "enabled": True, "endpoint": "http://phoenix:4317"},
            )
        )
    )

    by_name = {sink.name: sink for sink in sinks}
    assert by_name["local-jsonl"].__class__.__name__ == "LocalArtifactSink"
    assert by_name["opentelemetry"].__class__.__name__ == "OpenTelemetryLiveSink"
    assert by_name["langsmith"].__class__.__name__ == "LangSmithLiveSink"
    assert by_name["logfire"].__class__.__name__ == "LogfireLiveSink"
    assert by_name["arize"].__class__.__name__ == "ArizePhoenixLiveSink"


def test_langsmith_live_sink_exports_run_tree_without_network(tmp_path):
    store, root, _child = _store_with_child_run(tmp_path)
    trace = normalize_harness_trace(store, root.run_id)
    posted = []

    class FakeRunTree:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.children = []
            self.outputs = None

        def create_child(self, **kwargs):
            child = FakeRunTree(**kwargs)
            self.children.append(child)
            return child

        def end(self, *, outputs=None, **_kwargs):
            self.outputs = outputs

        def post(self):
            posted.append(self)

    sink = LangSmithLiveSink(enabled=False)
    sink.enabled = True
    sink._available = True
    sink._run_tree = FakeRunTree
    sink._client = object()

    result = sink.export_trace(trace, output_dir=tmp_path / "obs")

    assert result["status"] == "exported"
    assert len(posted) == 1
    assert posted[0].children
    assert posted[0].outputs["summary"]["run_count"] == 2


def test_logfire_live_sink_exports_summary_without_network(tmp_path):
    store, root, _child = _store_with_child_run(tmp_path)
    trace = normalize_harness_trace(store, root.run_id)
    infos = []

    class FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeLogfire:
        def span(self, *_args, **_kwargs):
            return FakeSpan()

        def info(self, message, **kwargs):
            infos.append((message, kwargs))

    sink = LogfireLiveSink(enabled=False)
    sink.enabled = True
    sink._available = True
    sink._logfire = FakeLogfire()

    result = sink.export_trace(trace, output_dir=tmp_path / "obs")

    assert result["status"] == "exported"
    assert {item[1]["run_id"] for item in infos} == {root.run_id, _child.run_id}


def test_export_unknown_run_raises_key_error(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")

    with pytest.raises(KeyError):
        normalize_harness_trace(store, "run_missing")
