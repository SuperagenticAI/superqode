# SystemOne Tune (GEPA Jev optimization)

Improve a fixed SystemOne decision pack from reviewed examples, then compare the
candidate on held-out data before you use it. The active harness stays unchanged
while an experiment runs.

Tune uses a pinned [GEPA](https://github.com/gepa-ai/gepa) revision through
SuperQode's optional tuning support. In the TUI the product language is **Tune**
and **tuning support**; GEPA is the optimizer under the hood.

This page is part of the **SystemOne Harness** docs:

- [Jev Integration](systemone.md) - SystemOne harness, packs, tool gates, evals
- [Progressive Tool Discovery](progressive-tool-discovery.md) - catalogue → search → rank → Jev → activate
- **SystemOne Tune (GEPA)** - this page

## Run Tune

Open `:systemone tune` in the TUI, or select **Improve decisions** on the
SystemOne entry in Harness Hub. The CLI provides the same workflow:

```sh
superqode harness tune
```

Tune currently improves one fixed Choice question, including structured
instructions and criteria. Choose a built-in pack or a SystemOne decision
harness, then import CSV, JSONL, JSON or YAML examples. With no file, the wizard
offers a small synthetic routing demo (`--demo` on the CLI). Use `--pack` to pick
a built-in pack, `--output` for the run directory, `--reflection-lm` to override
the reflection model, and `--seed` for deterministic splits. Each judgment and
optional rationale is saved immediately.

Fully labeled or partially labeled files keep the bounded one-shot workflow.
When every imported label is empty, Tune starts an active-learning session.
For each round Jev scores only the development pool, selects the most uncertain
examples plus a random audit example, and randomly selects a reserved test
example without scoring the test pool. The TUI explains why each example was
selected. `--batch-size` controls the 2 to 20 development judgments collected per
round and defaults to five.

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

# Multi-round active-learning demo from a repository checkout
superqode harness tune --data examples/tune/factory-route-active.csv \
  --batch-size 5 --max-evals 30 --max-reflection-cost 0.50

# Reviewed examples
superqode harness tune --spec examples/harnesses/systemone/factory-route.yaml \
  --data reviewed-tickets.csv --input request --label route \
  --reflection-lm openai/gpt-5 --max-evals 120 --max-reflection-cost 2 \
  --output .superqode/tuning/routing-v2 --seed 0 --live --json

# Resume annotation, change the reflection model, or inspect completed results
superqode harness tune --resume .superqode/tuning/<run>

# Resolve a proposal from a script; experimental is required below verification threshold
superqode harness tune --resume .superqode/tuning/<run> --accept --experimental --json
superqode harness tune --resume .superqode/tuning/<run> --reject --json
```

### Demo the active-learning loop

The checked-in `examples/tune/factory-route-active.csv` contains 35 development
and 35 reserved routing inputs with blank labels. Configure the Jev credential
and a reflection provider, run the active-learning command above, and confirm
pool evaluation. The first round presents five development cards and one
randomly sampled sealed card. The card heading identifies uncertain, random
audit, and sealed selections.

Label the six examples, optionally explain important boundaries, and start the
GEPA experiment. The result screen shows the sealed comparison and exact
question-pack diff. Accepting the first small run records an experimental
version; rejecting it keeps the current pack. Choosing to decide later leaves
the proposal intact for `--resume`. Resume again after accepting or rejecting
to acquire the next batch. Rejected rounds reuse cached pool predictions;
accepted rounds score the remaining pool against the newly accepted pack.

The active demo does not become verified after one round. Verification still
requires at least 30 reviewed development examples, 30 reviewed sealed examples,
an improved sealed score, no individual regression, and no evaluation errors.
The file IDs retain their intended route prefix to make live demonstrations
repeatable; the ID is not sent to Jev.

Input rows use `state`, `label`, and optional `id`, `rationale`, `group`, and
`split` fields. `--input` and `--label` map other column names. Use `group` to
keep related tickets/session examples together. Explicit splits are `train`,
`validation`, and `test`; existing `held-in`/`held-out` decision eval files are
also supported. Otherwise Tune partitions examples deterministically before
annotation. Duplicate inputs are rejected, and test examples never enter GEPA.

An experiment preserves output labels, schema, model configuration and
confidence policy. It writes candidate packs, harnesses, diffs, evaluation
evidence and reports under `.superqode/tuning`. Active sessions use versioned
candidate files, keep each round's GEPA output and evaluation evidence under
`rounds/round-NNNN`, and record accept/reject history in `run.json`. A proposal
can be accepted, rejected, or left pending and resumed later. Accepted
candidates seed the next round; rejected candidates leave the current pack
unchanged and reuse its cached pool predictions.
The comparison counts abstentions and errors separately, and checks for
regressions against the baseline. Small runs (fewer than 30 optimizer-visible
development examples or 30 test examples) are marked as pilots and cannot
qualify for adoption; larger runs
still require representative data and human review. **Use this version** opens
a standalone decision session. Active sessions may explicitly accept a small
candidate as **experimental**; only a candidate that passes the evidence gate is
marked **verified**. Acceptance never changes an active coding-session route.

The reflection spend limit is checked between model calls and excludes Jev
usage. The final baseline/candidate test calls are additional to `--max-evals`;
both allowances are displayed before starting. Inputs go to Jev; development
examples and rationales also go to the reflection provider. Existing state
redaction applies, but example files should not contain secrets.

Stop saves completed evidence. Annotation and pending candidate decisions can
be resumed; an interrupted optimization requires a new experiment and budget,
avoiding silent renewed spend. Production-call capture, new-question discovery,
Noul/Score tuning, and automatic adoption into permission or revision loops are
not included.

