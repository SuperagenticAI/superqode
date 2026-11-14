# SystemOne Google/OpenAI implementation handoff

Implemented against main after the 14 November 2026 ecosystem review.
User instruction: do not run tests, native builds, CI, or paid inference here.
None were run for this implementation. Source formatting and CLI help fixture
generation were performed; generating help never invokes command callbacks.

## Implemented surfaces

- `systemone/providers.py`: one provider descriptor source, supported model IDs,
  endpoints, key variable names and official setup links. Existing Jev 1.13 stays
  pinned; Jev 1.14 is an explicit choice.
- `systemone/api_clients.py`: Google/OpenAI native REST adapters using existing
  HTTP dependencies, with no vendor SDK upgrade. Translate structured questions,
  binary criteria, categorical distributions and ordinal levels. Validate complete
  answers, finite numbers, distributions, duplicate fields, refusals, bounds,
  question-count limits, rubric limits, and provider endpoint identity.
- `systemone/config.py`, HarnessSpec/loader/schema: explicit provider and reviewed
  policy fields. Existing TypeSafe/custom-compatible settings retain their defaults.
  Pinned profiles retain provider/model/policy identity against ambient selection
  overrides. A generic decision-key variable keeps a saved decision key separate
  from a coding key for the same vendor.
- Native AgentLoop tool filtering, permission gate, tool discovery, context
  pruning and rubric grading use the same provider selection. Hard deterministic
  denials remain ahead of model evaluation. Unreviewed Google/OpenAI profiles
  remain in shadow mode; pruning cannot remove context under an unreviewed policy.
- Standalone backend and typed outputs retain the shared pack and binding logic.
  Recordings use the common replay format; replay retains available provider/model
  and usage metadata. Decision reports include per-provider/model summaries.
- CLI adds `harness decision-providers`, `harness decision`, independent decision
  flags on `harness run`, and provider/model selection on Tune and routing groups.
  `serve decisions` aliases the existing authenticated routing HTTP/MCP service.
- TUI adds two connection profiles, provider listing/selection, direct pack
  connections, status/help and completion entries. Tune has its own decision
  provider/model controls, independent of the reflection model.
- macOS adds provider/model selectors, official links, session-only or named
  Keychain keys, explicit key reuse, an explicit connectivity action, actionable
  failures, bounded progress state, shadow explanation, reviewed enforcement,
  and project-owned harness creation before choosing the coding model.
- Mac project restore loads saved decision keys silently when permitted. Worker
  credentials are scoped to the selected decision engine; non-secret configuration
  is kept out of the secret-value redactor. Tune derives this selection from its
  saved manifest rather than a client-supplied arbitrary profile.
- External routing launchers persist provider/model/review preferences without
  keys. Old launcher names and Python imports remain usable; neutral routing
  aliases use the same implementation.
- `systemone_rubric` is accepted alongside `jev_rubric`. Acceptance/evidence
  validation and the local-only remote guard recognize both names.
- Public provider setup guide and Unreleased notes are checked in. CLI help
  fixtures were regenerated for the pinned Click and alternative Click renderer;
  no test functions or command callbacks were invoked.

## Intentional behavior

Google/OpenAI native adapters use only their documented decision endpoint and
refuse redirects carrying credentials. Custom SystemOne-compatible services use
the existing TypeSafe wire adapter. Native adapters do not silently downgrade to
chat generation, drop questions, alter rubric scales, or make partial refusals
look like successful complete decisions.

The reviewed-policy acknowledgement is a user opt-in, not evidence or a quality
certificate. It resets in native setup when provider/model changes. Existing Jev
behavior is preserved. Real calibration and provider access still depend on the
user's account and reviewed examples.

The normal setup page performs no model requests. Its Test decision action is
explicit, sends only synthetic evidence, reports connectivity only, and can incur
provider charges. Paid account tests were not performed during development.

## Validation for the user's system

These checks are for the validation owner to run later, not checks performed here.

1. Build the Mac app and run the project's Python/Swift checks. Exercise CLI help,
   new TUI completions, provider selection and the existing Jev/custom endpoint
   regressions. The source implementation is not a native compile result.
2. Use each provider with all three primitive question types. Inspect request
   shapes, auth headers, complete answers, usage, recordings and replay. Include
   an OpenAI partial refusal, a Google safety block, incomplete/duplicate answers,
   non-finite probabilities and unsupported rubric/question sizes.
3. Exercise total deadlines, cancellation, transient retries and redirect refusal.
   Confirm failures retain normal permissions, all tools and original context as
   appropriate. A standalone failed evaluation must not report successful output.
4. On the Mac, use session-only keys, named Keychain keys, restart from Finder and
   explicit saved-key access after a silent Keychain read fails. Verify no key is
   present in a profile YAML, job request, event, subprocess shell environment or
   saved experiment. Test different coding and decision keys for the same vendor.
5. Switch between project profiles using different decision providers. Inspect the
   worker environment and ensure a prior profile's key/model/review status does not
   transfer. Resume an existing thread and verify its harness identity remains.
6. Check shadow and explicitly reviewed enforcement through permission gates,
   discovery, filtering, pruning, rubric evaluation, Tune and HTTP/MCP. Confirm the
   neutral rubric alias remains blocked by local-only remote policies.
7. Prepare Tune experiments with Google/OpenAI and a separate reflection provider.
   Reopen them with different ambient selection variables and verify the saved
   provider/model remains pinned. Check sealed examples and candidate evidence
   before deciding whether to adopt a candidate.
8. With real account keys and explicit consent, verify basic inference and a tiny
   coding/tool task. Then compare independently graded held-out outcomes, required
   tool recall, false approvals, abstention, latency and measured cost. Connectivity
   alone is insufficient to certify any provider's decision policy.

## Publication

No version bump, tag, PyPI upload, signed app, notarization or release was made
for this work. CI is skipped on the implementation commit as requested. The
release owner must package a new Python distribution and a rebuilt Mac app with
the new engine when ready; an existing signed DMG cannot gain these source changes.
