# Coding and harness-optimization feature checklist

25 October 2026, `4dcac5c` plus the local working draft. This is a source-based
checklist, not a claim of complete parity or verified superiority. Native source
and tests still require compilation and interaction validation on macOS. Product
capabilities available through CLI/TUI do not automatically have a native workflow.

The [developer-experience plan](DEVELOPER-EXPERIENCE.md) records local implementation
and validation. See [session recovery](SESSION-RECOVERY.md) for the current change.

## Daily coding

| Capability | Current local status | Next acceptance condition |
| --- | --- | --- |
| Open projects, connect agents/models | Native source exists | Clean Mac onboarding succeeds with supported agent versions and actionable failures. |
| Streaming, tool activity and approvals | Native source exists | Validate permission denial, cancellation acknowledgement, keyboard use and VoiceOver per route. |
| Long-run history and retry | Implemented native draft | Reopen long completed/cancelled runs, switch while loading and resume after a failed fetch without lost or duplicate activity. |
| Command palette and shared menu actions | Implemented native draft | Validate Command-K, IME input, focus restoration, Settings-window invocation and disabled-action explanations. |
| Editing and integrated terminal | Native source exists | Preserve editor text during concurrent disk changes; validate terminal lifecycle and clipboard on real macOS. |
| Git diff, staging and local commits | Native source exists | Add explicit turn/uncommitted/branch review scopes, deletion staging and consistent sensitive-path handling. |
| Scoped diffs and line-range feedback | Implemented locally; native validation pending | Identify exactly which source/revision a comment refers to and preserve unrelated changes. |
| Session resume and cross-agent handoff | Native source exists with route limitations | Explain native resume versus transcript handoff and omitted context. |
| Session destinations and drafts | Implemented locally; conversation drafts and full destinations | A → B → Back restores the session, draft, selection and inspector. |
| Recoverable source-editor drafts | Implemented locally; persistent drafts and conflict comparison | Restart after a crash and recover text/base revision; offer Compare, Copy and Save As on conflict. |
| Fork/tree, pin/archive and session search | Broader operations through forms/CLI; dedicated native UX incomplete | Navigate lineage and search beyond recent rows without destabilizing selected-session ordering. |
| Reading-position-aware transcript | Implemented locally; Follow, message anchors and Jump to latest | Upward scrolling pauses follow; Jump to latest resumes; history loading preserves anchors. |
| Background notifications and Dock badge | Planned | Deduplicated approval/completion notifications reopen the exact session. |
| Independent windows and remote/mobile continuity | Native gap; other remote interfaces exist | First establish durable writer ownership, then restore independent destinations and reconnect without event loss. |
| Signed updater and migration recovery | Manual app updates today | Verify update signatures and supported data migrations/rollback on clean Macs. |

## Harness engineering and optimization

| Capability | Current local status | Next acceptance condition |
| --- | --- | --- |
| Harness Hub and repository-owned definitions | Native discovery exists; advanced authoring/diagnostics use other surfaces | Make creation, validation, capability inspection and revision selection a cohesive native workflow. |
| Evaluation setup/live execution | Native source exists | Keep skipped setup checks distinct from measured quality; disclose charges and execution route. |
| Baseline/candidate task comparison | Implemented native draft | Inspect wins, regressions, unknowns, reasons and cost/time changes for each candidate. |
| Optimizer held-out review | Implemented native draft | Use held-out task evidence; smoke checks, contradictory records and missing coverage cannot establish improvement. |
| Recorded/imported evidence | Native import/export exists, comparison projection added | Review the same projection for saved runs and raw/wrapped older reports without modifying source artifacts. |
| Staged Omni optimization and candidate diff | Native source exists | Test budget controls, interruption, stale candidate detection and independent held-out checks. |
| Broader optimizers, benchmarks, skills and memory | Available through typed forms/CLI/TUI to varying degrees | Build dedicated workflows based on frequency and support guarantees rather than copying every command into a form. |
| Experiment history and quality/cost frontier | Planned dedicated native view | Compare fixed source/configuration hashes, repeats, uncertainty and all failed-attempt costs. |
| Quality thresholds and adoption decisions | Existing backend gates; known semantics need separate fixes | Separate execution completion from quality; explicitly block missing/ungraded evidence under declared thresholds. |
| Versioned adoption, canary and rollback | Broader lifecycle exists outside a unified native flow | Record why a revision was adopted and restore its predecessor with matching evidence. |
| Resource/cost dashboard | Partial metrics; dedicated dashboard planned | Account for unknown usage and overshoot; distinguish reported spend thresholds from provider billing caps. |

## Delivery order

1. Fix durable worker ownership, valid terminal-result enforcement and worktree
   preservation. These protect both coding and matched experiment inputs.
2. Complete session destinations/draft recovery, scoped review and reading-aware
   streaming. These address frequent daily navigation and review workflows.
3. Validate the implemented command palette and comparison inspector on macOS.
   Add repeated, held-out experiment history and explicit quality thresholds.
4. Add routed notifications, revision adoption/rollback and resource dashboards.
5. Extend independent windows, remote monitoring and mobile continuity after the
   execution/ownership foundations are proven.

The comparison inspector is a read-only review aid. It does not replace the
existing promotion or adoption gates, verify imported evidence authenticity, or
establish that a harness outperforms another product. Those claims need controlled
benchmarks and real developer trials in the actual applications.
