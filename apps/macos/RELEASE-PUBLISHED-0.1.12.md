# macOS 0.1.12 website publication

Published 27 October 2026 (UTC), following the user's explicit instruction to
upload despite the outstanding findings in the
[readiness review](RELEASE-READINESS-0.1.12.md).

- macOS version: **0.1.12 / build 13**, **Public Beta**, Apple Silicon.
- Bundled Python engine: **2.26.0**. PyPI was not published in this operation.
- Source commit: **`32ab9721`**, branch `feat/macos-harness-engineering`.
  No merge into main or release tag was created by this upload.
- Production app and DMG signed with the existing Developer ID certificate.
  Both accepted by Apple; tickets stapled and validated. Gatekeeper accepted
  the app as Notarized Developer ID and accepted the signed DMG.
- App notarization submission: `715f283e-98c8-4396-b097-daeae798fdc5`.
- DMG notarization submission: `02e7283c-7bd5-48d2-800d-0b66ed2cab46`.
- SHA-256: `1866a61948209120a81dd288299b6863b0f683b548c9c2637e98cb2e81640d29`.

The existing FTPS uploader transferred the versioned archive and updated latest,
checking remote bytes before promotion. It then downloaded both public DMGs and
checksum files over HTTPS and verified that they matched the local artifact.
Credentials were read from outside the repository; none were added to Git.

- [Permanent latest DMG](https://superqode.dev/downloads/macos/latest/SuperQode-arm64.dmg)
- [Permanent latest checksum](https://superqode.dev/downloads/macos/latest/SuperQode-arm64.dmg.sha256)
- [Versioned DMG](https://superqode.dev/downloads/macos/0.1.12/SuperQode-0.1.12-arm64.dmg)
- [Versioned checksum](https://superqode.dev/downloads/macos/0.1.12/SuperQode-0.1.12-arm64.dmg.sha256)

Local artifacts are under `apps/macos/release/`. Local evidence logs:
`/tmp/superqode-0.1.12-production-build.log`,
`/tmp/superqode-0.1.12-production-notarize.log`,
`/tmp/superqode-0.1.12-notary-app.json`,
`/tmp/superqode-0.1.12-notary-dmg.json` and
`/tmp/superqode-0.1.12-godaddy-upload.log`.
