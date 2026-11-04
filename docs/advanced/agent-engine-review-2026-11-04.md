# Agent development engine review, 4 November 2026

SuperQode should make it easy to answer: **which harness works best on my repository, under my quality, cost, latency and permission constraints?** The latest source already contains much of the machinery. The next investment should make its measurements more trustworthy and connect the existing capabilities into one developer workflow.

This review does not establish that SuperQode or any competitor is universally better. That requires comparable workloads and measured results. One reproduced evaluation defect is fixed on the review branch; a separate workspace contamination problem remains open.

## Source and verification scope

SuperQode was fetched from `origin/main` at `23f3cba543cea209ab780ccd22d6020cb240f7fb`, dated 3 November 2026. Source metadata identifies Python **2.31.2** and macOS **0.3.3, build 19**. PyPI independently listed 2.31.2, uploaded on 3 November. This Linux review did not verify a downloaded macOS binary, notarization, an App Store listing, or native Swift execution.

Competitor repositories were inspected as source snapshots on 4 November. Their main-branch documentation may describe work beyond their latest release. These are source comparisons, not end-to-end tests of installed competitor applications.

| Product | First-party snapshot | Scope and limits |
| --- | --- | --- |
| SuperQode | [`23f3cba5`](https://github.com/SuperagenticAI/superqode/tree/23f3cba543cea209ab780ccd22d6020cb240f7fb) | Python engine, native Swift sources, tests and documentation. Targeted offline tests ran here. |
| Codex | [`010520de`](https://github.com/openai/codex/tree/010520de766c4f23f45a540b4c4d5c6c67fbf7ff) | Open-source CLI and app-server contracts. The official desktop feature site was blocked by this environment's network policy; this is not a full audit of the Codex desktop application. |
| T3 Code | [`8b44f42b`](https://github.com/pingdotgg/t3code/tree/8b44f42b14c8e273156474a924ccf29680dd7857) | Main README, remote access, source control, outside-agent integration and orchestration internals. |
| Herdr | [`ee5bfb50`](https://github.com/herdrdev/herdr/tree/ee5bfb5041bb3e4a49d591c72308aae3c81ecdde) | README and persistence/remote documentation. Some detailed documentation is under `docs/next`; it is development documentation. The website was blocked here. |
| Orca, provisional identification | [`stablyai/orca`, `79d83ba7`](https://github.com/stablyai/orca/tree/79d83ba7eb4557206c5070b46140099e0bf70c1d) | README, worktrees, browser design mode, SSH and review documentation. Several projects are named Orca; this comparison assumes the desktop agent workspace at onorca.dev until the intended product is confirmed. |

No competitor application was installed or benchmarked. Feature descriptions below are grounded in these sources; missing evidence is not proof that a competitor lacks a feature.

## Capabilities already present

The latest source is substantially ahead of the older Strands branch. Do not plan replacements for capabilities already implemented.

| Area | Current implementation | Remaining opportunity |
| --- | --- | --- |
| Harness authoring | Native Harness Studio imports/edits/validates specs, saves immutable revisions, binds check evidence to reviewed definitions, and runs repeated restricted read/edit checks. | Connect those revisions to repository-quality experiments and rollout history. Studio checks do not certify the full harness. |
| Evaluation and optimisation | Native Evaluations, task comparison and regression inspector, bounded Omni experiments, candidate diffs and reviewed adoption; CLI held-in/held-out splits and seesaw gates. | Improve execution integrity, repository outcome graders and the full native experiment lifecycle. |
| Reproducible benchmarks | HarnessBench already supports 1 to 100 repetitions, fingerprints, raw runs, artifact checksums, mean/stddev/min/max, coverage, per-task outcomes and Pareto ranking. Unknown cost remains unknown. | Isolate trials, add uncertainty estimates and percentile summaries, and expose these controls/results in a dedicated experiment experience. |
| Promotion | Existing staging, deterministic canary selection, activation, source digest checks and rollback; WorkOrders use promotion selection. | Make adoption/canary/rollback clear in the native app and integrate selection into ordinary desktop tasks. |
| Routing | Existing RLM adaptive routing, SystemOne example-based tuning, provider/model routes and explicit connection selection. | Combine repository evidence with harness, model and provider choices, while preserving permission and budget constraints. |
| Daily coding | Thread search/pins/archive/tabs, activity states, reviewed thread handoff, draft recovery, turn checkpoints, branch review, revision-bound line feedback, staging and local commits. | Complete and verify the issue-to-PR-to-CI loop; avoid duplicating these existing review controls. |
| Isolation and continuity | Draft-to-worktree flow, task/thread branches, writer leases, interrupted-task recovery and an opt-in background engine. | Reuse ownership/lease concepts for evaluation fixtures and systematic fault testing. UI detach survives with the daemon; engine/Mac loss interrupts work. |
| Connectivity | ACP discovery/setup/authentication/custom commands, subscription-backed agents, provider keys, local AI, Strands and other runtimes. | Capability/version contract tests and shorter recovery paths matter more than another provider logo. |
| Local models | Discovery, downloads, isolated MLX setup, server controls and guided DS4 configuration. | Measure first successful local task and expose compatibility evidence without implying coding quality from readiness probes. |

The [native app documentation](https://github.com/SuperagenticAI/superqode/blob/23f3cba543cea209ab780ccd22d6020cb240f7fb/apps/macos/README.md) explicitly distinguishes working features from previews. Super Agent Creator currently produces reviewed scaffolding with recursion off; its optional Monty check prints a template. Pro verification and team approval remain previews. Neither should be marketed as completed autonomous optimisation or production release certification.

## Reproduced evaluation findings

### P0: failed execution could become a passing evaluation, fixed on this branch

At the reviewed main commit, `_run_eval_task` in `src/superqode/harness/eval.py` grades `result.content` without checking execution completion. A backend can return an `AgentResponse` with matching answer text and `stopped_reason="error"`; the kernel records a failed run, but the evaluation and held-out gate can accept its text.

An offline fixture returned `EXPECTED` with an error stop for both variants:

```text
Before fix: report_status=passed; task_statuses=[passed, passed]; gate.accepted=true
After fix:  report_status=failed; task_statuses=[error, error]; gate.accepted=false
```

The fix checks every recorded run before invoking any grader. Incomplete, cancelled, approval-blocked, exhausted, unknown or error-bearing responses cannot count as successful evaluation evidence. Workflow failures and empty workflow results are also rejected. Run IDs and reported token/cost usage remain attached to unsuccessful trials.

Ten regression cases in `tests/test_harness_eval_execution.py` cover this contract, including a real HarnessKernel with an offline backend fixture. They make no paid model calls. This fixes admission of failed execution; it does not make text matching a sufficient coding-quality grader.

### P0: evaluation variants can contaminate one another's workspace, open

`run_harness_eval` passes the same `working_dir` into every variant and task. It does not create/reset a separate repository snapshot per trial. An offline fixture where the baseline writes `marker.txt` confirmed that the candidate then sees that file. Both trials were accepted by the held-out gate.

```text
baseline:  marker_existed=false
candidate: marker_existed=true
report_status=passed; gate.accepted=true
```

This can invalidate comparisons for coding or other mutating tasks, even when the task list and harness files are hashed. HarnessBench repeats this evaluation path; checksums preserve the recorded artifacts but cannot repair contaminated execution inputs. A configured sandbox is not, by itself, evidence that each trial received a fresh fixture.

Required design:

1. Capture an explicit source snapshot before evaluation, including the intended dirty files and selected context. Do not modify, reset or clean the developer's checkout.
2. Allocate a fresh owned workspace per task, variant and repetition. Use worktrees or copied fixtures for repository state; use a stronger sandbox where process/filesystem containment is required. Worktrees alone do not isolate the whole host.
3. Bind source-tree, task, harness, model, runtime, permissions and environment fingerprints to each trial. Record setup and teardown failures separately from grader failures.
4. Keep build caches separate from mutable task inputs; make any cache reuse explicit. Retain reviewed diff/test artifacts before cleaning owned resources.
5. Prove order independence: a baseline that creates/modifies/deletes files cannot change a candidate's starting state. Cover dirty repositories, cancellation, interrupted cleanup and non-Git directories.

Existing `harness2` attempt workspaces, native Studio fixture checks and desktop worktree ownership offer useful implementation patterns. They do not already isolate this generic evaluation path.

### P0: coding quality needs repository outcome evidence

The generic evaluator contract currently supports `decision`, `contains`, `non_empty` and `jev_rubric`. The smoke-only flag and rejection of `non_empty` promotion evidence are useful existing safeguards. However, an answer containing a requested phrase does not prove that a patch builds, passes tests or solves the task.

Add a trusted repository-task evaluator that records test/check exit codes, structured reports, required file/state assertions, resulting patches and relevant tool outcomes. Reuse existing repository check runners where appropriate. The host should execute reviewed suite commands; never treat commands emitted by the model as trusted grader configuration. Keep hidden-test material outside candidate-visible inputs, bound time/cost, and distinguish unsupported grading from a failed task. Rubric grading can supplement executable evidence where tests are insufficient.

This is a gap in the generic scorecard/adoption contract, not a claim that SuperQode has no check runners or test execution elsewhere.

## Lessons from the comparator sources

| Comparator | Relevant source evidence | Improvement for SuperQode |
| --- | --- | --- |
| Codex | The [app-server contract](https://github.com/openai/codex/blob/010520de766c4f23f45a540b4c4d5c6c67fbf7ff/codex-rs/app-server/README.md) makes capabilities, session operations, pending approval replay and structured errors explicit. | Test native adapters against advertised capabilities and supported CLI versions. A reconnect must restore pending decisions or surface an explicit incompatible/interrupted state. Do not assume every agent supports resume, fork, permission modes or remote cancellation. |
| T3 Code | [Remote access](https://github.com/pingdotgg/t3code/blob/8b44f42b14c8e273156474a924ccf29680dd7857/docs/user/remote-access.md) covers paired devices, reachable host requirements, route changes and credential renewal. [Source control](https://github.com/pingdotgg/t3code/blob/8b44f42b14c8e273156474a924ccf29680dd7857/docs/user/source-control.md) covers PR workflows and distinguishes turn work from changes introduced by Git operations. | Make the complete Git/PR/check loop first class and verify change attribution under merges. Build authenticated remote host attachment only after local recovery semantics are reliable. |
| T3 Code internals | [Orchestration overview](https://github.com/pingdotgg/t3code/blob/8b44f42b14c8e273156474a924ccf29680dd7857/docs/internals/overview.md) commits events, projections, command receipts and outbox effects together, and distinguishes provider completion from later checkpoint work. | Audit SuperQode's existing daemon for durable intent, retry deduplication, event ordering, stale-client fencing and checkpoint failures. Prefer targeted invariant fixes before considering an architecture rewrite. |
| Herdr | The [README](https://github.com/herdrdev/herdr/blob/ee5bfb5041bb3e4a49d591c72308aae3c81ecdde/README.md) distinguishes detach/reconnect from process loss on machine/server restart, and centralises working/blocked/idle across machines. | Make ownership, needs-attention and recovery status consistent across runtime adapters. Preserve the existing [SuperQode integration](../integrations/herdr.md); Herdr can remain a complementary terminal host. |
| Orca, provisional | [Worktrees](https://github.com/stablyai/orca/blob/79d83ba7eb4557206c5070b46140099e0bf70c1d/docs/site/content/docs/model/worktrees.mdx) frame a task from isolated checkout through review and archive. [Design Mode](https://github.com/stablyai/orca/blob/79d83ba7eb4557206c5070b46140099e0bf70c1d/docs/site/content/docs/browser/design-mode.mdx) attaches selected DOM, styles, screenshot and available source-map location to an agent. | Build a measured side-by-side harness experiment on isolated tasks. Later add a focused browser-to-task context bridge for web developers, reusing existing attachment/review controls. |

These sources establish useful workflow patterns. They do not establish that the competitors lack evaluation, outperform SuperQode, or have identical shipped behavior to their main branches.

## Ordered implementation plan

### 1. Make evaluation evidence dependable

Land the failed-execution fix after review. Then implement fresh trial workspaces and repository outcome graders before making stronger public claims about optimisation gains. Both baseline and candidate must start from the same declared source/context state. Cancellation, budget exhaustion and unavailable graders must never become a quality pass.

Acceptance: adversarial fixtures cannot pass through matching text, stale files, prior task edits, missing execution or unavailable grading. Successful normal runs still grade; failed trials retain cost and lineage. Hold-out inputs and expected outputs remain separated from optimizer-visible material.

### 2. Give macOS one complete harness improvement workflow

Connect the existing features into:

```text
Choose repository and goal
  -> select a saved Studio revision and reviewed task suite
  -> inspect permissions, budgets and execution setup
  -> compare baseline/candidates in isolated repeated trials
  -> inspect task outcomes, patches, costs and regressions
  -> review an optimised revision on held-out tasks
  -> use, canary, monitor or roll back the revision
```

Reuse the existing Evaluations, Optimization, HarnessBench and promotion services. Benchmarks and promotion currently use generic Tools forms for some advanced operations. Make the lineage, setup needs and current lifecycle state visible in one native experiment record rather than requiring the user to assemble files across screens.

Acceptance: a developer can complete this path without terminal commands, distinguish setup checks from quality measurements, reopen the same experiment after app restart, inspect what changed, and export the exact evidence package. Existing safeguards against stale revisions must remain enforced.

### 3. Route from measured repository evidence

Extend the existing RLM/SystemOne/model-route capabilities into an explicit project policy across harness, model and provider. Start with user-selected task classes and recent comparable evidence; avoid opaque automatic classification as a prerequisite.

Show the selected route, evidence age/coverage, expected cost/latency range, constraints and fallback. Hard permissions, required capabilities and budget must filter candidates before ranking. Unknown costs cannot be ranked as free. Invalidate stale evidence after relevant configuration, source, provider or model changes.

The existing canary selector is called by WorkOrders. This review found no call in the ordinary desktop task path. Integrate the same reviewed promotion selection there, record the selected revision per run, and keep in-flight sessions bound to their original revision.

Acceptance: repeated selection with the same policy/key is explainable; ineligible routes never run; provider failure preserves the declared fallback limits; canary scope and rollback are visible and testable for native tasks.

### 4. Present statistical evidence developers can judge

HarnessBench already provides repetitions, raw evidence and Pareto summaries. Add confidence intervals for paired task differences, explicit sample counts/coverage, and latency percentiles. Randomise or counterbalance trial order after isolation. Separate experiments that change only the harness from experiments that also change the model, provider or budget.

Acceptance: a single lucky run cannot be presented as a proven improvement; tiny or incomplete samples remain inconclusive. Users can inspect failures and reproduce aggregates from exported raw trials. Apply a user-reviewed total budget before increasing repetition counts.

### 5. Shorten first success and strengthen everyday reliability

Keep the existing guided connection flow. Offer three clear starting goals: use an existing authenticated agent, run a local model, or build/test a harness. Explain capability failures at the action that needs the capability. Keep one-off readiness, restricted read/edit checks and repository task quality distinct.

Measure time to first verified task, connection failure rate, manual recovery steps and lost drafts. A proposed target is under five minutes for an already authenticated supported agent, measured on clean test machines; this is a target, not a current performance claim.

Expand the existing recovery suite across UI quit, daemon kill, worker crash, provider disconnect, pending approval, sleep/wake, cancellation and stale writer leases. Verify no duplicated paid turn or side effect. Clearly mark ongoing, interrupted, resumable and completed work. Profile actual transcript/list latency and memory before proposing rendering rewrites.

### 6. Complete delivery, then remote and browser workflows

Extend the existing native review/staging/commit surface into a coherent issue-to-PR-to-CI path, with authenticated host selection, current check status and revision-bound feedback. Test turn attribution when an agent pulls or merges external changes. Use existing checkpoints and branch review rather than creating a second diff implementation.

For remote development, build on existing UHP/ACP/remote-worker components. Scope authenticated host attachment, event cursors, revocation and reconnect first; a mobile application is a later product decision. Retain Herdr compatibility.

A focused browser context capture can later reduce web UI task friction. Review DOM/screenshot/source context before attachment and measure its effect on task success. Rebuilding a full IDE, adding more provider branding or expanding preview labels should not outrank dependable evaluation and routing.

## Validation and release boundary

On this review branch, the selected Python harness and desktop regression checks completed in two batches with **237 passed, 16 skipped**. Three skipped checks require the optional ADK, OpenAI Agents and PydanticAI SDKs; thirteen require an explicitly configured isolated Strands interpreter. Those runtimes were not available to these test runs. Ruff lint and format checks, the public documentation style check, and the documentation build passed. Offline probes confirmed that the execution failure is now rejected and workspace contamination remains reproducible.

These checks validate the narrow fix and selected surrounding behavior. They do not certify every runtime, a live provider, Swift UI behavior, or an installed macOS release. No version was bumped and nothing was merged or released as part of this review.

Before a broader superiority or release-quality claim, use a declared pilot workload: several representative repositories, distinct coding task classes, executable outcomes, fixed permissions and comparable budgets. Start with a bounded pilot of roughly 30 to 50 tasks and repeated trials affordable under the agreed budget, then use observed variability to choose a sufficient sample. Report solved tasks, regressions, cost per solved task, latency, missing evidence, recovery success and onboarding failures. Publish the full evidence package and its limitations.

Useful starting code: `harness/eval.py`, `harness/evaluators.py`, `harness/bench.py`, `harness/acceptance.py`, `harness/promotion.py`, `workorders/runner.py`, `desktop_service/service.py`, `desktop_service/studio.py`, `desktop_service/task_worktree.py`, and the native `HarnessStudioView.swift`, evaluation/optimization views and `Workspace.swift`.
