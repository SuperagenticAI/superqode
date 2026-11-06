# macOS and iOS feature audit

Generated from `SuperQode/FeatureParity.json`, the same inventory used by the iOS All features screen.

The inventory accounts for all 14 Mac navigation areas and 24 typed Tools categories. This is inventory coverage, not a claim of complete mobile functionality.

## Finding

Full macOS parity is not implemented. Daily coding, contextual review, explicit approvals, reference files, images, file editing, queue controls, checkpoint restoration, evidence export, evaluation and staged optimization are implemented on the phone. Several are partial: custom evaluation/candidate setup, local-model lifecycle, harness authoring, routing/tuning, WorkOrder management, terminal/Git administration and notifications still require additional work.

The home screen promotes Code, Review, Evaluate and Optimize. Harness Lab opens on Evaluate & improve, with separate evaluation and optimization setup. WorkOrders, queues and checkpoints are discoverable in project tools; every major workflow is searchable in All features with its actual availability.

## Workflow comparison

### Daily development

| Workflow | Phone parity | Current behavior and gaps | Mac entry point |
| --- | --- | --- | --- |
| Coding and planning | Partial | Fresh conversations, explicit shared connections, supported Code/Plan/Direct Chat, protected drafts and recovery of interrupted submissions. Native phone tasks use Ask; Auto-edit and Full overrides remain Mac controls. | Threads workspace → composer |
| Conversation library | Available | Search, paginate, rename, pin, archive and continue recorded project conversations. | Threads workspace |
| Contextual review | Available | Review uncommitted, branch or completed-turn changes. Prepare line-bound feedback. Staging requires a separate permission approved on the Mac. | Features → Review |
| Project files | Available | Read highlighted project source, create files and save edits against the exact loaded revision with a separately approved editing grant. Conflicting saves can be compared with current Mac content before an explicit new save. | Features → Files |
| Reference files | Available | Attach up to ten non-sensitive UTF-8 files to Code/Plan and preview their context before sending. | Threads workspace → attach files |
| Images and screenshots | Available | Attach up to four PNG, JPEG, GIF or WebP images. Other photo formats are converted on the phone. Image drafts are protected locally; uploads are private, idempotent and bound to this device and project. Model image support still applies. | Threads workspace → attach images |
| Thread handoff | Available | Review bounded visible thread context, share it or prepare a fresh conversation with no inherited connection, permissions, images or private reasoning. Export recorded evidence as Markdown, JSON or HTML. | Threads workspace → handoff |
| Windows, tabs and command palette | Mac only | Multiple workspace windows, persistent thread tabs, layout controls and the full command palette remain Mac features. The phone uses native navigation and searchable All features. | Workspace windows / thread tabs / command palette |

### Harness quality

| Workflow | Phone parity | Current behavior and gaps | Mac entry point |
| --- | --- | --- | --- |
| Harness evaluation | Partial | Inspect bundled suites, choose task splits, validate setup and explicitly authorize live runs. Custom suites and candidate definitions are configured on the Mac. | Evaluations |
| Harness optimization | Partial | Run configured optimization with explicit budgets, review held-out evidence and compare improvements/regressions. Adoption stays on the Mac; local-only optimizer routes are not yet verified. | Optimization |
| Harness Studio | Mac only | Use Harness Studio on the Mac to edit, validate, version and activate harness definitions. The phone does not edit or activate definitions yet. | Harness Studio |
| Harness Hub | Partial | Use harnesses explicitly shared by your Mac. Discovering, installing and configuring new harnesses remains in the Mac's Harness Hub. | Harness Hub |
| Benchmarks and failure mining | Mac only | The Mac exposes CLI-backed benchmark, doctor, failure-mining and advanced optimization workflows. They are not native phone workflows yet. | Tools → Harness workflows / Benchmarks / Quality gauges |
| Routing and tuning | Mac only | Configure RLM routing/budgets and tune routing examples on the Mac. Shared harnesses use those settings when the phone starts work. | Harness Studio / Evaluations → routing and tuning |
| Candidate promotion | Mac only | Review adoption gates, stage, canary, activate or roll back candidates on the Mac. Evidence on the phone never authorizes promotion. | Optimization → adoption / Tools → Harness workflows |
| Skill optimization | Mac only | Use the Mac Tools forms for skill optimization and its evidence. This is separate from staged harness optimization. | Tools → Skill optimization |
| Agent factory and Creator Mode | Mac preview | Author, inspect, save and enable reviewed agent drafts on the Mac. Experimental Creator/Super Agent interfaces are not finished mobile features. | Super Agent / Tools → Agent factory |

### Execution and recovery

| Workflow | Phone parity | Current behavior and gaps | Mac entry point |
| --- | --- | --- | --- |
| WorkOrders and workers | Partial | Track tasks, budgets, worker responsiveness and acceptance checks. Creation and execution management remain on the Mac. | Tools → WorkOrders → Live WorkOrder board |
| Task queue | Available | Add tasks through shared connections; inspect, run, pause, reorder, remove and reset retries using explicit queue permission and a reviewed queue revision. Mac-only routes and control overrides cannot be started through this grant. | Threads workspace → task queue |
| Task checkpoints | Available | Inspect recorded diffs; explicitly undo, redo or restore sealed checkpoints with restoration permission. Changed checkpoint state and later file edits are refused by the Mac. | Features → Checkpoints |
| Forks and Git changes | Mac only | Create isolated fork workspaces and review/merge their commits on the Mac. The phone does not commit, merge or switch branches. | Threads workspace → fork / review branch |
| Terminal | Mac only | Interactive terminal and generic CLI workflows remain on the Mac. Agent tool requests can still be reviewed through exact-request approvals on the phone. | Features → Terminal |
| Execution recovery | Mac only | Resolve interrupted writer ownership and acknowledge recovery from the Mac. The phone can inspect run errors and stop permitted jobs. | Workspace → execution recovery |
| Run activity and approvals | Available | Inspect live runs, approve or deny exact requests, steer supported runs and stop permitted jobs. Updates resume when the phone app returns to the foreground. | Features → Agent activity |

### Connections and setup

| Workflow | Phone parity | Current behavior and gaps | Mac entry point |
| --- | --- | --- | --- |
| Local models | Partial | Use shared local-model connections from the phone. Downloading models, engine lifecycle, compatibility checks and new route setup remain in Local AI on the Mac. | Models → Local AI |
| Providers and subscriptions | Mac only | Install/sign in to agents and configure API keys on the Mac. Share supported connections with the phone; provider credentials stay there. | Connection settings → Providers / Subscriptions |
| Tools, MCP and skills | Mac only | Configure these in the Mac app. Shared harnesses retain their configured capabilities, permissions and tools when invoked from the phone. | Tools → MCP servers / Skills / Tool registry |
| External session import | Mac only | Discover and import external agent sessions on the Mac. The phone can use supported routes shared through SuperQode, not control arbitrary private sessions in other apps. | Threads workspace → external sessions |
| Background notifications | Mac only | Updates and approvals refresh while the phone app is open. Work continues on the Mac when the app closes; background push notifications are not implemented. | Settings → Notifications |
| Super Agent / Pro | Mac preview | This is a Mac preview with neutral open-source hooks, not a finished autonomous release gate or shipped mobile feature. | Super Agent preview |
| Memory and context compaction | Mac only | Manage memory, context-window limits, summarization and manual compaction on the Mac. The phone uses the shared harness configuration. | Tools → Memory / Workspace → context preview |
| Trust, policy and sandboxes | Mac only | Configure project trust, tool permissions, sandbox policy and execution recovery on the Mac. Native phone tasks use Ask; they cannot override the policy. | Tools → Project trust / Policy / Sandboxes |
| Runtime diagnostics | Mac only | Inspect and repair runtime readiness using Mac diagnostics and doctor workflows. | Tools → Runtime diagnostics / Diagnostics |
| Plugins and A2A credentials | Mac only | Install plugins and configure A2A credentials on the Mac. Existing supported connections can be explicitly shared. | Tools → Plugins / A2A credentials |

## Next implementation priorities

1. Complete advanced execution management: WorkOrder creation/review, scoped Git/fork workflows, context compaction and execution recovery. Preserve project scope and explicit device permissions.
2. Complete the harness lifecycle: custom suites and candidate selection, Studio authoring/version history, routing/tuning, evidence export and separately authorized adoption/promotion. A displayed score never authorizes a release.
3. Add scoped Mac administration: local-engine/model lifecycle and installer/readiness feedback, supported subscription sign-in, MCP/skills configuration and external-session import. Provider credentials must not become readable through generic remote RPCs.
4. Add private interactive terminal/Git workflows only with their own reviewed authorization model. Do not expose the existing generic CLI/tool runner just to make every button callable.
5. Design background notifications within the no-hosted-SuperQode-service constraint. Foreground polling is implemented; it is not background push.

## Verification and release qualification

Native availability and data projections are exercised with simulator/UI tests and account-free desktop boundary tests. A physical Mac/iPhone still needs private HTTPS, cellular Tailscale access, camera pairing, restart/reconnect, sleep/wake and revocation validation. Signing/distribution require the owner's Apple account. The existing Mac navigation performance gate has produced inconsistent results and remains a release qualification issue.

No full-parity, universal external-app compatibility, finished Pro feature or bug-free public-release claim is justified by this inventory. Mac-only entries are instructions, not hidden phone implementations.

## Source evidence

- [Mac navigation](../macos/Sources/SuperQode/WorkspaceNavigation.swift) and [section names](../macos/Sources/SuperQode/SuperQodeApp.swift).
- [Typed Tools categories](../macos/Sources/SuperQode/ToolsView.swift). These are CLI-backed forms, not separate native phone implementations.
- [Mac evaluation comparison](../macos/Sources/SuperQode/EvaluationComparisonView.swift), [review](../macos/Sources/SuperQode/ReviewWorkspaceView.swift), [queue](../macos/Sources/SuperQode/TaskQueueView.swift), [WorkOrders](../macos/Sources/SuperQode/WorkOrderBoardView.swift) and [checkpoints](../macos/Sources/SuperQode/CheckpointsView.swift).
- [Explicit companion RPC surface](../../src/superqode/desktop_service/remote_rpc.py) and [bounded project projections](../../src/superqode/desktop_service/remote_project.py).
- [Source build and pairing](README.md), [signing and distribution](RELEASE.md).

Regenerate with `python apps/ios/scripts/audit-parity.py`; validate coverage and document freshness with `python apps/ios/scripts/audit-parity.py --check`.
