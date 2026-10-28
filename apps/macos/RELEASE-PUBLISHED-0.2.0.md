# macOS 0.2.0 and Python 2.30.0 publication

Published **28 October 2026**, following the user's request to release the new
main versions, upload to GoDaddy and update the website.

## Source and versions

- Release source: `8dd3101e25802a3cf1a34bd339522022b5b0d41c` on main.
- macOS: **0.2.0 / build 14**, **Public Beta**, Apple Silicon, bundled engine
  **2.30.0**. Runtime provenance records the release source above.
- Python: **2.30.0**, annotated tag **v2.30.0** at the same source commit.
- Website: `SuperagenticAI/superqode-web` main commit
  `9fcfa6f539f3a72be998f97d4ce3cee7d5010ba7`.

The version update changes no application logic relative to the published 0.1.12
harness build. The new Python publication includes the harness engineering work
since Python 2.25.0. The [earlier readiness findings](RELEASE-READINESS-0.1.12.md)
remain open; renumbering and successful publication do not resolve them. The app
and website retain Public Beta labeling rather than claiming a stable certification.

## macOS distribution

The fresh production app passed its isolated native smoke test, including task
streaming, workspace navigation, evaluation and comparison inspectors, saved
offline tuning judgments and rejection of live synthetic practice execution.
The 46 focused publication, tuning, acceptance and lifecycle contracts passed.
The application code is the same code covered by the earlier 2,901-test review;
that prior run is not presented as a new full-suite local run.

The app and DMG were Developer ID signed, accepted by Apple, stapled and validated.
Gatekeeper accepted both. Apple submission IDs:

- App: `d44929f7-a6b3-431f-b671-fde03cca97b2`.
- DMG: `e979c869-71c4-4615-ba6f-27fa07e9373c`.

DMG size: **177,098,757 bytes**.
SHA-256: `f84e2a0411eb2434720c65a3194d93cb6f25a93dcd01c1600148dcc3e78e03b4`.

The existing external-credentials FTPS uploader verified remote bytes before
promotion, then downloaded both public installers and checksum files over HTTPS
and checked their hashes. Credentials remain outside Git.

- [Permanent latest DMG](https://superqode.dev/downloads/macos/latest/SuperQode-arm64.dmg)
- [Permanent latest checksum](https://superqode.dev/downloads/macos/latest/SuperQode-arm64.dmg.sha256)
- [Versioned DMG](https://superqode.dev/downloads/macos/0.2.0/SuperQode-0.2.0-arm64.dmg)
- [Versioned checksum](https://superqode.dev/downloads/macos/0.2.0/SuperQode-0.2.0-arm64.dmg.sha256)

## Python publication

The [Publish workflow](https://github.com/SuperagenticAI/superqode/actions/runs/40756241295)
completed successfully, including its verify and Docker-backed RLM contract gates,
PyPI publication and GitHub release creation.

- [PyPI 2.30.0](https://pypi.org/project/superqode/2.30.0/)
- [GitHub release v2.30.0](https://github.com/SuperagenticAI/superqode/releases/tag/v2.30.0)
- Wheel SHA-256: `f5402439fd2705551e82e33efe48f3f1c0daa13812d4a49156121a92196f8740`.
- Source distribution SHA-256: `8411c54848957042677c72adfa4dcfbe1603afb68067cced895e8a82fb6cdb9f`.

A fresh Python 3.13 environment installed `superqode==2.30.0` directly from PyPI
with normal dependency resolution. Compatibility checks passed for 108 installed
packages. `superqode --version`, `sq --help` and harness/tuning module imports
passed from installed site-packages. This check does not cover every optional extra.

## Website

The website's download metadata now records 0.2.0, the exact artifact size and
checksum. Its macOS section describes suite diagnostics, held-out comparisons,
guided tuning, saved judgments, offline practice and explicit live execution
consent. Download and checksum buttons retain permanent latest URLs.

All three download-integrity tests passed, and the static build generated 87
pages. The [GoDaddy deployment](https://github.com/SuperagenticAI/superqode-web/actions/runs/40758125014)
completed successfully. The public homepage was fetched over HTTPS and verified
to contain the new 0.2.0 version, feature announcement and latest download/checksum
links. React's server-rendered text boundaries were normalized for the version check.

## Local evidence

- `/tmp/superqode-0.2.0-runtime.log`
- `/tmp/superqode-0.2.0-production-build.log`
- `apps/macos/artifacts/release-0.2.0/smoke-report.json`
- `/tmp/superqode-0.2.0-release-contracts.log`
- `/tmp/superqode-0.2.0-production-notarize.log`
- `/tmp/superqode-0.2.0-notary-app.json` and `-notary-dmg.json`
- `/tmp/superqode-0.2.0-godaddy-upload.log`
- `/tmp/superqode-2.30.0-pypi.json`
- `/tmp/superqode-2.30.0-public-install.log` and `-public-help.log`
- `/tmp/superqode-web-0.2.0-build-final.log`
- `/tmp/superqode-0.2.0-live-website.html`
