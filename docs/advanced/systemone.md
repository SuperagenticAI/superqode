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
| Code with Jev observing decisions | `--harness systemone` | Shadow tool gates and tool discovery |
| Evaluate a decision pack | `harness run` or `:systemone connect` | Typed decision output |
| Compare decisions with labels | `harness eval` with a `decision` evaluator | Scorecard and per-task evidence |
| Grade and revise coding work | `--rubric` plus `SUPERQODE_RUBRIC_GRADER=systemone` | Bounded revisions and rubric result |
| Judge a harness response | `harness eval` with a `jev_rubric` evaluator | Model judgment with evidence |

Live Jev calls require `TYPESAFE_API_KEY` in the launching environment. Your
coding provider uses its own credentials. Enabling tool checks does not connect
a coding model; see [TUI setup](tui.md#jev-tool-checks).

## SystemOne coding harness and tool search

Select the bundled `systemone` harness with your usual coding provider:

```sh
superqode --harness systemone
```

In a connected coding session, use `:harness use systemone`. The coding model
continues to write code. Jev observes tool gates in shadow mode and recommends
tools during deferred discovery. Without `TYPESAFE_API_KEY`, Jev is skipped and
the existing permission policy and lexical tool search continue to work.
The separate `:connect` SystemOne models option still runs standalone decision packs.

This harness defers optional tool schemas and exposes `tool_search`. A search
retrieves up to eight candidates from the registered deferred tools. Jev chooses
from that closed set or `none`. When lexical retrieval finds no match, catalogs
of eight or fewer deferred tools can be considered directly. Larger catalogs
require a matching retrieval query; this is not an embedding search.

The default `tool_search_mode: shadow` records Jev's recommendation while
preserving lexical activation. To let Jev select which schema to activate:

```sh
export SUPERQODE_SYSTEMONE_TOOL_SEARCH=rerank
```

Selection requires Choice confidence at least 0.75, candidate-fit Noul at least
0.8, and the selected option's probability to exceed every other option by at
least 0.1. These are initial selection thresholds, not calibrated safety scores.
Uncertain answers and `none` activate nothing; client or schema errors fall back
to lexical search. Activating a schema never executes its tool or grants permission.

Set `SUPERQODE_SYSTEMONE_TRACE_DIR` to record sanitized discovery events under
its `tool-search/` subdirectory. Events include candidates, baseline tools,
Jev's selection, raw answers, distribution diagnostics and activated tools.
They are separate from permission allow/deny calibration records.

Custom specs can set `systemone.tool_search_mode` to `off`, `shadow`, or `rerank`.
`model_policy.config.deferred_tools: all` enables deferred schemas for any
provider. `SUPERQODE_DEFERRED_TOOLS=off` overrides the harness default.

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

## Improve decisions with SystemOne Tune

Open `:systemone tune` in the TUI, or select **Improve decisions** on the
SystemOne entry in Harness Hub. The CLI provides the same workflow:

```sh
superqode harness tune
```

Tune currently improves one fixed Choice question, including structured
instructions and criteria. Choose a built-in pack or a SystemOne decision
harness, then import CSV, JSONL, JSON or YAML examples. With no file, the wizard
offers a small synthetic routing demo (`--demo` on the CLI). Use `--pack` to pick a built-in pack, `--output` for the run directory, `--reflection-lm` to override the reflection model, and `--seed` for deterministic splits. Missing labels are collected one at a
time with an optional rationale, and each judgment is saved immediately.

Install the optional, tested optimization runtime with the TUI's **Install
tuning support** button or `superqode harness tune --setup`, then restart
SuperQode. This installs a pinned GEPA source revision into SuperQode's Python
environment. Jev needs its configured API credentials; reflection uses a
separate model. Tune detects configured OpenAI, Anthropic and Gemini API keys,
or accepts a LiteLLM `provider/model` identifier. It does not reuse coding-agent
subscription credentials.

```sh
# Built-in pack + demo dataset (live experiment, not a benchmark)
superqode harness tune --demo --live

# Reviewed examples
superqode harness tune --spec examples/harnesses/systemone-factory-route.yaml \
  --data reviewed-tickets.csv --input request --label route \
  --reflection-lm openai/gpt-5 --max-evals 120 --max-reflection-cost 2 \
  --output .superqode/tuning/routing-v2 --seed 0 --live --json

# Resume annotation, change the reflection model, or inspect completed results
superqode harness tune --resume .superqode/tuning/<run>
```

Input rows use `state`, `label`, and optional `id`, `rationale`, `group`, and
`split` fields. `--input` and `--label` map other column names. Use `group` to
keep related tickets/session examples together. Explicit splits are `train`,
`validation`, and `test`; existing `held-in`/`held-out` decision eval files are
also supported. Otherwise Tune partitions examples deterministically before
annotation. Duplicate inputs are rejected, and test examples never enter GEPA.

An experiment preserves output labels, schema, model configuration and
confidence policy. It writes `candidate-pack.yaml`, `candidate-harness.yaml`,
`changes.diff`, evaluation evidence and `report.json` under `.superqode/tuning`.
The comparison counts abstentions and errors separately, and checks for
regressions against the baseline. Small runs (fewer than 30 training or 30 test
examples) are marked as pilots and cannot qualify for adoption; larger runs
still require representative data and human review. **Use this version** opens
a standalone decision session after a qualifying comparison, not automatic
coding-session routing.

The reflection spend limit is checked between model calls and excludes Jev
usage. The final baseline/candidate test calls are additional to `--max-evals`;
both allowances are displayed before starting. Inputs go to Jev; development
examples and rationales also go to the reflection provider. Existing state
redaction applies, but example files should not contain secrets.

Stop saves completed evidence. Annotation can be resumed; an interrupted
optimization requires a new experiment and budget, avoiding silent renewed
spend. Recent-session acquisition, new-question discovery, Noul/Score tuning,
and automatic adoption into permission or revision loops are not included.

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

## Shadow tool checks and disagreement reports

Shadow mode evaluates the native coding loop's proposed tool calls while leaving
existing permissions in control. Jev cannot approve, deny, or force an approval
in this mode. Hard hook, YAML, and manager denials still skip model evaluation.
This setting affects tool gates, not standalone decision packs or rubric grading.

```sh
export TYPESAFE_API_KEY=api_key...
export SUPERQODE_SYSTEMONE=live
export SUPERQODE_SYSTEMONE_MODE=shadow
export SUPERQODE_SYSTEMONE_TRACE_DIR=.superqode/decision-traces
superqode --harness core
```

The TUI also supports `:systemone shadow`; `:systemone live` switches back to
enforcement. A harness can declare `systemone.mode: shadow` and
`systemone.trace_dir`. Trace paths in YAML resolve relative to the harness file.
Trace recording is opt-in and produces one sanitized JSON file per permission
check, with restrictive file permissions. Recording failures do not change
permission decisions. These traces contain task and command context; review them
before sharing. Pattern redaction cannot catch every secret.

Traces distinguish `intendedAction` (Jev recommendation), `policyAction` (existing
policy before Jev), and `permissionAction` (final permission outcome, not proof
of execution). Evaluated traces include full typed answers and distributions,
model, thresholds, pack hash, bounded state and truncation indicators. Hard-denied
checks have a skipped status and no invented Jev recommendation. Approval retries
are separate records identified by session and tool-call IDs.

```sh
superqode harness decision-report .superqode/decision-traces
superqode harness decision-report .superqode/decision-traces --reference humanAction
```

The JSON report includes a confusion matrix, disagreements, allow-against-deny,
deny-against-allow, allow-against-ask, ASK rate, errors, skipped checks, and median
latency. Policy disagreement is not a measured safety error. For human comparison,
review the trace against your authorization policy and add `humanAction` with
`allow`, `deny`, or `ask` to a copy of the trace. Unlabelled decisions remain
unlabelled; approvals, successful execution, and missing handlers do not supply
human labels automatically. Keep reviewed tuning and held-out trace directories
separate when selecting thresholds. Choice confidence is distribution certainty,
not permission or a safety probability.

Each evaluated trace also records distribution entropy, the top probability,
and the margin between the top two disposition options. A small margin identifies
near ties; none of these statistics establishes permission or safety. Reports
break labelled disagreements into confidence buckets.

Compare confidence thresholds against reviewed labels without making live calls:

```sh
superqode harness decision-report reviewed-traces --reference humanAction \
  --allow-confidence 0.75 --allow-confidence 0.90 --allow-confidence 0.95
```

The sweep recomposes full recorded answers with their recorded thresholds,
changing only `allow_confidence` (used for both Choice allow and Choice deny).
Missing answers and failed or skipped evaluations are excluded and counted.
Atomic Noul thresholds remain unchanged. Sweeps never edit packs or enable
enforcement. Use separate datasets for each model and pack version; retain a
held-out dataset before adopting thresholds. A quiet disagreement report alone
is insufficient if there are few labels or the data omits risky actions.

## Connect to Jev from the TUI

Open `:connect`, choose **Connect with SystemOne models**, then **Jev (TypeSafe AI)**.
With `TYPESAFE_API_KEY` set in the launching shell, this connects to the
`factory_route` decision pack. Enter a task to get a typed route suggestion.
Use `:systemone packs` to browse other packs and `:systemone connect <pack>` to
switch. This connection runs decision packs; coding sessions use their own model
connection and can enable the Jev tool-check sidecar separately.

If the key is missing, selecting Jev shows the TypeSafe console and access links,
the environment-variable setup command, and instructions to restart and reconnect.
The picker never asks you to paste credentials into chat or saves your key.
