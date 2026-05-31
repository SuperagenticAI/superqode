# SuperQode Product Goal

SuperQode is the portable harness layer for coding agents.

The goal is to let users define how an agent should work for their project, then run that same harness across models, tools, sandboxes, runtimes, protocols, and managed execution backends.

SuperQode should not feel like one fixed coding agent. It should feel like infrastructure for building, running, inspecting, and validating project-specific coding agents.

## Product Narrative

SuperQode should explain three paths clearly.

### 1. Use An Existing Harness

For users who want a coding agent immediately:

```bash
superqode --harness coding.yaml "fix this bug"
```

They should be able to start with a built-in or shared harness and run it without needing to understand every part of the system.

### 2. Define Your Own Harness

For teams and serious projects:

```bash
superqode harness init my-team-agent
```

Then configure:

- model policy
- tools
- permissions
- approvals
- skills
- validation
- runtime
- workflow
- output contract

The HarnessSpec is the center of the product. It should be safe to edit, easy to inspect, and clear enough that teams can review it like infrastructure configuration.

### 3. Plug Into Other Runtimes

For advanced users, the same harness should run through many execution backends:

- SuperQode built-in runtime
- OpenAI Agents
- PydanticAI
- Google ADK
- DeepAgents
- ACP agents
- MCP tools
- managed agent backends
- later A2A delegation

This makes the breadth intentional. SuperQode is not a scattered collection of integrations; it is one harness contract over many execution engines.

## Core Positioning

Most coding agents are fixed products. SuperQode is the harness layer.

Users should define the harness once, then decide where and how to run it:

```bash
superqode harness run --runtime builtin
superqode harness run --runtime pydanticai
superqode harness run --runtime openai-agents
superqode harness run --runtime managed
```

The execution engine can be local, open-source, framework-based, protocol-based, or managed by a lab. The project policy, workflow, validation, events, and evidence should remain under the SuperQode HarnessSpec.

## Product Mission

There are many coding agents.

SuperQode is the harness that belongs to your codebase.

Define the policy once. Run it anywhere. Inspect every step. Prove what happened.

SuperQode should adapt to the user's project, team, tools, models, permissions, and validation requirements. The user should not have to reshape their workflow around one fixed agent product.

## Minimal Core, Strong Contract

SuperQode should keep the core concept simple:

- a HarnessSpec
- a runtime backend
- a tool and protocol layer
- a session and event graph
- a TUI/CLI workbench
- a validation and evidence layer

Features should not become random product surface area. They should attach to the harness contract.

The default should be usable immediately, but the deeper value is that teams can make SuperQode their own without forking internals.

Advanced behavior should come from:

- HarnessSpec presets
- skills
- workflow steps
- runtime backends
- protocol integrations
- validation plugins
- TUI workbench panels

## What To Build Next

The next maturity push should be opinionated around the harness, not around one default agent.

### 1. HarnessSpec UX

The commands around HarnessSpec should be excellent:

- `init`
- `doctor`
- `inspect`
- `preview`
- `run`
- `events`
- `graph`
- `validate`

Users should feel safe editing YAML. Every harness should be explainable before it runs.

### 2. TUI As Harness Workbench

The TUI should not be only a chat screen. It should be a workbench for inspecting and controlling agent runs.

It should show:

- active harness
- runtime, provider, and model
- enabled tools
- permissions and approvals
- event timeline
- workflow steps
- files changed
- validation status
- session graph
- artifacts and run evidence

The TUI should make users confident that they understand what the agent is doing and what policy controls are active.

The TUI should also keep extension points visible:

- available skills
- available workflow presets
- active prompt/context resources
- active validation steps
- active runtime backend
- active protocol connections

### 3. Skills Maturity

Skills should become portable assets referenced by HarnessSpec:

```yaml
skills:
  - repo-triage
  - django-migration
  - api-contract-review
```

SuperQode skills should be project, repository, and release oriented. They should help teams encode repeatable engineering practices, not just prompt snippets.

### 4. Protocol Story

Protocols should have clear roles:

- MCP: tools and external capabilities
- ACP: editor/client integration and external coding agents
- A2A: later agent-to-agent delegation and workflows
- HarnessSpec: the policy and control contract over all of it

The protocols are implementation paths. The HarnessSpec is the product contract.

### 5. Validation And QE

Validation is the enterprise-grade wedge.

Every coding agent can write code. SuperQode should prove what happened, preserve artifacts, run validation, and emit CI-friendly evidence.

Important outputs:

- event graph
- approval history
- diffs
- changed files
- test runs
- validation results
- artifacts
- structured run summaries
- CI output

### 6. Durable Harness Sessions

Harness sessions should be durable enough to inspect, resume, branch, and explain.

The session should preserve:

- model and runtime changes
- active tool changes
- workflow step starts and finishes
- provider request starts and finishes
- tool call starts and finishes
- approvals
- compaction events
- validation results
- artifacts
- branch and fork relationships

Provider streams do not need to be magically resumable. Recovery should restart from clear durable boundaries, mark interrupted operations explicitly, and preserve enough state for the user to understand what happened.

### 7. Harness Hooks And Extension Safety

SuperQode should support hooks, but hooks must not corrupt an active run.

The product should separate:

- observers that only watch events
- handlers that can influence specific events
- structural operations that require the harness to be idle
- queue operations that are safe during a turn
- runtime configuration updates that affect future turns

This keeps customization powerful without making the harness unpredictable.

### 8. Observability Without Vendor Lock-In

SuperQode should emit stable structured lifecycle events that can be converted into logs, traces, metrics, dashboards, or CI artifacts.

The core should own the event contract, not depend on one observability vendor.

Useful event names include:

- `harness.run.start`
- `harness.workflow.step.start`
- `harness.workflow.step.end`
- `harness.provider.request.start`
- `harness.provider.request.end`
- `harness.tool.call.start`
- `harness.tool.call.end`
- `harness.validation.start`
- `harness.validation.end`
- `harness.approval.requested`
- `harness.approval.resolved`

## Marketing Page Structure

### Hero

Build portable coding agents for your codebase.

Define the harness once. Run it across models, tools, sandboxes, runtimes, and agent protocols.

Primary actions:

- Get started
- View HarnessSpec
- Run existing harness

### Section 1: Why SuperQode

Most coding agents are fixed products. SuperQode is the harness layer.

### Section 2: HarnessSpec

Show a small YAML example. This should be the star of the product.

```yaml
name: my-team-agent
workflow:
  preset: parallel-review
model_policy:
  primary: anthropic/claude-sonnet
execution_policy:
  allow_read: true
  allow_write: true
  approval_profile: balanced
skills:
  - repo-triage
  - api-contract-review
validation:
  enabled: true
```

### Section 3: Runtime Portability

Show that the same harness can run across local, framework, protocol, and managed runtimes.

### Section 4: Protocol Native

Explain:

- MCP for tools
- ACP for clients and external coding agents
- A2A for future collaboration
- HarnessSpec as the policy layer

### Section 5: TUI Workbench

Do not position the TUI as just chat. Position it as a place to inspect and control agent runs.

### Section 6: Validation

Show events, graph, approvals, diffs, test runs, artifacts, and CI output.

## Strong Product Line

SuperQode turns coding agents from apps into infrastructure.

## Architecture Direction

SuperQode should be layered explicitly:

1. HarnessSpec
   The portable contract for model, runtime, tools, skills, permissions, validation, events, and output.

2. Runtime Backends
   Built-in runtime, framework runtimes, protocol runtimes, managed runtimes, and future backends.

3. Protocol Layer
   MCP for tools, ACP for integration, and A2A for agent-to-agent workflows.

4. Workbench
   TUI and CLI for running, inspecting, approving, debugging, and validating harness runs.

5. Validation Layer
   QE, artifacts, test runs, event graph, and CI evidence.

## Related Product Notes

- [PyFlue And Flue Insights](PYFLUE_FLUE_INSIGHTS.md)
  How Flue and PyFlue validate the harness direction, and which ideas SuperQode should adopt for coding-agent workflows, durable runs, typed outputs, connector guides, and runtime portability.

## Product Principle

SuperQode should make breadth feel intentional.

Every feature should answer one of these questions:

- Does it make HarnessSpec easier to define?
- Does it make a harness safer to run?
- Does it make a run easier to inspect?
- Does it make runtime portability stronger?
- Does it create better validation evidence?

If the answer is no, the feature should wait.

## How SuperQode Wins

SuperQode should win by combining four things:

1. Ownership
   The harness belongs to the user's codebase and team.

2. Portability
   The same harness can run across local, framework, protocol, and managed runtimes.

3. Control
   Permissions, approvals, tools, skills, model policy, workflows, and validation are explicit.

4. Evidence
   Every important run can produce events, diffs, artifacts, validation results, and CI-friendly summaries.

The product should feel simple at first run and serious under inspection.
