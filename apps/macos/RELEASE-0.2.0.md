# macOS 0.2.0 release preparation

Target: **0.2.0 / build 14**, Public Beta, bundled engine **2.26.0**.

This is a version and documentation update to the published 0.1.12 harness
engineering build. It changes no application logic, dependency declarations or
engine version. Preserve the [0.1.12 publication record](RELEASE-PUBLISHED-0.1.12.md)
and its [readiness findings](RELEASE-READINESS-0.1.12.md); renumbering does not
resolve those findings or revalidate a new installer.

The existing app/DMG must be rebuilt with the new Info.plist, signed, notarized,
stapled and uploaded under the new version. Renaming the old DMG does not change
its embedded app version and would leave its signed metadata at 0.1.12. Do not
announce the new download as available until the new artifact and its published
checksum are verified. This preparation does not create a tag or publish a release.

## Announcement draft

**SuperQode for macOS 0.2 — the harness engineering update**

Evaluate your harnesses, review routing decisions, and explore bounded
optimization in a native Mac workspace. This update brings suite diagnostics,
held-out baseline/candidate comparisons, guided tuning with saved judgments,
and reviewed candidate adoption. Start with a credential-free setup check or
offline practice examples before running your own live experiments.

Available for Apple Silicon on macOS 14 or later as a public beta. Provider
charges apply to live execution. The release remains subject to the documented
limitations; this announcement does not claim full TUI parity or guaranteed
improvements for every model or project.

Publish this draft only after the 0.2.0 download is actually available.
