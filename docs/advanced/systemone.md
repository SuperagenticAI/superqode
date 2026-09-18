# Jev integration and decision harnesses

SuperQode can evaluate reviewed question packs independently of a coding model.
A pack defines the input contract, atomic questions, and confidence policy.
The harness validates and redacts state, calls the selected client, binds the
answers to their question types, and produces typed outputs. It executes no
model-selected commands.

## Choose an integration

| Workflow | Entry point | Result |
| --- | --- | --- |
| Check coding tools | Core/BYOK plus `:systemone live` | Allow, deny, or request approval |
| Evaluate a decision pack | `harness run` or `:systemone connect` | Typed decision output |
| Compare decisions with labels | `harness eval` with a `decision` evaluator | Scorecard and per-task evidence |
| Grade and revise coding work | `--rubric` plus `SUPERQODE_RUBRIC_GRADER=systemone` | Bounded revisions and rubric result |
| Judge a harness response | `harness eval` with a `jev_rubric` evaluator | Model judgment with evidence |

Live Jev calls require `TYPESAFE_API_KEY` in the launching environment. Your
coding provider uses its own credentials. Enabling tool checks does not connect
a coding model; see [TUI setup](tui.md#jev-tool-checks).

## Run a pack

```sh
uv run superqode harness run examples/harnesses/systemone-ticket-triage.yaml -p 'Our production checkout is down. Please help immediately.'
uv run superqode harness run examples/harnesses/systemone-factory-route.yaml -p 'Review this patch for correctness and security'
```

For the TUI, launch `uv run superqode`, then enter:

```text
:systemone connect factory_route
Review this patch for correctness and security
```

Alternatively launch with `--harness examples/harnesses/systemone-ticket-triage.yaml`.
The selected decision harness connects on the first input without a coding provider.
TypeSafe's live endpoint needs `TYPESAFE_API_KEY` in the launching environment.

## Define a reviewed pack

The complete example is `examples/systemone/ticket-triage-pack.yaml`.

```yaml
id: ticket_route
version: "1.0.0"
state_schema:
  type: object
  required: [ticket]
  properties:
    ticket: {type: string, minLength: 1}
  additionalProperties: false
input_key: ticket
questions:
  department:
    type: choice
    instructions: Which department should handle this ticket?
    criteria:
      technical: Bugs and outages.
      billing: Invoices, subscriptions, and refunds.
      other: Anything outside those departments.
decision_policy:
  min_confidence: 0.75
  noul_false_max: 0.2
  noul_true_min: 0.8
```

State may be text, a JSON object, or a JSON array. `state_schema` is optional
JSON Schema Draft 2020-12; references must stay within the schema. `input_key`
wraps plain text in an object under the named field. Invalid JSON, invalid
state, and inputs above 32,000 characters are rejected before evaluation.
Secret-named fields and common credential patterns are redacted before HTTP
and live recording. Avoid putting secrets in decision inputs; pattern matching
cannot identify every possible secret.

Choice and Score outputs require `min_confidence`. Noul becomes false at or below
`noul_false_max`, true at or above `noul_true_min`, and otherwise abstains.
Uncertain outputs are null and listed in `abstained`; raw typed answers remain
available. No deterministic action is inferred from a low-confidence value.
Pack hashes cover questions, schemas, and policies.

The reserved `tool_gate` pack keeps its existing ALLOW/DENY/ASK composition.
General packs return `status`, `outputs`, `answers`, `abstained`, and `metadata`.
The bundled `rubric` pack takes JSON with `rubric` and `work`; it evaluates a
verdict without invoking the headless revision loop. `factory_route` suggests a
route without changing the active coding session.

## Configure a compatible model

```yaml
version: 1
name: local-decisions
flavor: decision
runtime:
  backend: systemone
systemone:
  enabled: true
  client: live
  endpoint: http://localhost:9000/v1/systemone
  api_key_env: ""
  model: local-classifier
  pack: ./ticket-route.yaml
  timeout_ms: 5000
```

`endpoint` must implement the System One state/questions/answers wire contract.
An empty `api_key_env` sends no Authorization header; otherwise set it to the
name of that service's credential variable. The default endpoint and variable
are TypeSafe's endpoint and `TYPESAFE_API_KEY`. No other live model adapter or
local classifier is bundled. The exported async `SystemOneClient` protocol and
`evaluate_decision` function also support application-supplied Python clients.

Pack, replay, and recording paths in a harness file resolve relative to that
file. `client: stub` provides uncertain outputs offline. `client: replay` with
`replay_path` reuses fixture answers or live recordings. `record_dir` enables
sanitized live recordings. Airplane mode skips network evaluation; it does not
substitute a decision. Transport failures report an error, never a successful
classification. The native coding gate separately falls back to existing policy.

## Labelled decision evaluations

Use the normal harness evaluator to compare decision outputs against labels:

```bash
superqode harness eval-packs decision-routing
superqode harness eval --spec examples/harnesses/systemone-factory-route.yaml \
  --tasks src/superqode/data/eval_packs/decision-routing.yaml --split held-out --live --json
```

For installed packages, use the path printed by `harness eval-packs`. The
`decision-tool-gate` pack works with `examples/harnesses/systemone-tool-gate.yaml`.
It classifies proposed commands without executing them. Both datasets are small,
synthetic starter examples; they do not establish real-world accuracy or safety.
Review the labels against your policy and add representative examples before
calibrating thresholds. Keep held-out examples separate from tuning data.

An evaluator is declared per task:

```yaml
tasks:
  - id: review-request
    split: held-out
    prompt: Review this patch for correctness.
    evaluator:
      type: decision
      expected: {route: review}
```

Decision labels compare the named output fields exactly, including JSON types.
Tool-gate labels use `action: allow`, `action: deny`, or `action: ask`. An ASK
permission decision is a valid action; a general decision's abstention is an
unresolved evaluation. Scores are successful tasks divided by all tasks.
Coverage and accuracy among graded tasks are reported separately. Errors,
abstentions, and ungraded judgments do not count as passes. The result retains
the dataset hash, returned decision, pack hash, confidence, and available
transport metadata. Unknown monetary costs remain unknown.

The evaluator types are `decision`, `contains`, `non_empty`, and `jev_rubric`.
Existing `expect_contains` tasks continue to work. Tasks without an evaluator
retain the legacy non-empty smoke check, explicitly marked `smoke_only` in the
result; this is not a correctness test. A scorecard can contain both passing and
failing tasks; inspect the score and task results, not only execution status.

## Rubric grading and revisions

Enable Jev grading independently of tool permissions:

```bash
export SUPERQODE_RUBRIC_GRADER=systemone
superqode --harness core --rubric 'Explain the fix and include verification evidence' \
  --mode json -p 'Review the current changes'
```

The live client needs `TYPESAFE_API_KEY` in the process. Configured System One
model, endpoint, and deadline are inherited from an enabled System One
harness configuration. Offline restrictions apply independently. `SUPERQODE_SYSTEMONE=0` disables the client; explicit stub/replay settings
remain useful for offline tests. Without the rubric opt-in, the existing utility
model remains the grader.

A confident `needs_revision` decision asks the coding model to re-check the
rubric and supply missing evidence, within the existing revision limit. Jev
supplies the verdict, not generated critique text. Low confidence, unavailable
clients, invalid answers, and exhausted revision rounds produce `ungraded`.
Headless JSON includes `rubric_result`; anything other than `satisfied` makes
`success` false and exits with code 2. Utility-grader failures also now report
`ungraded` instead of claiming satisfaction.

To judge another harness's answer without enabling a revision loop, use
`evaluator: {type: jev_rubric, rubric: 'Your concrete requirement'}` in an eval
task. See `examples/systemone/rubric-eval.yaml`. Judgment evidence and judge usage
are recorded separately from the harness's execution usage. No LLM fallback is
automatic in this release. Model judgments do not prove that tests ran or replace
executable verification.
