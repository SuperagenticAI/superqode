# Optional A2A routing inside native RLM

Native RLM keeps exactly one model tool, `python`. Repository context stays in
`context`; Python selects and chunks it, `llm_query` performs bounded semantic
analysis, and `rlm.run` starts local child sessions. The additional `a2a`
namespace delegates selected evidence to an explicitly configured remote agent.
A2A is off by default. Installing a key never enables a route or a paid fallback.

## Set up from the TUI

In `:connect`, choose **Connect a harness with your model**, then **RLM**.
The RLM options offer **Use RLM on host**, **Use RLM with Docker**,
**Use RLM with Monty**, and **Configure optional A2A**. The execution choices
continue to the normal model connection flow with A2A disabled, branching an
existing session so its worker cannot retain a different sandbox. Optional A2A
opens the setup screen using the current native RLM sandbox, or host when no
RLM profile is selected. Back returns to the RLM options without enabling a
route. Choose the desired RLM sandbox before adding routing to that profile.

Open `:hub`, select a native RLM harness and choose **Optional A2A**, or switch
to RLM and run `:rlm a2a`. The setup screen provides separate controls for A2A
routing and paid hosted peers, the root credit allowance, task and concurrency
limits, and a peer editor. Enter the agent URL, alias, description, skill, key
environment variable name and service tariff. Choose **Add / update peer** to
retain the peer in the profile. The screen reports whether the referenced key
is set without showing or storing its value.

**Save profile** writes a new YAML file under `.superqode/harnesses` in the
working project. **Start new session** saves the profile and branches the
current session into a new RLM root, or selects the profile before the first
connection. The sandbox and local recursion settings remain those of the
selected harness. A running root keeps its original policy; its policy appears
separately from the editable profile so saving cannot look like a live change.
Wait for an active turn to finish before starting the new session.

Set credential environment variables before launching SuperQode. Paid routing
requires both explicit opt-ins, a positive root allowance, a peer tariff and
skill, and a key. Saving a profile is possible before the key is installed;
starting an enabled credentialed route requires its key to be present.

The harness switch summary displays A2A and paid-route status. Use the screen's
**Tasks** and **Usage** buttons, or `:rlm routing`, `:rlm peers`,
`:rlm delegations` and `:rlm usage`, to inspect worker policy and retained work.
Opening setup does not start a model call or restart a worker.

## Configure a route

Start from the [example spec](https://github.com/SuperagenticAI/superqode/blob/main/examples/harnesses/rlm-a2a.yaml), or add this
under `runtime.config` in a native RLM HarnessSpec. The same routing
configuration works with host, Docker, and Monty profiles.

```yaml
a2a:
  enabled: true
  hosted_enabled: false
  max_tasks: 4
  max_parallel: 1
  max_payload_bytes: 128000
  max_result_bytes: 1000000
  deadline_seconds: 300
  peers:
    - name: reviewer
      url: http://127.0.0.1:8000
      description: Review selected source and return findings with file locations.
      credential_env: REVIEWER_A2A_KEY
      skill: superqode-harness
```

Set the named environment variable on the SuperQode host. Leave `credential_env`
out for an anonymous user-owned peer. Credentials are resolved by the host;
Docker and Monty receive opaque local handles, not keys. Configurations reject
inline token fields and URLs containing credentials or query strings. Credentialed
routes reject redirects and agent cards that retarget the configured origin.
Bounded peer transport requests uncompressed responses and refuses compressed
bodies before consumption to avoid decompression bypassing the byte allowance.

To route to a SuperQode hosted specialist, explicitly enable `hosted_enabled`,
set a positive `max_hosted_credits`, and configure that peer with `hosted: true`,
its `credential_env`, `skill`, and positive integer `credits` tariff. The remote
server still checks the customer account independently. The client tariff is an
admission allowance; it is not a provider-dollar or token meter. Configure it to
match the service tariff. Our hosted server also checks the caller's versioned
credit ceiling and refuses a higher tariff before reserving or executing work;
other peers may ignore this metadata. Third-party/BYOK charges remain the user's responsibility.

## Select context, delegate, and collect

```python
selected = context.select('src/auth*.py')
bundle = [{'path': c.path, 'start': c.start, 'end': c.end, 'text': c.text}
          for c in selected.chunk(size=12000)]
review = a2a.start(peer='reviewer', task='Audit these authentication paths',
                   context=bundle, request_id='auth-audit-v1', required=True)
review.wait(timeout=20)
review.status()
findings = review.read(size=4000)
```

`a2a.peers()` lists allowed capabilities; `a2a.tasks()` lists this calling
session's tasks. Handles offer `status`, `poll`, `wait`, `read`, `summary`,
`reply`, `cancel`, and `follow_up`. `a2a.handle(id)` reconnects a saved handle
through an ownership check. Large responses stay in host storage; reads return
bounded slices. Returned file URLs are references and are never fetched implicitly.

A direct A2A Message completes without inventing a remote task ID. Tasks preserve
input-required and auth-required states. Use `reply(text)` for input-required work
and `follow_up(task, request_id=...)` for new work in a terminal conversation.
A wait timeout leaves work running. Cancellation records a request and the peer's
actual response; a cancellation refusal does not become a canceled task.

Required remote work and active local children block root completion. Explicit
`required=False` work remains visible in the final evidence. Remote text and
patches are unverified evidence. Apply changes locally and use the existing
completion gates and WorkOrder acceptance path for verification. Monty has no
shell or repository writes; choose host or Docker when tests or edits are needed.

## Recovery and inspection

Admission and credit reservations commit before sending. Reusing a stable
`request_id` for identical work returns its existing handle; changing its input
fails. Known remote task IDs recover through GetTask. A send with a lost
acknowledgment stays `unknown` and is never automatically replayed. Standard A2A
message IDs do not promise exactly-once execution. Polling authoritative task
snapshots avoids duplicating streamed artifact chunks on reconnection.

The resident root tracks tasks while the TUI is detached, including tasks owned
by child sessions. Restarting retains root task and credit allowances. Remote
usage is displayed as unknown unless accounting can establish it; unknown is
never reported as zero.

```text
:rlm peers
:rlm delegations
:rlm reconcile <local-handle> <verified-remote-task-id> <reason>
```

Reconciliation attaches an externally verified ID and reads the task; it never
resubmits. Do not reconcile by guessing a remote ID. Outbound state and events
live beside the session in `.delegations.sqlite3`; semantic call admission is
shared across root/child processes in `.delegations.subcalls.sqlite3`.

## Retained local inboxes

```python
rlm.message(rlm.parent_id(), 'Findings are ready', delivery_id='findings-v1')
inbox = rlm.inbox()
rlm.ack_inbox(inbox[0]['id'])
continuation = rlm.follow_up(completed_child, 'Check the follow-up question')
```

Inbox delivery IDs are durable and idempotent within a recursive root. Reading
does not consume a message; acknowledge after handling it. Parent, child, and
sibling addresses share that root; other roots cannot access them. Delivery
alone never wakes a model or adds an inference charge. Explicit `follow_up`
admits a new child run using the retained conversation, preserving the original
run's terminal record. Live `send` and `steer` keep their existing behavior.
The TUI also provides `:rlm inbox`, `:rlm message`, and `:rlm follow-up`.

## Monty limits

Install `superqode[monty]` and choose the Monty profile explicitly. Its restricted
interpreter can select context and invoke the host's allowed `llm_query`, local
child, and A2A bridges. VM network access remains unavailable; explicit A2A
configuration grants a separate host capability.

`monty_max_workers`, `monty_memory_bytes`, `monty_recursion_depth`,
`monty_suspensions`, `python_timeout`, `max_output_chars`, and
`max_checkpoint_bytes` bound resources. Feed, turn, and sleep limits are applied
at checkout. Timeouts revoke callback admission and discard the checkout.
Successful feeds checkpoint before returning and restore automatically in a
replacement worker. Completed child workers release their checkouts and pools.
Checkpoints are bounded, digested, and pinned to the Python API and actual worker
binary; restore reapplies the current host capabilities and rejects changed VM
resource limits, because Monty loads those limits from the snapshot. Only trusted host checkpoint
references should enter restore. Snapshots are never accepted through A2A.

Monty memory accounting is not a process RSS limit, and inference/remote waits
have separate budgets. Semantic `token_budget` stops admission after observed
usage reaches its allowance; concurrent in-flight calls can overshoot it. Call
counts and concurrency are root-wide. Unknown remote work can continue after a
local deadline, and its reservation stays visible for reconciliation.

## Hosted task credits

Keep the public catalogue/shortlist service for free users. A paid harness pilot
requires a signing secret, a durable authoritative credit database, explicit
skill grants, and a deliberately bounded specialist HarnessSpec. The native RLM
factory requires an isolated read-only spec with shell disabled; it turns off
recursion and outbound A2A, caps semantic calls at 16, concurrency at two, and
prompt/response sizes at 32,000/4,000 characters. Existing lower limits stay in
force. An embedded custom controller must provide its own bounded executor.

```bash
superqode a2a-keys credits --store credits.sqlite3 grant customer-1 \
  --credits 10 --skill superqode-harness --days 30 --max-parallel 1
superqode a2a-keys issue customer-1 --tier standard --days 30
superqode serve a2a --spec reviewer.yaml --paid-harness \
  --credit-store credits.sqlite3 --task-credits 1
superqode a2a-keys credits --store credits.sqlite3 show customer-1
```

Keys authenticate; grants authorize skills and spending. Anonymous callers and
unentitled trial keys cannot run the paid skill. A trial account can receive an
explicit finite grant. Signed `operator` tier labels cannot bypass customer
limits. Paid-mode shortlist interpretation uses the free deterministic parser.

Reservations and settlement are atomic and survive restart; status/reconnect
never charges again. The bounded task tariff is charged after execution, even
if the task reports failure. A process crash retains its reservation. After
checking the actual outcome, an operator can settle it once with an audit reason:

```bash
superqode a2a-keys credits --store credits.sqlite3 reconcile customer-1 TASK_ID \
  --charged 0 --reason 'Peer confirmed work never started'
```

All serving processes must use the same authoritative database. Local SQLite
coordinates processes on one durable host/storage installation; unrelated
replicas with separate files do not share balances. Multi-host deployments need
a central transactional ledger. Worker request deadlines, turn and payload caps
bound the pilot; task credits do not establish a dollar ceiling on arbitrary
provider or external work. Do not expose an unrestricted paid recursive root.

See the [evaluation pack](https://github.com/SuperagenticAI/superqode/blob/main/examples/rlm-a2a-eval/README.md) before changing
routing defaults. This feature does not establish measured model-cost savings
or superior answer quality on its own.

## Release checklist

The default installation needs no A2A configuration and continues local RLM
execution. Outbound delegation uses the core HTTP client; `superqode[a2a]` is
required for hosting the optional A2A service. `superqode[monty]` is required
only for a Monty sandbox. Docker needs its CLI, a running daemon and the
configured Python image; host execution needs neither optional sandbox.

Before publishing:

1. Choose an unused release version, move the Unreleased notes into its release
   section, and update `pyproject.toml`, `src/superqode/__init__.py`, `uv.lock`
   and `install/acp-registry/superqode/agent.json` together. Run
   `python scripts/check_release_metadata.py --tag vVERSION`.
2. Run the native RLM, A2A, WorkOrder evidence and mounted TUI contracts with
   the `dev`, `a2a` and `monty` extras installed. Run real Docker checks with a
   working daemon. The publish workflow now requires these contracts and
   Docker availability before publishing the package.
3. Build and inspect the wheel and source distribution. Run lint, formatting
   and public documentation checks, and verify the published Agent Card through
   the existing release gate.
4. For a hosted paid launch, configure the signing secret
   `SUPERQODE_A2A_KEY_SECRET`, durable task and credit database paths, an isolated
   read-only specialist spec, and a model route. Grant credits and skills, issue
   a customer key, and match the client tariff to `--task-credits`. Verify an
   authorized task, an unentitled refusal, reconnect and settlement against the
   deployed service before distributing keys. Use one authoritative credit
   database for all workers on that deployment.
5. Check the TUI using a fresh session: routing off, paid routing off, a
   user-owned peer, a hosted peer with a missing key, a finite paid allowance,
   and Tasks/Usage after a completed or interrupted delegation.

No server credentials or production entitlements are created by installing
this release. Keep routing opt-in while measuring the evaluation pack's cost,
latency and task-quality outcomes.

## Cloud Run rollout boundary

The client and TUI release does not require enabling a new skill on the public
A2A service. The repository's `Dockerfile` serves the shortlist only and uses
`--no-task-store`; `cloudbuild.yaml` updates `superqode-a2a` in `europe-west1`.
A read-only check on 2026-10-04 confirmed that the live endpoint's Agent Card
matches the checked-in catalogue card. This does not verify private Cloud Run
settings or a deployed paid execution path.

The implemented credit ledger, harness session store and default durable task
store use local SQLite. That supports a pilot on one durable host. Cloud Run's
local filesystem is per-instance and disappears when the instance stops, so
those files cannot serve as its production account or recovery database.
Mounting a Cloud Storage bucket does not solve this: Cloud Storage FUSE lacks
file locking and concurrent writes can overwrite each other. See Google's
[container contract](https://docs.cloud.google.com/run/docs/container-contract)
and [volume limitations](https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts).

Before offering our paid execution skill on Cloud Run:

- Implement and test shared transactional storage for credit reservations,
  entitlements, task state and session ownership. Cloud SQL PostgreSQL is one
  supported deployment option; the current SQLite ledger has no PostgreSQL
  adapter. Store bounded artifacts and checkpoints separately in object storage.
- Persist dispatch and execution ownership so an acknowledged task survives
  worker termination. Cloud Tasks with a private worker or Cloud Run Jobs can
  provide managed dispatch, but retries need durable admission and claim checks;
  they do not establish exactly-once model execution. Retain unknown outcomes
  for reconciliation rather than automatically spending again.
- Supply a bounded read-only specialist spec and its runtime dependency in a
  dedicated worker image. Monty requires the `monty` extra; the current public
  image installs only `a2a`. Validate the actual runtime inside that image.
- Configure provider credentials and `SUPERQODE_A2A_KEY_SECRET` through Secret
  Manager, explicit customer grants, the task tariff, IAM, task deadlines and
  concurrency limits. A remote bind also needs `--expose-harness` and `--spec`;
  `--paid-harness` alone does not expose the execution skill.
- Test refusal, cancellation, cross-instance GetTask, restart/rollout recovery,
  retained unknown execution, and settlement against staging before advertising
  the paid skill or distributing keys for it.

Returning immediately and continuing work in a process is insufficient for a
durable Cloud Run task. Request-based billing limits CPU outside requests, and
even instances with continuously allocated CPU can be terminated. See Google's
[background execution guidance](https://docs.cloud.google.com/run/docs/configuring/billing-settings),
[Cloud Tasks integration](https://docs.cloud.google.com/run/docs/triggering/using-tasks)
and [duplicate-delivery guidance](https://docs.cloud.google.com/tasks/docs/common-pitfalls).

Keep the public shortlist deployment while developing the paid worker path.
Deploying the client alone does not turn that catalogue endpoint into a remote
RLM execution service.
