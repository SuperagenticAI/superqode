# Installation

This guide covers SuperQode installation, including prerequisites, verification, optional runtime extras, and troubleshooting.

**Safety note (OSS):** Run the open-source SuperQode in a safe, controlled environment (sandbox, VM, or low-risk machine). This reduces the blast radius for testing workflows and agent-driven actions.

---

## Quick Install

```bash
uv tool install superqode
```

Or run once without installing:

```bash
uvx superqode
```

That's it. If you installed the tool, verify with:

```bash
superqode --version
```

---

## System Requirements

!!! warning "Local Model Hardware"
    The SuperQode CLI is lightweight, but local model serving is not. Running Ollama, LM Studio, MLX, vLLM, SGLang, DS4, or llama.cpp can use significant CPU, GPU, memory, battery, and cooling capacity. Use local models only on hardware that can safely support the selected model and context size.

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

### Method 2: uvx (No Persistent Install)

Run SuperQode directly through uv when you want a temporary command.

```bash
uvx superqode --version
```

## Installation for Developers

For contributors or those wanting the latest features:

```bash
# Clone the repository
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode

# Install using uv (recommended for dev)
uv sync --extra dev --extra docs

# Verify installation
uv run superqode --version
```

### Environment-Aware Extras

Optional extras must be installed into the same Python environment that is running
SuperQode. The TUI shows that environment before offering any one-click install,
then prints the exact command it will run and waits for your confirmation.

Use the command that matches how you launched SuperQode:

| Running from | Command shape |
| --- | --- |
| `uv tool install superqode` | `uv tool install "superqode[<extra>]"` |
| SuperQode source checkout | `uv pip install -e ".[<extra>]"` |
| Another project venv | `uv add "superqode[<extra>]"` |
| Plain virtualenv | `uv pip install "superqode[<extra>]"` |

For direct package installs such as MLX, SuperQode targets the running interpreter
explicitly:

```bash
uv pip install --python /path/to/superqode/python "mlx-lm>=0.31.0,<0.32.0"
```

---

## Post-Installation Setup

### 1. Initialize Configuration

```bash
# In your project directory, create a repo config
cd /path/to/your/project
superqode config init
```

This creates `superqode.yaml` in the current directory with local-first defaults for Ollama and `qwen3:8b`.

### 2. Set Up Local Models

For the local-first path, start Ollama and pull a starter model:

```bash
ollama pull qwen3:8b
```

Then run `superqode`, use `:local init`, `:connect local`, and select `superqode.local.yaml` with `:harness superqode.local.yaml`.

### 3. Set Up API Keys (BYOK Mode)

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
    uv pip install vllm
    ```

### For ACP Agents

=== "OpenCode"

    ```bash
    npm i -g opencode-ai

    # Verify installation
    opencode --version
    ```

### Linting and Type Checking

Install language-specific linters for code analysis in harness runs:

=== "Python"

    ```bash
    uv pip install ruff mypy pyright
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

```

### Expected Output

```bash
$ superqode --version
SuperQode v0.1.4

$ superqode auth info
╭─────────────────────────────────────────────────╮
│              Authentication Status               │
├─────────────────────────────────────────────────┤
│ Provider      │ Status    │ Model Access        │
├───────────────┼───────────┼─────────────────────┤
│ anthropic     │ ✓ Valid   │ <anthropic-model>     │
│ openai        │ ✓ Valid   │ <openai-model>             │
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
    uv tool install superqode
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
    uv tool upgrade superqode
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
- [Your First Session](first-session.md) - Complete walkthrough
- [Configuration](configuration.md) - Customize SuperQode
