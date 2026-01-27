<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Architecture Overview

This document provides a high-level overview of SuperQode's internal architecture, explaining how the various subsystems work together to deliver agentic quality engineering.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SUPERQODE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │   CLI / TUI     │    │   Web Server    │    │   LSP Server    │         │
│  │   Interface     │    │   (Dashboard)   │    │   (IDE)         │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
│           │                      │                      │                   │
│           └──────────────────────┴──────────────────────┘                   │
│                                  │                                          │
│                    ┌─────────────▼─────────────┐                           │
│                    │    Execution Pipeline     │                           │
│                    │  (Request -> QR Report)   │                           │
│                    └─────────────┬─────────────┘                           │
│                                  │                                          │
│    ┌─────────────────────────────┼─────────────────────────────┐           │
│    │                             │                             │           │
│    ▼                             ▼                             ▼           │
│  ┌─────────────┐    ┌─────────────────────┐    ┌─────────────────┐        │
│  │  Workspace  │    │    Agent Runtime    │    │   QR Generator  │        │
│  │  Manager    │    │  (Prompts + Tools)  │    │   (Reports)     │        │
│  └──────┬──────┘    └──────────┬──────────┘    └────────┬────────┘        │
│         │                      │                        │                  │
│         │           ┌──────────┴──────────┐             │                  │
│         │           │                     │             │                  │
│         ▼           ▼                     ▼             ▼                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │  Snapshot   │  │  Provider   │  │   Tools     │  │  Artifacts  │       │
│  │  & Revert   │  │  Gateway    │  │   System    │  │  Storage    │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
│                          │                                                  │
│         ┌────────────────┼────────────────┐                                │
│         │                │                │                                │
│         ▼                ▼                ▼                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                        │
│  │    BYOK     │  │    ACP      │  │   Local     │                        │
│  │  (LiteLLM)  │  │  (Agents)   │  │  (Ollama)   │                        │
│  └─────────────┘  └─────────────┘  └─────────────┘                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Safety & Permissions Layer                        │   │
│  │         (Sandbox, Approvals, Dangerous Op Detection)                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Subsystems

### 1. Execution Pipeline

The execution pipeline orchestrates the entire QE session lifecycle:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Runner** | `execution/runner.py` | Coordinates QE session execution |
| **Modes** | `execution/modes.py` | Quick vs Deep mode configuration |
| **Resolver** | `execution/resolver.py` | Resolves roles and execution targets |
| **NL Parser (Enterprise)** | Enterprise module | Parses natural language requests |
| **NL Executor (Enterprise)** | Enterprise module | Executes parsed commands |

**Data Flow:**

```
User Request
     │
     ▼
NL Parser (parse intent, extract targets)
     │
     ▼
Role Resolver (select appropriate QE roles)
     │
     ▼
Execution Runner (orchestrate session)
     │
     ├──► Workspace Manager (create sandbox)
     │
     ├──► Agent Runtime (execute with tools)
     │
     ├──► QR Generator (create reports)
     │
     └──► Artifact Storage (persist results)
```

[:octicons-arrow-right-24: Execution Pipeline Details](execution-pipeline.md)

---

### 2. Workspace Manager

The workspace manager provides ephemeral, isolated environments for testing:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Manager** | `workspace/manager.py` | Orchestrates workspace lifecycle |
| **Snapshot** | `workspace/snapshot.py` | File-based isolation |
| **Git Snapshot** | `workspace/git_snapshot.py` | Git stash-based isolation |
| **Worktree** | `workspace/worktree.py` | Git worktree isolation |
| **Git Guard** | `workspace/git_guard.py` | Prevents accidental commits |
| **Diff Tracker** | `workspace/diff_tracker.py` | Tracks all changes |
| **Artifacts** | `workspace/artifacts.py` | Manages QE artifacts |
| **Watcher** | `workspace/watcher.py` | File system monitoring |
| **Coordinator** | `workspace/coordinator.py` | Multi-agent coordination |

[:octicons-arrow-right-24: Workspace Internals](workspace-internals.md)

---

### 3. Agent Runtime

The agent runtime manages AI agent interactions:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Agent Loop** | `agent/loop.py` | Main agent execution loop |
| **System Prompts** | `agent/system_prompts.py` | Base system prompts |
| **QE Expert Prompts (Enterprise)** | Enterprise module | Role-specific prompts |
| **Edit Strategies** | `agent/edit_strategies.py` | Code modification strategies |
| **Tool Call** | `tool_call.py` | Tool invocation handling |
| **Agent Stream** | `agent_stream.py` | Streaming response handling |

---

### 4. Provider Gateway

The provider gateway abstracts different AI model sources:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Manager** | `providers/manager.py` | Provider lifecycle management |
| **Registry** | `providers/registry.py` | Provider registration |
| **Models** | `providers/models.py` | Model definitions |
| **Health** | `providers/health.py` | Provider health checks |
| **Usage** | `providers/usage.py` | Token/cost tracking |
| **LiteLLM Gateway** | `providers/gateway/litellm_gateway.py` | BYOK provider |
| **OpenResponses** | `providers/gateway/openresponses_gateway.py` | OpenResponses provider |

---

### 5. Tools System

The tools system provides capabilities to AI agents:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Base** | `tools/base.py` | Base tool classes |
| **File Tools** | `tools/file_tools.py` | File read/write operations |
| **Edit Tools** | `tools/edit_tools.py` | Code editing |
| **Shell Tools** | `tools/shell_tools.py` | Command execution |
| **Search Tools** | `tools/search_tools.py` | Code search |
| **Web Tools** | `tools/web_tools.py` | Web fetching |
| **LSP Tools** | `tools/lsp_tools.py` | Language server integration |
| **Permissions** | `tools/permissions.py` | Tool permission enforcement |
| **Validation** | `tools/validation.py` | Input/output validation |

[:octicons-arrow-right-24: Tools System](tools-system.md)

---

### 6. Safety & Permissions

The safety layer ensures secure operation:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Permission Rules** | `permissions/rules.py` | Permission rule engine |
| **Sandbox** | `safety/sandbox.py` | Sandbox enforcement |
| **Warnings** | `safety/warnings.py` | Safety warning system |
| **Danger Detection** | `danger.py` | Dangerous operation detection |
| **Approval** | `approval.py` | User approval workflow |

[:octicons-arrow-right-24: Safety & Permissions](safety-permissions.md)

---

### 7. QR Generator

The QR (Quality Report) generator creates research-grade reports:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Generator** | `qr/generator.py` | Report generation |
| **Templates** | `qr/templates.py` | Report templates |
| **Dashboard** | `qr/dashboard.py` | QR visualization |

---

### 8. SuperQE Orchestrator

The SuperQE orchestrator coordinates multi-role sessions:

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Orchestrator** | `superqe/orchestrator.py` | Multi-role coordination |
| **Session** | `superqe/session.py` | QE session management |
| **Roles** | `superqe/roles.py` | Role definitions |
| **Verifier** | `superqe/verifier.py` | Fix verification |
| **Noise Filter** | `superqe/noise.py` | False positive filtering |
| **Events** | `superqe/events.py` | JSONL event streaming |
| **Constitution** | `superqe/constitution/` | Behavior constraints |
| **Frameworks** | `superqe/frameworks/` | Test framework support |
| **Skills** | `superqe/skills/` | Reusable QE skills |

---

## Request Lifecycle

A complete QE session follows this lifecycle:

```
1. REQUEST
   User runs: superqe run . --mode quick -r security_tester

2. PARSE
   - CLI parses arguments
   - Resolves roles from registry
   - Determines execution mode

3. WORKSPACE SETUP
   - Creates ephemeral workspace (snapshot/worktree)
   - Initializes git guard
   - Starts diff tracking

4. AGENT EXECUTION
   - Loads role-specific prompts
   - Connects to provider (BYOK/ACP/Local)
   - Executes agent loop with tools
   - Handles tool calls (file, shell, search)

5. VERIFICATION
   - Verifies findings
   - Filters noise/false positives
   - Validates suggested fixes

6. REPORT GENERATION
   - Generates QR (Quality Report)
   - Creates patches for fixes
   - Generates test files

7. ARTIFACT STORAGE
   - Saves QR to .superqode/qe-artifacts/
   - Stores patches and tests
   - Records session metadata

8. CLEANUP
   - Reverts all workspace changes
   - Restores original code
   - Preserves artifacts only
```

---

## Configuration Flow

```
superqode.yaml (project)
        │
        ▼
~/.superqode.yaml (user)
        │
        ▼
Environment Variables
        │
        ▼
CLI Arguments (highest priority)
```

---

## Module Dependencies

```
CLI/TUI
   │
   ├──► commands/* (Click commands)
   │
   ├──► execution/* (Pipeline)
   │       │
   │       ├──► workspace/* (Isolation)
   │       │
   │       ├──► agent/* (Runtime)
   │       │       │
   │       │       └──► tools/* (Capabilities)
   │       │
   │       └──► superqe/* (Orchestration)
   │
   ├──► providers/* (Model access)
   │
   ├──► safety/* (Security)
   │
   └──► qr/* (Reporting)
```

---

## Extension Points

SuperQode can be extended at these points:

| Extension Point | Location | How to Extend |
|-----------------|----------|---------------|
| **Custom Roles** | `superqe/roles.py` | Add role definitions |
| **New Tools** | `tools/` | Implement base tool class |
| **Providers** | `providers/gateway/` | Add gateway implementation |
| **Frameworks** | `superqe/frameworks/` | Add test framework support |
| **Skills** | `superqe/skills/` | Add reusable QE skills |

---

## Related Documentation

- [Execution Pipeline](execution-pipeline.md) - Detailed execution flow
- [Workspace Internals](workspace-internals.md) - Isolation mechanisms
- [Safety & Permissions](safety-permissions.md) - Security model
- [Tools System](tools-system.md) - Tool development
- [Session Management](session-management.md) - Session persistence
