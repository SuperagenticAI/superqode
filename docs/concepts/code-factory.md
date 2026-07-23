# Code Factory

A code factory is an organization-owned system that turns intent into verified code changes through coding agents, harnesses, models, repositories, context, tools, policies, evaluation gates, and delivery workflows.

It is not defined by the number of agents. It is defined by whether work can move from a goal to an inspectable, verified, and governed result.

## The problem

Organizations often adopt several coding agents, but each agent keeps its own sessions, context, tools, permissions, and evidence. A collection of agent clients does not provide a consistent system for repository delivery.

A dependable code factory must answer:

- how an agent is configured for a repository
- how existing agents and organization-owned harnesses work together
- how work is isolated, resumed, reviewed, and accepted
- how quality, cost, latency, and regressions are measured
- how policies, credentials, budgets, and approvals are enforced
- how harness changes are evaluated and promoted safely

SuperQode provides these controls through one terminal-first Agent Engineering framework.

## Three ways to supply a coding agent

### Build

Create an organization-owned HarnessSpec that defines model routing, context, memory, tools, workflow, sandboxing, checks, and approvals.

### Select

Select a built-in or locally published harness from the SuperQode catalog and adapt it for the repository. The current registry is local and repository-oriented. SuperQode does not claim a hosted public marketplace.

### Connect

Connect an established coding agent through a native integration, SDK runtime, or the Agent Client Protocol. This allows teams to retain agents they already use while applying consistent orchestration, evaluation, governance, and evidence around them.

## Code Factory architecture

| Factory requirement | SuperQode component |
| --- | --- |
| Agent definition | HarnessSpec |
| Existing agent connection | Native integrations, ACP, and SDK runtimes |
| Interactive work | Persistent sessions, harness switching, forks, and handoffs |
| Durable repository delivery | WorkOrders, task graphs, leases, isolated workers, checks, reviews, and acceptance |
| Routing and lineage | `sq factory` |
| Governance | Policies, approvals, budgets, credential controls, and audit events |
| Measurement | Harness evals, benchmarks, evidence, and scorecards |
| Improvement | Candidate generation, held-out evaluation, adoption, and rollback |
| Operation | CLI, TUI, headless workers, and focused remote-control interfaces |

```text
Intent
  |
  v
Agent or HarnessSpec
  |
  v
Session or WorkOrder
  |
  v
Isolated execution and evidence
  |
  v
Evaluation, policy, and delivery gates
  |
  v
Verified code change
  |
  v
Guarded harness improvement
```

## Terminal-first operation

The CLI and TUI are the primary interfaces. Builders can connect agents, switch harnesses without discarding a session, run WorkOrders, inspect evidence, approve delivery, and evaluate improvements without depending on a hosted web workspace.

Focused APIs and channels can expose a running local SuperQode instance when remote access is useful. They complement the terminal workflow rather than replace it.

## Build a code factory

Start with one of these paths:

```bash
# Build an organization-owned harness
superqode harness init repo-coder --template coding --output harness.yaml

# Inspect available harnesses
superqode harness list

# Connect an established ACP coding agent
superqode
# Then run: :connect
```

Add durable repository delivery when a change requires roles, dependencies, recovery, and acceptance:

```bash
sq work create "Implement the approved repository change" \
  --acceptance-test "pytest -q" \
  --queue
sq work worker WORK_ID --once
sq work watch WORK_ID
sq work approve WORK_ID --actor maintainer
sq work merge WORK_ID --actor maintainer
```

Evaluate and improve the harness independently of the underlying model:

```bash
sq harness eval --spec harness.yaml --tasks tasks.yaml
sq harness optimize --spec harness.yaml --tasks tasks.yaml
```

## Product boundary

SuperQode provides the terminal execution, delivery, evaluation, governance, and optimization layers of a code factory. It does not require a proprietary web, mobile, or desktop client suite. It can work with established coding agents instead of requiring an organization to replace them.

The `sq factory` command is one module within this product model. It manages routing and lineage. WorkOrders, harness evaluation, policy, and optimization provide the remaining delivery controls.

## Next steps

- [Code Engineering](code-engineering.md)
- [What Is Harness Engineering](../harness-engineering.md)
- [Building a Code Factory with SuperQode](../advanced/software-factory.md)
- [How SuperQode Relates to Omnigent](../advanced/superqode-vs-omnigent.md)
