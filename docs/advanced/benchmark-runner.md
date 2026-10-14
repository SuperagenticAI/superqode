# Graded coding comparisons

Use `superqode benchmark compare` for coding quality comparisons. Each attempt
receives an isolated copy of the task seed. Independent executable checks grade
the resulting code. An agent's successful process exit alone does not establish
coding correctness. The separate HarnessBench response-text checks are useful
for smoke testing, but should not be reported as solved coding tasks.

## Prepare a manifest

Paths in `cwd` are relative to the manifest. Commands are argument arrays; the
runner appends the task prompt to each target command. Use explicit provider,
model and pinned revision values for every target.

```json
{
  "targets": [
    {"name": "candidate", "command": ["/absolute/path/to/candidate-wrapper"], "provider": "your-provider", "model": "your-model", "revision": "exact-revision"},
    {"name": "baseline", "command": ["/absolute/path/to/baseline-wrapper"], "provider": "your-provider", "model": "your-model", "revision": "exact-revision"}
  ],
  "tasks": [
    {"id": "bug-fix", "prompt": "Fix the bug and run the tests.", "cwd": "fixtures/bug-fix", "timeout_seconds": 300, "checks": [["python3", "verify.py"]], "protected_paths": ["verify.py"]}
  ]
}
```

Configure wrappers for the installed CLI versions. The declared models must
match for a controlled harness comparison. Graders should exercise behavior,
including negative cases, without depending on the assistant's prose. Protected
paths detect grader modifications. A copied workspace is not a security sandbox;
use an appropriate container or host boundary for untrusted agents.

## Validate and run

```bash
superqode benchmark compare comparison.json --dry-run --output plan.json
superqode benchmark compare comparison.json --repetitions 3 --output results.json
```

Dry runs inspect executable availability, task directories, graders and protected
paths without starting agents, running graders, or checking accounts. They do
not certify authentication or upstream behavior. A live run requires working
provider access and can incur model charges.

Reports contain per-attempt results, timing, source hashes, grader evidence and
a scorecard. Review `comparison_ready` and `comparison_blockers` before making
comparative claims. Missing usage is unknown, not free. Account for failed
attempts, subagents and auxiliary model calls. Harness-reported costs are
estimates rather than billing verification.

Run both a matched-model comparison and a separate recommended-configuration
product trial. Label them separately. Keep held-out tasks and use multiple
trials. Small sample tasks alone do not establish performance on production
repositories. Publish versions, operating system, task-level outcomes, costs and
failures alongside any headline success rate.

## Inspecting attempt workspaces

Use `benchmark compare ... --artifacts /tmp/comparison-artifacts` to keep each
attempt's workspace and result metadata after grading, including failed and
timed-out attempts. The artifact directory must sit outside every seed task
directory. Links created by an agent are retained as links, not followed during
collection. Treat retained workspaces as agent output; inspect the patch before
executing anything from them. Without this option, temporary attempt workspaces
are removed as before.
