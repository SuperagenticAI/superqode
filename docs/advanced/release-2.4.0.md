# SuperQode 2.4.0: Jev integration

SuperQode 2.4.0 brings Jev into the harness as a typed decision service. Use it to
review proposed tool calls, evaluate structured decisions, compare outputs with
labels, or grade work against a rubric. Your coding model continues to write
code and produce explanations.

## General decision harness

The new `systemone` backend runs reviewed question packs through the same harness
interface used elsewhere in SuperQode. Packs define questions, permitted answers,
optional input schemas, and confidence policy. Supported question types are
Choice, Score, and Noul (yes/no probability).

Results include typed outputs, raw answers, abstained fields, a pack hash, and
available model and transport metadata. Low-confidence outputs remain unresolved.
Examples cover ticket triage, tool permissions, and factory-route suggestions.

```bash
superqode harness run examples/harnesses/systemone-factory-route.yaml \
  -p 'Review this patch for correctness and security'
```

In the TUI:

```text
:systemone connect factory_route
Review this patch for correctness and security
```

Direct decision sessions require no coding provider. Live requests need
`TYPESAFE_API_KEY` in the launching environment. The example paths above refer to
a repository checkout; installed users can supply their own harness YAML.

## Tool checks in the coding loop

Connect a coding model through `:connect`, choosing Core and BYOK, then run
`:systemone live`. The coding model and Jev use separate credentials.

- ALLOW proceeds subject to existing permission rules.
- DENY blocks the proposed tool call.
- ASK enters the human approval flow, including for otherwise auto-allowed tools.
- Client failures are displayed and defer to the existing permission policy.

Hard policy denials remain authoritative. Tool checks are opt-in and apply to the
native coding runtime. They do not intercept tools inside external agent runtimes.
A chat response that uses no tools does not invoke the gate.

## Labelled evaluations

`harness eval` can compare decision fields with exact typed labels. New routing
and tool-permission datasets provide small synthetic examples with held-in and
held-out splits. Tool-permission evaluations do not execute the proposed commands.

```bash
superqode harness eval-packs decision-routing
superqode harness eval --spec examples/harnesses/systemone-factory-route.yaml \
  --tasks src/superqode/data/eval_packs/decision-routing.yaml \
  --split held-out --live --json
```

For installed packages, pass the dataset path printed by `harness eval-packs`.
Scorecards distinguish wrong answers, abstentions, errors, and ungraded results.
They report coverage and accuracy among graded tasks alongside the overall score.
Decision evidence retains confidence and pack identity; the dataset has its own
hash. Unknown monetary costs remain unknown.

Existing substring checks remain supported. The legacy non-empty check is marked
as a smoke test. The starter datasets are not accuracy or safety benchmarks;
use representative, reviewed labels before tuning production thresholds.

## Rubric grading and revisions

```bash
export SUPERQODE_RUBRIC_GRADER=systemone
superqode --harness core --rubric 'Address the request and include verification evidence' \
  --mode json -p 'Review the current changes'
```

This requires your coding provider's configuration and the separate TypeSafe key.
Jev returns a rubric verdict. A confident `needs_revision` asks the coding model
to re-check the requirements within the existing revision limit. Jev does not
write critique text, and this release does not add automatic LLM fallback.

Low confidence, invalid answers, unavailable clients, and exhausted revision
rounds produce `ungraded`. Headless JSON includes `rubric_result`; an unsatisfied
or ungraded rubric sets `success` to false and exits with code 2. A `jev_rubric`
evaluator can also grade a harness response without running a revision loop.
Model judgments remain separate from executable verification.

## Configuration and compatibility

- Jev is opt-in; existing coding connections continue to work independently.
- The default live model is pinned to `jev-1.13.0`.
- Compatible endpoints must implement the System One wire contract. This release
  does not bundle a local classifier or a Pydantic AI/LangChain adapter.
- Stub and replay clients support offline development. Airplane policies prevent
  live evaluation.
- Recording and request preparation redact common credential patterns. Recordings
  preserve decision inputs and answers for replay.
- Factory-route outputs remain suggestions; they do not switch active models.

**Migration note:** utility-grader failures previously counted as `satisfied`.
They now report `ungraded`. Automation using `--rubric` should handle exit code 2
and inspect `rubric_result` rather than assuming every completed run passed review.

See the [integration guide](systemone.md) for pack schemas, evaluator configuration,
confidence policy, endpoint setup, and recording options.
