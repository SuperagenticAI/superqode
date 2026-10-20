# Native Connect acceptance

Scope: finish Connect before expanding terminal feature parity. The native menu reads the shared terminal connection profiles rather than maintaining a second list.

## Start coding

Open a project → Connect → Connect to an existing harness → Subscriptions → select an agent you already use → sign in if needed → Start coding. The selected agent owns its model and harness; redundant model selection is hidden.

For your own model, use Connect a harness with your model, select the harness, then choose its supported local or API-key model route. Advanced routing is optional.

## Implemented paths

| Path | Native behavior | Acceptance evidence |
|---|---|---|
| Existing subscription | Shared vendor routes; subscription billing overrides removed; agent-owned models; exact resume where supported | Scripted runtime and real CLI subprocess tests; real accounts pending |
| Sign-in and installation | Browser/device progress, cancellation, embedded interactive login terminal, reviewed catalog installer command | Shared login and cancellation tests; vendor installation/account checks pending |
| Harness plus model | Shared ownership ladder, provider allow-lists and declared credential mappings, Prime RPC attachment | Catalog, credential boundary and route tests |
| ACP | Agent selection, streamed coding, host permissions, advertised model/mode/config controls, slash commands, exact supported resume | Local ACP subprocess writes code and runs approved commands; denial and escape tests |
| A2A | Agent Card discovery, bearer/OAuth/header/mTLS configuration, streaming/polling, exact continuation and acknowledged cancellation | Local HTTP fixtures passed in full integration run; fresh rerun currently sandbox-blocked |
| UHP | Server/harness discovery, direct streaming, bearer configuration, continuation and acknowledged cancellation | Local HTTP fixtures passed in full integration run; fresh rerun currently sandbox-blocked |
| Build/configure | Shared guided wizard, presets, YAML, RLM sandbox/budgets/tool settings, A2A routing, SystemOne and vendor keys | Validation, preservation, exclusive-create and credential redaction tests |
| Navigation | Back, root breadcrumb, Escape, top-anchored pages, independently scrolling forms | Packaged native smoke; interactive accessibility acceptance pending |

Unsupported experimental plan entries remain explanatory guidance, matching the terminal. Credentials being saved, or a launcher being detected, never counts as a verified connection.

## Release acceptance still required

Use real accounts to sign in, code, approve/deny, cancel and resume each supported vendor adapter. Check a clean Mac with supported macOS versions and installed local inference prerequisites. Review native navigation, keyboard access, contrast and Reduce Motion interactively. These checks require the actual accounts and environment; fixture success does not establish them.

The app communicates directly with the selected provider or remote agent. There is no SuperQode cloud relay. Remote peers receive prompts and explicitly selected context; OAuth credentials remain in the shared local credential store, while manually supplied remote credentials must be reconnected after restart.

See [feature coverage](FEATURE-COVERAGE.md) for the separate broader parity backlog and [release requirements](RELEASE.md) for signing, notarization and App Store blockers.
