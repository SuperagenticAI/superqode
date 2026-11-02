---
title: Observability
description: Export SuperQode runs to OpenTelemetry, MLflow, LangSmith, Logfire, and Arize Phoenix.
---

# Observability

Local JSONL events, run graphs, and export artifacts are included. Install the
external sink bundle when traces must also be sent to another system:

```bash
uv tool install "superqode[observability]"
superqode harness observability status
```

| Integration | Configuration | Result |
| --- | --- | --- |
| OpenTelemetry | Enable the OTEL sink and set an OTLP endpoint | Live harness spans are exported to the collector |
| MLflow | Enable the MLflow sink and select an experiment | Run artifacts and metrics are logged to MLflow |
| LangSmith | Enable the LangSmith sink and provide its credential | The normalized run becomes a LangSmith run tree |
| Logfire | Enable the Logfire sink and configure Logfire | Run summaries and events are mirrored as spans and logs |
| Arize Phoenix | Enable the Arize sink and configure its OTEL collector path | Harness traces are sent through the Phoenix OTEL route |

Export a completed run:

```bash
superqode harness observability export <run-id> \
  --spec harness.yaml \
  --output .superqode/obs/<run-id>
```

For PydanticAI model and tool tracing, install the dedicated extra and enable
tracing in your HarnessSpec:

```bash
uv tool install "superqode[pydanticai-logfire]"
```

Configure your Logfire destination and credentials before enabling external
trace export.

See the [Harness CLI observability reference](../cli-reference/harness-commands.md#harness-observability-status)
and [configuration reference](../configuration/yaml-reference.md).
