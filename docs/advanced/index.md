# Advanced Features

Advanced SuperQode features for users who want more control over tools, safety, sessions, harnesses, and the TUI.

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
- [Validation Features](../qe-features/index.md) - validation features overview
- [CLI Reference](../cli-reference/index.md) - Command reference
