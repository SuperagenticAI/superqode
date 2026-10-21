# macOS App Store preparation guide

This contributor handoff covers a future Mac App Store release. Keep it at the
repository root, separate from the public product documentation in `docs/`.
Account configuration, signing records, machine paths and release evidence belong
in private storage outside the repository.

## Current position

SuperQode ships as a Developer ID signed, notarized DMG through its website.
That distribution route is separate from Mac App Store submission. Notarization
acceptance does not establish App Store eligibility or approval.

The app uses a native Swift interface and a bundled Python engine. Its current
coding workflows include external agent processes, existing agent credentials,
project file access and an integrated terminal. The website build is not an
App Store sandboxed distribution. App Store compatibility has not been proven.

## Start here when continuing this work

1. Read [the Mac app guide](apps/macos/README.md) and
   [beta limitations](apps/macos/BETA-NOTES.md). Inspect the current checkout;
   do not assume an earlier version or validation result still applies.
2. Review Apple's current requirements linked below. Establish whether the
   core coding experience can operate within App Sandbox and review rules.
3. Record a capability assessment before changing signing or packaging. Include
   what works, what needs redesign and what requires clarification from Apple.
4. Keep the existing website distribution working. Prepare any store-specific
   implementation as an explicit distribution configuration.
5. Report the proposed feature differences before removing existing workflows.
   This guide is a handoff, not authorization to upload or submit an app.

## First gate: coding capability under App Sandbox

Prove these behaviors in a sandboxed prototype with fixtures before committing
to an App Store release:

- User-selected project access, persistent security-scoped bookmarks, source
  editing and Git operations, including relaunch and revoked access.
- Bundled Python execution, subprocess sandbox behavior, signed native libraries
  and writing state into permitted application locations.
- Supported external agent connections and authentication. Access to another
  agent's files or Keychain items must not be assumed from the website build.
- Terminal commands, build tools and child-process cleanup. An external helper
  must not be treated as a way to bypass sandbox or review restrictions.
- Local model discovery and provider connections with the required network
  entitlements. Distinguish model data from downloaded executable components.
- Agent installation, package installation, plugins and other executable
  downloads. Review each against Apple's rules before exposing it in a store
  configuration; do not assume a developer-tool exemption applies.
- Conversation persistence and handoffs, permission prompts, cancellation and
  recovery when a capability is unavailable.

Apple's review rules require sandboxing for Mac App Store apps and place limits
on installation, downloaded functionality and update mechanisms. Those are
architecture questions for this app, not simply certificate changes. See
[App Review Guidelines, sections 2.4.5 and 2.5.2](https://developer.apple.com/app-store/review/guidelines/).

## Implementation and submission sequence

1. **Architecture:** resolve the capability gate above and agree the supported
   store feature set. Keep account-specific findings and test evidence private.
2. **Build:** prepare an Xcode-supported archive and App Store distribution
   configuration. Configure App Sandbox, necessary entitlements, bundled helpers
   and nested signing. The current DMG scripts are not a verified store exporter.
3. **Identity:** have the account owner confirm the bundle identifier, team,
   seller identity and App Store Connect record. Configure App Store distribution
   signing and provisioning through Xcode or the developer portal. Developer ID
   signing and a notarization credential profile do not replace store signing.
4. **Metadata:** prepare the app description, support and privacy-policy URLs,
   screenshots and icons using existing SuperQode branding. Complete current
   privacy, age-rating, encryption/export and accessibility questions accurately.
   Inspect the app and SDKs for applicable privacy-manifest requirements.
5. **Validation:** test first launch and a complete coding task on a clean Mac,
   plus permissions, credentials, files, terminal, supported protocols, handoffs,
   cancellation, offline failures, accessibility and light/dark appearance. Review
   dependencies and licenses for the actual archived runtime. Do not reuse a DMG
   audit as evidence for a different build.
6. **Beta:** after explicit owner authorization, validate and upload the store
   build using a currently supported Apple tool. Use TestFlight where appropriate;
   provide a safe reviewer workflow without sharing personal agent credentials.
7. **Review:** complete App Review notes explaining execution, external services,
   data handling, installation behavior and any limitations. Obtain owner
   authorization before submission. Do not promise approval or review timing.
8. **Release:** verify the approved build and store listing, then update the
   website links. Store builds must use the permitted App Store update route.

## Source map

| Area | Repository location |
| --- | --- |
| Native interface | `apps/macos/Sources/SuperQode/` |
| Swift package | `apps/macos/Package.swift` |
| App metadata and branding | `apps/macos/resources/` |
| Current build and runtime tooling | `apps/macos/scripts/` |
| Bundled runtime security requirements | `apps/macos/runtime-requirements.txt` |
| Desktop engine and connections | `src/superqode/desktop_service/` |
| Connection and desktop regression coverage | `tests/test_desktop_*.py` |

## Information boundaries

Commit reusable implementation and generic contributor guidance. Keep Apple
account details, team identifiers, signing identities, passwords, API keys,
Keychain profile names, provisioning files, device identifiers, local paths,
submission logs and private operational notes outside Git. Do not include them
in screenshots or example commands. Use disposable projects and scripted agents
for routine tests; real-account tests need the owner's authorization.

## Apple references

Requirements change; recheck these before starting and before submission:

- [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [App Sandbox](https://developer.apple.com/documentation/security/app-sandbox)
- [Preparing an app for distribution](https://developer.apple.com/documentation/xcode/preparing-your-app-for-distribution)
- [Upload builds to App Store Connect](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/)
- [Notarizing software distributed outside the store](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
