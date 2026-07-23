# Advanced Features

Advanced SuperQode features for users who want more control over tools, safety, sessions, harnesses, and the TUI.

---

## The Engine

<div class="grid cards" markdown>

-   **Inside the Agent Loop**

    ---

    The run lifecycle and every guard: steering, auto-continue, reminders, doom-loop detection, deferred tools, compaction, rubric self-grading.

    [:octicons-arrow-right-24: Inside the Agent Loop](agent-loop.md)

-   **Tools Catalog**

    ---

    Every builtin tool: three edit dialects, interactive shell sessions, vision, peer agents, and the guarantees behind all of them.

    [:octicons-arrow-right-24: Tools Catalog](tools-catalog.md)

-   **Policies & Safety**

    ---

    The order of authority: hooks, exec-policy rules, env filtering, permission escalation, sandboxing.

    [:octicons-arrow-right-24: Policies & Safety](policies.md)

-   **Multi-Agent Workflows**

    ---

    Sub-agents, long-lived peer agents with live steering, A2A, and rubric quality gates.

    [:octicons-arrow-right-24: Multi-Agent Workflows](multi-agent.md)

-   **Headless & CI**

    ---

    One-shot runs, JSON events, schema-validated output, rubric gates, session exports, worktree isolation.

    [:octicons-arrow-right-24: Headless & CI](headless-ci.md)

</div>

---

## User Controls

<div class="grid cards" markdown>

-   **Safety & Permissions**

    ---

    Security model, permission rules, and dangerous operation handling.

    [:octicons-arrow-right-24: Safety & Permissions](safety-permissions.md)

</div>

---

## Features

<div class="grid cards" markdown>

-   **Memory & Learning**

    ---

    Persistent learning system that remembers patterns and learns from feedback.

    [:octicons-arrow-right-24: Memory & Learning](memory.md)

-   **Tools System**

    ---

    Comprehensive tool system with 20+ tools for AI coding agents.

    [:octicons-arrow-right-24: Tools System](tools-system.md)

-   **Harness System**

    ---

    Reusable specs for runtime, model, tool, approval, event, and output policy.

    [:octicons-arrow-right-24: Harness System](harness-system.md)

-   **Optimization Story**

    ---

    Choose the right optimization layer: local model routing, harness specs, markdown skills, or custom staged optimizers.

    [:octicons-arrow-right-24: Optimization Story](optimization.md)

-   **Skill Optimization**

    ---

    Use GEPA to evolve markdown skills against SuperQode harness eval tasks, with staged output and bounded-edit checks.

    [:octicons-arrow-right-24: Skill Optimization](skill-optimization.md)

-   **HarnessBench**

    ---

    Produce verifiable same-model harness comparisons with repeated raw runs, variance, Pareto scorecards, and artifact checksums.

    [:octicons-arrow-right-24: HarnessBench](harnessbench.md)

-   **Contextual Policy and Credentials**

    ---

    Layer organization, project, harness, WorkOrder, and session rules while keeping host-bound secrets outside model context.

    [:octicons-arrow-right-24: Contextual Policy](contextual-policy.md)

-   **Harness Promotion**

    ---

    Move audited candidates through deterministic canaries, live held-out gates, activation, and verified rollback.

    [:octicons-arrow-right-24: Harness Promotion](harness-promotion.md)

-   **Omnigent Compatibility**

    ---

    Import Omnigent `agent.yaml` files into SuperQode harness specs while keeping SuperQode as the controlling harness.

    [:octicons-arrow-right-24: Omnigent Compatibility](omnigent-compat.md)

-   **Building a Code Factory**

    ---

    Understand how HarnessSpecs, sessions, WorkOrders, workers, evidence, delivery gates, evaluation, and optimization form one builder system.

    [:octicons-arrow-right-24: Code Factory guide](software-factory.md)

-   **SuperQode and Omnigent**

    ---

    Understand the ideas both products share, their different design priorities, SuperQode's remote-control options, and the Omnigent import path.

    [:octicons-arrow-right-24: SuperQode and Omnigent](superqode-vs-omnigent.md)

-   **Session Management**

    ---

    Persistent session storage, sharing, and coordination.

    [:octicons-arrow-right-24: Session Management](session-management.md)

-   **Terminal UI**

    ---

    Rich terminal interface with widgets and interactive features.

    [:octicons-arrow-right-24: TUI](tui.md)

</div>

---

## How These Features Work Together

These advanced features help you run controlled coding-agent sessions:

- **Memory & Learning**: Learns from feedback
- **Harness System**: Defines reusable runtime, model, tool, approval, and event policy
- **Session Management**: Persists work
- **Tools System**: Provides capabilities

---

## Configuration

Most advanced features are configured in `superqode.yaml`:

```yaml
superqode:
  permissions:
    default: ask
  session:
    storage: file
  memory:
    enabled: true
```

---

## Next Steps

- [Configuration Reference](../configuration/yaml-reference.md) - Full config options
- [CLI Reference](../cli-reference/index.md) - Command reference
