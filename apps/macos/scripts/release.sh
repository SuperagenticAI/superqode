#!/bin/bash
# Build, sign, notarize, staple and verify a shareable SuperQode DMG, then
# write its SHA-256 checksum. Run on an Apple Silicon Mac from any directory.
#
# One-time setup (secrets stay in Keychain, never in this repository):
#   security find-identity -v -p codesigning
#   xcrun notarytool store-credentials superqode-notary --apple-id YOU --team-id TEAMID
#
# Settings come from the environment, or from MACOS_SIGNING_IDENTITY and
# MACOS_NOTARY_PROFILE lines in ~/.env.macos-release (read as plain KEY=value,
# never executed):
#   SIGNING_IDENTITY  "Developer ID Application: Name (TEAMID)"
#   NOTARY_PROFILE    Keychain profile from notarytool (default superqode-notary)
#   SKIP_ENGINE=1     reuse the existing engine payload instead of rebuilding it
#   UPLOAD=1          also publish to superqode.dev with upload-release.py
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
CONFIG="${SUPERQODE_MACOS_RELEASE_CONFIG:-$HOME/.env.macos-release}"

config_value() {
    [ -f "$CONFIG" ] || return 0
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONFIG" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

step() { printf '\n==> %s\n' "$*"; }

SIGNING_IDENTITY="${SIGNING_IDENTITY:-$(config_value MACOS_SIGNING_IDENTITY)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-$(config_value MACOS_NOTARY_PROFILE)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-superqode-notary}"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "Run this on an Apple Silicon Mac." >&2; exit 1
fi
if [ -z "$SIGNING_IDENTITY" ] || [ "$SIGNING_IDENTITY" = "-" ]; then
    echo 'Set SIGNING_IDENTITY="Developer ID Application: Name (TEAMID)".' >&2
    echo 'List identities with: security find-identity -v -p codesigning' >&2
    exit 1
fi
case "$SIGNING_IDENTITY" in
    "Developer ID Application:"*) ;;
    *) echo "A Developer ID Application identity is required for a shareable DMG." >&2; exit 1 ;;
esac
if ! security find-identity -v -p codesigning | grep -Fq "$SIGNING_IDENTITY"; then
    echo "Signing identity not found in Keychain: $SIGNING_IDENTITY" >&2; exit 1
fi
if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
    echo "Notary profile '$NOTARY_PROFILE' is missing or invalid. Create it with:" >&2
    echo "  xcrun notarytool store-credentials $NOTARY_PROFILE --apple-id YOU --team-id TEAMID" >&2
    exit 1
fi

VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_DIR/resources/Info.plist")
BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP_DIR/resources/Info.plist")
DMG="$APP_DIR/release/SuperQode-$VERSION-arm64.dmg"
echo "SuperQode $VERSION ($BUILD) from $(git -C "$ROOT_DIR" rev-parse --short HEAD)"
if [ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=no)" ]; then
    echo "Warning: the repository has uncommitted changes that will be included."
fi

cd "$ROOT_DIR"
if [ "${SKIP_ENGINE:-0}" != "1" ]; then
    step "Building the engine payload"
    UV_PROJECT_ENVIRONMENT=apps/macos/.build-venv uv sync --frozen --no-dev --no-editable --python 3.13
    python3 apps/macos/scripts/bundle-runtime.py
fi
python3 apps/macos/scripts/make-icon.py

step "Building and signing SuperQode.app"
SIGNING_IDENTITY="$SIGNING_IDENTITY" "$APP_DIR/scripts/build-app.sh"
codesign --verify --deep --strict "$APP_DIR/release/SuperQode.app"

step "Packaging the DMG"
rm -f "$DMG" "$DMG.sha256"
"$APP_DIR/scripts/package-distribution.sh"
[ -f "$DMG" ] || { echo "Expected $DMG" >&2; exit 1; }

step "Signing the DMG"
codesign --force --sign "$SIGNING_IDENTITY" --timestamp "$DMG"

step "Notarizing (usually a few minutes)"
SUBMIT_LOG="$(mktemp)"
trap 'rm -f "$SUBMIT_LOG"' EXIT
xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait | tee "$SUBMIT_LOG"
if ! grep -q "status: Accepted" "$SUBMIT_LOG"; then
    ID=$(sed -n 's/^[[:space:]]*id: //p' "$SUBMIT_LOG" | head -n 1)
    echo "Notarization was not accepted. Details:" >&2
    [ -n "$ID" ] && xcrun notarytool log "$ID" --keychain-profile "$NOTARY_PROFILE" >&2
    exit 1
fi

step "Stapling and verifying"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
codesign --verify --strict "$DMG"
spctl --assess --type open --context context:primary-signature -v "$DMG"

step "Writing the checksum"
( cd "$(dirname "$DMG")" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256" )
cat "$DMG.sha256"

if [ "${UPLOAD:-0}" = "1" ]; then
    step "Publishing to superqode.dev"
    python3 "$APP_DIR/scripts/upload-release.py" --upload "$DMG"
fi

printf '\nReady to share:\n  %s\n  %s\n' "$DMG" "$DMG.sha256"
