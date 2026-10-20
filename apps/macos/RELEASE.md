# Native macOS release requirements

The app is a runnable native preview, not a completed public release. Desktop code is Swift/SwiftUI/AppKit. Execution uses the original bundled Python engine, not a Swift port of the terminal/core product.

## Verified on the build machine

- Release SwiftPM build produces an arm64 Mach-O executable using SwiftUI/AppKit.
- Ad hoc bundle signature passes deep, strict verification.
- Native packaged-app smoke test passes private pipe startup, shared HarnessSpec definitions, ACP routes, Hub entries and evaluation packs, shell-check output, setup evaluation, file-boundary rejection, task streaming and same-session continuation against a local fixture provider.
- The related desktop/harness/ACP Python suites pass 446 tests with one skipped, including real worker credential handoff, session override removal, configured-versus-verified readiness, missing/embedding-model checks and credential redaction from output, check artifacts and stderr.
- Native Keychain save/read/update/delete passes with an isolated dummy item; cleanup removes it. Session-only fixture keys reach the worker and are absent from persisted engine state.
- Brand asset preflight validates ten Mac icon slots and an opaque RGB 1024px icon rendered from the repository SVG. The application bundles the compiled asset catalog.
- Direct A2A/UHP discovery, streaming, exact continuation and acknowledged-cancellation fixtures pass, with bearer credentials excluded from saved requests and redacted from responses. A scripted subscription CLI passes native approve/deny handling, trusted profile resolution and API-key stripping; no real vendor subscription was billed.
- Direct native source editing, source-file creation, staging and unstaging are implemented with project/revision/running-task guards. Explicit project text attachments have scoped UTF-8 and size validation.
- The simplified coding composer, shared-catalog Connect ladder, native Back navigation, shared brand surfaces and gradient response renderer compile in the release build and pass the packaged smoke test. Diagnostic view renders were inspected; real running-app accessibility and visual acceptance are still required.
- DMG and ZIP packaging scripts produce local install artifacts.

These checks do not establish paid-provider quality, universal feature parity or public distribution readiness.

App Store submission is a separate channel from a notarized download. See the [App Store preparation guide](app-store/README.md) and [feature coverage audit](FEATURE-COVERAGE.md). The current binary is not sandboxed or upload-ready.

## Required before public shipment

- Developer ID signing and Apple notarization. This workstation currently has no valid Developer ID signing identity. Ad hoc signing verifies local bundle integrity but does not establish public distribution trust.
- Validate nested CPython/native extension signing with hardened runtime, notarize and staple, then verify first-launch quarantine behavior on a clean Mac.
- Test Apple Silicon on the declared minimum macOS version. Intel is not built or validated.
- Real provider and supported external-agent testing, approval recovery and authentication from a Finder launch. Verify Keychain restoration and authorization across app upgrades with the final Developer ID identity, including a locked Keychain.
- Live paid optimization with explicit budget consent and candidate adoption against a disposable project. Setup checks deliberately skip model execution.
- Accessibility and keyboard-only testing, VoiceOver, contrast and large text, long streams, large diffs and UI responsiveness.
- Finish broader onboarding and runtime management. The shared Connect ladder, existing subscription routes, direct A2A/UHP streaming tasks, HarnessSpec import/editor, native API-key setup and installed Ollama selection are implemented; shared login/install flows, vendor-key paths, RLM/routing forms and SystemOne are now mapped; model downloads and managed local-engine workflows are available through native command forms; multi-field enterprise auth retains the shared external configuration prerequisites.
- Complete the coverage audit for terminal features: Tools exposes typed native forms for WorkOrders, skills/memory/MCP, refinement/promotion and additional optimizers. A durable explicitly started coding queue is implemented. A live WorkOrder board, native PTY, direct chat, image attachments and supported-runtime steering are implemented. Explicit built-in context compaction and token-window controls are implemented. Per-session fork/tree and owner-specific commands, global approval-mode switching, bespoke resource browsers and optimizer dashboards still require acceptance mapping. A dedicated PR dialog is additional product scope.
- Safe migration, recovery and a signed update strategy. No automatic update mechanism ships in this preview.
- License and notice review for bundled runtime dependencies.

## Current technical boundaries

Resolved HarnessSpec definitions and supported catalog connections execute through the native app. Native builtin sessions continue; ACP requires advertised resume and an unchanged route. Vendor runtimes require a resumable thread. A2A/UHP stream and continue against the selected server; cancellation reports server acknowledgement or an explicit unconfirmed failure. Remote descriptors persist, while manually supplied credentials must be reconnected. This is not remote control of the Mac or a mobile access service. Project checks and advanced workflow commands execute as the current user. Tool policy remains enforced by the selected harness; the app is not an OS sandbox.

Evidence exports contain task text, tool details and potentially project content. Review before sharing. Closing the app with active work asks before stopping runs. Interrupted history is retained and is never automatically replayed.
