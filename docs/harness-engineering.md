# What Is Harness Engineering

A coding agent is a model running inside a **harness**: the software that
decides what the model sees, which tools it can call, how it remembers, how its
work is checked, and what it is allowed to do. The harness, not the model
alone, determines how the agent behaves.

Harness engineering treats that surrounding system as a versioned engineering
artifact that can be specified, measured, reviewed, and improved.

SuperQode is the open-source, terminal-first Agent Engineering framework for your code factory, with first-class support for local and open models. Harness Engineering is the technical discipline that makes each coding agent inspectable, portable, measurable, and improvable within that larger lifecycle. This page
defines the discipline and documents the SuperQode harness lifecycle.

---

## Relationship to prompts and context

Coding-agent behavior depends on three related engineering layers:

1. **Prompt engineering.** Write a better instruction.
2. **Context engineering.** Assemble the right context around the instruction.
3. **Harness engineering.** Design the whole system the model runs inside:
   tools, memory, search, approvals, sandbox, workflow, checks, and model
   routing.

Each layer includes the preceding layer. A well-designed prompt inside an
incomplete harness can still produce unreliable behavior because the harness
controls retries, tool calls, context limits, and verification.

---

## Local and open model considerations

Closed coding products commonly provide a fixed harness optimized for one model
family. Its configuration may not be inspectable, versionable, or portable to
other runtimes.

Open-weight model distributions commonly provide model weights without a
complete coding harness. A harness designed for a hosted frontier model can
misconfigure a local model by overusing context, assuming unsupported native
tool calls, or omitting edit verification.

SuperQode stores the harness as a repository-owned artifact and accounts for
the operational constraints of local and open models. See
[Local Agentic Coding](local-agentic-coding.md) for the model-by-model details.

---

## Repository-owned HarnessSpec

In SuperQode, a harness is a YAML artifact stored in the repository. It can be
reviewed, committed to version control, and executed across supported runtimes.

```yaml
# harness.yaml: the portable run contract
name: my-coder
flavor: coding
runtime:
  backend: builtin
model_policy:
  primary: ollama/qwen3-coder
  temperature: 0.1
  tool_call_format: prompt      # for models without a reliable native tool head
execution_policy:
  sandbox: docker
  approval_profile: balanced
  allow_write: true
  allow_shell: true
  allow_network: false
agents:
  - id: coder
    tools: [read_file, grep, glob, repo_search, edit_file, patch, bash]
```

Inspect the normalized harness configuration before execution:

```bash
superqode harness explain --spec harness.yaml
```

---

## Harness lifecycle

SuperQode supports five repeatable operations on a HarnessSpec.

### Build

Create a HarnessSpec with the interactive wizard or a model-family template.

```bash
superqode harness wizard
superqode harness init my-coder -t qwen-coding
superqode harness explain --spec harness.yaml
```

See [Bring Your Own Harness](getting-started/bring-your-own-harness.md) and the
[Harness System](advanced/harness-system.md) reference.

### Run

Execute the same HarnessSpec through builtin, OpenAI Agents, Google ADK, Codex
SDK, Claude Agent SDK, DeepAgents, or PydanticAI runtimes. MCP tools, ACP agents,
and A2A workflows can be connected without changing the repository-owned
contract.

```bash
superqode harness run --spec harness.yaml --runtime codex-sdk --prompt "review this repo"
```

See [Runtime Backends](runtimes.md) and
[Connection Methods and Vendors](concepts/modes.md).

### Evaluate

Run an evaluation task file to produce a scorecard. The scorecard can be used
as a regression gate so that a candidate fails when it breaks a task completed
by the baseline.

```bash
superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml --live --json > baseline.json
superqode local bench --agentic
```

See [Run, Measure, Optimize](advanced/harness-optimization.md) and the
[Benchmark Runner](advanced/benchmark-runner.md).

### Govern

Apply explicit tool permissions, sandbox policy, budgets, credential controls,
approval requirements, and delivery gates. Policy decisions are recorded with
the run evidence and can be inspected before approval or promotion.

```bash
superqode policy init
superqode policy show
superqode policy explain tool_call --tool bash
```

See [Contextual Policy](advanced/contextual-policy.md) and
[Safety and Permissions](advanced/safety-permissions.md).

### Optimize

Optimization starts from a versioned artifact, measures candidate changes,
checks them for regressions, and requires explicit human adoption. A live agent
does not modify its active HarnessSpec without this process.

```bash
superqode local optimize                 # best local/open model routing per role
superqode harness optimize --spec harness.yaml --tasks eval-tasks.yaml
superqode skills optimize review --engine gepa --harness harness.yaml --tasks eval-tasks.yaml --live
```

See the [Optimization Story](advanced/optimization.md) and
[Skill Optimization](advanced/skill-optimization.md).

---

## Integration with existing coding agents

SuperQode connects to hosted providers, Codex, Claude Code, and other agents
through [BYOK](providers/byok.md), [ACP](providers/acp.md), and runtime SDKs.
The HarnessSpec remains under repository ownership.

| | Closed coding agents | Open-source coding agents | SuperQode |
|---|---|---|---|
| Use any model | Mostly their own | Yes | Yes, Open Models first |
| Run local models | Fallback | Yes | Design center |
| The harness | Closed, vendor-owned | A fixed loop you configure | A versioned artifact you own |
| Measure the harness | No | No | Eval scorecards and regression gates |
| Optimize the harness | No | No | Staged candidates with human adoption |

### Harness deployment and ownership

The harness is a distinct layer of the agent stack and is also available as a
managed cloud service. In this model, users declare an agent in configuration
and a hosted platform assembles and executes the agent loop.

SuperQode stores the harness as a file in the repository and executes it on
infrastructure controlled by the user. The harness can be versioned and reviewed
with the rest of the codebase, and its behavior remains consistent across local
models, hosted providers, and remote runtimes. This approach is intended for
teams that require direct control over harness configuration and execution.

When an external coding agent is used, SuperQode retains the repository-owned
contract. For example, it can import an
[Omnigent](advanced/omnigent-compat.md) specification and convert it into a
portable `HarnessSpec`.

---

## Start here

1. Install SuperQode and generate a local harness for your machine:
   `superqode local init --repo .`. See [Installation](getting-started/installation.md).
2. Build and explain your first harness in
   [Bring Your Own Harness](getting-started/bring-your-own-harness.md).
3. Measure and improve it with the [Optimization Story](advanced/optimization.md).
4. Read the full field reference in the [Harness System](advanced/harness-system.md).
