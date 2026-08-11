# Native RLM demo

This fixture is intentionally incomplete. `deploy_audit/report.py` must turn a
JSONL deployment history into the release-health summary defined in
`RUNBOOK.md`. The parser, tests and incident notes contain the evidence needed
to implement it.

Start with a failing baseline:

```bash
python -m unittest discover -s tests -v
```

Then open SuperQode in this directory, select `Model → Harness → RLM`, and use
the checked-in `rlm-docker.yaml` when Docker isolation is available.

Suggested task:

```text
Implement build_release_health in deploy_audit/report.py from the repository evidence and run the unit tests. Inspect the runbook, parser, fixture and tests before editing. Use context as data for the incident material and delegate independent reviews of the parser contract and test expectations before deciding on the implementation.
```

During a recording, `:rlm status`, `:rlm agents`, `:rlm usage` and
`:rlm sandbox doctor` show the runtime without adding model-facing tools. Close
the TUI while the task is running, reopen the same session, and use
`:rlm attach` to demonstrate that the resident worker continued.
