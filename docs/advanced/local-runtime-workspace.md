# Local runtimes and Apple on-device inference on macOS

Open **Local AI → Quick Start**. Apple on-device appears with the harness and model
choices, and **Runtimes & performance** is on the same page. The download guide
supports Ollama and LM Studio, and you can connect a server you already run.
Saving a profile only stores its settings.

## Connect another local server

1. Choose a setup template: **vLLM Metal**, **oMLX**, **Jan**, **GPT4All**, or
   **Other compatible server**. Give the profile a name.
2. Enter its exact loopback base URL, including `/v1` when the server uses it.
   Defaults are starting points, not evidence that a server is installed. Two
   servers using the same port cannot run there at the same time.
3. If needed, enter its API key. Keep it for this app session or explicitly
   save it in your Mac Keychain. Keys are never saved in profile JSON, prompts,
   the project or the timing database. Removing a key also removes the saved
   Keychain item. A keyless profile does not inherit another server's key.
4. Set the context cap to the size the server actually loaded. The default is
   a conservative starting cap, not an automatic measurement of loaded context.
   Choose the declared tool capability; leave it unknown if you have not checked.
5. Save, then choose **Check server & models**. Discovery lists advertised chat
   models without generating text or sending project files. Review the context
   source, since a model-card maximum does not establish a loaded allocation.
6. Select a model. Use it for chat, or run **Run tool check** before enabling a
   coding harness. The check asks for a generated-data function call; it does
   not execute a tool or access project files. Core, PiPy and RLM use the shared
   compatible route. Other external SDKs have their own setup contracts.

Profiles accept HTTP(S) loopback addresses such as `127.0.0.1`, `localhost` and
`[::1]`. Remote hosts, embedded credentials, URL query keys and redirects are
refused. This feature connects to this Mac; it is not remote server exposure.
An external server can itself proxy cloud models, so verify its configuration
before describing the entire workflow as offline. Tools and delegated models
also keep their own network policies.

A successful tool-shape check is a starting point. Model artifact, quantization,
chat/tool parser, loaded context, runtime version and harness all affect coding
quality. Use held-out edits/tests to compare real outcomes. Changing runtime
settings or editing its key invalidates previous checks; reconnect existing
bindings after changing their configuration. Restoring the same explicitly
remembered Keychain credential at app startup preserves its check identity.

## Installation and model setup

**Installation & setup** prepares a reviewable vendor recipe. On Apple Silicon
with Homebrew, the vLLM Metal and oMLX templates offer fixed Homebrew commands.
Nothing runs before **Install runtime** is selected. Other platforms or missing
Homebrew receive manual guidance and an official documentation link.

Installation uses no provider keys, does not select/download model weights and
does not start inference. Afterwards, follow the vendor's memory/model recipe
to load compatible weights and start a loopback server. Then check its models.
Keep a server you already run; SuperQode does not take ownership of an external
server or silently restart it with different context/cache settings.

- [vLLM Metal installation and memory-tier recipes](https://docs.vllm.ai/projects/vllm-metal/en/latest/recipes/)
- [oMLX setup and supported model formats](https://github.com/jundot/omlx)
- [Jan's local API server](https://docs.jan.ai/desktop/api-server)
- [GPT4All local API server](https://docs.gpt4all.io/gpt4all_api_server/home.html)
- [Homebrew](https://brew.sh)

Installation and tool checks run as visible, supervised jobs. Inspect their
collapsed output or choose **Stop**. Homebrew can leave partially installed
packages after cancellation; review and retry its install to finish. A completed
install is not a claim that model weights are ready or coding has been tested.

If a compatible server rejects `stream_options`, disable **Request token usage
from this server** and save the profile. Counts and rates then remain unknown
unless the server reports them anyway. Explicit structured-output and reasoning
options are forwarded; support for a particular schema/effort level is still a
property of that server/model. Requests fail clearly rather than replaying a
partially generated answer.

## Apple Foundation Models

The **Apple on-device model** card uses the bundled native Foundation Models
bridge. No Homebrew package, Python SDK, API key, HTTP server or subscription is
required for this route. It needs macOS 26+, an eligible Mac, Apple Intelligence
enabled, and Apple's system model ready. Choose **Check availability** for the
specific state and [Apple's setup guidance](https://support.apple.com/en-us/121115).

**Use for chat** selects `apple-foundation/system-on-device` and Direct Chat.
Text streams incrementally; Stop terminates an active helper. No cloud fallback,
subscription, API key, Python SDK or inference server is used. Images and reasoning
controls are not supported by this route. Downloaded Qwen, GLM, DeepSeek and Gemma
weights use their own runtimes rather than Apple's system model.

**Use with Silicon Harness** selects `silicon`. Its four default tools are
`read`, `search`, `write` and `edit`. They use SuperQode's normal project path checks, Ask/Auto-edit/Full controls
and file tracking. Shell and network tools remain disabled even in Full mode.
Native Apple tools only request an action: they hand validated arguments back to
the host executor before any file operation. The framework's tool loop ends at
that boundary; the next request restores calls/results as native transcript
entries. No write happens inside the Apple helper.

Keep tasks small. Apple's on-device model has limited reasoning and context;
tool output uses a 2 KB budget so a file read leaves room for the instructions,
tool schemas and reply. Truncated file reads retain continuation guidance.
This configuration does not establish frontier coding capability. Project
instructions remain in effect; oversized instructions or tool output can require
a shorter prompt or a new thread. The configuration bounds model iterations at
eight. Verify changes with independent tests rather than relying on the model's
claim of success.

Conversations use native transcript entries instead of a JSON conversation
prompt. An unchanged, continuing text chat can reuse its native session within
the same gateway/worker. Helpers are exclusively checked out; at most two idle
helpers remain for 30 seconds, with no listener or disk transcript cache.
Cancellation, errors, tool handoffs or changed history invalidate native session
reuse. The desktop still starts a new supervised worker per user turn, so native
KV caches do **not** persist between desktop chat turns. Context is replayed as
native transcript entries in that case. First-use prewarming occurs only after
an explicit request. These changes are opportunities for lower overhead, not a
measured Apple throughput guarantee.

Availability reports the current locale's support. Model-not-ready, refused,
unsupported-language, context-full and invalid structured-output errors have
distinct guidance, without silently retrying or sending input to another model.
The request guard includes tool/schema overhead, conservatively caps context at
4,096 tokens and refuses an oversized history with new-thread guidance instead
of silently dropping conversation turns. Newer SDK builds on macOS 26.4+ also
check native transcript/schema token counts before generation; those counts are
recorded separately from unreported generation usage.
Framework context errors advise a new thread; no hidden summary model is invoked.
Token counts stay unknown when this bridge cannot report them.

The gateway supports native guided output with
`response_format={"type": "json_schema", "json_schema": {"name": "Result", "schema": ...}}`.
Supported schemas include explicitly named object properties, arrays, strings,
string enums, numbers, integers and booleans. References, unions, open objects
and unsupported keywords fail before generation. Size/range/pattern constraints
are also checked against the original schema before delivery, even when they
have no native generation guide. Malformed results and invalid tool arguments
are never delivered for execution. Use separate requests for tool calling and
structured final output; unconstrained `json_object` is not a guided schema.

**Local AI → Advanced → Compare** includes Apple's model when it is available and this
build supports tools. Select the Apple on-device configuration and a shared
context no larger than 4,096. Trial isolation, independent repository graders,
cancellation, request timings and saved results use the existing comparison
engine. The bridge records the OS runtime version but does not expose immutable
weight revisions, quantization, residency or cache-hit counts; these stay
unknown. Do not treat the two starter tasks as a coding certification.

**Use for optional summaries and utility tasks** explicitly routes the existing
utility hooks, including memory extraction and rubric grading, to this native
provider. Validate grading quality before using model scores as a release gate;
independent tests remain necessary. If availability changes, this native utility
route fails without sending its input to a cloud/session fallback. The option is
off by default and can be turned off even if the model becomes unavailable.

The older `SUPERQODE_UTILITY_PROVIDER=apple-fm` alias remains supported. The app's
bundled bridge can supply it; standalone Python installations can still use the
optional SDK adapter. That legacy alias retains its existing session-fallback
behavior. Use the explicit `apple-foundation/system-on-device` route when no
fallback is required.

On an eligible physical Mac, the source checkout provides an explicit SDK check:

```bash
python3 apps/macos/scripts/check-apple-model.py --require-available
```

It exercises real streaming, native session reuse, guided output, tool requests
and tool-result transcript continuation. The tool test uses a synthetic result;
it never executes a file operation. The same check runs in native CI, which
explicitly reports `generation_tested: false` when its runner lacks the system
model. Schema/transcript construction and tool handoff also have native tests
that do not require model availability. Python fixtures separately exercise real
SuperQode workers, Ask approval and project path boundaries. Fixture success is
not evidence of real model quality or throughput.

Source builds compile `SuperQodeAppleModel` alongside the app and package/sign it
in `Contents/MacOS`. Builds without a Foundation Models SDK and unsupported Macs
report unavailability. Terminal commands published by the Mac app inherit its
bridge path and coordination state directory. A standalone source CLI can set
`SUPERQODE_APPLE_HELPER` to its own compiled bridge.

## Keep local execution responsive

The local execution manager reserves generation slots across SuperQode model
turns, including different projects, Core/PiPy, CodeGem, compatible profiles,
Apple requests and synchronous local endpoint benchmarks. One is the default;
raise **Simultaneous generations** only after checking memory and actual latency.
This does not schedule requests made by other applications or automatically
unload models already resident in separate servers.

Each slot covers a model request, then releases before tool execution. Waiting
can be cancelled. Kernel leases release if a worker exits unexpectedly, so a
dead process cannot permanently block new requests. A queued request times out
after two minutes without starting model generation; you can cancel sooner.
Crash records are marked
interrupted by lease ownership, rather than trusting a possibly reused PID.

**Warm model** sends a bounded short request and records its timing. Use it when
you want to pay a cold load before the first task. Servers control residency and
cache eviction; warmup does not guarantee that weights stay loaded indefinitely.
Existing Ollama/LM Studio warmup and local benchmark calls use the same shared
coordination. Keep context and prompt prefixes stable to benefit from the
server's cache, and measure cold and warm runs separately.

The performance panel records no prompts, replies or keys. It shows:

| Observation | Interpretation |
| --- | --- |
| Queue time | Waiting for a SuperQode generation slot |
| First output | Request preparation/server time before text, thinking or tool data |
| First text | Time before the visible answer, which can follow reasoning |
| Turn duration | Client time for the complete model request, including server preparation and output |
| Context/output cap | Applied contract when known; unknown values stay unknown |
| Server loading/prefill/decode | Shown only when the protocol reports these timers |
| Output tokens | Server-reported counts; streamed fragments are not tokens |
| RAM/available/swap | OS observations; available memory is approximate on the fallback Mac counter path |

Counters do not establish which model owns all GPU memory. Avoid comparing
client-timed throughput with server kernel timings as if they were identical.
High swap, oversized context, cold loads, reasoning and competing applications
can each cause a different kind of slowdown. The panel links to the existing
local benchmarks and harness evaluation workflows for controlled comparisons.

## Silicon Harness

In **Local AI → Start**, choose **Use Silicon Harness** on the Apple on-device
model card. Silicon also appears in the harness picker for compatible local
models. Silicon offers bounded repository search, ranged reads, targeted edits,
and file creation. The Apple route reads the window reported by the operating
system and falls back to 4,096 tokens when the SDK provides no usable size.
Compare can run Silicon and Apple on-device on the same model and repository
suite to measure whether the extra tools improve task completion.

Create a Project Harness in Harness Studio or use a harness file to override
the tools, prompt, and checks. The `agents` list replaces the inherited list.
For example, this project runs a named check after a completed coding turn:

```yaml
name: project-silicon
inherits: silicon
checks:
  enabled: true
  custom_steps:
    - name: unit tests
      command: python -m pytest -q
      timeout: 60
```

### Use a project harness

SuperQode lists harness files from this repository, such as `harness.yaml` at
the project root and files in `.superqode/harnesses/`, in a **This project**
section. There are two ways to choose one:

- **Start a new thread:** in **Local AI → Start**, the Apple on-device model card
  shows a **Harness:** menu when the project has a harness based on Silicon.
  Choose it, then choose **Use Silicon Harness**. SuperQode remembers the choice
  for the project.
- **Switch during a conversation:** choose **Switch harness…** next to the
  connection chip under the composer. The harness chooser lists **This project**
  first, then **Built-in**, then **Agents and other harnesses**. Choose a harness
  that fits the current model to return to the same conversation. The change
  applies from your next message.

A harness card shows **Based on Silicon Harness** when its file inherits
`silicon`. If a harness cannot use the current model, its card says **Needs a
different model**, and choosing it continues to model setup. The composer chip
names the active harness, for example **Apple on-device · project-silicon**.

### Silicon options in Harness Studio

You can set the options below without editing YAML. Open **Harness Studio**,
choose **Silicon Harness** in **Start from**, then choose **Load**. In the
right column, choose **Silicon options…**:

- **Use MCP servers** adds `execute` to the tool list, writes the
  `runtime.config.silicon_mcp` allowlist for the servers and tool names you
  pick, sets `allow_network: true`, and adds an allow rule for `execute` and
  each `mcp_<server>_<tool>`. It is off by default and needs at least one
  server in the project's MCP configuration.
- **Monty Code Mode** sets `runtime.config.silicon_mcp_code: true`. It is
  available only when MCP is on and Monty is installed.
- **Run in Apple Container** adds `apple_container` to a check step, with a
  local image pinned by digest and the project files to copy. It is available
  on macOS 26 or later when Apple's `container` tool is installed.
- **Fail the run when a check fails** sets `checks.fail_on_error`, and
  **Add a check** appends a check step.

The sheet shows the Apple tool count and warns when the tools would exceed
five. Choose **Preview changes** to see the YAML diff, then **Apply to draft**.
The draft stays the source of truth: validate it and save a revision as usual.

The host runs the check with the local OS sandbox, a reduced environment, and
network access denied. The result appears alongside the coding response.
Checkpoints and the turn's Changes view let you review and undo its edits.

### Apple Container verification

On Apple Silicon with macOS 26 or later, prepare Apple Container with Apple's
signed installer, a running service, its Linux kernel, and a locally cached
ARM64 image. Add `apple_container` to a check that can run in Linux.

```yaml
name: project-silicon
inherits: silicon
checks:
  enabled: true
  fail_on_error: true
  custom_steps:
    - name: linux verification
      command: python3 verify.py
      timeout: 60
      apple_container:
        image: docker.io/library/python@sha256:218ad6ba54faeb7f1089f391c597a80c9d69ca88e561f71ebd77fb452d39249b
        files:
          - verify.py
```

List the exact files the check needs. SuperQode copies the current files into
a disposable workspace, rejects symlinks, and discards guest changes. The guest
uses a read-only root filesystem, a temporary directory, and loopback-only
networking. Prepare tool dependencies in the pinned image ahead of time.
An unavailable service or missing image fails the check. Checks without this
setting still use the local OS sandbox in Silicon, including commands that
need macOS or Xcode.

### Official MLX in Quick Start

Install **MLX** on the Start tab, then choose **Download MLX model**. Review
the publisher, pinned revision, transfer size, and estimated fit before
starting the download. Choose the downloaded snapshot to start coding. The
managed server uses Apple's `mlx-lm` in its own environment and serves over
loopback. Use a supported text model for this route.

### Optional MCP

Silicon can keep one search and one execution interface even when several
MCP servers are connected. In a derived harness, add `execute` to the agent's
tool list, allow network access explicitly, and list the configured server IDs
and tools you want to expose. Standard project MCP settings supply the server
connections. The execution policy still controls each resolved capability.

```yaml
name: silicon-docs
inherits: silicon
agents:
  - id: coder
    role: focused development
    tools: [read, search, edit, write, execute]
    system_prompt: Use repository search for code and MCP search for private documentation.
runtime:
  config:
    silicon_mcp:
      docs_local: [lookup]
execution_policy:
  allow_network: true
  permission_rules:
    - tool: execute
      action: allow
    - tool: mcp_docs_local_lookup
      action: allow
```

The model uses `search(query, scope: "mcp")`, then calls
`execute(capability, arguments_json)` with the exact discovered capability.
The host validates arguments against the current server schema. Apple requests
are preflighted against the bridge's five-tool and schema limits.

Set `runtime.config.silicon_mcp_code: true` on an MCP-enabled Silicon
harness to try the experimental Monty variant. It uses the same two tools.
The execute schema accepts a short Python snippet, with one permitted MCP
call per snippet through `tool_call("server/tool", {"argument": "value"})`.
The macOS app bundles Monty. For the standalone CLI, install
`superqode[monty]` before selecting this variant. Use Compare to evaluate it
separately from the direct call mode.

### exo cluster and Send to…

Start exo on the Mac running SuperQode and join the cluster in exo. Open
**Local AI → Start → Set up exo cluster**. Save the profile using
`http://127.0.0.1:52415/v1` or its configured loopback endpoint, then choose
**Check server & models**.

SuperQode reads exo's cluster state (`GET /state`) and shows:

- each node with its name, chip, and installed and available memory;
- **Models on your cluster**: every model exo reports on a node, marked
  **Running**, **Downloaded** or **Downloading** with progress, plus its size,
  context cap and the nodes that hold it.

exo's `GET /v1/models` lists its whole catalogue, so SuperQode uses it only for
context and size details. Older exo builds without downloads in their state are
read with `GET /v1/models?status=downloaded`. If the cluster state cannot be
read, SuperQode shows the error and lists no models.

**Start** on a downloaded model asks for confirmation, then starts it with
exo's own API: `GET /instance/previews` to find a placement that fits,
`POST /place_instance`, and `GET /instance/await` for up to 300 seconds. The
start runs as a job that you can stop. Stopping ends the wait; exo may keep
loading the model, and you stop a running model in exo. If a node chosen for
the placement is missing part of the model, exo downloads it first.

Only running models appear in the **Running model** picker, because only those
can answer requests. Run the tool check for the model you want to use. Choose
**Use for chat** to start directly on exo. To code with exo, enable **Use a
coding harness**, pick a harness such as Silicon Harness, Core or a project
harness, and choose **Use for coding** after the tool check passes. Running
models from the saved profile also appear in **Compare** when the profile
allows tools.

To continue a finished coding turn on exo, open **Send to…**. It sits next to
**Switch harness…** under the composer, and in the run header of a finished
coding turn. The menu lists one item per saved exo profile, for example
**exo cluster (localhost:52415)…**. An item is disabled, with the reason, when
exo does not answer, no model is running, or no running model has passed the
tool check. The whole menu is disabled, with the reason, when no finished
coding turn is selected, the turn is a chat turn, the turn belongs to another
project, or a run is active.

Picking a target opens a preview. Review and edit the objective, response
excerpt, checks and patch, choose the model, and check the harness the run will
use. SuperQode keeps the turn's harness when it can run on a local model, so a
project harness such as silicon-demo keeps its checks. Otherwise it uses Core.
**Send** starts a new run with permission prompts on. Inference runs **On your
network** and tool effects are handled by SuperQode on this Mac.

The engine routes are `handoff.targets`, `handoff.preview` and `handoff.start`.
Targets have an id such as `exo:<profile id>`, a kind, a title, whether they are
available and why not, and the models they offer. exo is the only target kind
today.
