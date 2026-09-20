# Free SystemOne Tune demo data

Original synthetic routing tickets for the `factory_route` pack.
No third-party corpus. Free to use in demos and tests.

- `factory-route-free.csv`: 70 labeled examples (35 development / 35 test)
- `factory-route-active.csv`: the same 70 inputs with blank labels and
  rationales, for the uncertainty-ranked, multi-round workflow
- Tune deterministically reserves 8 of the 35 development rows for validation,
  leaving 27 search rows. Both subsets are optimizer-visible; the 35 test rows
  remain sealed until the final comparison.
- Columns: `id`, `state`, `label`, `split`, `rationale`
- Labels: `private`, `local`, `cheap`, `best`, `review`, `long-context`, `no-subscription`

## Active-learning demo

From the repository root, configure Jev and one reflection provider, then run:

```sh
export TYPESAFE_API_KEY="..."
export OPENAI_API_KEY="..." # or Anthropic, Gemini, or another LiteLLM provider

superqode harness tune --setup
superqode harness tune \
  --data examples/tune/factory-route-active.csv \
  --batch-size 5 \
  --max-evals 30 \
  --max-reflection-cost 0.50
```

The first round scores 35 development inputs, then asks for five development
judgments and one randomly reserved test judgment. Each card says whether it
was selected for uncertainty, random audit, or sealed evaluation. Add an
optional rationale when a routing boundary matters.

After GEPA finishes, review the metric change and question diff. Choose
`accept` to keep the proposal as an experimental version, `reject` to keep the
current pack, or `later` to leave the decision pending. The terminal prints the
saved run directory.

Resume the next round with:

```sh
superqode harness tune --resume .superqode/tuning/<run-id>
```

For a non-interactive pending decision:

```sh
superqode harness tune --resume .superqode/tuning/<run-id> \
  --accept --experimental --json

superqode harness tune --resume .superqode/tuning/<run-id> \
  --reject --json
```

This demo is intentionally a pilot. A candidate becomes verified only after it
passes the regression gate with at least 30 reviewed development and 30 sealed
test examples.
