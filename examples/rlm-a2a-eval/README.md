# RLM/A2A comparison pack

`tasks.json` defines three small tasks, expected evidence, comparison conditions,
and required measurements. Run with the same root model, revision, task inputs,
budgets and acceptance gates across conditions. For the long-log task, repeat
`source` as directed and append `selected`. For the migration task, use the stated
local gate to reject the broken implementation. Monty must hand verification to
a configured executor or report that verification is unavailable.

Start with the offline contract/failure suite; it invokes no paid models:

```bash
.venv/bin/python -m pytest tests/rlm/test_rlm_a2a_delegation.py \
  tests/test_a2a_hosted_credits.py tests/rlm/test_rlm_monty_kernel.py \
  tests/rlm/test_rlm_sandboxed_kernel.py -q
```

Those checks exercise actual host and Monty kernels, Docker's portable protocol
surface, independent A2A wire fixtures, actual inbound SDK requests, concurrent
admission, lost acknowledgments, restart, timeouts, retained inboxes and quotas.
Real Docker boundary checks are in `tests/rlm/test_rlm_docker_kernel.py` and skip
when no daemon is available. They are a required pre-release check on a Docker host.

Model evaluations require configured user-owned routes and explicit allowances.
Collect the listed metrics for each task/condition/profile; retain the raw events
and exported bundle digests. Separate cold and warm workers. Repeat model trials
and report variation, failed gates and unknown spend, including unsuccessful
runs. Compare local and loopback A2A with the exact same specialist first, so
specialist tools/data are not mistaken for a benefit from transport itself.

The deterministic tests establish correctness and bounded context export. They
are not evidence of answer-quality improvements, production cost savings or a
new default profile. Automatic routing remains disabled until workload results
justify it. Pi Durable findings remain exploratory and do not replace RLM or
WorkOrders.
