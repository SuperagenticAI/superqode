# Tool composition and WorkOrder recovery

SuperQode reuses its existing Monty interpreter, MCP client manager, and WorkOrder SQLite store. These additions do not require LangGraph, a second interpreter, or a cloud runtime.

## Tool composition

Install the existing optional `monty` extra and enable the host-tool bridge:

```bash
uv sync --extra monty
SUPERQODE_RLM_TOOLS=1 superqode --harness workbench
```

`python_repl` then provides four functions:

| Function | Behaviour |
| --- | --- |
| `tool_search(query, limit=5)` | Search registered native tools using existing discovery. Return selected schemas on demand. |
| `tool_call(name, arguments)` | Dispatch through the same hooks, argument validation, permissions, contextual policy, and result limits as a direct call. |
| `tool_parallel(calls)` | Execute up to eight independent calls to trusted native read-only tools. Remote MCP annotations do not authorize parallel execution. |
| `tool_evidence(invocation_id)` | Read retained output for a child of the current composition. Report missing or expired evidence explicitly. |

Use `tool_call("mcp_search", ...)` to discover remote capabilities and `tool_call("mcp_execute", {"server": ..., "tool": ..., "arguments": ...})` to invoke them when the selected execution profile enables MCP. Structured MCP results are returned as `structured_content`. Native results retain their `output` string. The bridge cannot enable a capability disabled by the execution profile.

```python
calls = [
    {"name": "read_file", "arguments": {"path": "README.md"}},
    {"name": "read_file", "arguments": {"path": "pyproject.toml"}},
]
results = tool_parallel(calls)
[(r["invocation_id"], len(r["output"])) for r in results if r["success"]]
```

The bridge limits one program to 32 child calls, eight parallel calls, and at most 30 seconds. Monty memory is limited to 1-128 MiB. Text and structured result fields are each bounded to 64,000 bytes; oversized structured results are omitted with an explicit flag. Nested orchestration tools are unavailable. Cancelling the program cancels owned child tasks; cancellation cannot undo a completed external effect.

Composition is off by default. With the flag unset, no host-function guidance is appended to the tool description. The flag extends the standalone tool in the native agent loop. It does not change the resident RLM kernel or its existing read-only Monty research profile.

## PiPy programs

PiPy has a separate opt-in `python_program` tool. Install the existing Monty
extra and enable it in the selected harness spec:

```yaml
name: pipy-programs
inherits: pipy
runtime:
  config:
    monty:
      enabled: true
```

The model can compose its active read tools with `tool_search(query, limit=5)`
and `tool_call(name, arguments)`. Individual calls run sequentially;
`tool_parallel` batches trusted native reads as described below. The host validates
arguments, runs PiPy call/result hooks, revalidates extension replacements,
and applies current contextual policy. `bash`, `write`, `edit`, nested
orchestration, direct OS access and third-party imports are unavailable from
this tool. The existing native `python_repl` and resident RLM profile keep
their separate execution contracts.

```python
readme = tool_call("read", {"path": "README.md"})
project = tool_call("read", {"path": "pyproject.toml"})
{"readme_bytes": len(readme["output"]), "project_bytes": len(project["output"])}
```

Without a WorkOrder recovery scope, execution is temporary and the result
reports `checkpointed: false`. Inside a WorkOrder, a SQLite transaction stores
the suspended Monty interpreter and invocation intent together. Tool outcomes
are committed before supplying them to the interpreter. A restored program
receives committed results without repeating those calls. Unknown outcomes
retry only when the host capability explicitly permits replay; otherwise the
task requires reconciliation.

Checkpoints record code/capability fingerprints, workspace identity, the actual
Monty API version and worker binary hash. Changes block reuse. Current hooks
and call/result policy are checked against all retained calls before continuing
or returning a completed program. A changed result projection also blocks reuse.
Use a new WorkOrder after changing program inputs or the workspace; the pilot
does not migrate old checkpoints onto changed inputs or newer workers.

Task ownership and attempt checks fence old workers. Program revisions fence
two restored copies within the same attempt. Checkpoints remain private BLOBs
in the existing WorkOrder database, with SHA-256 integrity checks before load.
They must come from trusted local storage. Snapshot hashes do not authenticate
untrusted producers.

Limits are 32 host calls, 30 seconds per execution attempt, two seconds of
interpreter computation, 32 MiB of interpreter memory, and an 8 MiB checkpoint.
Host arguments and serialized results are bounded to 64,000 bytes. Retained
tool text, structured details and final program text are each capped at 8,000
bytes. Results identify truncated text, omitted structured details and omitted
images; image blocks are not passed into the Python program. WorkOrder time and
tool-call budgets also apply. Tool-call reservations count retries, including
an intent committed immediately before a crash.

### Explicit MCP capabilities

PiPy programs use the same shared MCP manager. In addition to server declarations,
the host must list each remote capability allowed inside a program:

```yaml
runtime:
  config:
    mcp_servers:
      project_docs:
        command: python
        args: ["docs_server.py"]
    monty:
      enabled: true
      mcp_tools:
        - server: project_docs
          tool: lookup
          read_only: true
          replay_safe: false
```

Use `tool_call("mcp_search", {"query": "lookup"})` to discover remote schemas,
then `tool_call("mcp_call", {"server": "project_docs", "tool": "lookup",
"arguments": {...}})`. Schema and connection checks still occur in the shared
MCP adapter. Server annotations alone do not authorize a program capability.
`read_only: true` is a host declaration, not proof about server behavior.
`replay_safe` defaults to false: a read can incur fees or other external effects.
Unknown MCP usage remains unknown. This pilot cannot reserve unknown MCP spend,
so WorkOrders with cost or token caps reject new MCP program calls before dispatch.

### Standalone WorkOrder execution

A saved program can also run as a complete PiPy WorkOrder task without requesting
an LLM response. Create an investigation WorkOrder, write a restricted Python
program to `inspect.py`, then run:

```bash
sq work create "Inspect project metadata" --repo . --harness pipy \
  --role investigator --max-attempts 5 --queue
sq work program-run WORK_ID --code inspect.py --program-id inspect --json
sq work programs WORK_ID --json
sq work invocations WORK_ID --json
```

The command leases one ready investigator or custom task, loads the selected PiPy spec, policy and
extensions, and enables only its declared native read tools plus configured MCP.
It renews ownership, observes cancellation, saves the program result before task
completion, and deduplicates usage by program identity. Repeating the same command
after a safe expired lease continues the program or reuses its final result.
Program completion returns the WorkOrder to its existing review/acceptance flow.

Model-driven coding WorkOrders retain their conservative whole-harness envelope
by default. PiPy can opt into a separate coding recovery driver with
`runtime.config.recovery.enabled: true`; see [PiPy recovery](pipy.md#opt-in-coding-workorder-recovery).
Monty checkpoints alone do not checkpoint LLM requests or shell processes.
Unknown unsafe outcomes still require reconciliation.

PiPy programs support `tool_parallel(calls)` for up to eight trusted native
read-only calls. Each child counts against program and WorkOrder call budgets;
MCP calls and write tools cannot enter these batches. `tool_search` uses shared
retrieval and includes explicitly admitted remote capabilities. Current remote
schemas are validated again when calls or retained results are prepared.

`store(key, value)` and `load(key)` provide branch-local JSON values. Writes
publish only after successful program completion. `store(key, None)` deletes a
key. Keys are limited to 256 bytes, values to 16,000 bytes, and the store and
pending writes to 32,000 bytes each. Recovery reconstructs committed program
state and checks current policy before publication.

Concurrent interpreter futures and filesystem write capabilities remain outside
this program integration. Process-exit
tests cover checkpoint publication, committed result injection, final result
reuse, unknown-effect reconciliation, cancellation, workspace/runtime drift,
ownership and budgets. They do not establish remote exactly-once behavior or
hardware power-loss guarantees.

## Child receipts and evidence

The parent tool result includes a `composition` receipt with child identities, start/end times, status, effective argument hashes, result hashes, byte counts, permission decisions, and reported usage when available. Harness runs also record `tool.composition` events. Unknown usage remains unknown.

Selected output is stored under `.superqode/composition-evidence/` with owner-only files. Retention is 24 hours, 64,000 bytes per result, 1 MiB per program, and at most 1,024 retained files. Cleanup occurs during subsequent evidence operations, rather than through a background service. Sensitive results can opt out; known environment secrets and common credential patterns are redacted. This is bounded redaction, not a guarantee of detecting every secret. Receipts identify unavailable, truncated, redacted, or expired evidence. The model-facing script result may remain small without concealing the child call history.

## Shared MCP in PiPy

PiPy accepts the same inline server declarations as other harnesses:

```yaml
name: pipy-with-integrations
inherits: pipy
runtime:
  config:
    mcp_servers:
      project_docs:
        command: python
        args: ["docs_server.py"]
```

Configured automatic connections start in the background. The model receives two stable schemas, `mcp_search` and `mcp_call`, independent of catalog size. Search returns selected schemas; calls resolve the named server and current tool schema. Server identities containing underscores remain distinct. The shared manager refreshes catalogs after list-change notifications, owns transport cleanup, validates arguments, and supports cancellation and timeouts.

`mcp_call` also accepts `kind: resource` or `kind: prompt`, with a resource URI or prompt name in `tool`. The current resource path returns the first resource content item; prompts render text. Tool results preserve typed MCP images and structured data. Other typed tool blocks are retained as JSON text rather than interpreted as new executable capabilities.

PiPy runs with process permissions. The hosting adapter enforces active contextual call/result policy, including on recovered results. PiPy still has no interactive approval flow or OS sandbox. Core and workbench retain their declared execution profiles; MCP support does not imply those profiles are interchangeable.

## Images and session records

PiPy preserves supported user images through the gateway. Images from tool results become attributed user attachments after the complete tool-result batch, matching the provider's text-only tool-message shape. Limits are four images per message and 4 MiB per image, with PNG, JPEG, GIF, and WebP MIME types. Known text-only models reject image input before sending a request. Unknown model capability still depends on the provider accepting the request.

The session reader supports tested version 3 context-edit, usage, system-message, and compaction checkpoint records. Context edits affect projected model context without rewriting history. Recorded tool names are restricted to implementations registered by the host. Session import does not load executable extension code or guarantee compatibility with future record types.

## OAuth identity

Native MCP manager credentials are scoped to the configured server ID and exact URL. Two accounts pointing at one endpoint do not share tokens automatically. Legacy URL-only credentials require explicit migration to a selected account or a new login; migration is available through `MCPAuthStorage.for_server(id).adopt_legacy_credentials(url)`. An interrupted migration may leave a `.migrating` file for manual inspection; it is not assigned to an account automatically.

OAuth authorization metadata is pinned for the pending flow. Issuer mismatches are rejected; advertised issuer-response support requires the callback issuer. Callback state is single-use and duplicate parameters are rejected. Refreshes are serialized with an OS-owned file lock, reload credentials after locking, and preserve omitted refresh tokens and scopes. Explicit scope step-up keeps existing grants. Headless token lookup can refresh but does not open a browser.

## Recovery contract

WorkOrders remain the unit of scheduled work. Before executing an owned harness task, SuperQode commits an invocation identity, input/configuration fingerprint, attempt, owner, and intent. It commits the outcome before task completion. Nested core tools, PiPy tools, and native MCP calls use the same invocation contract when a recovery scope is active.

| Boundary | Behaviour |
| --- | --- |
| Committed matching outcome | Reuse the outcome under current policy and workspace checks. |
| Expired lease with no uncertain unsafe invocation | Existing scheduler recovery may reclaim work within its attempt limit. |
| Explicitly replay-safe invocation | Retry only when both persisted and current descriptors allow it. Read-only alone does not imply replay safety. |
| Unknown unsafe outcome | Block the task and require reconciliation. Do not automatically repeat a remote side effect or paid call. |
| Stale owner or attempt | Reject completion, invocation commits, and heartbeats on the attempt-aware paths. |
| Changed inputs, configuration, or committed workspace | Require reconciliation. |
| Surviving resident RLM worker | Existing worker reattachment remains available; this change does not journal each kernel operation. |
| External harness | Protect the whole task envelope; internal operations need runtime-specific evidence. |

SQLite uses WAL and full synchronization. Tests establish process-interruption behaviour on local storage. They do not establish cloud storage, hardware power-loss, exactly-once remote effects, or universal workspace restoration guarantees.

Workspace verification hashes the Git revision, relevant tracked/untracked file contents, modes, and symlink targets. It excludes ignored files and SuperQode's own state. Verification is bounded to 50,000 files and 256 MiB. It detects changes but does not reconstruct deleted files or recreate the environment. If an interrupted integration changes the workspace after the harness outcome commit, recovery conservatively requires reconciliation.

## Inspect and reconcile

```bash
sq work invocations WORK_ID --json
sq work invocations WORK_ID --task TASK_ID
sq work reconcile WORK_ID TASK_ID INVOCATION_ID \
  --actor operator --reason "Verified remote operation did not happen" --allow-retry
sq work resume WORK_ID
```

Stop the owning worker before reconciling. Use `--result verified-result.json` instead of `--allow-retry` when a verified outcome is available. The JSON must use that operation's saved result shape; a harness outcome also needs its verified `--workspace` fingerprint. Reconciliation records the actor and reason. Resuming a blocked task does not resolve an unknown side effect by itself. Neither reconciliation nor retry performs automatic rollback.

Unknown attempt usage is retained as unknown. Reused outcome accounting is deduplicated by invocation identity. Budget decisions still use the existing WorkOrder policy; this pilot does not add a provider-enforced spend reservation service.

## Evaluation checkpoints

```bash
superqode harness eval --spec harness.yaml --tasks tasks.yaml --live --json \
  --recovery-store .superqode/evaluation.sqlite3
```

Run the same command with the same configuration, dataset, and workspace to reuse committed cases. A changed configuration or dataset receives a new evaluation identity. An interrupted case with an unknown outcome requires reconciliation through its evaluation WorkOrder. Cases run sequentially within a variant's mutable workspace.

The regression suite kills a real process after 70 of 100 case commits. A fresh process reconstructs the run from SQLite, reuses those 70 results, and executes only the remaining 30. It also kills a process after a simulated external effect and confirms that recovery blocks rather than repeating the action.

## Measurements and promotion

`model.payload` events measure the content-free gateway request boundary: message and system bytes, tool-schema bytes/count/hash, and catalog version. Byte measurements are not provider token counts. Provider usage remains a separate reported value.

Deferred-catalog fixtures cover 0, 10, 100, and 1,000 unused tools and verify constant initial schema payloads. Benchmarks use fresh workspace copies and deterministic expected text or checks; a successful CLI exit without a correctness criterion is ungraded. Scorecards include all reported attempt costs per solved task and retain unknown spend explicitly.

A paid, pinned Pi-versus-SuperQode comparison has not been run for these changes. Composition remains opt-in and evaluation recovery remains a pilot until matched task success, cost, latency, and recovery evidence justify promotion.
