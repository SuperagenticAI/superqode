# Installation

This guide covers all installation methods for SuperQode (TUI) and SuperQE (CLI), including prerequisites, verification, and troubleshooting.

**Safety note (OSS):** Run the open-source SuperQode/SuperQE in a safe, controlled environment (sandbox, VM, or low-risk machine). This reduces the blast radius for testing workflows and agent-driven actions.

---

## Quick Install

```bash
uv tool install superqode
```

Or using pip:

```bash
pip install superqode
```

That's it! Verify with:

```bash
superqode --version
superqe --version
```

---

## System Requirements

### Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| **Operating System** | macOS 12+, Linux (Ubuntu 20.04+, Debian 11+), Windows 10+ (WSL2) |
| **Python** | 3.12 or higher |
| **Memory** | 4GB RAM minimum, 8GB recommended |
| **Disk Space** | 500MB for installation |

### Python Version Check

```bash
python3 --version
# Should output: Python 3.12.x or higher
```

If you need to install Python 3.12+:

=== "macOS"

    ```bash
    brew install python@3.12
    ```

=== "Ubuntu/Debian"

    ```bash
    sudo apt update
    sudo apt install python3.12 python3.12-venv
    ```

=== "Windows (WSL2)"

    ```bash
    sudo apt update
    sudo apt install python3.12 python3.12-venv
    ```

---

## Installation Methods

### Method 1: uv (Primary Recommendation)

**Best for performance and security.** Use `uv` for the fastest installation and perfectly isolated tooling.

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install SuperQode
uv tool install superqode
```

### Method 2: pip (Primary Recommendation)

Standard installation via PyPI.

```bash
# Install SuperQode
pip install superqode

# Verify installation
superqode --version
```

---

## Alternate Installation Methods (No Python Required)

These methods provide a pre-compiled binary. They are convenient for users who do not want to manage a Python environment, but may have a slightly slower startup time (~1-2 seconds) compared to the primary methods.

### Method 3: Homebrew (macOS/Linux)

```bash
brew tap SuperagenticAI/superqode
brew install superqode
```

### Method 4: Installer Script

```bash
curl -fsSL https://super-agentic.ai/install.sh | bash
```

---

## Installation for Developers

For contributors or those wanting the latest features:

```bash
# Clone the repository
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode

# Install using uv (recommended for dev)
uv sync

# Or standard pip install
pip install -e ".[dev]"

# Verify installation
superqode --version
```

---

## Post-Installation Setup

### 1. Initialize Configuration

```bash
# In your project directory, create a repo config
cd /path/to/your/project
superqe init
```

This creates `superqode.yaml` in the current directory (project-level config).

### 2. Set Up API Keys (BYOK Mode)

For cloud providers, set your API keys as environment variables:

=== "Anthropic"

    ```bash
    export ANTHROPIC_API_KEY=sk-ant-...
    ```

=== "OpenAI"

    ```bash
    export OPENAI_API_KEY=sk-...
    ```

=== "Google AI"

    ```bash
    export GOOGLE_API_KEY=...
    # or
    export GEMINI_API_KEY=...
    ```

=== "All Providers"

    Add to your shell profile (`~/.bashrc`, `~/.zshrc`):

    ```bash
    # SuperQode API Keys
    export ANTHROPIC_API_KEY=sk-ant-...
    export OPENAI_API_KEY=sk-...
    export GOOGLE_API_KEY=...
    export DEEPSEEK_API_KEY=...
    export GROQ_API_KEY=...
    ```

### 3. Verify Provider Configuration

```bash
# Check authentication status
superqode auth info

# List available providers
superqode providers list

# Test a specific provider
superqode providers test anthropic
```

---

## Optional Dependencies

### For Local Models

=== "Ollama"

    ```bash
    # macOS
    brew install ollama

    # Linux
    curl -fsSL https://ollama.com/install.sh | sh

    # Start Ollama
    ollama serve

    # Pull a model
    ollama pull qwen3:8b
    ```

=== "LM Studio"

    Download from [lmstudio.ai](https://lmstudio.ai/) and install the desktop application.

=== "vLLM"

    ```bash
    pip install vllm
    ```

### For ACP Agents

=== "OpenCode"

    ```bash
    npm i -g opencode-ai

    # Verify installation
    opencode --version
    ```

### For Full QE Capabilities

Install language-specific linters for harness validation:

=== "Python"

    ```bash
    pip install ruff mypy pyright
    ```

=== "JavaScript/TypeScript"

    ```bash
    npm install -g eslint typescript
    ```

=== "Go"

    ```bash
    go install golang.org/x/lint/golint@latest
    go install honnef.co/go/tools/cmd/staticcheck@latest
    ```

=== "Rust"

    ```bash
    rustup component add clippy
    ```

---

## Verify Installation

### Basic Verification

```bash
# Check version
superqode --version

# View help
superqode --help

# Launch TUI
superqode
```

### Full Verification

```bash
# Check all dependencies
superqode auth info

# List providers
superqode providers list

# List agents
superqode agents list

# List QE roles
superqe roles
```

### Expected Output

```
$ superqode --version
SuperQode v0.1.4

$ superqode auth info
╭─────────────────────────────────────────────────╮
│              Authentication Status               │
├─────────────────────────────────────────────────┤
│ Provider      │ Status    │ Model Access        │
├───────────────┼───────────┼─────────────────────┤
│ anthropic     │ ✓ Valid   │ claude-sonnet-4     │
│ openai        │ ✓ Valid   │ gpt-4o              │
│ ollama        │ ✓ Running │ qwen3:8b            │
╰─────────────────────────────────────────────────╯
```

---

## Troubleshooting

### Common Issues

??? question "Python version too old"

    **Error:** `requires Python 3.12+`

    **Solution:** Install Python 3.12 or higher using your package manager or pyenv.

    ```bash
    # Using pyenv
    pyenv install 3.12.0
    pyenv global 3.12.0
    ```

??? question "Command not found after installation"

    **Error:** `superqode: command not found`

    **Solution:** Ensure your PATH includes the `~/.local/bin` directory used by uv/pip.

    ```bash
    export PATH="$HOME/.local/bin:$PATH"
    source ~/.bashrc  # or ~/.zshrc
    ```

??? question "Permission denied"

    **Error:** `Permission denied` during installation

    **Solution:** Use `--user` flag or install via uv:

    ```bash
    pip install --user superqode
    # or use uv
    uv tool install superqode
    ```

??? question "SSL certificate errors"

    **Error:** `SSL: CERTIFICATE_VERIFY_FAILED`

    **Solution (macOS):**

    ```bash
    /Applications/Python\ 3.12/Install\ Certificates.command
    ```

??? question "Ollama connection refused"

    **Error:** `Connection refused` when using local models

    **Solution:** Ensure Ollama is running:

    ```bash
    ollama serve
    ```

### Getting Help

If you encounter issues not covered here:

1. Check the [GitHub Issues](https://github.com/SuperagenticAI/superqode/issues)
3. Run with verbose logging: `superqode --verbose`

---

## Upgrading

### Upgrade SuperQode

=== "pip"

    ```bash
    pip install --upgrade superqode
    ```

=== "uv"

    ```bash
    uv tool upgrade superqode
    ```

### Check for Updates

```bash
# View current version
superqode --version

# Check PyPI for latest version
pip index versions superqode
```

---

## Uninstalling

=== "pip"

    ```bash
    pip uninstall superqode
    ```

=== "uv"

    ```bash
    uv tool uninstall superqode
    ```

### Remove Configuration

```bash
# Remove user configuration
rm -rf ~/.superqode.yaml
rm -rf ~/.superqode/

# Remove project configurations
rm -rf .superqode/
rm -f superqode.yaml
```

---

## Next Steps

- [Quick Start Guide](quickstart.md) - Get started in 5 minutes
- [Your First QE Session](first-session.md) - Complete walkthrough
- [Configuration](configuration.md) - Customize SuperQode
