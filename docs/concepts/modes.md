# Three Execution Modes

SuperQode supports three distinct execution modes for connecting to AI models and agents. Each mode has different capabilities and use cases.

---

## Overview

| Mode | Description | Capabilities | Best For |
|------|-------------|--------------|----------|
| **ACP** | Agent Client Protocol | File editing, shell, MCP | Advanced automation |
| **BYOK** | Bring Your Own Key | Chat, streaming, analysis | Cloud providers |
| **Local** | Local/Self-hosted | Chat + streaming (+ tool calling if supported) | Privacy, cost control |

```
┌─────────────────────────────────────────────────────────────┐
│                    EXECUTION MODES                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │     ACP     │  │    BYOK     │  │    LOCAL    │         │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤         │
│  │ Agent       │  │ Your API    │  │ Self-hosted │         │
│  │ Protocol    │  │ Keys        │  │ Models      │         │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤         │
│  │ OpenCode    │  │ LiteLLM     │  │ Ollama      │         │
│  │ Claude Code │  │ Gateway     │  │ vLLM        │         │
│  │ Aider       │  │             │  │ LM Studio   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## ACP Mode (Agent Client Protocol)

### What is ACP?

ACP mode connects to full-featured coding agents that can edit files, run shell commands, and use MCP tools. The agent manages its own LLM interactions.

### How It Works

1. SuperQode connects to an ACP-compatible agent
2. Agent spawns and handles LLM communication
3. Agent has full coding capabilities
4. SuperQode orchestrates and displays results

### Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion | ✓ |
| Streaming | ✓ |
| Tool calling | ✓ |
| File editing | ✓ |
| Shell execution | ✓ |
| MCP tools | ✓ |
| Extended thinking | ✓ |
| Multi-file changes | ✓ |

### Supported Agents

| Agent | Status | Capabilities |
|-------|--------|--------------|
| **OpenCode** | Supported | File editing, shell, MCP, 75+ providers |
| **Claude Code** | Coming Soon | Native Claude integration |
| **Aider** | Coming Soon | Git-integrated pair programming |
| **Cursor** | Planned | IDE integration |

### Usage

```bash
# Install OpenCode first
npm i -g opencode-ai

# Connect via TUI
:connect acp opencode

# Connect via CLI
superqode connect acp opencode
```

### Configuration

```yaml
# superqode.yaml
default:
  mode: acp
  coding_agent: opencode

agents:
  opencode:
    description: "OpenCode coding agent"
    protocol: acp
    command: opencode
    capabilities:
      - file_editing
      - shell_execution
      - mcp_tools
```

### Agent Capabilities

ACP agents can:

- **Edit Files**: Create, modify, and delete files
- **Run Commands**: Execute shell commands with streaming output
- **Use MCP Tools**: Access Model Context Protocol tools
- **Multi-file Operations**: Make coordinated changes across files
- **Extended Thinking**: Show reasoning process

---

## BYOK Mode (Bring Your Own Key)

### What is BYOK?

BYOK mode allows you to use cloud AI providers by providing your own API keys. SuperQode never stores your keys-they're read from environment variables.

### How It Works

1. You set API keys as environment variables
2. SuperQode connects via LiteLLM gateway
3. Direct API calls to the provider
4. Responses streamed back to you

### Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion | ✓ |
| Streaming | ✓ |
| Tool calling | ✓ (if model supports) |
| File editing | ✗ (no agent) |
| Shell execution | ✗ (no agent) |
| MCP tools | ✗ (no agent) |
| Extended thinking | ✓ (Claude) |
| Cost tracking | ✓ |

### Supported Providers

=== "US Labs (Tier 1)"

    | Provider | Models | Free Tier |
    |----------|--------|-----------|
    | Google AI | Gemini 3 Pro, Gemini 3, Gemini 2.5 Flash | Yes |
    | Anthropic | Claude Opus 4.5, Sonnet 4.5, Haiku 4.5 | No |
    | OpenAI | GPT-5.2, GPT-4o, o1 | No |
    | xAI | Grok 3, Grok 2 | No |
    | Mistral AI | Mistral Large, Codestral | No |
    | Groq | Llama 3.3, Mixtral | Yes |

=== "China Labs"

    | Provider | Models |
    |----------|--------|
    | Zhipu | GLM-4, GLM-4V |
    | Alibaba | Qwen-Max, Qwen-Plus |
    | Deepseek | Deepseek-V3, Deepseek-R1 |

=== "Model Hosts"

    | Provider | Models |
    |----------|--------|
    | OpenRouter | 95+ models |
    | Together AI | 200+ open models |
    | Fireworks AI | Optimized inference |
    | Replicate | Community models |

### Usage

```bash
# Set API key
export GOOGLE_API_KEY=your-api-key-here

# Connect via TUI
:connect byok google gemini-3-pro

# Connect via CLI
superqode connect byok google gemini-3-pro
```

### Configuration

```yaml
# superqode.yaml
default:
  mode: byok
  provider: google
  model: gemini-3-pro

providers:
  google:
    api_key_env: GOOGLE_API_KEY
    recommended_models:
      - gemini-3-pro
      - gemini-3
      - gemini-2.5-flash
```

## Local Mode

### What is Local Mode?

Local mode connects to self-hosted LLM servers running on your infrastructure. No API keys required-models run locally.

### How It Works

1. You run a local model server (Ollama, vLLM, etc.)
2. SuperQode connects to the local endpoint
3. All inference happens on your hardware
4. Complete privacy-no data leaves your machine

### Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion | ✓ |
| Streaming | ✓ |
| Tool calling | ✓ (if model supports) |
| File editing | ✗ (no agent) |
| Shell execution | ✗ (no agent) |
| MCP tools | ✗ (no agent) |
| Cost tracking | ✗ (free) |

### Supported Providers

| Provider | Default Port | Description |
|----------|--------------|-------------|
| **Ollama** | 11434 | Easy local deployment |
| **LM Studio** | 1234 | GUI-based local models |
| **vLLM** | 8000 | High-performance inference |
| **SGLang** | 30000 | Structured generation |
| **MLX-LM** | 8000 | Apple Silicon optimized |
| **TGI** | 80 | Text Generation Inference |
| **llama.cpp** | 8080 | C++ inference |

### Usage

```bash
# Start Ollama
ollama serve

# Pull a model
ollama pull qwen3:8b

# Connect via TUI
:connect local ollama qwen3:8b

# Connect via CLI
superqode connect local ollama qwen3:8b
```

### Configuration

```yaml
# superqode.yaml
default:
  mode: local
  provider: ollama
  model: qwen3:8b

providers:
  ollama:
    base_url: http://localhost:11434
    type: openai-compatible
    recommended_models:
      - qwen3:8b
      - llama3.2:latest
      - codellama:13b

  vllm:
    base_url: http://localhost:8000
    type: openai-compatible
```

### Recommended Local Models

For QE tasks, these models work well:

| Model | Size | Good For |
|-------|------|----------|
| qwen3:8b | 8B | General QE, fast |
| llama3.2:8b | 8B | General purpose |
| codellama:13b | 13B | Code analysis |
| deepseek-coder:6.7b | 6.7B | Code generation |
| mistral:7b | 7B | Fast inference |

---

## Mode Comparison

### Feature Matrix

| Feature | BYOK | ACP | Local |
|---------|------|-----|-------|
| Chat completion | ✓ | ✓ | ✓ |
| Streaming | ✓ | ✓ | ✓ |
| Tool calling | ✓* | ✓ | ✓* |
| File editing | ✗ | ✓ | ✗ |
| Shell execution | ✗ | ✓ | ✗ |
| MCP tools | ✗ | ✓ | ✗ |
| Extended thinking | ✓* | ✓ | ✓* |
| Cost tracking | ✓ | ✗ | ✗ |
| Privacy | ✗ | ✗ | ✓ |
| No API key needed | ✗ | ✓** | ✓ |

*Model-dependent
**Agent handles its own auth

### When to Use Each Mode

=== "Use ACP When"

    - You need full coding agent capabilities
    - File editing and shell execution are required
    - You want to use MCP tools
    - You need multi-file coordinated changes
    - You want the agent to handle its own LLM

=== "Use BYOK When"

    - You need cloud model capabilities
    - You want to use specific providers (Google Gemini, Anthropic, OpenAI)
    - You need extended thinking (Claude/Gemini)
    - Cost tracking is important
    - You don't need file editing in QE

=== "Use Local When"

    - Privacy is paramount
    - You want to avoid API costs
    - You have sufficient local compute
    - Internet connectivity is limited
    - You're running in an air-gapped environment

---

## Mixing Modes

You can configure different roles to use different modes:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          mode: acp  # Agent for comprehensive security testing
          coding_agent: opencode

        api_tester:
          mode: byok  # Cloud model for API analysis
          provider: google
          model: gemini-3-pro

        unit_tester:
          mode: local  # Local model for cost-effective testing
          provider: ollama
          model: qwen3:8b
```

---

## OpenResponses Gateway

For advanced local model usage, SuperQode supports the OpenResponses specification:

```yaml
superqode:
  gateway:
    type: openresponses
    openresponses:
      base_url: http://localhost:11434
      reasoning_effort: medium
      truncation: auto
      enable_apply_patch: true
      enable_code_interpreter: true
```

OpenResponses provides:

- Unified API across providers
- 45+ streaming event types
- Built-in tools (apply_patch, code_interpreter)
- Reasoning/thinking content support

---

## Next Steps

- [Ephemeral Workspace](workspace.md) - How code isolation works
- [QE Roles](roles.md) - Understanding testing roles
- [Providers](../providers/index.md) - Detailed provider documentation
