# Strands release validation

Review date: 1 November 2026. Implementation baseline: `c7cc683904602e273eefbf6626e5cc7356119ad8`.

## Release status

The backend has passed local runtime, SDK, desktop and native UI validation on
Apple Silicon. Live AWS Bedrock and hosted API-key provider inference still
require credentials. This report does not authorize merging, tagging or publishing.

## Corrections made during validation

- Forward the shared OpenAI `OPENAI_API_BASE` endpoint as the SDK's
  `OPENAI_BASE_URL`, retaining explicit `OPENAI_BASE_URL` precedence.
- Let upstream detect caching support for `auto`. Explicitly passing `auto`
  previously rejected the default Ollama preset before making a model call.
- Advertise desktop session continuity for Strands when sessions are enabled.
  The native app previously started a new session on each follow-up.
- Add a separate wall-clock worker deadline, including time suspended in a UI
  event consumer, without cancelling that consumer. Active tools respect both
  execution deadlines.
- Add SDK and desktop integration coverage, Responses API fixtures and a
  selectable native smoke harness to the macOS CI workflow.

## Completed checks

| Check | Evidence |
| --- | --- |
| Selected Python regressions | 318 passed, including nine actual SDK integration tests |
| Native Swift tests | 63 passed on the original feature branch snapshot |
| Actual isolated SDK | Harness 0.3.3, SDK 1.63.0, Monty 0.0.23 |
| OpenAI adapter | Local Responses API fixture, governed file read and scoped credential forwarding |
| Ollama adapter | Local HTTP fixture, usage, errors, saved credentials and restored sessions |
| Real local inference | Ollama `qwen3.5:2b` read a disposable file through the governed `read` tool and returned `STRANDS_LIVE_74921`; 1603 total tokens |
| SDK execution limit | Token-limited run rejected as unsuccessful |
| Desktop process | Default preset runs and a follow-up restores its session and tool history |
| Native app smoke | Strands selected in an ad-hoc signed debug app; two Responses API fixture requests, session continuation and ephemeral app credentials verified |
| Permission boundaries | Deny/ask, read-only mode, symlink escape, command filtering and cancellation regressions passed |
| Wheel | Built and installed in a fresh temporary environment; setup and doctor passed outside the source checkout |
| Static checks | Ruff lint/format, documentation style, release metadata and diff whitespace passed |

The SDK tests use local fixtures and do not establish hosted-provider access or
model quality. The real local-model check is a bounded execution smoke test,
not a comparison against SuperQode's existing backend.

## Distribution validation

A Developer ID release build and notarization validation are in progress.
This section must be updated with their actual results before treating those
checks as complete. The published application remains unchanged.

## Remaining provider validation

No AWS profiles or supported saved provider keys were available to this review.
Before declaring Bedrock or hosted providers production-validated, run bounded
inference with actual authorized credentials and the intended models/regions.
Check successful streaming and tool calls, authentication errors, cancellation,
and timeout/limit behavior. OpenAI-compatible endpoints must support the
Responses API used by this pinned Strands harness.

## Reproduce the SDK checks

```bash
superqode harness strands setup --python /tmp/strands-check/bin/python
SUPERQODE_TEST_STRANDS_PYTHON=/tmp/strands-check/bin/python \
  .venv/bin/python -m pytest -q tests/test_strands_backend.py \
  tests/test_strands_setup.py tests/test_strands_runtime_integration.py
```

For a built macOS application, the fixture runner supports:

```bash
SUPERQODE_STRANDS_PYTHON=/tmp/strands-check/bin/python \
SUPERQODE_SMOKE_HARNESS=strands \
SUPERQODE_SMOKE_APP=/absolute/path/to/SuperQode.app \
SUPERQODE_SMOKE_ARTIFACTS=/tmp/strands-native-artifacts \
  python3 apps/macos/scripts/smoke-test.py
```

The runner uses a disposable project and state directory, local provider
fixtures and test-scoped native credential storage.
