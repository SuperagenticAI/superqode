# Native RLM profile coding pilot

Run the offline execution smoke test without provider calls:

```bash
python -m superqode.rlm.evaluation \
  --tasks examples/rlm-profile-eval/tasks.json \
  --output /tmp/rlm-profile-smoke --repetitions 2
```

Use an empty output directory. Each attempt gets a fresh workspace and an
independent grader whose source is supplied externally. Modified code is
graded inside the selected execution boundary, including Docker; it is never
imported on the host for a Docker attempt. Grader processes have bounded output
and process-group deadlines. Outputs include
`attempts.jsonl`, `scorecard.json`, session logs and a shared inference ledger.
Attempts record the task digest, profile settings, provider/model, usage and time.

A live pilot requires explicit model selection and reported-spend limits:

```bash
python -m superqode.rlm.evaluation \
  --tasks examples/rlm-profile-eval/tasks.json \
  --output /tmp/rlm-profile-live --live \
  --provider YOUR_PROVIDER --model YOUR_MODEL \
  --max-cost-usd 5 --max-calls 100 --repetitions 2 \
  --profiles python hybrid selective hybrid-selective --sandbox docker
```

The provider must be configured in the environment used to run SuperQode. Provider
credentials remain outside Docker. The Docker image must have the dependencies
needed by the fixture. Host Python+Bash requires a POSIX host with Bash.

A USD threshold stops subsequent requests after provider-reported charges. The
current request may exceed it; this is not an absolute provider billing cap.
Missing prices stop the live pilot and remain unknown in the scorecard. A2A is
not enabled by this runner.

The 12 bundled tasks exercise small single-file Python bug fixes. Scripted edits
are supplied solely for the offline smoke test. Offline passes do not measure
model quality or cost. Live results are exploratory; add representative repository
tasks and repeated measurements before promoting an experimental profile.
