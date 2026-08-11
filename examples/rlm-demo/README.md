# Native RLM example

This fixture is intentionally incomplete. `deploy_audit/report.py` must turn a
JSONL deployment history into the release-health summary defined in
`RUNBOOK.md`. The parser, tests and incident notes contain the evidence needed
to implement it.

Start with a failing baseline:

```bash
python -m unittest discover -s tests -v
```

## Analyze with Monty

The optional Monty profile provides persistent Python, repository context, and
focused model calls without exposing a shell, writable filesystem, third-party
imports, or recursive child processes. Install the optional dependency:

```bash
uv tool install 'superqode[monty]'
```

Run the read-only HarnessSpec:

```bash
superqode --harness rlm-monty.yaml
```

Submit an analysis task that does not require repository changes:

```text
Analyze RUNBOOK.md, deploy_audit/parser.py, INCIDENT.md, and tests/test_report.py. Use context selection and llm_query_batched to identify the complete build_release_health contract. Return an implementation plan with the ordering, retry, latency, and malformed-record rules. Do not modify files or run commands.
```

Monty supports `context`, `workspace.read`, `llm_query`, and
`llm_query_batched`. It refuses `workspace.write`, `workspace.edit`,
`shell.run`, completion gates, and `rlm.run`.

## Implement with Docker

Run the coding HarnessSpec with Docker isolation:

```bash
superqode --harness rlm-docker.yaml
```

Connect a configured model when prompted.

Suggested task:

```text
Implement build_release_health in deploy_audit/report.py from the repository evidence and run the unit tests. Inspect the runbook, parser, fixture and tests before editing. Use context as data for the incident material and delegate independent reviews of the parser contract and test expectations before deciding on the implementation.
```

Use the RLM command surface to inspect and manage the active session:

```text
:rlm status
:rlm sandbox doctor
:rlm agents
:rlm usage
:rlm detach
:rlm attach
:rlm stop
```

The model receives only the persistent `python` tool. The Docker profile keeps
Python execution inside the configured container with network access disabled.
After the task completes, verify the implementation:

```bash
python -m unittest discover -s tests -v
```
