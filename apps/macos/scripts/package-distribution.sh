#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="$APP_DIR/release/SuperQode.app"
VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")
ARCH="$(uname -m)"
codesign --verify --deep --strict "$APP"
STAGING="$(mktemp -d /tmp/superqode-dmg.XXXXXX)"
trap 'rm -rf "$STAGING"' EXIT
ditto "$APP" "$STAGING/SuperQode.app"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname SuperQode -srcfolder "$STAGING" -ov -format UDZO "$APP_DIR/release/SuperQode-$VERSION-$ARCH.dmg"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$APP_DIR/release/SuperQode-$VERSION-$ARCH.zip"
echo 'Archives created. Public distribution still requires Developer ID signing and notarization.'
