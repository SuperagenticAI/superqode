# RLM profiles, history and budgets

The native Python RLM remains the default. It keeps repository context as data,
uses a persistent Python namespace and supports semantic queries and recursive
coding children. Version 2.6 adds experimental profiles without replacing that
workflow. No model quality or cost improvement has been established yet.

## Choose a profile

In the TUI, open `:connect`, choose **Connect a harness with your model**, then
**RLM**. Existing host, Docker, Monty and optional A2A choices remain available.
New choices include Python+Bash, Python+Bash in Docker, selective observations
and **RLM settings**. You can also open `:rlm settings` directly.

Settings select the tool surface, execution boundary, observation strategy and
inference limits. **Save profile** writes a project HarnessSpec. **Start new session**
branches into a new session with that spec and continues model connection.
Changing these settings requires a new session; an active worker retains its
original policy. Existing A2A settings are preserved when saving a profile.

Direct connection shortcuts:

```text
:connect rlm-host
:connect rlm-docker
:connect rlm-monty
:connect rlm-hybrid
:connect rlm-hybrid-docker
:connect rlm-selective
:connect rlm-settings
:connect rlm-a2a
```

Built-in presets:

| Preset | Model tools | Boundary | Observations |
| --- | --- | --- | --- |
| `rlm` | Python | Host | Transcript |
| `rlm-docker` | Python | Docker | Transcript |
| `rlm-monty` | Python | Monty | Transcript |
| `rlm-hybrid` | Python, Bash | Host | Transcript |
| `rlm-hybrid-docker` | Python, Bash | Docker | Transcript |
| `rlm-selective` | Python | Host | Selective |

Python+Bash needs POSIX process groups on the host. On Windows, select Docker.
Bash must be installed in the selected environment. Monty remains a read-only
research profile with no shell, writes or coding children. It supports history
reads, context exploration and semantic queries. A combined Monty and Docker
execution profile is future work.

## Harness configuration

These fields belong under a native RLM HarnessSpec's `runtime.config`:

```yaml
runtime:
  backend: rlm
  config:
    sandbox: docker
    allow_network: false
    tool_surface: python-bash
    observations: selective
    recent_messages: 12
    observation_chars: 2000
    budget:
      max_calls: 100
      max_tokens: 200000
      max_cost_usd: 5.0
```

Limits of zero mean unlimited. These limits apply to the complete session
family: root inference, recursive coding children and semantic queries. Existing
semantic-subcall quotas remain additional limits. The shared allowance persists
across worker restarts and explicit child continuations.

The call allowance is checked atomically before inference. Token and USD limits
are thresholds over provider-reported usage, not absolute billing caps: the
current request can cross a threshold. With either threshold enabled, concurrent
inference waits for a live request to settle before admission. An interrupted
request requires explicit usage reconciliation. Missing token or price
reports block further calls under the corresponding threshold. Known cost and
unknown reports are shown separately, including in run statistics.

A2A stays off by default. It is selected separately through `:rlm a2a`, with
explicit peers and key environment references. Hosted credits have their own
admission policy and are not converted into model USD. Remote token and USD
usage remains unknown. This release requires no Cloud Run changes for native
profiles; hosted paid execution still depends on the service's existing setup.

## History and selective observations

The persistent Python namespace offers branch-scoped history:

```python
matches = history.search('failing assertion', limit=10)
page = history.read(matches[0]['id'], start=0, size=4000)
history.stats()
```

History includes original tool output and pre-compaction messages from the
current branch. Handles from another branch cannot be read. Selective mode
projects a provider-facing copy: large tool results become compact receipts and
bounded previews, and older assistant responses become history references. It
preserves user instructions, roles and tool-call/result identities. Full session
records remain intact and readable through history handles. This is an
experimental retrieval strategy; reducing visible output can also hurt quality.

## Durable Bash jobs

Bash and Python share the same workspace, job ledger and sandbox. Python can
manage a job without placing all its output into the conversation:

```python
job = commands.run('python3 -m pytest -q', request_id='check-auth', timeout=120)
job.status()
job.wait(timeout=5)
job.read(stream='stdout', start=0, size=4000)
```

The Bash tool exposes run/start, status, read, wait, cancel and list. A command
returns a compact receipt; read retrieves a bounded page. Captured output has a
per-stream bound and reports omitted characters. Reusing a request ID with the
same inputs returns the existing job; changed inputs are refused. Timeouts and
cancellation stop the process group, including descendants.

Mutating commands serialize across the family. Explicit `read_only` jobs can
run together; this is a caller declaration, not filesystem isolation. Convenience
workspace writes also wait for a clear command lease. Raw Python filesystem or
subprocess operations and the legacy `shell.run` bypass this coordination.
Host Python is unrestricted. Use Docker for a boundary; these APIs are guardrails.

The broker filters credential-named environment variables. Host Python can
still access the SuperQode process environment directly. Docker keeps provider
credentials and inference on the host, and Monty exposes neither the filesystem
nor subprocesses. An interrupted job retains an unknown outcome and a workspace
lease; SuperQode never automatically retries its side effects.

## Inspect and recover from the TUI

```text
:rlm profile
:rlm budget
:rlm budget unresolved [offset]
:rlm usage
:rlm history failing assertion
:rlm history read <id> [start] [size]
:rlm jobs
:rlm job status <id>
:rlm job read <id> stdout [start] [size]
:rlm job cancel <id>
```

Operational inspection remains available during a model turn. Outstanding or
unknown jobs prevent acceptance until they are settled. Inspect partial writes
before explicitly recording a verified interrupted outcome:

```text
:rlm job reconcile <id> <returncode> <verification reason>
:rlm budget reconcile <call-id> <tokens> <USD> <verification reason>
```

A surviving command must be cancelled first. Budget reconciliation refuses a
live inference request; stop it and verify its provider usage before recording
values. Reconciliation is an audit record, not a retry or a billing refund.

## Compare profiles before claiming savings

The [coding pilot example](https://github.com/SuperagenticAI/superqode/tree/main/examples/rlm-profile-eval)
compares profiles using fresh workspaces, fixed model selection, alternating
profile order, independent graders inside the selected execution boundary and per-attempt family usage. Offline mode
uses scripted edits and only checks execution plumbing. The bundled tasks are
small bug fixes; broader repository tasks and repeated live measurements are
needed before claiming a quality or cost advantage.

Continual harness refinement, speculative execution and persistent agency are
outside this release.
