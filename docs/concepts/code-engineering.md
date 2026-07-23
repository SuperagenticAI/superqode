# Code Engineering

Code Engineering is the discipline of applying evaluation, governance, provenance, and optimization to code produced by humans and agents.

Generating code is only one step. Production use also requires control over how intent becomes a change, which context and tools are available, how results are verified, what evidence is retained, and how the system improves.

## The problem

A capable model can produce useful code, but it does not provide a complete engineering system. Organizations still need to answer:

- which agent, model, and harness produced a change
- which repository context, memory, tools, and policies shaped the result
- whether the change passed acceptance, regression, security, and cost gates
- which artifacts and decisions support approval
- whether a proposed harness improvement performs better on held-out work
- how to recover, reject, or roll back when a run fails

Code Engineering makes these controls part of the code production lifecycle.

## Relationship to Agent Engineering

Agent Engineering covers the design, evaluation, governance, and operation of reliable agent systems. Code Engineering applies that discipline to systems that create and modify code.

Harness Engineering is a technical discipline within this model. It treats the software around a model, including context, memory, tools, workflows, policies, checks, and control loops, as a versioned artifact that can be evaluated and improved.

```text
Agent Engineering
        |
        +-- Code Engineering
                |
                +-- Harness Engineering
```

These terms describe different levels of the same product:

| Level | Meaning in SuperQode |
| --- | --- |
| Agent Engineering | The broader discipline for building and operating reliable agents |
| Code Engineering | The discipline applied to code production and repository change |
| Harness Engineering | The engineering of the system around each coding model |
| Code Factory | The organization-owned operating system that combines agents, harnesses, repositories, policies, evaluation, and delivery |

## The Code Engineering lifecycle

SuperQode implements a repeatable lifecycle:

1. **Build** a repository-owned HarnessSpec or select a compatible harness.
2. **Connect** an established coding agent through a native runtime or ACP.
3. **Orchestrate** interactive sessions or durable WorkOrders.
4. **Evaluate** quality, cost, latency, recovery, and regression behavior.
5. **Govern** tools, credentials, budgets, approvals, and delivery decisions.
6. **Optimize** harness candidates under held-out evaluation and human-controlled promotion.

The result is not only generated code. It is a verified change with reproducible configuration, execution evidence, and an explicit delivery decision.

## How SuperQode supports Code Engineering

| Requirement | SuperQode capability |
| --- | --- |
| Versioned agent configuration | Repository-owned HarnessSpec |
| Agent and model independence | Native runtimes, ACP, SDK adapters, BYOK, and local models |
| Repository delivery | WorkOrders, isolated workers, patches, checks, reviews, and acceptance gates |
| Evaluation | Harness evals, benchmarks, scorecards, and negative evidence |
| Governance | Layered policy, approvals, budgets, credential controls, and audit records |
| Optimization | Candidate search, Pareto comparison, held-out gates, adoption, and rollback |
| Operational access | Terminal-first CLI and TUI, headless workers, and focused remote control |

## Scope

SuperQode currently focuses on repository-based code work. This includes application code, infrastructure definitions, data pipelines, configuration, tests, and technical documentation managed as code.

The product does not assume that one coding agent or one model should own the complete lifecycle. An organization can build its own harness, select a local harness from the catalog, or connect an established coding agent while retaining consistent evaluation, governance, and evidence.

## Next steps

- [Code Factory](code-factory.md)
- [What Is Harness Engineering](../harness-engineering.md)
- [Harness System](../advanced/harness-system.md)
- [WorkOrders](../advanced/workorders.md)
- [Optimization](../advanced/optimization.md)
