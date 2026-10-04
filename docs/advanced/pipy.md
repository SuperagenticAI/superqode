# PiPy

PiPy is a native SuperQode harness inspired by
[pi](https://github.com/earendil-works/pi). It follows the same architecture in
Python: an event-first agent loop, parallel tool execution, mid-run steering, an
append-only session tree, and a small tool surface.

It is opt in. `core` remains the default harness, and installing or upgrading
SuperQode changes nothing until you select PiPy.

## Select it

```bash
superqode --harness pipy
```

In the TUI, open `:connect` and select **PiPy**. The row is labelled
**Pi-inspired Pythonic version**. You can also address it directly:

```text
:connect harness-pipy
```

`:harness` lists it alongside the full catalogue. The aliases `pi` and
`pi-python` resolve to the same harness.

## Pure host permissions and contextual policy

PiPy executes tools with the permissions of the process that launched
SuperQode. It has no interactive approval flow or OS sandbox. The hosting
adapter enforces active contextual call/result policy, including when reusing
an outcome from a WorkOrder. Selecting PiPy does not grant approval or sandbox
support to the harness.

Use `core` or `workbench` when those execution controls are required:

```bash
superqode --harness core
```

The independent `superqode.pipy` library does not import the approval manager,
permission manager, or sandbox. Its hosting adapter supplies policy checks;
import-graph tests preserve the library boundary.

Configured integrations use SuperQode's shared MCP manager. PiPy exposes
`mcp_search` and `mcp_call` with deferred schemas, typed tool images and structured
results. See [tool composition and recovery](tool-composition-and-recovery.md)
for configuration and the capability limits.

Hosted PiPy can also expose an optional `python_program` tool by setting
`runtime.config.monty.enabled: true` in a harness spec and installing the
`monty` extra. Programs compose active native read tools and explicit MCP
capabilities using restricted Python. WorkOrder executions save a suspended
program before each host call and commit results before resuming it. See
[PiPy programs](tool-composition-and-recovery.md#pipy-programs) for activation,
checkpoint inspection and the standalone WorkOrder execution route.

## What PiPy takes from pi

| Area | Behaviour |
| --- | --- |
| Loop | Parallel tool execution by default, with per-tool sequential opt out. `tool_execution_end` in completion order, tool results in assistant order |
| Streaming | Tool progress reaches event subscribers while a tool is running; completed results enter the next model request |
| Tools | `read`, `bash`, `edit`, `write` by default; `grep`, `find` and `ls` selectable |
| Editing | `edit` takes an array of replacements, all matched against the original file, with fuzzy matching through smart quotes and Unicode dashes |
| Prompt | Tool list built from each tool's own snippet, deduplicated guidelines, project context, skills, working directory last |
| Sessions | Append-only JSONL tree with branch, resume, fork and compaction |
| Steering | Messages injected mid-run, and follow-ups that wait for the agent to settle |

The table is the tested behaviour. PiPy does not reproduce every pi extension,
provider, or session feature.

## Sessions

PiPy keeps its own session store, separate from every other harness:

```text
~/.superqode/pipy/sessions/--Users-you-your-repo--/<timestamp>_<id>.jsonl
```

One directory per working directory, one file per session. PiPy supports the
tested version 3 record formats, including context edits, usage entries and
system checkpoints. Original history remains intact when projecting context
edits. Future entry types and executable extension/tool implementations require
separate compatibility work; session import is not universal byte compatibility.

Sessions are append-only. Compaction, branching and renaming all add entries
rather than rewriting history, so navigating back to an earlier point is
lossless.

Each SuperQode session is mapped to the PiPy session it owns by a
`superqode-index.json` beside the session files, so a later turn reopens the
same session rather than starting a new one.

Set `SUPERQODE_PIPY_SESSION_DIR` to move the store, or `SUPERQODE_PIPY_DIR` to
move the whole PiPy root.

## Reading an existing pi repository

PiPy reads pi's project-level resources so an existing pi repository works
without changes:

- `.pi/skills/**/SKILL.md`
- `.pi/prompts/*.md`
- `AGENTS.md` or `CLAUDE.md`

Instructions load from the PiPy agent directory (`~/.superqode/pipy/`), then
ancestor directories from filesystem root to the working directory. Within each
directory, `AGENTS.override.md` takes precedence over `AGENTS.md` and `CLAUDE.md`.
An override affects only that directory. Canonical paths prevent duplicate loads.

`SYSTEM.md` replaces the default system prompt and `APPEND_SYSTEM.md` adds to it.
For each filename, PiPy selects the first nonempty readable file from `.pi/`,
`.superqode/pipy/` in the working directory, then the PiPy agent directory.
Explicit SDK prompts take precedence, including an empty append string. Resource
reload rereads these files. PiPy does not implicitly load the real pi user's
global instructions or execute TypeScript extensions.

SDK callers can set `include_context_files=False` and
`include_system_prompt_files=False`. Hosted HarnessSpecs expose these as
`runtime.config.context_files: false` and `system_prompt_files: false`; explicit
prompts use `system_prompt` and `append_system_prompt`.

PiPy stores session metadata under `~/.superqode/pipy/`. It never writes into `~/.pi/`, so a
real pi installation cannot be affected.

## Switching harnesses

Each harness keeps its own session store. Switching to PiPy starts or resumes a
PiPy session; switching away starts or resumes that harness's own session. The
conversation does not transfer, and neither store is modified by the other.

That is a session boundary, not a fault. Fork a PiPy session if you want to
explore an alternative without disturbing the original.

These are typed as `:pipy <command>`, aliased `:pi`. `:pipy help` lists them:

| Command | Effect |
| --- | --- |
| `:pipy compact` | Summarise older context and keep working |
| `:pipy tree` | Move to another point in the session tree, summarising the branch left behind |
| `:pipy fork` | Copy the current branch into a new session, leaving the source untouched |
| `:pipy resume` | List prior sessions for this directory |
| `:pipy resume <n or path>` | Reopen that PiPy session into the live chat and register it in `:sessions` |
| `:pipy new` | Start a fresh session |
| `:pipy name` | Name the current session |
| `:pipy model` | Switch the model for the next turn |
| `:pipy session` | Show the session id, path, tree leaf and stats |
| `:pipy export` | Render the current branch as Markdown |
| `:pipy skill` | Invoke a skill by name |
| `:pipy prompt` | Run a prompt template by name |

## Providers

PiPy runs through SuperQode's provider gateway, so every provider SuperQode
supports is available. Stop reasons, token usage and cost are carried through to
the session record.

Supported user and tool images pass through the provider gateway. Tool images
retain their source attribution. MIME, size and known model capability checks
run before dispatch; see [image limits](tool-composition-and-recovery.md#images-and-session-records).

## Extensions

SuperQode extensions apply to PiPy through the normal hook points: session
start, prompt submit, before and after a tool call, turn complete and stop. An
extension may block a tool call, which pi's own extensions can also do.

`PERMISSION_REQUEST` is deliberately not wired, because that hook point is the
approval stack PiPy omits.

## Relationship to Tau

[Hugging Face Tau](tau.md) is a separate optional integration and is unaffected
by PiPy. Tau remains selectable, keeps its own sessions and its own read-only
tool policy. PiPy takes no dependency on Tau.

## Attribution

PiPy is derived from pi, which is distributed under the MIT License, Copyright
(c) 2025 Mario Zechner. Modules ported from pi name the upstream file they came
from, and the full notice is in `NOTICE` at the repository root. PiPy is not
affiliated with or endorsed by the pi project.

## Shared MCP controls

Hosted PiPy resolves the same user and project JSON configuration as the native
MCP client. Inline `runtime.config.mcp_servers` declarations override file entries.
`mcp_search` discovers enabled servers on demand, including servers without
automatic connection. Automatic connection starts in the background.

Use `sq mcp list`, `sq mcp login SERVER`, `sq mcp logout SERVER`, and
`sq mcp reconnect SERVER` outside a session. In the TUI, use `:mcp list`,
`:mcp reload`, `:mcp login SERVER`, and `:mcp logout SERVER`. These controls use
shared transports and credentials; they are not model-callable administrative tools.
See [MCP configuration](../configuration/mcp-config.md).

## Opt-in coding WorkOrder recovery

Enable recovery in a PiPy HarnessSpec:

```yaml
runtime:
  backend: pipy
  config:
    recovery:
      enabled: true
```

Within an active single-step WorkOrder, PiPy records the starting session branch,
complete model responses and native tool outcomes before advancing. A retry
replays committed responses with their original tool-call IDs, checks the current
policy and committed workspace, and avoids repeating completed model or tool calls.
Recovery uses sequential tool execution. Ordinary interactive session resume is unchanged.

An interrupted model request or unsafe tool call with an unknown outcome requires
reconciliation. Recovery verifies the workspace; it does not restore deleted
files or reattach shell processes. New model requests with token or cost caps
are blocked until provider spend reservation is supported. This is an opt-in
process-recovery integration, not a power-loss or remote exactly-once guarantee.

## Python SDK examples

`examples/pipy/session.py` demonstrates session creation and events with an offline
provider by default. `examples/pipy/custom_tool.py` demonstrates a typed custom
tool and cancellation. Both use the independent `superqode.pipy` library.

### Typed Python tools

`create_typed_tool` derives a tool schema from a Pydantic model and passes a
validated model instance to an async executor. It runs through the existing
tool, event and WorkOrder recovery paths:

```python
from pydantic import BaseModel, ConfigDict, Field
from superqode.pipy import AgentToolResult, ToolContext, create_typed_tool

class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=10)

async def lookup(args: Lookup, context: ToolContext) -> AgentToolResult:
    context.check_cancelled()
    context.emit(AgentToolResult(content="Looking up records"))
    return AgentToolResult(content=f"Found {args.key}", details=args.model_dump())

tool = create_typed_tool("lookup", "Read records", Lookup, lookup, replay_safe=True)
```

Field and model validators run before executor code, including direct SDK calls.
An executor returns `AgentToolResult` to preserve images, usage, structured
details and termination hints. Replay safety defaults to false and must reflect
the executor's actual effects. Validators should be deterministic and have no
external effects. The offline example is `examples/pipy/typed_tool.py`.

## Hosted context and evidence

Hosted context selection is opt-in through `runtime.config.context`. The same
policy is available to Core. Start with shadow mode to inspect proposals:

```yaml
runtime:
  backend: pipy
  config:
    context:
      mode: shadow
      selector: rules
      conditional_instructions: true
```

Modes are `off`, `shadow` and `enforce`; selectors are `rules` and `jev`. Jev
uses the configured System One client, bounded evidence previews, a timeout and
a per-run call ceiling. It retains evidence when unavailable or uncertain.
`scorer_version` can pin an evaluation configuration. Selector calls with
unreserved spend are disabled inside cost/token-capped WorkOrders.

Decisions persist across restart and small plain assistant additions while
existing history remains unchanged. Changes to tasks, instructions, evidence,
errors or tool calls, and increases in context pressure, trigger selection
again within the call ceiling. Shadow mode preserves the baseline tool output
and records proposed excerpts; only enforce mode applies them.

In the interactive TUI, `:context evidence` shows the last native context
selection, proposed excerpt and bounded original retrieval. After continuation
or session restart, run a new step and reopen the view to inspect whether the
persisted decision was reused. External harness loops do not provide this
native inspection. WorkOrder recovery and evidence are visible through
`:work view ID`; see the [TUI delivery workflow](workorders.md#tui-delivery-and-recovery-review).

Original permitted text is stored in the host's SQLite context store, outside
the model prompt. `SUPERQODE_CONTEXT_STORE` overrides its location; the default
is `~/.superqode/context/artifacts.sqlite3`. `read_context_chunk` accepts a
reference, character offset and bounded limit. Retrieval rechecks current host
policy. Missing evidence returns an explicit error and never replays a tool.
The PiPy session archive and original usage accounting remain intact.

`conditional_instructions: true` enables explicit `sq:when` project blocks with
path, tool or task conditions. Unmarked instructions remain present. Matching
uses PiPy's own loaded resources and preserves their precedence. The standalone
library does not import the host's context policy.

Persisted `context.selection` and `context.retrieval` events expose decisions,
fallbacks and reference IDs. Size fields count characters, not provider tokens;
shadow proposals do not represent actual savings.

## Demo from the TUI

Select a PiPy spec with `:harness use ./pipy-demo.yaml`; enable the optional
Monty extra and `runtime.config.monty.enabled` for program composition.

- `:mcp reload`, `:mcp status` and `:mcp tools` inspect shared integrations.
- `:mcp login SERVER` and `:mcp logout SERVER` control a configured OAuth account.
- Ask PiPy to use `python_program` to batch native reads, filter results and
  store a small value. Ask it to load that value on the next turn.
- With a vision model, `:paste /absolute/path/screenshot.png` stages an image;
  submit a normal prompt to send it through PiPy. Existing attachment and model
  capability limits still apply.
- `:pipy session`, `:pipy fork`, `:pipy tree` and `:pipy export` show continuity.
- `:work programs`, `:work program-run`, `:work invocations` and `:work reconcile`
  run the same WorkOrder commands as `sq work`.
- `:benchmark compare` runs the same comparison command as `sq benchmark compare`.

Recovery applies only inside an active WorkOrder with recovery enabled. Ordinary
chat does not create coding checkpoints.
