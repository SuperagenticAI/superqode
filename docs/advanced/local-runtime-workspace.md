# Local runtimes and Apple on-device inference on macOS

Open **Local AI → Runtimes & performance**. Use the existing Quick Start tab for
guided Ollama/LM Studio downloads, or keep the server and weights you already
have. No server is installed, launched or queried merely by saving a profile.

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
This initial integration is for text conversations and lightweight tasks. It
rejects images and coding tools before starting generation. Qwen, GLM, DeepSeek
and Gemma weights run in other inference engines, not in Apple's system model.
The bridge streams text, terminates its child on cancellation and never falls
back to a cloud model. SDK errors or long conversations produce actionable
shorten/check-availability guidance. Token usage stays unknown when the SDK does
not report it.

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
dead process cannot permanently block new requests. Crash records are marked
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
