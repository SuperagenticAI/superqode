# SystemOne cloud validation

Validation completed in the Linux cloud workspace on 14 November 2026.
**761 passed, 0 failed, 9 skipped** across 36 test files.
GitHub CI was not started. No release was published.

[Machine-readable evidence](systemone-validation-results.json) records every
collected case ID, outcome, duration and skip reason, plus 225 mocked decision
HTTP attempts. It includes source hashes and the base source commit. Requests
are explicitly labelled `httpx.MockTransport`; they are not live vendor calls.
The evidence contains no request prompts, response bodies or authentication values.

The follow-up [official API contract review](systemone-official-api-review.md)
links the vendor guides, SDK definitions and hashed source manifest. Documentation
examples have independent request/answer fixtures in addition to synthetic cases.

## Decision APIs exercised

| Provider | Requested model | Mocked HTTP attempts |
| --- | --- | --- |
| google | `gemini-decision-1` | 88 |
| openai | `gpt-6-luna` | 85 |
| typesafe | `jev-1.13.0` | 40 |
| typesafe | `jev-1.14.0` | 12 |

All four models were exercised with Choice, Score and Noul/predicate questions,
usage, recording and replay. Additional cases exercise real backend execution,
stream event projection, permission composition and rubric grading using the
native adapters with the final HTTP transport replaced by fixtures.

## Recorded case coverage

- Exact endpoints, POST payloads, provider authentication schemes, API model IDs,
  structured instruction/criteria translation and non-ASCII internal question IDs.
- Missing keys; separate coding and decision keys for the same vendor; pinned
  provider/model/policy settings; custom no-auth SystemOne-compatible endpoints.
- Shadow defaults, explicit reviewed enforcement, offline gating, provider-specific
  routing and frozen Tune configuration.
- All three primitives, reordered answers, integer-valued float score indices,
  complete answer sets, probabilities, rubric legends, numeric types and limits.
- Missing/unknown/duplicate questions, wrong answer types, missing probabilities,
  invalid sums, negative values, non-finite JSON numbers and invalid choices/scores.
- HTTP 400 safety blocking, 401, 403, 404, 422, 429, 500, 502, 503, 504 and 529;
  retry success and exhaustion; redirect refusal; invalid JSON; bounded responses.
- Total deadlines across slow body reads and retry waits; caller cancellation;
  question-count, rubric-size and request-size rejection before transport.
- Opt-in private recording, sanitized success/failure outcomes, retry histories,
  token telemetry, failed-record replay rejection, mixed recording directories,
  concurrent evaluation isolation and successful inference despite recording failure.
- Native configuration/provider RPCs, synthetic connectivity checks, secret-free
  project profiles/database, real worker subprocess environment construction,
  TUI mounting/provider selection/decision execution and CLI command contracts.
- Reserved decision-key removal from inherited shell environments, including when
  the ordinary shell environment or allowlist would otherwise include it.
- Existing decision packs, composition, discovery, context pruning, audits, Tune,
  HTTP/MCP SDK routing, desktop lifecycle/threads/evaluation, governance and shell
  policy regressions.

## Issues found and fixed

The initial regression run found two assertions tied to Jev-only wording; those
now assert the provider-neutral wording. New recording tests found token counters
being hidden by the broad secret-name matcher. Recording now preserves only known,
typed telemetry fields while keeping credential redaction. Validated answer IDs
such as `contains_token` remain replayable, and the known API key is masked if
it appears elsewhere in a record. Existing recording hooks remain compatible.

Worker boundary review also found that the reserved decision key could reach a
model-spawned shell under ordinary environment inheritance. The shell environment
builder now always removes that reserved key. Both inherit/filter policies and the
allowlist case have regression coverage.

## Official contract follow-up

The latest run adds thirteen documentation-derived request/answer cases across
all four models, plus regression checks for server retry instructions, billing
exhaustion, actionable setup errors, malformed keys, TypeSafe response types,
Google option controls and bounded/strict response decoding. CLI, mounted TUI
and native RPC tests cover the new `provider_check` pack. Native setup checks
yes/no, choice and score in one explicit synthetic request.

A local Python wheel was built, checked for the updated adapters/check pack and
imported outside the source tree. The package-check evidence is
[recorded separately](systemone-package-validation.json). The wheel was not
published and no version changed.

## Skips and limits

Four existing TypeSafe live tests skipped without `TYPESAFE_API_KEY`. Four new
live checks for Jev 1.13, Jev 1.14, Gemini Decision 1 and GPT-6 Luna skipped because
paid API smoke is opt-in. No TypeSafe, Gemini/Google or OpenAI provider API key is
configured in this workspace. Vendor account entitlement, actual decision quality,
real provider latency and live billing were not verified.

One real GEPA optimizer test skipped because the optional GEPA package is absent.
The remaining Tune tests, including sealed-data and fake-optimizer contracts, ran.
The macOS Swift UI, Keychain and native compilation need a Mac; Python desktop
RPC and subprocess tests do not substitute for those checks.

For a later explicit paid smoke run, configure the selected vendor keys privately
and set `SUPERQODE_TEST_LIVE_DECISIONS=1` before running
`tests/test_systemone_provider_live.py`. The tests use tiny synthetic evidence
and record their calls privately. Never put a key in this report or repository.

## Reproduction

The reusable opt-in evidence plugin is `tests/systemone_evidence.py`. Load it with
`-p systemone_evidence` and `--decision-evidence=PATH` while including `src:tests`
in `PYTHONPATH`. It records case outcomes and metadata for mocked decision HTTP
calls, without altering the provider response or invoking live calls itself.

The executed suite included `test_systemone_*.py`, context pruning, decision
evaluators, Jev SDK, connection profiles, CLI contracts, desktop configuration,
service/threads/tuning/evaluation, harness acceptance, discovery, policy, governance
and Herdr boundary tests. Ruff lint, public documentation style and diff whitespace
checks also passed. Full logs and JUnit output are retained under `/tmp` in the
current cloud workspace; the checked-in JSON preserves per-case evidence.
