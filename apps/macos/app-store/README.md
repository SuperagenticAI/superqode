# Mac App Store submission preparation

**Status: brand assets prepared; application is not upload-ready.** The current DMG/ZIP is a direct-distribution native preview. Do not submit it as a sandboxed App Store build.

## Existing SuperQode branding

The asset generator uses the repository's `assets/superqode-logo.svg` without redesigning it. It renders the vector separately at each size, rather than enlarging the 800px raster logo. Generated assets include:

- `resources/Assets.xcassets/AppIcon.appiconset`: all ten standard Mac slots, 16/32/128/256/512 points at 1x and 2x, through 1024 pixels.
- `resources/Assets.xcassets/BrandMark.imageset`: transparent native in-app marks, also used in the sidebar.
- `resources/icon.icns`: Finder/Dock compatibility icon with a transparent rounded silhouette.
- `app-store/branding/SuperQode-1024.png`: opaque RGB 1024px preview of the glossy macOS tile.
- `app-store/branding/SuperQode-Dock.png`: transparent 1024px master for the rounded glass tile, coloured lighting and original gradient mark.
- `app-store/branding/manifest.json`: original SVG hash and output dimensions.

Regenerate with `python3 apps/macos/scripts/make-icon.py`. Validate with `python3 apps/macos/scripts/app-store-preflight.py --assets-only`. Apple describes icon delivery in its [app icon instructions](https://developer.apple.com/help/app-store-connect/manage-app-information/add-an-app-icon).

## App Store path is a separate release gate

The current app runs as a normal Mac application. Apple requires Mac App Store applications to use App Sandbox, self-contained installation and appropriate process behavior. Its additional-code rules also need assessment for pluggable runtimes and external coding agents. This is an architectural compatibility gap, not something that an icon or signing flag resolves. See [App Review Guidelines 2.4.5 and 2.5.2](https://developer.apple.com/app-store/review/guidelines/) and [App Sandbox configuration](https://help.apple.com/xcode/mac/current/en.lproj/devbd04af149.html).

Before creating a submission archive:

1. Prototype sandboxed access to user-selected repositories with persisted security-scoped bookmarks. Confirm access survives restart and works through the bundled Python engine and tools.
2. Sign and test the app and all bundled executable helpers with the appropriate sandbox/inheritance configuration. Validate Keychain access under the final application identity.
3. Establish which ACP/SDK/CLI/local-runtime routes can operate within that distribution model. The current external agent launcher is not verified as App Store compatible. Do not add an undisclosed helper to evade sandbox or review restrictions.
4. Use a real Xcode application archive/export workflow, the App Store distribution and installer identities, provisioning and the correct App Store Connect bundle record. Developer ID notarization is the separate direct-download path.
5. Complete privacy and third-party SDK review, license notices, encryption/export answers, age rating, support/privacy URLs and reviewer instructions. Do not invent these owner-specific declarations.
6. Finish the [terminal feature coverage audit](../FEATURE-COVERAGE.md), real-vendor authentication and coding tests, accessibility and clean-Mac validation.

`python3 apps/macos/scripts/app-store-preflight.py` checks local assets and reports blockers with a nonzero exit status. It never reports the current preview as submission-ready.

## Screenshots

Apple currently accepts Mac screenshots at 1280×800, 1440×900, 2560×1600 or 2880×1800, all 16:10. Capture the real shipped application at one of those sizes. Prepare coding with tool activity, changes/approval, Harness Hub, evaluation comparison and optimization review. Remove private project data and credentials. See [Apple screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications).

No fabricated marketing screenshots are included. The PNGs under the ignored `artifacts/` directory are diagnostic view renders with known AppKit material limitations, not reviewed App Store screenshots. Check current [submission requirements](https://developer.apple.com/app-store/submitting/) again at release time.
