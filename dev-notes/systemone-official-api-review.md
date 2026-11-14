# SystemOne official API contract review

Reviewed on 14 November 2026 after the first cloud validation. This follow-up
retrieved official vendor guides, TypeSafe's OpenAPI document and the current
OpenAI/Google SDK definitions over HTTPS. All sources in the
[source manifest](systemone-official-api-sources.json) returned HTTP 200. The
manifest records retrieval time and content hashes; it contains no credentials.
No paid provider inference was performed.

## Verified contracts

| Provider | Models | REST endpoint | Authentication | Translation |
| --- | --- | --- | --- | --- |
| TypeSafe | `jev-1.13.0`, `jev-1.14.0` | `POST https://api.typesafe.ai/v1/systemone` | Bearer key | `state`, named question map, answer map |
| Google | `gemini-decision-1` | `POST https://generativelanguage.googleapis.com/v1beta/decisions` | `x-goog-api-key` | `input`, named question map, answer map |
| OpenAI | `gpt-6-luna` | `POST https://api.openai.com/v1/decisions` | Bearer key | `input`, named question array, answer array |

Primary references:

- [TypeSafe model IDs and account model listing](https://docs.typesafe.ai/models.md),
  [OpenAPI](https://api.typesafe.ai/openapi.json) and
  [request rules/errors](https://docs.typesafe.ai/api/errors.md).
- [Google Decisions REST guide, examples and limits](https://aistudio.google.com/docs/decisions-api),
  [model](https://aistudio.google.com/docs/models/gemini-decision-1) and
  [official Python types](https://github.com/googleapis/python-genai/blob/main/google/genai/decisions.py).
- [OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions),
  [create reference](https://developers.openai.com/api/reference/resources/decisions/methods/create),
  [request types](https://github.com/openai/openai-python/blob/main/src/openai/types/decision_create_params.py)
  and [response types](https://github.com/openai/openai-python/blob/main/src/openai/types/decision.py).

The adapters use REST directly, so Decisions SDK releases are not required and
existing coding-model SDK versions do not need to change. OpenAI's optional
organization/project headers remain supported for shell-launched processes.
Decision API billing and access are separate from consumer coding subscriptions.

## Independent contract evidence

`tests/fixtures/systemone/official-api-contracts.json` contains ten short
source-linked examples derived from the published guide/OpenAPI examples.
Per-case notes describe each adaptation. These are documentation fixtures,
not captured vendor responses. Tests cover both pinned Jev versions, for
thirteen request/answer cases in total.

Google examples cover yes/no, binary criteria, choice and score. The score
example intentionally retains Google's rounded probabilities, whose sum is
1.01, and the guide's reported score. The adapter accepts documented rounding
without silently normalizing probabilities.

OpenAI examples cover predicates, categorical probabilities and weighted scores.
Names are remapped to stable wire IDs, and rubric labels to numeric indices,
matching the request we actually send. Responses are matched by name; a refusal,
missing question, unexpected label or duplicate cannot produce partial success.
The predicate's image example is explicitly adapted to synthetic text, because
this harness sends text evidence.

TypeSafe fixtures are assembled from the published OpenAPI field examples.
Custom SystemOne-compatible endpoints retain their legacy behavior; the
TypeSafe-specific ten-level rubric limit applies to the official endpoint.

## Corrections from this review

- All three transports now use bounded streaming response reads and strict JSON
  decoding. Redirects never forward credentials, including with an injected
  HTTP client configured to follow redirects. Non-finite overflow, duplicate
  response fields and malformed usage objects are rejected.
- TypeSafe now honors `Retry-After`. Shared handling also recognizes HTTP dates
  and OpenAI's millisecond retry header. The total evaluation deadline bounds
  all waits and retries. A long server wait is not shortened into an early retry.
- Errors explain key/project permissions, account/region model access, request
  limits, rate limits, exhausted billing and temporary service outages. Known
  quota exhaustion is not retried. Google's HTTP 400 `API_KEY_INVALID` detail
  produces key setup guidance. Upstream messages and bodies are not displayed.
- Invalid pasted keys fail before transport with setup guidance. Google option
  names reject DEL/C1 controls and non-ASCII spaces before a paid request.
- TypeSafe rejects a conflicting answer primitive while preserving compatibility
  with legacy responses that omit the type field.
- Native **Test decision** now checks yes/no, choice and score in one synthetic
  request. The same `provider_check` pack is installed with the Python package
  and available in CLI/TUI. It does not execute tools, review a policy or assert
  that the model's judgments are correct.
- macOS setup uses existing Google/OpenAI marks and the official TypeSafe mark.
  Asset provenance is retained in the source manifest. No remote image load is
  needed when opening the page.

## Supported scope and account validation

The harness supports its existing Noul/Choice/Score primitives with bounded
text or serialized JSON evidence. It does not expose every feature of each
vendor's API: media uploads, TypeSafe Box questions/experimental long-context
headers and custom OpenAI cache controls are not added by this change.
OpenAI's documented implicit prefix caching can operate without extra fields.
The client deliberately caps request and response bodies at 4 MiB, below vendor
upload limits; the regular decision pipeline applies its smaller evidence bounds.

No API key for these providers is configured in this cloud workspace. The
explicit live smoke tests remain skipped. Public documentation and offline
contract tests cannot verify a particular account's entitlement, region, billing,
latency, calibration or current service availability. Native Swift compilation,
Keychain and a real Mac setup flow also remain unverified here.

To validate an account, use **Test decision** on the Mac or the documented CLI/TUI
`provider_check` flow. The explicit opt-in cloud smoke tests use the same probe
and exercise all three primitives for each configured model. Each probe is one
small metered request with synthetic data. The result certifies connectivity and
answer shape only. Keep new policies in shadow mode until held-out evaluation.

The latest executed case list and transport metadata are in
[cloud validation](systemone-validation.md). GitHub CI and release publishing
remain untouched.
