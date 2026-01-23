# Quick Start

Get started with SuperQode in 5 minutes.

---

## Install SuperQode

```bash
pip install superqode
```

---

## Overview

This guide covers:

1. **Project Setup** - Initialize and configure your project
2. **Choose Workflow** - TUI for exploration or CLI for automation
3. **Connect to Agent** - Set up your preferred connection mode
4. **Run First QE Session** - Start quality engineering

---

## Step 1: Initialize Your Project

Navigate to your project and initialize SuperQode:

```bash
cd /path/to/your/project
superqe init
```

This will:
- Create `superqode.yaml` in the current directory from the comprehensive role catalog
- Enable core, implemented roles so you can run immediately
- Leave the rest disabled so you can prune what you don’t need

### Edit Configuration

After initialization, edit `superqode.yaml` to set your preferred model:

```bash
nano superqode.yaml
```

Choose your connection mode:

```yaml
# Option 1: ACP (recommended for full features)
default:
  mode: acp
  coding_agent: opencode

# Option 2: BYOK (use your own API keys)
default:
  mode: byok
  provider: google
  model: gemini-3-pro

# Option 3: Local (privacy-first)
default:
  mode: local
  provider: ollama
  model: qwen3:8b
```

---

## Step 2: Choose Your Workflow

SuperQode offers two workflows:

### TUI (Terminal UI) - For Exploratory Testing

**Best for:** Interactive exploration, ad-hoc testing, learning

```bash
# Launch TUI
superqode
```

Then use TUI commands:
- `:connect acp opencode` - Connect to agent
- `:qe security_tester` - Switch to security role
- Chat with agent: "Check for SQL injection vulnerabilities"

### CLI (Command Line) - For Automation

**Best for:** CI/CD, batch processing, automation

```bash
# Run QE session directly
superqe run . --mode quick

# With specific roles
superqe run . -r security_tester -r api_tester
```

---

## Step 3: Connect to a Provider

Choose your preferred connection mode:

=== "ACP (Coding Agents)"

    Connect to ACP-compatible coding agents (recommended):

    ```bash
    # Option 1: Use TUI (recommended)
    superqode
    # Then in TUI:
    # Type :connect (or :c) for an interactive picker
    # The TUI will guide you through selecting ACP and available agents

    # Or connect directly:
    :connect acp opencode

    # Option 2: Use CLI (simple interactive mode)
    superqode connect acp opencode
    ```

=== "BYOK (Cloud Providers)"

    Connect to cloud AI providers using your API key:

    ```bash
    # Set API key (if not already in environment)
    export GOOGLE_API_KEY=your-api-key-here

    # In TUI: Type :connect (or :c) for an interactive picker
    # The TUI will guide you through selecting BYOK and providers/models

    # Or connect directly:
    :connect byok google gemini-3-pro
    ```

    Or from command line:

    ```bash
    superqode connect byok google gemini-3-pro
    ```

=== "Local Models"

    Connect to local/self-hosted models:

    ```bash
    # Start Ollama first
    ollama serve

    # In TUI: Type :connect (or :c) for an interactive picker
    # The TUI will guide you through selecting Local and available providers/models

    # Or connect directly:
    :connect local ollama qwen3:8b

    # From command line
    superqode connect local ollama qwen3:8b
    ```

---

## 3. Run Your First QE Session

### Quick Scan (60 seconds)

For fast feedback during development:

```bash
superqe run . --mode quick
```

**Note:** QE sessions are run via CLI commands, not TUI commands. In the TUI, you interact directly with agents by typing natural language requests after switching to a QE role with `:qe <role>`.

### Deep QE (Full Analysis)

For comprehensive quality analysis:

```bash
superqe run . --mode deep
```

---

## 4. View Results

After a QE session completes, you'll see:

### Console Output

```
╭─────────────────────────────────────────────────────╮
│                 QE Session Complete                  │
├─────────────────────────────────────────────────────┤
│ Duration: 45.2s                                      │
│ Roles Run: 3 (security_tester, api_tester, fullstack)│
│ Findings: 5 (1 critical, 2 high, 2 medium)          │
├─────────────────────────────────────────────────────┤
│ Artifacts Generated:                                 │
│   • QR: .superqode/qe-artifacts/qr/qr-2024-01-18-1a2b3c4d.json │
╰─────────────────────────────────────────────────────╯
```

### Artifacts Location

All artifacts are saved to `.superqode/qe-artifacts/`:

```
.superqode/qe-artifacts/
├── manifest.json
├── qr/
│   ├── qr-<date>-<session>.json    # Quality Report (JSON)
│   └── qr-<date>-<session>.md      # Quality Report (Markdown)
├── patches/
│   └── ...                         # Suggested patch files (when available)
└── generated-tests/
    └── ...                         # Generated tests (when available)
```

---

## 5. Essential Commands

### TUI Commands (prefix with `:`)

| Command | Description |
|---------|-------------|
| `:connect` or `:c` | Interactive connection picker (recommended) |
| `:connect acp <agent>` | Connect directly to ACP agent |
| `:connect byok <provider> <model>` | Connect directly to BYOK provider |
| `:connect local <provider> <model>` | Connect directly to local model |
| `:qe <role>` | Switch to QE role mode (e.g., `:qe security_tester`) |
| `:disconnect` | Disconnect current session |
| `:status` | Show session status |
| `:help` | Show help |
| `:quit` | Exit SuperQode |

### CLI Commands

| Command | Description |
|---------|-------------|
| `superqode` | Launch TUI |
| `superqe run .` | Run QE on current directory |
| `superqode connect byok` | Connect to BYOK provider |
| `superqode providers list` | List available providers |
| `superqode agents list` | List available agents |
| `superqe init` | Initialize configuration |

---

## 6. Quick Examples

### Example 1: Security Scan

```bash
# Run security-focused QE
superqe run . -r security_tester --mode quick
```

### Example 2: API Testing

```bash
# Test API endpoints
superqe run . -r api_tester -r unit_tester
```

### Example 3: Full QE with Suggestions (Enterprise)

```bash
# Deep QE with fix suggestions (sandbox mode)
superqe run . --mode deep --allow-suggestions --generate
```

### Example 4: CI-Friendly Output (Enterprise)

```bash
# JSONL output for CI/CD
superqe run . --mode quick --jsonl

# JUnit XML for test reporting
superqe run . --mode quick --junit results.xml
```

---

## 7. Understanding the Output

### Finding Severity Levels

| Severity | Description | Action |
|----------|-------------|--------|
| **Critical** | Security vulnerability, data loss risk | Fix immediately |
| **High** | Significant bug or security issue | Fix before release |
| **Medium** | Bug or code smell | Fix soon |
| **Low** | Minor issue or suggestion | Fix when convenient |

### Confidence Scores

Each finding includes a confidence score (0.0 - 1.0):

- **0.9 - 1.0**: Very high confidence, verified finding
- **0.7 - 0.9**: High confidence, likely valid
- **0.5 - 0.7**: Medium confidence, review recommended
- **< 0.5**: Low confidence, may be false positive

---

## 8. Keyboard Shortcuts (TUI)

| Shortcut | Action |
|----------|--------|
| `Ctrl+C` | Cancel current operation |
| `Ctrl+D` | Exit SuperQode |
| `Ctrl+K` | Open command palette |
| `Ctrl+L` | Clear screen |
| `Ctrl+R` | Refresh |
| `Tab` | Auto-complete |
| `↑/↓` | Navigate history |
| `Esc` | Cancel/close dialog |

---

## Next Steps

Now that you've completed the quick start:

1. **[Your First QE Session](first-session.md)** - Detailed walkthrough
2. **[Configuration Guide](configuration.md)** - Customize SuperQode
3. **[Understanding Modes](../concepts/modes.md)** - Learn about BYOK, ACP, Local
4. **[QE Roles](../concepts/roles.md)** - Understand testing roles
5. **[CI/CD Integration](../integration/cicd.md)** - Add to your pipeline

---

## Tips for Success

!!! tip "Start with Quick Scan"
    Use `--mode quick` during development for fast feedback. Save `--mode deep` for pre-release validation.

!!! tip "Focus on Critical Findings"
    Address critical and high severity findings first. Configure noise filters to reduce false positives.

!!! tip "Review Suggested Fixes"
    When using `--allow-suggestions`, always review the generated patches before applying.

!!! tip "Use CI Integration"
    Add SuperQode to your CI/CD pipeline with `--jsonl` output for automated quality gates.
