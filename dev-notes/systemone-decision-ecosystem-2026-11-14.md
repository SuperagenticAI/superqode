# SystemOne decision-model ecosystem and integration plan

Subsequent implementation: see [implementation handoff](systemone-decision-implementation.md)
and the [user setup guide](../docs/advanced/systemone-providers.md). The research
below describes the earlier baseline and distinguishes vendor documentation
from runtime measurements. Later [cloud validation](systemone-validation.md)
records Python and mocked API tests; native builds and real provider inference
have not been performed here.

Researched 14 November 2026 against main `a9ce9048` (Python 2.31.15,
macOS 0.4.8/build 34). This is a source review and implementation proposal.
No provider adapter was added, paid inference performed, or CI started.

## Recommendation

Keep one SystemOne harness with three selectable decision providers:
TypeSafe Jev, Google Gemini Decision, and OpenAI Decisions. Keep the coding
model independently selectable. For example, a local Qwen coding model could
use Jev, Gemini Decision, or OpenAI Decisions for tool selection, provided the
user explicitly allows the selected evidence to leave the Mac.

Both Google and OpenAI now document dedicated Decisions APIs. These are more
appropriate than asking a chat model to emit JSON containing its own claimed
confidence. Existing OpenAI/Gemini coding-model support does not implement these
decision endpoints. TypeSafe AI and Jev are the vendor and model respectively,
not two existing decision providers.

Add Google first because its three question types resemble our current packs,
then OpenAI with explicit request/response translation. New provider/model
configurations should start in shadow mode and require separate calibration
before enforcing permissions or pruning context. Preserve existing Jev
configuration and behavior during migration.

## Verified market capabilities

Facts below are from the linked official documentation retrieved on the review
date. Account access, observed latency, and calibration quality have not been
verified with real credentials.

| Property | TypeSafe Jev | Google Gemini Decision | OpenAI Decisions |
| --- | --- | --- | --- |
| Current documented model | `jev-1.14.0`; `jev-1.13.0` remains available | `gemini-decision-1` | `gpt-6-luna`, currently the only supported Decisions model |
| Endpoint | `POST https://api.typesafe.ai/v1/systemone` | `POST https://generativelanguage.googleapis.com/v1beta/decisions` | `POST https://api.openai.com/v1/decisions` |
| Authentication | Bearer TypeSafe API key | `x-goog-api-key` | Bearer OpenAI API key |
| Shared evidence field | `state` | `input` | `input` |
| Questions | Map keyed by question ID | Map keyed by question ID | Array; give each question a unique `name` |
| Binary question | `noul` | `noul` | `predicate` |
| Categorical/rubric question | `choice` / `score` | `choice` / `score` | `choice` / `score` |
| Answers | Map keyed by question ID | Map keyed by question ID | Array with question `name`; individual answers can be refusals |
| Questions per request | Bounded by context, with no separate question-count limit documented | 1–1,000 | 1–400 |
| Choice/score constraints | Our current Choice cap is 255; check vendor and pack bounds | 2–255 choices; 2–255 score levels | 2–255 choices; 2–10 score levels |
| Input | Text/JSON; image support uses explicit danger-zone opt-in | Text, images, audio, video, PDFs | Text, JSON, images, conversation and tool-call history |
| Context | Default 64k per request / 32k per question; explicit experimental long-context header raises both to 262k | 262,144 tokens across evidence and questions | Do not infer an endpoint-specific limit solely from the general Luna model card; bound requests and handle endpoint errors |
| Paid input price per million tokens | $0.042 | $0.10 | $0.10 uncached; regional/long-context adjustments apply |
| Output cost | Free | Zero output tokens | No output-token charge; documented response examples report zero output tokens |
| Provider prefix cache | Not assumed in this proposal | Not supported | Supported; reusable shared-input prefix must be at least 1,024 tokens |

Sources: [TypeSafe models](https://docs.typesafe.ai/models.md),
[TypeSafe OpenAPI](https://api.typesafe.ai/openapi.json),
[Google Decisions guide](https://aistudio.google.com/docs/decisions-api),
[Google model](https://aistudio.google.com/docs/models/gemini-decision-1),
[Google pricing](https://aistudio.google.com/docs/pricing#gemini-decision),
[OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions),
[OpenAI create reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).

For an illustrative 20 million uncached input tokens, the listed base cost is
$0.84 for Jev and $2.00 for Google or OpenAI, excluding premiums. This is an
arithmetic illustration, not a SuperQode workload estimate. Include evidence,
question instructions and criteria when measuring actual token cost. Shared
evidence is evaluated once per request; splitting a request repeats that cost.

Google lists a free tier, but its pricing/terms distinguish data use between
free and paid services. Do not select a free cloud route automatically for a
private repository. Rate limits are project-specific; the published Gemini
Decision free-tier table lists 200 RPM, 50,000 TPM and 10,000 RPD, which are
simultaneous constraints rather than guaranteed capacity. See
[Google limits](https://aistudio.google.com/docs/rate-limits#gemini-decision)
and [terms](https://aistudio.google.com/docs/terms#paid-services).

OpenAI documents general availability, approximately 10x lower latency than
Responses, prompt caching, data residency, and eligibility for Zero Data
Retention/HIPAA use. These are vendor claims and account-dependent options,
not measurements or guarantees from this review. Default abuse-monitoring
retention and caching exceptions still matter; see
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

Use documented API credentials and metered billing for the initial integration.
Do not treat existing Codex, ChatGPT, Gemini CLI, or consumer-plan sign-in tokens
as authorization for these endpoints. Any future subscription route needs its
own documented authentication and entitlement contract.

## What SuperQode already has

| Existing surface | Code | Reuse and remaining work |
| --- | --- | --- |
| Async client protocol | `src/superqode/systemone/client.py` | `evaluate(state, questions) -> Answers` is already provider-neutral and accepts injected clients |
| Choice, Score, Noul answers | `systemone/types.py` | Closed-set binding exists; new adapters need stricter validation before binding and must preserve provider metadata |
| Reviewed/hashable packs | `systemone/pack.py`, `systemone/packs/*.yaml` | Keep logical pack identity stable; record separate provider translation and policy versions |
| Live HTTP transport | `systemone/live.py` | Jev-only wire contract, bearer auth, bounded total deadline, limited retries and optional recording |
| Settings/factory | `systemone/config.py`, `harness/spec.py`, `harness/loader.py` | `stub`, `replay`, `live`; `live` constructs Jev and defaults to `jev-1.13.0` |
| Standalone decisions | `harness/backends/systemone.py`, `systemone/decision.py` | Can reuse a provider-neutral factory; missing keys must not produce a simulated success |
| Coding permission checks | `systemone/compose.py`, `systemone/runtime.py`, `agent/loop.py` | Code composes ALLOW/DENY/ASK; hard denials precede model evaluation; new providers need calibrated policies |
| Tool filtering | `systemone/tool_router.py` | Neutral provider protocol, immutable turn plans, always-keep tools and full-catalogue fallback already exist; construction is hardcoded to Jev |
| Tool discovery and context pruning | `systemone/tool_search.py`, `systemone/context_prune.py` | Discovery uses the factory; pruning has an additional direct Jev construction path |
| HTTP/MCP/SDK routing | `jev_tools/service.py`, `jev_tools/sdk.py`, `tool_gateway/` | Reusable routing core; coordinator, preflight and public commands remain Jev-specific |
| Rubric grading and tuning | `agent/rubric.py`, `systemone/tune.py`, `widgets/systemone_tune.py` | Factory reuse is possible; Tune checks/messages and reproducibility manifests need provider identity and decision cost budgets |
| TUI connection | `providers/connection_profiles.py`, `app/mixins/connect.py` | Jev-only profile and TypeSafe-key guard |
| Native connection | `apps/macos/Sources/SuperQode/ConnectionConfigurationViews.swift` | `SystemOneConnectionView` currently asks only for a TypeSafe key |
| Mac credentials/worker | `desktop_service/service.py`, native `Workspace.swift` | `connect.systemone.key`, Keychain identity and worker injection currently specialize in TypeSafe |
| Evidence | `systemone/audit.py`, `data/eval_packs/decision-*.yaml` | Audit and held-in/held-out starter fixtures exist; synthetic starter labels are insufficient to certify a provider |

The code paths in the table are under `src/superqode/` unless otherwise noted.
Changing only the endpoint or model string will not work: request fields,
authentication, criteria, answer containers and usage fields differ.

## Critical semantic differences

### Confidence thresholds cannot be copied between providers

TypeSafe documents Choice confidence as
`(p_max - 1/n) / (1 - 1/n)`. Google documents Choice confidence as the top
outcome's probability. With three options and top probability 0.80, Jev's
documented statistic is 0.70 while Google's is 0.80. The current 0.75 gate
would treat those equivalent distributions differently. TypeSafe also uses a
spread-based Score confidence, while Google describes top-outcome confidence.

OpenAI returns separate confidence for Choice/Score; its guide recommends
setting thresholds from application labels. Do not assume its statistic matches
TypeSafe or Google. OpenAI predicates expose a probability without a separate
confidence field. Google's binary answer also carries confidence; our existing
Noul model ignores extra fields, so retain it separately if relevant.

Store raw probabilities, vendor confidence and its documented meaning. Calibrate
policies by provider, model, pack hash, translation version and task. A common
top-probability metric could support comparisons, but must be a separately named,
versioned policy change, not a silent rewrite of existing Jev confidence.

Sources: [TypeSafe confidence](https://docs.typesafe.ai/confidence.md),
[Google confidence](https://aistudio.google.com/docs/decisions-api#confidence),
[OpenAI interpretation](https://developers.openai.com/api/docs/guides/decisions#interpret-the-answers).

### Google is close to Jev, but not wire-compatible

Translate `state` into `input`. Serialize structured evidence as explicit text
or supported input content, rather than sending arbitrary Jev JSON as Google
content blocks. Translate binary criteria keys `true`/`false` to Google's
`true_description`/`false_description`. Serialize structured instructions and
criteria deterministically because Google question instructions are text-only.

Validate/remap internal question IDs to the documented 1–64 ASCII key format
and preserve a bijection back to the pack IDs. Validate option keys too. Google
sorts Choice keys in UTF-8 order, with alphabetical tie-breaking; always map
by ID, never assume insertion order. Google scores retain their zero-based
expected value and level distribution.

Google usage fields include `total_input_tokens`, `total_output_tokens`,
`total_tokens` and modality breakdown. Normalize these for our existing usage
display without losing the raw provider fields. Safety blocking returns HTTP
400 with an error code rather than an ordinary answer. Return a typed blocked
evaluation, not a fabricated Noul or an empty success.

### OpenAI requires an explicit translation layer

Translate each internal question ID to a unique `name`. Convert:

- Noul to a `predicate`; incorporate both binary outcome descriptions into
  instructions, since the predicate has no Jev `criteria` map. Map the returned
  `probability` back to Noul without inventing a separate confidence.
- Choice criteria to `choices: [{value, description}, ...]`, retaining string
  option IDs. Convert probability entries `{value, probability}` back to a map.
- Score levels to `levels: [{label, description}, ...]`. Map returned numeric
  indices and probability entries back to the original ordered levels; do not
  round expected scores or accept label/index mismatches.

Use a user `input_json` part for bounded object/array evidence where its documented
shape permits it, or deterministic text for general existing state shapes. Do
not inject repository evidence into developer instructions. OpenAI's structured
JSON input has additional depth, size and value-count limits.

Any question can return `type: refusal` while others receive answers. Match
answers by unique name and validate the full requested set, duplicates and
types. Do not drop a refused question or fill it with a favorable default. For
the first implementation, fail the whole evaluation conservatively if any
required question refuses, preserving refusal metadata. Later partial-result
support requires a versioned per-consumer policy.

Reject an unsupported pack before sending: OpenAI supports at most 400
questions and 10 rubric levels, while existing local types allow larger packs.
Never silently remove questions or collapse rubric levels. Explicit batching
can follow later, with a total deadline, complete-result requirement and
accurate repeated-input costs.

## Proposed implementation

1. Extend settings/spec/loader with an explicit decision `provider`, separate
   from transport `client`. Keep `client: live`, `provider: typesafe` as the
   migration default. Select provider-specific model, endpoint and key defaults.
   Keep existing custom SystemOne-compatible endpoints working; do not identify
   a provider by a substring in a model name or by guessing from its key.
2. Implement Google and OpenAI `SystemOneClient` adapters using existing async
   `httpx` and injected MockTransport. Keep Jev intact. Reuse pooled clients
   within a worker with explicit shutdown, bounded responses and no cross-host
   redirects carrying credentials. Do not route through ordinary chat generation.
3. Put provider selection behind one client factory across standalone packs,
   gates, discovery, filtering, pruning, rubrics, Tune and service surfaces.
   Fix the direct constructors and Jev-only credential/preflight guards in the
   table. Preserve existing `*-jev` commands as TypeSafe-specific compatibility
   aliases; expose generic SystemOne controls without relabeling Google's
   decisions as Jev.
4. Preserve existing deterministic denials, sandbox and approval receipts.
   Provider failure means the normal permission policy remains in force, full
   tool visibility is retained, context is kept, or a standalone run reports
   failure/abstention as appropriate. It must never create an automatic ALLOW.
   Successful enforced model ALLOW can currently preapprove some calls, so
   calibration and opt-in are especially important.
5. Add neutral provider/model identity, resolved model when supplied, request ID,
   latency, question count, normalized/raw usage, refusal/block status, pack
   hash, adapter revision and policy revision to evidence. Unknown costs/tokens
   stay unknown; explicit zero-output usage remains zero. Bind turn caches and
   replay to provider/model, pack, policy, task and project boundaries.
6. Keep one total evaluation deadline including retries, cancellation, backoff
   and any chunks. Honor bounded `Retry-After` for transient failures; never
   retry a safety block, refusal, invalid schema or bad credentials as ordinary
   transient errors. New providers must not inherit an unmeasured latency promise.
7. Add TUI/macOS provider selection and named Keychain storage. Pass only the
   selected decision key to the worker, independently of coding credentials.
   Update external-harness launchers and the local routing service through the
   same provider-aware construction path.

The current lockfile has `openai==2.54.0` and `google-genai==2.12.1`. Google
documents Decisions SDK support from 3.2 onward. Official SDK source inspected
for this review is OpenAI 3.51.0 and Google 3.3.0, and both expose Decisions.
Do not bulk-upgrade the coding SDKs just to obtain these endpoints. Direct REST
using our existing HTTP dependency avoids changing unrelated Gemini/Codex
integrations. If SDKs are chosen instead, verify the exact compatible release
and dependency constraints independently.

## Native and terminal user experience

The SystemOne setup should ask for a **Decision engine**: Jev, Google Gemini
Decision, or OpenAI Decisions. Show the supported decision model, official
documentation, separate API billing and where evidence is sent. Then choose
the coding harness/model independently. Do not put decision-only models in a
normal chat-model picker or suggest they write code.

Reuse a saved provider API key only when the user explicitly chooses it. Keep
session-only and Keychain options. Saving/opening settings makes no inference
request. An explicit **Test decision** sends tiny synthetic evidence after
showing the provider and possible cost; it verifies connectivity, not quality.
Missing keys and unavailable models need actionable guidance and disabled
run controls, rather than a live button that silently does nothing.

Show the decision provider, elapsed time, timeout/fallback status and eventual
result. These are typed responses with no text-token stream to wait for. Stop
the activity indicator on success, refusal, failure or cancellation. Details
such as probabilities and raw JSON should be collapsed by default. Put
thresholds, endpoint overrides and budget controls under Advanced.

Label new setups **Shadow: recommendations only** until calibration is reviewed.
When local coding is selected, state that the optional cloud decision engine
receives bounded evidence. Existing redaction and the 32,000-character general
state cap are valuable protections, not proof that the data never leaves the
device. Airplane/private-local policy must prevent cloud decision requests.

## Evaluation and optimization before enforcement

Build on existing packs, replay/audit and GEPA Tune, retaining group-separated
held-in/held-out data. The bundled six-case synthetic packs are starter fixtures,
not enough evidence for a reliability or release claim. Use reviewed cases
covering routing, irrelevant tools, missing evidence, prompt injection,
destructive commands, exfiltration patterns, Chinese/English instructions and
ambiguous outcomes. Use actual task/test outcomes as independent evidence;
model agreement alone is not truth.

Compare providers on the same frozen questions and evidence. Report task
success, required-tool recall, schema reduction, abstention coverage, selective
error, false ALLOWs, false denials, Brier score/reliability bins for labeled
binary outcomes, categorical log loss, rubric error, p50/p95 latency, timeouts,
and measured cost including question tokens. Tune on held-in data and make
the final decision on untouched held-out data. Derive acceptance targets from
the intended risk/budget, not a vendor's headline benchmark.

Do not optimize only schema reduction: filtering that saves tokens but loses
the required tool is worse. Likewise, a rubric grader alone cannot certify
that code works. Record provider/model/adapter/policy versions in experiment
manifests so changed models do not inherit earlier approvals.

## Acceptance checks for implementation

- Contract fixtures for all three question types, structured instructions,
  custom IDs, criteria translation, score distributions and raw metadata.
- Complete answer-set validation: missing/duplicate/unknown questions, unknown
  choices, invalid score bounds, non-finite numbers and malformed distributions.
  Accommodate documented rounding without silently inventing missing values.
- OpenAI partial refusal and Google safety block follow the consumer's safe
  fallback; no permissive missing-answer defaults.
- Choice/score/question-count limits reject unsupported packs before sending;
  future batching never acts on partial results or resets the outer deadline.
- Cancellation, slow reads, bounded retry, wrong key, missing entitlement,
  429/5xx, redirects and offline policy preserve normal execution boundaries.
- Provider changes do not mutate Jev packs, transfer thresholds, leak another
  provider's key, or contaminate cached turn plans and replay evidence.
- Coverage through standalone backend, Core tool gate, discovery, tool router,
  context pruning, rubric grader, Tune, HTTP/MCP gateway and external launchers.
- TUI and native tests cover provider selection, Finder-launched Keychain access,
  session-only keys, explicit connectivity test, actionable errors and completed
  activity indicators. Native compilation and account smoke tests run on the
  user's Mac validation system.
- Explicit real-account smoke tests for Google and OpenAI confirm endpoint
  access, actual usage and latency. No paid calls during settings display or
  ordinary offline tests.

## Suggested delivery order

First implement provider-aware configuration plus Google and OpenAI adapters
with complete contract coverage. Then wire every routing/service/Tune path
and provider selection in both interfaces before advertising complete support.
Keep new configurations in shadow mode and preserve Jev defaults. Run a shared
held-out comparison before allowing reviewed provider-specific enforcement.
Pool connections and keep
decisions once per turn before exploring cascades or more elaborate routing.

Separately offer Jev 1.14 as an explicit model choice, with multilingual evals
against the pinned 1.13 baseline. Its new Box/image/long-context features are
outside the current three-type SystemOne contract and must not be enabled
implicitly. Local structured-output models such as Qwen/Gemma or Apple's
Foundation Models can be future experimental decision backends, but are not
equivalent calibrated Decisions endpoints. They need their own adapter,
uncertainty evidence and offline evaluation before permission enforcement.

This research does not establish a fastest or most accurate vendor. The
opportunity is a provider-neutral decision plane with measured quality, cost
and latency while SuperQode continues to own policies and evaluation.

## Additional primary sources

- [TypeSafe 1.14 changelog](https://docs.typesafe.ai/changelog.md)
- [TypeSafe release and experimental capabilities](https://typesafe.ai/blog/jev-1-14)
- [OpenAI Decisions Python resource](https://github.com/openai/openai-python/blob/main/src/openai/resources/decisions.py)
- [OpenAI Python SDK metadata](https://github.com/openai/openai-python/blob/main/pyproject.toml)
- [Google Decisions Python resource](https://github.com/googleapis/python-genai/blob/main/google/genai/_gaos/decisions.py)
- [Google binary criteria types](https://github.com/googleapis/python-genai/blob/main/google/genai/_gaos/types/decisions/noulcriteria.py)
- [Google Python SDK metadata](https://github.com/googleapis/python-genai/blob/main/pyproject.toml)

Vendor links and SDK main branches can change after this review. Re-check
request schemas, entitlement, privacy terms and pricing before implementation
or publication. No claim here is based on paid-account runtime measurements.
