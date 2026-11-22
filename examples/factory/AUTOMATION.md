# Bounded improvement campaigns

**Factory Studio → Improve → Bounded automation (advanced)** and
`sq factory campaign` operate the same durable campaigns. Automation is off in
both starters. Saving a policy does not start models; enable its bounded worker
explicitly or run one queued experiment at a time.

Merge an explicit policy into the saved definition, preserving the rest of the
Factory. Its token, tool, cost and time limits must fit `governance.budget`:

```yaml
improvement:
  optimization:
    automatic_experiments: true
    editable: [skills, harnesses, routes, workflow]
    protected: [governance, improvement.checks, orchestration.acceptance_checks]
    experiment_policy:
      triggers: [incident]
      event_sources:
        incident: .superqode/factory-events/incident.json
      max_experiments: 1
      max_seconds: 300
      max_tokens: 90000
      max_tool_calls: 20
      max_cost_usd: 1
      cooldown_seconds: 60
      max_depth: 0
      stop_after_holds: 1
      experiment:
        binding: coder
        tasks: .superqode/evals/outputs.yaml
        fixture: '@empty'
        target_kind: harness
        reflection_model: ollama/qwen3-coder
        optimizer_engine: evaluator-optimizer
        max_evals: 4
        max_seconds: 120
```

The suite requires meaningful held-in and held-out cases. A starter label is
not a customer acceptance contract. Review, save and version the Factory before
preparing its campaign. Model routes and editable surfaces retain their normal
Factory restrictions.

## Admit an event

Supported trigger kinds are `reviewed_failure`, `reviewer_feedback`, `cost_drift`,
`incident` and `dependency_update`. Non-failure kinds require an exact JSON source
path under `.superqode/factory-events/`, declared in `event_sources`. File
ownership must restrict who can publish that evidence; a local file is not
authentication of a remote publisher. [Signed intake](INTAKE.md) is a separate
application-work admission path.

`reviewed_failure` references a current source-verified failure and its exact
review digest. Only reviewed application-defect or model-protocol findings may
trigger tuning. Infrastructure, evaluator, budget and unknown findings require
repair rather than instruction optimization.

In Studio, choose the trigger, **Review event source**, then explicitly queue
the reviewed digest. These actions make no model calls. The CLI equivalent is:

```sh
sq factory campaign create --project /path/to/project
sq factory campaign enqueue CAMPAIGN_ID --project /path/to/project \
  --digest CAMPAIGN_DIGEST --kind incident --key incident-123 \
  --source .superqode/factory-events/incident.json --source-digest SOURCE_DIGEST
sq factory campaign run CAMPAIGN_ID --project /path/to/project \
  --digest CAMPAIGN_DIGEST --live
```

Identical source fingerprints are deduplicated, including delivery aliases.
Reusing an idempotency key with changed evidence is refused. Parent events must
belong to the same campaign and fit its recursion-depth limit.

## Run automatically within the bound

**Start bounded campaign worker** or the following command processes admitted
events without another approval for each model request:

```sh
sq factory campaign worker CAMPAIGN_ID --project /path/to/project \
  --digest CAMPAIGN_DIGEST --live
sq factory campaign inspect CAMPAIGN_ID --project /path/to/project
sq factory campaign stop CAMPAIGN_ID --project /path/to/project --digest CAMPAIGN_DIGEST
```

The worker stops at a hold, a candidate requiring review, a drain request,
exhausted reservations or its shared deadline. Time waiting for events and
cooldowns consumes that deadline. It cannot run indefinitely. Starting a new
worker does not reset the campaign clock. A stop request drains the current
action; cancelling the native job interrupts it and may require reconciliation.

Each child reserves a fixed fraction of the campaign's token, API-cost and tool
ceilings before execution. Reservations are never recycled after interruption.
The child's normal request ledger includes reflection, scoring and final
comparison. Unknown usage, an overrun or uncertain work prevents further
admission. A crash leaves a running event held for operator review, without an
automatic retry.

Only one automatic final comparison may expose a particular suite/fixture pair
across campaigns. Once consumed, choose genuinely fresh assessment cases for a
new automatic experiment. Creating another campaign does not refresh held-out
independence. Ties and regressions remain held.

Campaign results never activate a Factory. An eligible candidate must still be
reviewed through the normal draft-adoption path, saved, committed and trialled.
Protected application verification and signed delivery remain separate actions.
