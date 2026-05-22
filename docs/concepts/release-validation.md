# Release Validation

Release validation is a secondary SuperQode workflow for proving a change before it ships.

The main product surface is the coding harness: interactive TUI sessions, headless coding runs, HarnessSpec files, runtime adapters, model policy, tool policy, sandbox policy, and stored run events. Validation uses the same foundation to check generated changes, collect evidence, and produce reports.

---

## How It Fits

SuperQode has three related layers:

| Layer | Purpose |
| --- | --- |
| Coding harness | Inspect, edit, run, and verify code with controlled tools |
| Runtime backend | Execute the harness through the native loop, ADK, OpenAI Agents SDK, DeepAgents, PydanticAI, or another adapter |
| Validation workflow | Run quality checks, role-based review, evidence collection, and release readiness checks |

Validation is not a separate product in the docs. It is a workflow that can be attached to coding sessions, CI jobs, release checks, or future A2A flows.

---

## When To Use It

Use release validation when you need evidence that a change is ready:

- before merging a large implementation
- before cutting a release
- after an automated coding run changes several files
- when security, API behavior, or test quality needs focused review
- when CI needs machine-readable output

For day-to-day implementation, start with the coding harness. For proof and reporting, add validation.

---

## Common Commands

```bash
superqode qe run .
superqode qe run . --mode quick
superqode qe run . --mode deep
superqode qe run . -r security_tester -r api_tester
superqode qe run . --jsonl
superqode qe run . --junit results.xml
```

Useful follow-up commands:

```bash
superqode qe roles
superqode qe status
superqode qe artifacts
superqode qe report
superqode qe logs
superqode qe dashboard
```

---

## Outputs

Validation can produce:

- findings with evidence
- role-specific reports
- JSONL event streams
- JUnit output for CI
- dashboards and local artifacts
- fix suggestions when enabled

These outputs are meant to support release decisions. They do not replace the coding harness, runtime backends, or HarnessSpec.

---

## Next Steps

- [Harness System](../advanced/harness-system.md) for the harness and runtime model
- [Validation Commands](../cli-reference/qe-commands.md) for validation command details
- [CI/CD Integration](../integration/cicd.md) for automation examples
