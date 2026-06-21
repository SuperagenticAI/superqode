# What Is Harness Engineering

A coding agent is not just a model. It is a model running inside a **harness**: the
software that decides what the model sees, which tools it can call, how it
remembers, how its work is checked, and what it is allowed to do. The model
supplies the reasoning. The harness supplies everything else.

Harness engineering is the practice of treating that surrounding system as a
real engineering artifact: something you design, write down, measure, and
improve, instead of a hidden default you inherit from a product.

SuperQode is a harness engineering framework for coding agents, optimized for local and open models. This page
explains the idea, why it matters now, and the four moves SuperQode gives you on
a harness you own.

---

## The third layer

The way teams get value out of models has moved through three layers:

1. **Prompt engineering.** Write a better instruction.
2. **Context engineering.** Assemble the right context around the instruction.
3. **Harness engineering.** Design the whole system the model runs inside:
   tools, memory, search, approvals, sandbox, workflow, checks, and model
   routing.

Each layer wraps the one before it. A great prompt inside a weak harness still
produces an unreliable agent, because the harness is what controls retries,
tool calls, context limits, and verification. The harness is now the layer that
decides whether a coding agent works on real code.

---

## Why this matters most for local and open models

Closed coding products ship a large, fixed harness tuned to one model family.
You cannot see it, version it, or change it, and it is built to keep you on that
vendor's model. That harness can be very good, but it is theirs.

Open Models are in the opposite position. The weights are yours to run, but they
arrive with **no harness at all**. A local model dropped into a harness designed
for a frontier API will look weak, not because it cannot code, but because the
harness wastes its context, assumes a native tool head it does not have, and
never verifies its edits.

This is the gap SuperQode closes. It treats the harness as the product you own,
and it is tuned for the realities of local and Open Models. See
[Local Agentic Coding](local-agentic-coding.md) for the model-by-model details.

> The model is the part you can swap. The harness is the part you build. Own it.

---

## A harness is a file you own

In SuperQode a harness is a single YAML artifact that lives in your repository.
It can be reviewed in code review, committed to version control, and run
anywhere the same way.

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

Read exactly what any harness will do, in plain English, before you run it:

```bash
superqode harness explain --spec harness.yaml
```

---

## The four moves

Harness engineering in SuperQode is four repeatable actions on that file.

### Build

Author a harness without writing YAML from scratch. Answer a few questions with
the wizard, or start from a model-family template and edit from there.

```bash
superqode harness wizard
superqode harness init my-coder -t qwen-coding
superqode harness explain --spec harness.yaml
```

See [Bring Your Own Harness](getting-started/bring-your-own-harness.md) and the
[Harness System](advanced/harness-system.md) reference.

### Measure

A harness you cannot measure is a guess. Run an eval task file to produce a
scorecard, and use it as a regression gate: a candidate that breaks a task the
baseline solved fails the gate.

```bash
superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml --live --json > baseline.json
superqode local bench --agentic
```

See [Run, Measure, Optimize](advanced/harness-optimization.md) and the
[Benchmark Runner](advanced/benchmark-runner.md).

### Extend

The same harness contract runs across runtimes and connects outward when you
choose: builtin, OpenAI Agents, Google ADK, Codex SDK, Claude Agent SDK,
DeepAgents, and PydanticAI, plus MCP tools, ACP agents, and A2A workflows. Only
the route changes; the contract stays the same.

```bash
superqode harness run --spec harness.yaml --runtime codex-sdk --prompt "review this repo"
```

See [Runtime Backends](runtimes.md) and [Connection Modes](concepts/modes.md).

### Optimize

Improve the harness with evidence instead of guesswork. Every optimizer follows
the same safe contract: start from a versioned artifact, measure it, stage a
candidate, gate it against regressions, and let a human adopt it. The live agent
never rewrites itself blindly.

```bash
superqode local optimize                 # best local/open model routing per role
superqode harness optimize --spec harness.yaml --tasks eval-tasks.yaml
superqode skills optimize review --engine gepa --harness harness.yaml --tasks eval-tasks.yaml --live
```

See the [Optimization Story](advanced/optimization.md) and
[Skill Optimization](advanced/skill-optimization.md).

---

## Why not just use someone else's harness

You can. SuperQode connects to hosted providers, Codex, Claude Code, and other
agents through [BYOK](providers/byok.md), [ACP](providers/acp.md), and runtime
SDKs. The difference is who owns the contract.

| | Closed coding agents | Open-source coding agents | SuperQode |
|---|---|---|---|
| Use any model | Mostly their own | Yes | Yes, Open Models first |
| Run local models | Fallback | Yes | Design center |
| The harness | Closed, vendor-owned | A fixed loop you configure | A versioned artifact you own |
| Measure the harness | No | No | Eval scorecards and regression gates |
| Optimize the harness | No | No | Staged candidates with human adoption |

### A harness you own, not a harness you rent

The harness is now a recognized layer of the agent stack, to the point that it
is offered as a managed cloud service: you declare an agent in configuration and
a hosted platform assembles and runs the loop for you, billed as cloud capability.

SuperQode takes the opposite stance. The harness is a file in your repository,
not a service in someone else's cloud. It runs local first on hardware you
control, it is versioned and reviewed like the rest of your code, and it behaves
the same whether you point it at a local model, a hosted provider, or a remote
runtime. A managed harness is useful when you want to outsource operations.
SuperQode is for teams that want to own the harness itself.

Even when you borrow another agent's strengths, SuperQode stays the controlling
harness. It can import an [Omnigent](advanced/omnigent-compat.md) spec, for
example, and convert it into a portable `HarnessSpec` rather than handing control
to another runtime.

---

## Start here

1. Install SuperQode and generate a local harness for your machine:
   `superqode local init --repo .`. See [Installation](getting-started/installation.md).
2. Build and explain your first harness in
   [Bring Your Own Harness](getting-started/bring-your-own-harness.md).
3. Measure and improve it with the [Optimization Story](advanced/optimization.md).
4. Read the full field reference in the [Harness System](advanced/harness-system.md).
