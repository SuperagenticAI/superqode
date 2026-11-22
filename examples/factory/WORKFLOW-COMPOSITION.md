# Explicit workflow composition

Factory composition now supports explicit stage handoffs, typed reviewer
experiments, conditional stages and a finite implementation/review revision
loop. The original definitions remain valid without new fields.

Use [composed-workflow.yaml](composed-workflow.yaml) as an authoring example.
Bind your model, acceptance commands and protected evaluators before a real
trial. The example does not configure release signing authority.

## Stage input/output contracts

Declare `outputs` by name. Each output is `text`, `json` with named primitive
`fields`, or `review`. JSON fields are required and extra fields are refused.
Supported field types are string, boolean, integer and number, with optional
bounded enum choices. There are no arbitrary schemas, external references or
executable validators. Outputs have a default 16 KB limit each, a maximum 64 KB
declared allowance per stage, and at most sixteen names.

An `inputs` entry names a predecessor `stage` and `output`. The producer must
be an ancestor in the declared dependency graph. Input names are local aliases.
Set `candidate_bound: true` when the producer's evidence must describe the exact
candidate being consumed. The controller compares the captured Git tree before
running the consumer. Stale or missing required evidence blocks execution;
an output from another attempt or modified receipt cannot satisfy a handoff.

Models return a single labelled JSON object:

```text
SUPERQODE_OUTPUT: {"analysis":{"needs-fix":true,"summary":"Repeated categories overwrite prior amounts."}}
```

The controller checks output coverage, types, fields and sizes before integrating
a writer's patch. Receipts bind the WorkOrder, producer, attempt, Factory
snapshot, declaration, input provenance and candidate tree. A failed stage's
published artifact cannot satisfy a consumer. Existing untyped dependency
evidence remains available as explicitly untrusted context.

The initial adapter requires one worker per Factory. Existing time, token, cost,
tool and stage-attempt budgets still apply.

## Typed-reviewer experiments

A reviewer output contains exactly `verdict`, `summary` and `issues`. Verdicts
are `approved` or `changes_requested`. Approval requires empty issues; requesting
changes requires nonempty, concrete issues. The normal reviewer marker remains:

```text
SUPERQODE_OUTPUT: {"decision":{"verdict":"approved","summary":"Reviewed the candidate and its edge cases.","issues":[]}}
SUPERQODE_REVIEW: {"verdict":"approved","summary":"Reviewed the candidate and its edge cases.","issues":[]}
```

The two judgments must agree. A malformed, contradictory or writing reviewer
does not establish a valid typed handoff. Final typed review must approve the
exact integrated candidate, so a later change requires fresh review.

**Factory Studio → Workflow → Whole-workflow instruction experiment** exports a
paired Trial Suite for an entry, dependent or reviewer stage. Save and commit
declared Factory sources, then validate the definition; export requires a clean
committed application baseline. Only the selected stage's goal changes; schemas, branches,
loop bounds, gates, permissions and protected acceptance stay fixed. Supply an
overall task, export, then review and prepare/run it from **Trial suites**.
Exporting makes no inference calls and grants no adoption or release authority.
Experiments are immutable and limited to 32 distinct exports per project.

**Improve → Workflow entry-stage goal** also supports an ungated entry reviewer
on a pinned, read-only candidate fixture. Every held-in and held-out case must
use the typed `review` grader with `expected_verdict`; optional `issue_contains`
checks grade labelled findings. Plain substring matches cannot qualify a
reviewer experiment. This adapter does not invent predecessor evidence or run
the complete workflow. Whole-workflow experiments use Trial Suites instead.
When a reviewer declares named outputs, every case pins the same `output_names`;
custom output limits must also match the grader's `max_bytes`.

## Conditional stages

A stage's `when` compares one explicitly declared input, or one named field in
that input, to a primitive `equals` value. Equality preserves JSON value types.
No model-generated code or expression is evaluated to choose the branch.

False conditions create a durable **skipped** task with a decision receipt and
event before its gate or model invocation. Skipped tasks have no fabricated
output or usage report. A downstream `optional: true` input may receive null
from a skipped producer; a required input is held. Human gates still apply to
selected stages. **Trial suites → Scorecard & evidence** exposes typed handoffs,
candidate bindings, skipped stages and their receipts.

## Bounded revision loops

The initial `revision_loop` adapter names one implementer and its directly
dependent reviewer, with `max_iterations` between two and four. The reviewer
must declare one typed review output and consume a candidate-bound implementer
output. Loop members cannot have additional `when` predicates. There is one
revision block per Factory; nested loops and arbitrary cycles are unsupported.

The compiler expands the block into a finite DAG of at most 64 total stages.
Each iteration keeps its own task identity, outputs, invocation and gate history.
`changes_requested` from an intermediate reviewer allows the next iteration,
whose implementer receives a reserved `revision-feedback` input. Approval skips
remaining iterations. A request for changes at the final iteration blocks the
workflow. Missing, contradictory or stale review evidence is held.

Consumers after the block use the last executed output, retaining its actual
producer and receipt; skipped iterations do not fabricate replacement outputs.
The original WorkOrder budget is shared across every iteration and retry. No
iteration widens permissions, resets a budget or approves release. Human gates
remain explicit at every selected occurrence.

This implements bounded composition and instruction comparison. Automatic graph
search, a full visual workflow editor, automatic activation and broad
multi-machine orchestration remain outside this adapter.
