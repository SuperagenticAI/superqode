# Comprehensive Framework Comparison Report

## Executive Summary

This report provides a detailed feature-by-feature comparison of SuperQode against four leading agent harness frameworks: **Pi** (TypeScript), **Deep Agents** (Python), **OpenCode** (TypeScript/Bun), and **Fast-Agent** (Python).

> **Updated May 2026**: SuperQode now has parity with most minimal harness features including:
> - 27+ built-in tools (file, edit, shell, search, web, MCP, skills)
> - Session persistence (JSONL) with /sessions, /resume commands
> - Auto-summarization + manual compaction (/compact)
> - Large output handling (save to file)
> - Plan mode (analyze without execution)
> - Skills system (loads from .agents/skills/)
> - ACP + MCP protocol support
> - Multiple BYOK providers (OpenAI, Anthropic, Google, DeepSeek, Azure, OpenRouter, Groq, Ollama)

---

## 1. Architecture Overview

### 1.1 Technology Stack

| Framework | Language | Package Manager | Core Framework | TUI Framework |
|-----------|----------|-----------------|---------------|---------------|
| **SuperQode** | Python 3.10+ | pip/uv | Custom async | Textual |
| **Pi** | TypeScript | npm/bun | Custom | Custom (differential rendering) |
| **Deep Agents** | Python 3.11+ | uv | LangGraph | Textual |
| **OpenCode** | TypeScript | bun | Effect framework | Custom |
| **Fast-Agent** | Python 3.13+ | uv | FastMCP + MCP SDK | prompt-toolkit |

### 1.2 Repository Structure

| Framework | Monorepo | Packages | Database |
|-----------|----------|----------|----------|
| **SuperQode** | ❌ Single | 1 | JSONL + JSON |
| **Pi** | ✅ 5 packages | ai, agent, coding-agent, tui, web-ui | JSONL |
| **Deep Agents** | ✅ 6+ packages | deepagents, cli, acp, evals, partners, repl | LangGraph |
| **OpenCode** | ✅ 22 packages | core, opencode, llm, ui, docs, etc. | SQLite (Drizzle) |
| **Fast-Agent** | ✅ 3 packages | fast-agent-mcp, fast-agent-acp, hf-inference-acp | Session manager |

> **Note**: SuperQode is a **minimal harness** (like Claude Code/Pi), not a framework (like PyFlue/Flue). It focuses on running agents directly via CLI/TUI rather than building agent applications. No LangChain/LangGraph dependencies.

---

## 2. LLM Provider Support

### 2.1 Provider Matrix

| Provider | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|----------|-----------|-----|-------------|----------|------------|
| **OpenAI** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Anthropic** | Limited | ✅ | ✅ | ✅ | ✅ |
| **Google Gemini** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Azure OpenAI** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **DeepSeek** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Mistral** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Groq** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Cerebras** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **xAI** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **OpenRouter** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Amazon Bedrock** | ❌ | ✅ | ✅ | ✅ | ✅ (optional) |
| **HuggingFace** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **Local (Ollama)** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **TensorZero** | ❌ | ❌ | ❌ | ❌ | ✅ (optional) |

### 2.2 Provider Features

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Unified API Layer** | ❌ | ✅ (pi-ai) | ✅ (LangChain) | ✅ (Vercel AI SDK) | ✅ |
| **API Key Detection** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **OAuth Support** | ❌ | ✅ | Via LangChain | ✅ | ✅ (KeyRing) |
| **Model Registry** | Config-based | ✅ Dynamic | ✅ Profiles | ✅ Dynamic | ✅ |
| **Custom Models** | ❌ | ✅ | ✅ | ✅ | ❌ |

---

## 3. Tool System

### 3.1 Built-in Tools

| Tool | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|------|-----------|-----|-------------|----------|------------|
| **Read** | ✅ | ✅ | ✅ (read_file) | ✅ | ✅ |
| **Write** | ✅ | ✅ | ✅ (write_file) | ✅ | ✅ |
| **Edit** | ✅ | ✅ | ✅ (edit_file) | ✅ | ✅ |
| **Bash/Shell** | ✅ | ✅ | ✅ (execute) | ✅ | ✅ |
| **Glob** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Grep** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Find** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Web Search** | ✅ (EXA + DuckDuckGo) | ❌ | ❌ | ✅ | ✅ |
| **Web Fetch** | ✅ (unified fetch) | ❌ | ❌ | ✅ | ❌ |
| **Code Search** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **LSP** | Basic | ❌ | ❌ | ✅ Full | ✅ |
| **Todo/Plan** | ✅ | ❌ | ✅ | ✅ | ✅ |
| **Repo Clone** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Repo Overview** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Compact** | ✅ | /compact | ❌ | /compact | ❌ |
| **MCP Tools** | ✅ (opt-in) | Via ext | Via langchain-mcp | ✅ Native | ✅ Native |
| **Skills Tools** | ✅ | ✅ | ✅ | ❌ | ✅ |

### 3.2 Tool Customization

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Custom Tools** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Tool Registry** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Tool Permissions** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **MCP Tools** | Basic | Via ext | Via langchain-mcp | ✅ Native | ✅ Native |

---

## 4. Agent System

### 4.1 Agent Types

| Type | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|------|-----------|-----|-------------|----------|------------|
| **Default Agent** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Read-only Agent** | ✅ (Plan mode) | ❌ | ❌ | ✅ (plan) | ❌ |
| **Sub-agents** | ✅ Via A2A | Via ext | ✅ | ✅ | ✅ |
| **Workflow Agent** | ✅ A2A workflows | ❌ | ❌ | ❌ | ✅ |
| **Chain Agent** | ✅ A2A sequential | ❌ | ❌ | ❌ | ✅ |
| **Parallel Agent** | ✅ A2A parallel | ❌ | ❌ | ❌ | ✅ |
| **Router Agent** | ✅ A2A supervisor | ❌ | ❌ | ❌ | ✅ |
| **Evaluator-Optimizer** | ❌ | ❌ | ❌ | ❌ | ✅ |

### 4.1.1 Multi-Agent Orchestration

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Sequential Workflow** | ✅ (A2A) | Via ext | Via LangGraph | Via MCP | Via MCP |
| **Parallel Execution** | ✅ (A2A) | Via ext | Via LangGraph | Via MCP | Via MCP |
| **Supervisor Pattern** | ✅ (A2A) | Via ext | Via LangGraph | Via MCP | Via MCP |
| **Fan-out/Fan-in** | ✅ (A2A) | Via ext | Via LangGraph | Via MCP | Via MCP |
| **Workflow Presets** | ✅ (QE, CI, Deploy) | Via ext | Via LangGraph | Via MCP | Via MCP |

### 4.2 Agent Switching

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Dynamic Switching** | Role-based | Via Ctrl+L | Via profiles | Tab key | /model command |
| **Agent Profiles** | Config | Settings | Profiles | Agent cards | Agent cards |
| **Scoped Models** | ❌ | ✅ | ❌ | ❌ | ❌ |

---

## 5. Session & Context Management

### 5.1 Storage

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Session Storage** | ✅ JSONL | JSONL | Checkpoint (LangGraph) | SQLite | Session manager |
| **Session Tree/Branching** | ❌ | ✅ | ✅ (LangGraph) | ❌ | ❌ |
| **Session Forking** | Handoff | /fork | Via LangGraph | ❌ | ❌ |
| **Session Cloning** | ❌ | /clone | Via LangGraph | ❌ | ❌ |
| **Session Commands** | /sessions, /resume | Via UI | Via LangGraph | Via UI | Via command |

### 5.2 Context Management

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Auto Summarization** | ✅ (configurable) | ✅ | ✅ | ✅ | ❌ |
| **Manual Compaction** | ✅ /compact | /compact | ❌ | /compact | ❌ |
| **Context Overflow Handling** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Large Output Handling** | ✅ Save to file | Save to file | Save to file | Save to file | ❌ |
| **Plan Mode** | ✅ (analyze only) | Via read-only | Via config | Via plan mode | ❌ |

---

## 6. Extension & Customization

### 6.1 Extension Systems

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Extension System** | ❌ | ✅ TypeScript | ✅ Middleware | ✅ MCP | ✅ MCP |
| **Custom Commands** | ❌ | ✅ | Via middleware | Slash commands | Slash commands |
| **Custom UI** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Custom Keybindings** | ❌ | ✅ | ❌ | ❌ | ❌ |

### 6.2 Skills & Templates

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Skills System** | ✅ (from .agents/skills/) | ✅ | ✅ (SkillsMiddleware) | ❌ | ✅ |
| **Prompt Templates** | Basic config | ✅ Markdown | ✅ | ✅ System prompts | ✅ |
| **Themes** | Fixed | ✅ Hot-reload | Fixed | Fixed | Fixed |

---

## 7. Protocol Support

### 7.1 Communication Protocols

| Protocol | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|----------|-----------|-----|-------------|----------|------------|
| **ACP (Agent-Client Protocol)** | ✅ Server | ✅ | ✅ (libs/acp) | ✅ | ✅ |
| **MCP (Model Context Protocol)** | Basic adapter | Via ext | Via langchain-mcp | ✅ Native | ✅ Native |
| **A2A (Agent-to-Agent)** | ✅ Client + Server | Via ext | Via LangGraph | Via MCP | Via MCP |
| **RPC Mode** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **HTTP Server** | ✅ (FastAPI) | ❌ | ❌ | ✅ | ✅ (FastMCP) |

### 7.2 Remote Execution

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Remote Sandboxing** | ACP-based | RPC mode | LangSmith + local | ACP | MCP + ACP |
| **Client/Server Architecture** | ❌ | ❌ | ❌ | ✅ | ❌ |

---

## 8. Authentication & Security

### 8.1 Auth Methods

| Method | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|--------|-----------|-----|-------------|----------|------------|
| **API Key** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **OAuth** | ❌ | ✅ | Via LangChain | ✅ | ✅ |
| **Environment Variables** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **KeyRing Storage** | ❌ | ❌ | ❌ | ❌ | ✅ |

### 8.2 Security Features

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Permission System** | ✅ Approval | Via ext | ✅ FilesystemMiddleware | ✅ Permission eval | ✅ Tool permissions |
| **Dangerous Cmd Detection** | ✅ | Via ext | ❌ | ❌ | ❌ |
| **Approval Workflow** | ✅ | Via ext | Human-in-loop | ❌ | ❌ |

---

## 9. CLI & Interface

### 9.1 Interface Options

| Interface | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|-----------|-----------|-----|-------------|----------|------------|
| **Interactive TUI** | ✅ Textual | ✅ Custom | ✅ Textual | ✅ Custom | ✅ prompt-toolkit |
| **Headless/CLI** | ✅ | ✅ (print mode) | ✅ | ✅ | ✅ |
| **JSON Mode** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Desktop App** | ❌ | ❌ | ❌ | ✅ (cross-platform) | ❌ |

### 9.2 Commands & Shortcuts

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Slash Commands** | ❌ | ✅ | ❌ | ✅ | ✅ |
| **Keyboard Shortcuts** | Limited | ✅ | ✅ | ✅ | Limited |
| **Tab Completion** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **File Reference (@)** | ❌ | ✅ | ❌ | ✅ | ❌ |

---

## 10. Advanced Features

### 10.1 Special Capabilities

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Image Input** | Limited | ✅ | Via LangChain | ✅ | ❌ |
| **Image Generation** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Thinking/Reasoning** | ❌ | ✅ | Via model | ✅ | Via model |
| **Cross-Provider Handoff** | ❌ | ✅ | Via LangChain | ❌ | ❌ |
| **Token/Cost Tracking** | Basic | ✅ | Via LangSmith | ✅ | Via telemetry |

### 10.2 Observability

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Logging** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Tracing** | ❌ | ❌ | Via LangSmith | ✅ | ✅ OpenTelemetry |
| **Session Sharing** | ❌ | /share | ❌ | ✅ | ✅ (export) |
| **Trace Export** | ❌ | ❌ | ❌ | ❌ | ✅ (HF, Codex) |

---

## 11. Enterprise Features

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Cloud/Enterprise** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Identity Management** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Team Features** | Role system | ❌ | ❌ | ✅ | ❌ |
| **Self-hosted** | ✅ | ✅ | ✅ | ❌ | ❌ |

---

## 12. Package Distribution

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **npm Packages** | N/A | ✅ Pi packages | N/A | N/A | N/A |
| **pip Packages** | ✅ | N/A | ✅ | N/A | ✅ |
| **Extension Registry** | ❌ | ✅ | ❌ | ❌ | MCP servers |
| **Skills Marketplace** | ❌ | ❌ | ❌ | ❌ | Skills registry |

---

## 13. Gap Analysis: SuperQode

### 13.1 Critical Gaps (Must Have)

| Gap | Priority | Effort | Competitor Reference |
|-----|----------|--------|----------------------|
| Unified LLM API layer | Critical | High | Pi, OpenCode |
| Full MCP support | Critical | High | Fast-Agent, OpenCode |
| Skills system | Critical | Medium | Pi, Fast-Agent |
| Session branching/tree | Critical | Medium | Pi |
| Context compaction | Critical | Medium | Pi, OpenCode |

### 13.2 Important Gaps (Should Have)

| Gap | Priority | Effort | Competitor Reference |
|-----|----------|--------|----------------------|
| Multiple agent types | High | Medium | Fast-Agent |
| Slash commands | High | Low | Fast-Agent, OpenCode |
| Sub-agent support | High | Medium | All |
| Extension system | High | High | Pi, Deep Agents |
| Interactive shell mode | Medium | Low | Fast-Agent |

### 13.3 Nice to Have

| Gap | Priority | Effort | Competitor Reference |
|-----|----------|--------|----------------------|
| Desktop app | Low | Very High | OpenCode |
| Enterprise features | Low | Very High | OpenCode |
| OAuth/KeyRing auth | Medium | Medium | Fast-Agent |
| Trace export | Low | Medium | Fast-Agent |
| OpenTelemetry | Low | Medium | Fast-Agent |

---

## 14. Recommendations

### 14.1 Short-term (1-3 months)

1. **Add MCP support** - Implement full MCP integration like Fast-Agent
2. **Add slash commands** - Build command system for model switching, skills
3. **Improve shell mode** - Add interactive shell with `!` prefix support

### 14.2 Medium-term (3-6 months)

1. **Unified LLM API** - Implement multi-provider layer (similar to pi-ai or Vercel AI SDK)
2. **Skills system** - Add Agent Skills support
3. **Session improvements** - Add JSONL storage with tree structure
4. **Context compaction** - Implement automatic summarization

### 14.3 Long-term (6-12 months)

1. **Extension system** - Build extensible plugin architecture
2. **Multiple agent types** - Add workflow agents (chain, parallel, router)
3. **Database storage** - Migrate from JSON to SQLite
4. **Desktop app** - Consider cross-platform desktop application

---

## 15. Conclusion

SuperQode currently lags significantly behind all four reference frameworks in terms of features and capabilities. The most critical gaps are:

1. **Provider support** - Limited to basic OpenCode/ LiteLLM integration
2. **Protocol support** - Lacks full MCP integration
3. **Extension/customization** - No extension or skills system
4. **Session management** - No branching, compaction, or advanced storage

The closest competitors in architecture are **Deep Agents** (both Python-based) and **Fast-Agent** (Python-based with MCP focus). SuperQode could potentially match Deep Agents more easily due to shared language, while Fast-Agent provides the best model for MCP-first development.

To achieve feature parity, a significant refactoring and feature development effort would be required, with an estimated timeline of 6-12 months for core features and 12-18 months for full parity.

---

## Appendix: Quick Reference Matrix

| Feature | SuperQode | Pi | Deep Agents | OpenCode | Fast-Agent |
|---------|-----------|-----|-------------|----------|------------|
| **Language** | Python | TypeScript | Python | TypeScript | Python |
| **LLM Providers** | Limited | 30+ | LangChain | 20+ Vercel | Multiple |
| **TUI Framework** | Textual | Custom | Textual | Custom | prompt-toolkit |
| **Protocol** | ACP | ACP/RPC | ACP | ACP | MCP + ACP |
| **Extension System** | ❌ | Extensions | Middleware | MCP | MCP |
| **Skills** | ❌ | ✅ | ✅ | ❌ | ✅ |
| **Sub-agents** | Limited | Via ext | ✅ | ✅ | ✅ |
| **Workflows** | Plan | ❌ | LangGraph | ❌ | Chain/Parallel |
| **Session Storage** | JSON | JSONL | Checkpoint | SQLite | Session manager |
| **Context Compaction** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Desktop App** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Enterprise** | ❌ | ❌ | ❌ | ✅ | ❌ |