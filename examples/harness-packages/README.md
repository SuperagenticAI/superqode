# Python harness packages

The `hello-harness` directory is the smallest independently installable
SuperQode harness. Its package contains one async function and one Python entry
point. SuperQode supplies the controller, sessions, event ledger, export, and
conformance checks.

Try it from the repository root:

```bash
uv pip install -e examples/harness-packages/hello-harness
superqode harness list
superqode harness run hello "say hello"
superqode harness protocol conformance hello
```

The entry point is the only registration required:

```toml
[project.entry-points."superqode.harnesses"]
hello = "superqode_hello_harness:run"
```

Packages that need custom cancellation, steering, checkpoints, or ACP behavior
may export a complete `HarnessAdapter` object instead of a function.
