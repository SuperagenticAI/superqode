<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# SuperQE Advanced Commands

Advanced Quality Engineering with CodeOptiX integration - AI-powered evaluation capabilities.

---

## Overview

The `superqe advanced` command group provides advanced quality engineering features powered by CodeOptiX:

```bash
superqe advanced COMMAND [OPTIONS] [ARGS]
```

**Requirements:** Any supported LLM provider (Ollama, OpenAI, Anthropic, Google) with proper authentication.

---

## run

Run SuperQE enhanced evaluation with CodeOptiX.

```bash
superqe advanced run [PATH] [OPTIONS]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `PATH` | Directory to analyze | `.` (current directory) |

### Options

| Option | Description |
|--------|-------------|
| `--behaviors` | Comma-separated behaviors: `security-vulnerabilities,test-quality,plan-adherence` |
| `--use-bloom` | Use Bloom scenario generation for intelligent testing |
| `--agent` | Specific agent to evaluate (claude-code, codex, gemini-cli) |
| `--output`, `-o` | Output directory for enhanced results |
| `--json` | Output enhanced results as JSON |
| `--verbose`, `-v` | Show detailed SuperQE analysis logs |

### Prerequisites

SuperQE requires an LLM provider to be configured. You can use any supported provider:

#### Option 1: Ollama (Local, Free)
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama
ollama serve

# Pull a model (in another terminal)
ollama pull llama3.1
```

#### Option 2: OpenAI (Cloud)
```bash
# Set API key
export OPENAI_API_KEY="your-api-key-here"
```

#### Option 3: Anthropic (Cloud)
```bash
# Set API key
export ANTHROPIC_API_KEY="your-api-key-here"
```

#### Option 4: Google (Cloud)
```bash
# Set API key
export GOOGLE_API_KEY="your-api-key-here"
```

### Examples

```bash
# Basic SuperQE evaluation
superqe advanced run .

# Security-focused evaluation
superqe advanced run . --behaviors security-vulnerabilities

# Multiple behaviors with Bloom scenarios
superqe advanced run . --behaviors security-vulnerabilities,test-quality --use-bloom

# Focus on specific agent
superqe advanced run . --agent claude-code --behaviors all

# Export results
superqe advanced run . --output ./superqe-results --json
```

### What SuperQE Provides

SuperQE enhances basic QE with:

- **🔬 Deep Behavioral Evaluation**: Beyond basic checks, analyzes code patterns and security vulnerabilities
- **🧬 GEPA Evolution Engine**: Agent optimization for better testing strategies
- **🌸 Bloom Scenario Generation**: Intelligent test case creation based on code analysis
- **🛡️ Advanced Security Analysis**: Comprehensive vulnerability detection

### Output

SuperQE generates enhanced results including:

- Detailed behavioral analysis
- Security vulnerability reports
- Test quality assessments
- Plan adherence verification
- Scenario-based testing results

---

## behaviors

List all available SuperQE enhanced behaviors.

```bash
superqe advanced behaviors
```

### Output

Shows CodeOptiX-powered behaviors:

```
Enhanced Behaviors (CodeOptiX-powered):
  🔬 security-vulnerabilities: Detects hardcoded secrets, SQL injection, XSS vulnerabilities
  🔬 test-quality: Evaluates test completeness, assertion quality, and coverage
  🔬 plan-adherence: Checks if implementation matches requirements and plans
```

### Prerequisites

Requires CodeOptiX to be available (automatically installed with SuperQode).

---

## agent-eval

Compare multiple AI agents using SuperQE evaluation.

```bash
superqe advanced agent-eval [PATH] [OPTIONS]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `PATH` | Directory to analyze | `.` (current directory) |

### Options

| Option | Description |
|--------|-------------|
| `--agents` | Comma-separated list: `claude-code,codex,gemini-cli` (required) |
| `--behaviors` | Behaviors to evaluate (default: security-vulnerabilities,test-quality) |
| `--output`, `-o` | Output directory for comparison results |

### Examples

```bash
# Compare Claude Code and Codex
superqe advanced agent-eval . --agents claude-code,codex

# Compare all agents with comprehensive evaluation
superqe advanced agent-eval . --agents claude-code,codex,gemini-cli --behaviors all

# Save comparison results
superqe advanced agent-eval . --agents claude-code,gemini-cli --output ./comparisons
```

### Output

Generates agent comparison reports showing:

- Performance metrics across behaviors
- Strengths and weaknesses of each agent
- Recommendations for agent selection
- Detailed analysis of evaluation results

---

## scenarios

Manage Bloom scenario generation for SuperQE.

```bash
superqe advanced scenarios ACTION [PATH] [OPTIONS]
```

### Actions

| Action | Description |
|--------|-------------|
| `generate` | Generate scenarios for a behavior |
| `list` | List available scenarios |

### Options

| Option | Description |
|--------|-------------|
| `--behavior` | Behavior to generate scenarios for |
| `--count` | Number of scenarios to generate (default: 5) |
| `--output`, `-o` | Output file for scenarios |

### Examples

```bash
# Generate security scenarios
superqe advanced scenarios generate . --behavior security-vulnerabilities --count 10

# Generate test quality scenarios
superqe advanced scenarios generate . --behavior test-quality --output scenarios.json

# List available scenarios
superqe advanced scenarios list
```

### What are Bloom Scenarios?

Bloom scenarios are intelligently generated test cases that:

- Analyze code patterns and potential vulnerabilities
- Create targeted test scenarios based on code structure
- Provide comprehensive coverage beyond basic testing
- Adapt to code changes and new patterns

---

## Setup and Requirements

### LLM Provider Configuration

SuperQE requires an LLM provider to be configured. Choose any supported provider:

#### Ollama (Recommended for Local Usage)
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama (background)
ollama serve &

# Pull required models
ollama pull llama3.1
ollama pull llama3.2:3b  # Optional: lighter model
```

#### Cloud Providers (OpenAI, Anthropic, Google)
SuperQE works with all major cloud LLM providers. Configure your API keys:

```bash
# OpenAI
export OPENAI_API_KEY="your-openai-key"

# Anthropic
export ANTHROPIC_API_KEY="your-anthropic-key"

# Google
export GOOGLE_API_KEY="your-google-key"
```

### CodeOptiX Integration

CodeOptiX is automatically included with SuperQode:

```bash
# CodeOptiX is installed as part of SuperQode
pip install superqode  # Includes CodeOptiX integration
```

### Verification

```bash
# Check if SuperQE is ready
superqe advanced behaviors

# Test basic functionality
superqe advanced run . --behaviors security-vulnerabilities
```

---

## SuperQE vs Basic QE

| Feature | Basic QE | SuperQE |
|---------|----------|---------|
| **Engine** | Multi-agent orchestration | CodeOptiX + Multi-agent |
| **Analysis** | Pattern-based detection | Deep behavioral analysis |
| **Security** | Basic vulnerability checks | Advanced threat detection |
| **Testing** | Deterministic test execution | AI-powered scenario generation |
| **Requirements** | Any LLM provider | Ollama required |
| **Performance** | Fast (seconds to minutes) | Comprehensive (minutes) |

### When to Use Basic QE

- **Pre-commit checks**: Fast feedback during development
- **CI/CD pipelines**: Quick validation gates
- **Resource constraints**: Limited compute or time
- **Simple projects**: Basic quality assurance needs

### When to Use SuperQE

- **Security-critical code**: Deep vulnerability analysis
- **Complex applications**: Comprehensive behavioral testing
- **Pre-release validation**: Thorough quality assessment
- **Research-grade reports**: Detailed forensic analysis

---

## Common Workflows

### Security-First Development

```bash
# SuperQE security evaluation during development
superqe advanced run . --behaviors security-vulnerabilities --verbose

# Follow up with basic QE for broader testing
superqe run . --mode deep -r security_tester,api_tester
```

### Comprehensive Pre-Release

```bash
# SuperQE comprehensive evaluation
superqe advanced run . --behaviors all --use-bloom

# Generate detailed reports
superqe advanced run . --output ./release-report --json
```

### Agent Selection

```bash
# Compare agents for your use case
superqe advanced agent-eval . --agents claude-code,gemini-cli --behaviors security-vulnerabilities

# Choose best agent for your workflow
```

---

## Troubleshooting

### Ollama Connection Issues

```bash
# Check if Ollama is running
ps aux | grep ollama

# Start Ollama if not running
ollama serve

# Test connection
curl http://localhost:11434/api/tags
```

### Model Availability

```bash
# List available models
ollama list

# Pull required model
ollama pull llama3.1

# Check model status
ollama show llama3.1
```

### Performance Issues

```bash
# Use lighter model for faster evaluation
superqe advanced run . --agent llama3.2:3b

# Reduce scope for quicker results
superqe advanced run ./specific-directory --behaviors security-vulnerabilities
```

---

## Next Steps

- [QE Commands](qe-commands.md) - Basic quality engineering
- [Installation](../getting-started/installation.md) - Get started with SuperQode
- [Ollama Setup](https://ollama.ai) - Install Ollama for SuperQE
- [CodeOptiX Documentation](https://github.com/your-org/codeoptix) - Learn about CodeOptiX
