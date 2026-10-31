# AWS Strands harness integration research

Research date: 31 October 2026. Status: source review and isolated feasibility
probes completed; production integration is not implemented by this research.

## Recommendation

Support **Strands harness as an optional execution engine inside SuperQode**.
Keep SuperQode responsible for harness selection, routing policy, experiment
reproducibility, held-out evaluation, optimisation and reviewed adoption.

Use two explicit integration surfaces:

1. An **ACP connection** for users bringing the Strands CLI. Its basic transport
   already interoperates with SuperQode. Ship permission handling and connection
   discovery before presenting it as a supported coding route.
2. A **Strands harness backend using an isolated Python worker** for the product's
   differentiating evaluation, optimisation and routing workflows. Use
   `strands_harness.create_harness`, rather than only `strands.Agent`, when the user selects
   the assembled AWS harness. This preserves its context-management and agent
   behaviour while allowing SuperQode to control experiment configuration.

Do not label either route a subscription connection: the inspected Strands
providers use AWS credentials, API keys or model servers. ACP is a transport,
not an authentication method or billing plan. Adding a catalog entry alone would
not integrate Strands with SuperQode's harness evaluations.

## Checked-out sources and published packages

SuperQode main was fast-forwarded without replacing local changes. It is at
`727deeb42f28f3972e091147163113da5e295298`, with macOS source version **0.2.1 / build 15** and
Python **2.30.0**. This records source metadata, not a new installer verification.

| Source | Reviewed revision | Local checkout |
| --- | --- | --- |
| [SuperQode](https://github.com/SuperagenticAI/superqode/tree/727deeb4) | `727deeb4` | `/workspace/superqode` |
| [Strands harness SDK monorepo](https://github.com/strands-agents/harness-sdk/tree/1af083deb09c956041ddbb47d1f12da59b896bc4) | `1af083deb09c956041ddbb47d1f12da59b896bc4` | `/workspace/strands-harness-sdk` |
| [Strands Evals](https://github.com/strands-agents/evals/tree/32e72bb0639fc69d6763a671b461b12bc08c83af) | `32e72bb0639fc69d6763a671b461b12bc08c83af` | `/workspace/strands-evals` |

The AWS repository is now a monorepo. `harness-py` and `harness-ts` contain the
assembled harness, `strands-py` and `strands-ts` contain the underlying SDKs,
`strands-cli` contains the Node CLI and ACP server, and `strands-mcp` supplies a
documentation MCP server. The old `sdk-python` README resolves to this layout.
The harness metadata identifies AWS as the author and uses Apache 2.0 licensing.
Preserve LICENSE/NOTICE files when distributing dependencies or copying code.

Public registry metadata checked during this investigation:

| Package | Published version checked | Relevance |
| --- | --- | --- |
| [`strands-harness`](https://pypi.org/project/strands-harness/0.3.3/) | 0.3.3 | Assembled Python harness; Python >=3.10 |
| [`strands-agents`](https://pypi.org/project/strands-agents/1.63.0/) | 1.63.0 | Underlying Python SDK installed by the isolated probe |
| [`@strands-agents/cli`](https://registry.npmjs.org/@strands-agents%2Fcli/0.2.3) | 0.2.3 | Published CLI; Node >=22 |
| [`@strands-agents/harness`](https://registry.npmjs.org/@strands-agents%2Fharness/0.3.3) | 0.3.3 | Latest TypeScript harness observed |
| [`strands-agents-evals`](https://pypi.org/project/strands-agents-evals/1.8.0/) | 1.8.0 | Separate evaluation package; not required to run the harness |

**Version mismatch matters:** CLI 0.2.3 declares harness `~0.1.1`. The isolated
npm installation resolved harness **0.1.1** and SDK **1.23.0**, despite the latest
standalone harness being 0.3.3. Do not advertise all upstream-main or Python 0.3.3
features as properties of that CLI. Pin and report the actual resolved versions.
The CLI's ACP `agentInfo.version` is hard-coded as `0.0.1` in the inspected server;
use package metadata or `strands --version` for installation/version checks.

## What is in the harness

These are source-confirmed facilities, rather than results of a comparative
quality benchmark:

| Facility | Strands implementation | Value to SuperQode |
| --- | --- | --- |
| Assembled agent | `create_harness()` returns a normal `strands.Agent`, with tuned instructions and configurable defaults | A peer harness execution option without replacing SuperQode's outer lifecycle |
| Model portability | Provider/model resolution plus custom `Model` instances | AWS Bedrock and BYOK routes selected explicitly by the developer |
| Context management | Auto/agentic context manager, tool-result offloading and retrieval, provider-aware caching | Compare context strategies against latency, token use and task success |
| Coding tools | Shell, read/write/edit, web fetch/search, programmatic tool caller, subagent | A usable coding engine, provided permission and sandbox contracts are bridged |
| Delegation | Bounded subagent depth, inherited/narrowed authority, background work | Evaluate delegation strategies while measuring total work and cost |
| Persistence | Snapshot sessions, skill loading, durable file memory | Resume coding sessions; disable or isolate memory and skills for reproducible experiments |
| Control | Async interventions, allow/deny/confirm actions, Cedar option, cancellation, request limits | Map SuperQode permission and execution controls into Strands |
| Observability | SDK events and OpenTelemetry; optional harness exporter setup | Preserve run, tool, model, context and routing evidence |
| Routing | SDK `ModelRouter`, fallback strategy and custom strategies | Optional model-call routing inside a Strands run; distinct from choosing the harness itself |
| Evaluation ecosystem | Separate Evals SDK with output/trajectory/state evaluators, simulation, diagnosis, chaos and red-team facilities | Additional diagnostic experiments after an explicit evaluator/evidence bridge |

Implementation references: [factory and defaults][factory], [models][models],
[interventions][interventions], [routing][routing], [evals package][evals].

The Python harness defaults to Bedrock, enables sessions/skills/memory, and
includes powerful tools. `interventions=None` resolves to no approval handlers.
The SDK's default environment is `NotASandboxLocalEnvironment`. A programmatic
code interpreter does not isolate its callable shell/file/MCP tools from the host.
These defaults must be projected into SuperQode policy explicitly.

## Authentication and billing

| User's route | Strands support found | SuperQode behaviour to provide |
| --- | --- | --- |
| AWS Bedrock | Standard AWS SDK credential chain: profiles, configured SSO credentials, environment or workload identity | Profile/region fields, existing AWS sign-in workflow, actionable expiry/access errors; normal Bedrock billing |
| Bedrock API token | CLI recognises `AWS_BEARER_TOKEN_BEDROCK`; region must match; Python `BedrockModel` exposes `api_key` | Explicit Bedrock token route, region validation and secret redaction; real account test still needed |
| Anthropic | `ANTHROPIC_API_KEY` and optional custom endpoint | BYOK, not Claude consumer subscription |
| OpenAI | `OPENAI_API_KEY` and optional custom endpoint | BYOK, not ChatGPT subscription |
| Gemini | CLI documents `GEMINI_API_KEY`; SuperQode's Google provider recognises both Google/Gemini key names | Map the selected provider key to the child process explicitly; avoid relying on shell inheritance |
| Ollama | Local endpoint; CLI `OLLAMA_HOST`, optional server key | Local model discovery and a connection test; no cloud subscription required |
| LiteLLM proxy/custom model | Configurable proxy endpoint/key or custom SDK `Model` | Explicit endpoint, provider capability and cost provenance |
| Kiro, Amazon Q Developer, ChatGPT or Claude subscription | No native subscription/OAuth connector found in the inspected Strands model providers or stock ACP server | Keep existing subscription agents as separate SuperQode routes; do not extract or repurpose their login tokens |

A user may configure their own entitled model gateway or a custom `Model`, but
that does not establish a supported consumer-subscription integration. Nesting a
whole coding agent behind a custom model would require a separate design and
would not be equivalent to giving Strands that agent's underlying model access.

Strands ACP's `authenticate` handler returns an empty response, with no advertised
login method. Credentials must already be available to the child/provider. Opening
an ACP connection does not verify inference permission, model availability or
billing entitlement.

SuperQode already treats Bedrock as advanced authentication rather than a single
API-key field ([desktop credential handling][sq-credentials]). A macOS app opened
from Finder may not inherit terminal exports. Supply selected credentials only to
the relevant worker, support profile/region configuration, and report the actual
credential source without storing secrets in HarnessSpecs, reports or logs.

## ACP: tested connection and remaining gaps

The published CLI supports:

```text
strands --acp-server --model <provider/model>
```

The inspected [stock ACP server][acp-server] supports initialize, new session,
load session/transcript replay, prompts, cancel, client-supplied MCP servers,
text/reasoning/tool/media updates and usage. It permits only one canonical
workspace per process. SuperQode's existing subprocess-per-task/workspace
structure is compatible with that restriction.

The session advertises no model/mode configuration controls. The server does not
register `session/set_model` or `session/set_config_option`. Set the model in the
launch command/profile and restart as needed; do not present a working in-session
model picker on the strength of ACP alone.

**Permission boundary:** the stock server does not call
`session/request_permission`. It runs tools in the Strands process, rather than
requesting SuperQode's ACP filesystem or terminal services. Consequently,
SuperQode's scoped ACP filesystem callbacks cannot constrain those direct tools.
`--interventions ask` alone does not supply a complete client approval/resume
bridge in this stock server.

There is an important exception: the monorepo's authored **Python-agent ACP
bridge** (`strands-cli/src/tui/project/acp.ts`) does forward permission events to
`session/request_permission`, using its Python worker's interrupt/resume support.
That is a promising prototype route. It needs an explicitly configured policy,
selected Python runtime, and end-to-end validation. It rejects ACP-supplied MCP
servers for authored agents, even though its initialize response advertises MCP
transport capabilities. Do not generalise its behaviour to the stock server.

SuperQode currently has no Strands entry in its runtime registry, harness backend
registry, bundled ACP manifests or dedicated integration docs. For an initial ACP
route, add a bundled manifest and connection profile, launch-time model/profile
settings, install/version checks and a permission-capable bridge. Native macOS
ACP routes use the deterministic bundled catalog, with user entries excluded on
that path: adding a user TOML for terminal discovery is not sufficient for the
shipped Mac connection list. Installs must remain explicit; selection must not
silently run `npx` downloads.

## Full harness backend: integration design

Implement a `strands` harness backend that delegates to a versioned worker
protocol over private stdio. Keep the Strands Python environment separate from
SuperQode's environment and manage it as an optional, explicitly installed
integration. A worker process isolates dependencies and lifecycle; it is **not**
an operating-system security sandbox.

The current [HarnessBackend contract][sq-backend] already supplies HarnessSpec,
provider/model, working directory, session, sandbox selection and metadata. It
returns an AgentResponse and normalized events. The existing DeepAgents backend
is a useful peer implementation reference, but its capability claims should not
be copied without implementing them for Strands.

| SuperQode input/contract | Proposed Strands mapping |
| --- | --- |
| `runtime.backend: strands` | Optional backend registry entry and discovery/doctor checks |
| `runtime.config` | Validated allowlist for effort, context strategy, caching, delegation and memory/session policy; reject unsupported keys |
| `model_policy` | Explicit provider/model or a deliberately constructed SDK `Model`; no silent fallback to the harness's expensive default model |
| Tools and `allow_shell` | Bridge the SuperQode tool registry or filter Strands builtins; include plugin, MCP, subagent and programmatic-call surfaces in enforcement |
| Permission rules | Async intervention bridge to SuperQode decisions; deny/ask must precede execution; missing UI must block the call |
| Sandbox choice | Concrete Strands `Sandbox` adapter or external sandbox; reject unsupported choices instead of labelling host execution isolated |
| Prompt/context | Harness instructions plus explicitly selected SuperQode context; avoid applying both frameworks' compaction policies independently |
| Session | Project/route/config-bound opaque session id and private directory; restore only when compatible |
| Turn/token/time budgets | SDK request `limits`, deadline cancellation, aggregate delegate/auxiliary work accounting and worker shutdown |
| Result | Map stop reason, content, tool count, iterations, token usage and errors to AgentResponse; unavailable cost remains unknown, not zero |
| Events | Stable run/model/tool/delegate/context/routing records with provider/config/version provenance and cache usage |
| Cancellation | Agent cancellation plus shutdown/drain and subprocess cleanup; no success result after an incomplete or cancelled run |

Keep a single authority for model fallback. Initially, let SuperQode choose the
model and harness. Add SDK ModelRouter only as an explicit later mode with events
showing which model actually ran. The inspected router documents limitations:
`agent.model`/trace identity and compression sizing can reflect the first candidate,
structured-output calls bypass routing, and failover after partial streaming can
leave partial text followed by the replacement response. These affect truthful
routing evidence and token/window comparisons ([router source][routing]).

## SuperQode implementation locations

These are proposed edits, not files changed by this investigation:

| Area | Files and purpose |
| --- | --- |
| ACP discovery | `src/superqode/agents/data/strandsagents.com.toml`, `agents/install_commands.py`: bundled identity, pinned launch/install and Node availability |
| Connect catalog | `providers/harness_catalog.py`, `providers/connection_profiles.py`, `app/harness_picker.py`: separate ACP and harness-engine entries with BYOK/AWS/local auth |
| Native routing/auth | `desktop_service/routes.py`, `connect_workflow.py`, `connections.py`: explicit provider/model launch projection, AWS profile/region and child-scoped environment |
| Execution | New `harness/backends/strands.py` plus worker protocol/package; `harness/backends/registry.py`: inspect, run, stream, capability and dependency reporting |
| AgentRuntime surface | `runtime/registry.py` and optional `runtime/strands.py` if direct runtime selection is exposed; avoid advertising a runtime that only exists as a harness backend |
| Presets and discovery | `harness/templates.py`, `harness/catalog.py`: explicit Strands template with controlled tools, memory and context defaults |
| Evidence | `harness/events.py`, `agent/loop.py` response mapping, `harness/eval.py`: retain normalized usage and actual model/backend provenance |
| Graders and adoption | `harness/evaluators.py`, `harness/acceptance.py`: optional richer graders with an explicit acceptance design, preserving existing fail-closed rules |
| macOS | `ConnectWorkflowView.swift`, `ConnectionConfigurationViews.swift`, `Features.swift`: AWS/BYOK/local setup, launch-time model controls and evaluated candidate evidence |
| Packaging | `pyproject.toml`/`uv.lock` only after dependency design is settled; macOS build scripts and runtime provenance for any embedded worker |

SuperQode already has an ACP attachment mechanism for BYOK/local agents in
`desktop_service/connect_workflow.py`. Reuse its provider allowlists and secret
handling where applicable. Its generic non-local attachment currently requires a
single provider API key, so AWS profile/region authentication needs a specific
extension rather than being forced through that path.

## Evaluation and optimisation: where differentiation comes from

A Strands coding connection alone would add another agent to the list. The useful
product is the ability to **measure and tune Strands against other harnesses**:

1. Select the same task suite, task split, fixture repository and provider/model
   constraints for a SuperQode baseline and a Strands candidate. Run each in a
   fresh fixture/worktree; use fresh session ids and disable memory, skill
   auto-discovery and undeclared external tools unless they are explicit variables.
2. Compare success and regressions, latency, token/cache usage, tool/delegate work,
   cost evidence and policy violations. Hold permissions and allowed workspace
   operations constant across engines; otherwise the benchmark measures different
   privileges rather than harness quality.
3. Optimise a constrained set of instructions, context/offloading settings, effort,
   delegation depth and tool choices on held-in tasks. Freeze SDK versions, source
   hashes, model identifiers, judge configuration and runtime settings per trial.
4. Validate the candidate on sealed held-out tasks using supported graders and
   the existing [fail-closed acceptance gate][sq-acceptance]. Keep candidate hash
   verification and reviewed adoption. A score from an external report is not an
   adoption authorization.
5. Present a measured recommendation in macOS: which harness worked better for
   this project/task class, at what cost/latency, with what regressions and evidence.

[SuperQode evaluation][sq-eval] currently executes HarnessSpecs through
HarnessKernel. There is no registered generic ACP harness backend in the inspected
backend registry. Do not assume an ACP catalog entry automatically becomes an
`evals.start` or optimisation target. The proposed backend is what closes that gap.

The [Strands Evals implementation][evals] offers useful additional work:
trajectory/tool-selection checks, environment-state assertions, skill selection
and instruction-following checks, failure/root-cause analysis, conversation/tool
simulation, chaos faults and adversarial tests. Integrate those as explicit
optional evaluators/diagnostic experiments after normalizing their evidence.
SuperQode's evaluator validator currently accepts only `decision`, `contains`,
`non_empty`, and `jev_rubric`; its adoption gate accepts a narrower graded subset.
Adding Strands scores requires deliberate schema, judge provenance, incomplete
result and acceptance-policy work. Do not relabel a trajectory score as `contains`
or weaken the gate to accept arbitrary imported reports.

## Dependency and macOS packaging constraints

A solver trial confirmed this concrete conflict:

```text
strands-harness==0.3.3 -> pydantic-monty==0.0.23
superqode[monty]       -> pydantic-monty>=1.0.0,<2
Result: unsatisfiable in a single Python environment
```

The old Monty requirement is unconditional in the harness package. Turning off its
programmatic-tool-caller option does not remove the package dependency. SuperQode
also auto-discovers Monty by importability in its tool registry, so installing an
old Monty into its core environment could expose an incompatible native feature
even when the developer did not request the Monty extra. Prefer the isolated
worker; do not force a downgrade or mutate the shipped engine to bypass resolution.

This is one demonstrated incompatibility, not a full optional-extra compatibility
matrix. The isolated install selected OpenTelemetry API 1.45.2; SuperQode has its
own locked OpenTelemetry/ADK constraints. Full shared-environment solving, audits
and macOS packaging still require validation if that design is pursued.

PyPI lists a `pydantic-monty-runtime==0.0.23` macOS arm64 wheel. That establishes
artifact availability, not successful app signing or notarization. An embedded
worker needs locked hashes, notices, runtime provenance, native-binary signing,
clean install/upgrade tests and new notarization. Alternatively, first ship an
explicit external-runtime installer and accurate unavailable states. Do not
require silent dependency downloads when a developer selects Strands in the app.

## Feasibility checks actually run

All probes ran on Linux in separate research environments. No cloud model,
provider login, paid inference, deployment or release was invoked. No upstream
source files or SuperQode application logic were modified for these checks.

| Check | Observation | Limit |
| --- | --- | --- |
| Install published CLI | `strands --version` returned 0.2.3; resolved harness 0.1.1 / SDK 1.23.0 | Isolated npm install used `--ignore-scripts`; not a macOS installer test |
| Actual SuperQode ACP client | `ACPClient.start()` succeeded; advertised session loading/images/embedded context/HTTP+SSE MCP; empty config options | No production catalog entry added |
| Stream and usage via CLI | Local OpenAI-compatible HTTP fixture on the Ollama route produced `strands-acp-ok`, `end_turn`, usage 10 input / 4 output / 14 total tokens | Synthetic transport fixture, not a real Ollama/model quality test |
| ACP session restore | Stopped the child and started another with exact resume required; same session restored | Cancellation under active tools and native UI were not exercised |
| Python harness | Installed harness 0.3.3 / SDK 1.63.0 in a Python 3.12 environment | No claim of full SuperQode dependency compatibility |
| Python streaming/tool | Scripted SDK Model emitted a tool call; custom harmless tool ran exactly once | Defaults were disabled to isolate the execution contract |
| Python permission deny | Custom InterventionHandler denied the same tool; zero tool executions | UI ask/allow/resume still needs bridge tests |
| Python session restore | Second agent restored two prior messages, produced fixture output and usage | Offline scripted Model; no quality claim |
| Dependency conflict | `uv pip install --dry-run` rejected harness 0.3.3 plus Monty >=1,<2 | Expected failure, no environment mutation |

Reproduction material in this workspace:

```text
/workspace/strands-research/acp_probe.py
/workspace/strands-research/python_probe.py
/tmp/strands-acp-probe.log
/tmp/strands-python-probe.log
/tmp/strands-monty-conflict.log
/tmp/strands-cli-install.log
/tmp/strands-python-install.log
```

The ACP fixture serves local Chat Completions SSE. The Python fixture subclasses
`strands.models.Model`. Neither is an integration with an actual model provider.
These probes demonstrate API feasibility, not an already-supported product feature.

## Implementation sequence and release gates

1. **Connection foundation:** bundled ACP entry, explicit install/version probe,
   launch-time provider/model/profile configuration, visible credential provenance,
   and honest capability reporting. Bridge ask/deny and shutdown before enabling
   arbitrary coding tools. Cover both TUI discovery and native macOS routes.
2. **Harness engineering backend:** isolated Python worker, validated config,
   HarnessBackend registration, event/result/usage mapping, tool and sandbox
   contract, session/cancellation cleanup, provider-specific credentials. Add a
   discoverable Strands HarnessSpec template to both interfaces.
3. **Evaluation and optimisation:** Strands as a baseline/candidate in the existing
   suite/comparison UI; fresh evaluation state and fixed tool privileges; bounded
   search space and sealed held-out acceptance; replayable configuration evidence.
4. **Optional depth:** trajectory/state/skill evaluators, fault injection, measured
   per-task-class routing and advanced SDK ModelRouter support. Add each only with
   corresponding evidence and capability tests.

Before release, exercise: provider credential absence/expiry and correct billing
route; launch-time model correctness; approve/deny/ask across shell/file/MCP and
children; timeout/cancel/worker death without orphan processes; exact project
resume without evaluation-state leakage; token/cost accounting including auxiliary
work; failed/abstained/incomplete grading; source/config digest changes; explicit
install failure/offline operation; and native macOS clean install, streaming,
permissions, comparisons, signing and notarization. Run real-provider checks with
an explicitly configured account and bounded budget.

This research recommends an integration. It neither adds Strands to the shipped
app nor certifies AWS's benchmark claims, model quality, security audit or release
readiness. No remote push, version bump or publication was performed for this research.

[factory]: https://github.com/strands-agents/harness-sdk/blob/1af083deb09c956041ddbb47d1f12da59b896bc4/harness-py/src/strands_harness/agent.py
[models]: https://github.com/strands-agents/harness-sdk/blob/1af083deb09c956041ddbb47d1f12da59b896bc4/harness-py/src/strands_harness/models.py
[interventions]: https://github.com/strands-agents/harness-sdk/blob/1af083deb09c956041ddbb47d1f12da59b896bc4/harness-py/src/strands_harness/interventions.py
[routing]: https://github.com/strands-agents/harness-sdk/blob/1af083deb09c956041ddbb47d1f12da59b896bc4/strands-py/src/strands/models/routing/router.py
[acp-server]: https://github.com/strands-agents/harness-sdk/blob/1af083deb09c956041ddbb47d1f12da59b896bc4/strands-cli/src/tui/acp/server.ts
[evals]: https://github.com/strands-agents/evals/tree/32e72bb0639fc69d6763a671b461b12bc08c83af/src/strands_evals
[sq-backend]: ../../src/superqode/harness/backends/base.py
[sq-credentials]: ../../src/superqode/desktop_service/connections.py
[sq-eval]: ../../src/superqode/harness/eval.py
[sq-acceptance]: ../../src/superqode/harness/acceptance.py
