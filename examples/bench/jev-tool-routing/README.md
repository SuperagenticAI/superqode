# Jev Tool Routing benchmark fixture

This is the calculator fixture used for the Jev Tool Routing benchmark snapshot
published on 21 September 2026. It is intentionally small so the comparison
measures tool-catalogue routing instead of code generation.

The expected result is two passing tests, and `add(19, 23)` returns `42`.
Run the control before invoking a coding harness:

```bash
python -m unittest -q
```

The complete shadow/enforce procedure, provider requirements, harness commands,
and measurement definitions are in the
[Jev Tool Routing command guide](../../../docs/cli-reference/optimize-commands.md#reproduce-the-benchmarks).
