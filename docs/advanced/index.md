<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Advanced Features

Advanced features, architecture documentation, and systems in SuperQode for power users, developers, and custom workflows.

---

## Architecture & Internals

<div class="grid cards" markdown>

-   **Architecture Overview**

    ---

    High-level system architecture and how components work together.

    [:octicons-arrow-right-24: Architecture](architecture.md)

-   **Execution Pipeline**

    ---

    How QE sessions run from request to report generation.

    [:octicons-arrow-right-24: Execution Pipeline](execution-pipeline.md)

-   **Workspace Internals**

    ---

    Ephemeral workspace isolation, snapshots, and revert guarantees.

    [:octicons-arrow-right-24: Workspace Internals](workspace-internals.md)

-   **Safety & Permissions**

    ---

    Security model, permission rules, and dangerous operation handling.

    [:octicons-arrow-right-24: Safety & Permissions](safety-permissions.md)

-   **Evaluation Engine**

    ---

    Framework for testing QE capabilities with structured scenarios.

    [:octicons-arrow-right-24: Evaluation Engine](evaluation-engine.md)

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

-   **Guidance System**

    ---

    Verification-first system prompts that guide QE agents.

    [:octicons-arrow-right-24: Guidance System](guidance-system.md)

-   **Harness System**

    ---

    Fast validation for QE-generated patches before inclusion in QRs, including BYOH custom steps.

    [:octicons-arrow-right-24: Harness System](harness-system.md)

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

## System Architecture

These advanced features work together to provide a complete QE platform:

- **Memory & Learning**: Learns from feedback
- **Guidance System**: Guides agent behavior
- **Harness System**: Validates suggestions
- **Session Management**: Persists work
- **Tools System**: Provides capabilities

---

## Configuration

Most advanced features are configured in `superqode.yaml`:

```yaml
superqode:
  qe:
    # Guidance
    guidance:
      enabled: true
      ...

    # Harness
    harness:
      enabled: true
      ...

    # Memory (automatic)
    # ML (automatic)
    # Session (automatic)
```

---

## Next Steps

- [Configuration Reference](../configuration/yaml-reference.md) - Full config options
- [QE Features](../qe-features/index.md) - QE features overview
- [CLI Reference](../cli-reference/index.md) - Command reference
