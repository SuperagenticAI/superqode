---
title: Optimization
description: Configure GEPA, GEPA Omni, MetaHarness, AutoResearch, and SkillOpt.
---

# Optimization

Optimization is optional. Candidate HarnessSpecs and skills are staged for
review. Adoption or promotion requires an explicit user action.

| Integration | Dependency | Use | Additional requirement | Detailed guide |
| --- | --- | --- | --- | --- |
| GEPA | `uv tool install "superqode[optimization]"` | Reflective optimization for skills and harness artifacts | A reflection model and evaluation tasks | [Optimization Story](../advanced/optimization.md) |
| GEPA Omni | `superqode[optimization]` plus a GEPA build containing the Omni API | Run GEPA, AutoResearch, and GEPA meta-harness exploration, then continue from the winner | Claude CLI for the AutoResearch and meta-harness explorers | [Harness Optimization](../advanced/harness-optimization.md#optimize-with-gepa-omni) |
| AutoResearch | Installed through the GEPA Omni path | Agent-driven candidate editing and evaluation | Authenticated Claude CLI | [Skill Optimization](../advanced/skill-optimization.md) |
| GEPA meta-harness | Installed through the GEPA Omni path | Maintain and evaluate a candidate frontier | Authenticated Claude CLI | [Skill Optimization](../advanced/skill-optimization.md#engines) |
| Superagentic MetaHarness | Install separately with `uv tool install superagentic-metaharness` | Export and optimize a HarnessSpec project | Selected MetaHarness backend | [Harness Optimization](../advanced/harness-optimization.md#optimize-harness-optimize-metaharness-optional) |
| SkillOpt | **Included** coordinator; GEPA engines use `superqode[optimization]` | Optimize and stage markdown skills | Held-in and held-out task sets | [Skill Optimization](../advanced/skill-optimization.md) |

For GEPA Omni while its required API is newer than the tagged package, install
GEPA from its current source branch in the same environment:

```bash
uv tool install "superqode[optimization]" \
  --with "gepa @ git+https://github.com/gepa-ai/gepa.git"
```

Run the bounded smoke test before increasing the evaluation budget:

```bash
scripts/run_tiny_omni_experiment.sh \
  --spec examples/harnesses/omni-tiny-local.yaml
```

Review the [harness optimization guide](../advanced/harness-optimization.md)
before increasing the evaluation or token budget.
