---
name: superqode-harness
description: Run, inspect, validate, or evaluate a SuperQode HarnessSpec inside the current QM agent computer.
---

# SuperQode Harness

Use this skill only when the user asks for SuperQode, a HarnessSpec, harness comparison, or harness evaluation.

1. Locate the requested HarnessSpec. Prefer an explicit path; otherwise look for `superqode.local.yaml`, `harness.yaml`, or `.superqode/harnesses/` in the current workspace.
2. Before the first execution of an unfamiliar spec, run `superqode harness validate --spec <path>` and `superqode harness inspect --spec <path> --json` when those commands are available in the installed version.
3. Read the execution policy. Tell the user when it permits writes, shell commands, network access, delegation, or an external runtime.
4. Run a bounded task with `superqode harness run --spec <path> --prompt <task> --working-dir <workspace> --json`. Reuse `--session <id>` only when continuing the same user-approved context.
5. Return the response plus `run_id`, `session_id`, stopped reason, pending approvals, and the narrowest relevant evidence. Do not paste the full event ledger unless requested.
6. Use `superqode harness events <run-id>` or `superqode harness graph <run-id>` for diagnosis and audit. Do not infer success only from prose; check the reported status and configured checks.

Never run `superqode auth` or `superqode serve` inside the QM agent computer. Credentials and long-lived A2A services belong to the deployment operator. Do not weaken a HarnessSpec's execution policy to bypass a denial or approval.
