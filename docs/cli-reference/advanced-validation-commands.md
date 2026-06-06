# Validation Commands

Validation commands run quality checks and produce evidence for release decisions. They are secondary to the main coding harness, but they use the same project configuration, provider setup, and workspace safety model.

---

## Overview

```bash
superqode qe COMMAND [OPTIONS] [ARGS]...
```

Use validation commands when you want to check a project, produce CI output, inspect findings, or review generated artifacts.

---

## Run

Run validation against a project path.

```bash
superqode qe run [PATH] [OPTIONS]
```

Common options:

| Option | Description |
| --- | --- |
| `--mode quick` | Fast validation pass for local development |
| `--mode deep` | Broader validation pass for release readiness |
| `--role`, `-r` | Run one or more focused roles |
| `--jsonl` | Stream machine-readable events |
| `--junit PATH` | Write JUnit output for CI |
| `--allow-suggestions` | Allow verified fix suggestions |
| `--generate` | Generate tests or fixes where supported |
| `--worktree` | Use git worktree isolation |

Examples:

```bash
superqode qe run .
superqode qe run . --mode quick
superqode qe run . --mode deep
superqode qe run . -r security_tester -r api_tester
superqode qe run . --jsonl
superqode qe run . --junit results.xml
```

---

## Roles

List available validation roles:

```bash
superqode qe roles
```

Examples:

```bash
superqode qe run . -r security_tester
superqode qe run . -r api_tester -r unit_tester
```

---

## Reports And Artifacts

Inspect outputs from previous validation sessions:

```bash
superqode qe status
superqode qe artifacts
superqode qe show <artifact-id>
superqode qe report
superqode qe logs
superqode qe dashboard
```

These commands help review findings, evidence, reports, logs, and generated artifacts after a run.

---

## Feedback And Suppressions

QE-specific feedback and suppression memory has been removed for the upcoming QE
refactor. The compatibility commands now return a refactor notice instead of
writing learned suppressions.

For general project facts, preferences, procedures, and SpecMem recall, use
`superqode memory`.

---

## CI Usage

For CI, prefer JSONL or JUnit output:

```bash
superqode qe run . --mode quick --jsonl
superqode qe run . --mode quick --junit results.xml
```

Use `--mode deep` for slower release gates where comprehensive evidence matters more than runtime.
