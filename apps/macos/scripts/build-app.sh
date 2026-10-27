#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
export CLANG_MODULE_CACHE_PATH="$APP_DIR/.build/ModuleCache"
export SWIFTPM_MODULECACHE_OVERRIDE="$CLANG_MODULE_CACHE_PATH"
export PYTHONDONTWRITEBYTECODE=1
if [ -d /Applications/Xcode.app/Contents/Developer ]; then
    export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
fi
SWIFT="$(xcrun --find swift)"
CONFIGURATION="${CONFIGURATION:-release}"
SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
"$SWIFT" build --build-system native --sdk "$SDK_PATH" --package-path "$APP_DIR" --scratch-path "$APP_DIR/.build" --disable-sandbox -c "$CONFIGURATION"
BINARY_DIR="$("$SWIFT" build --build-system native --sdk "$SDK_PATH" --package-path "$APP_DIR" --scratch-path "$APP_DIR/.build" --disable-sandbox -c "$CONFIGURATION" --show-bin-path)"
DEST="${SUPERQODE_APP_DESTINATION:-$APP_DIR/release/SuperQode.app}"
if [ ! -x "$APP_DIR/runtime/python/bin/python3" ]; then
    echo 'Missing engine payload. See apps/macos/README.md for runtime setup.' >&2
    exit 1
fi
mkdir -p "$DEST/Contents/MacOS" "$DEST/Contents/Resources"
# Publish a new executable inode so running previews retain their mapped binary.
cp "$BINARY_DIR/SuperQode" "$DEST/Contents/MacOS/SuperQode.next"
mv -f "$DEST/Contents/MacOS/SuperQode.next" "$DEST/Contents/MacOS/SuperQode"
cp "$APP_DIR/resources/Info.plist" "$DEST/Contents/Info.plist"
# SwiftPM dependency resources (including the native terminal renderer).
for RESOURCE_BUNDLE in "$BINARY_DIR"/*.bundle; do
    [ -d "$RESOURCE_BUNDLE" ] || continue
    ditto "$RESOURCE_BUNDLE" "$DEST/Contents/Resources/$(basename "$RESOURCE_BUNDLE")"
done
if [ -f "$APP_DIR/THIRD-PARTY-NOTICES.txt" ]; then cp "$APP_DIR/THIRD-PARTY-NOTICES.txt" "$DEST/Contents/Resources/"; fi
if [ -f "$APP_DIR/resources/icon.icns" ]; then cp "$APP_DIR/resources/icon.icns" "$DEST/Contents/Resources/icon.icns"; fi
if [ -d "$APP_DIR/resources/Assets.xcassets" ]; then
    xcrun actool "$APP_DIR/resources/Assets.xcassets" --compile "$DEST/Contents/Resources" --platform macosx --minimum-deployment-target 14.0 --app-icon AppIcon --output-partial-info-plist "$APP_DIR/.build/AppIcon-Info.plist" --target-device mac
fi
# ditto preserves executable bits, symlinks and native library metadata.
rm -rf "$DEST/Contents/Resources/runtime"
ditto "$APP_DIR/runtime" "$DEST/Contents/Resources/runtime"
# Refresh the engine source, including desktop protocol, without altering dependency locks.
rm -rf "$DEST/Contents/Resources/runtime/backend/superqode"
ditto "$ROOT_DIR/src/superqode" "$DEST/Contents/Resources/runtime/backend/superqode"
find "$DEST/Contents/Resources/runtime" -type d -name __pycache__ -prune -exec rm -rf {} +
# Apply the hash-locked security fixes to every packaged runtime, including when
# the local base payload predates these versions.
RUNTIME_PYTHON="$DEST/Contents/Resources/runtime/python/bin/python3"
RUNTIME_SITE="$("$RUNTIME_PYTHON" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
uv pip install --python "$RUNTIME_PYTHON" --target "$RUNTIME_SITE" --require-hashes --no-deps -r "$APP_DIR/runtime-requirements.txt"
"$RUNTIME_PYTHON" "$APP_DIR/scripts/check-runtime-dependencies.py"
python3 "$APP_DIR/scripts/stamp-runtime.py" "$DEST/Contents/Resources/runtime"
python3 "$APP_DIR/scripts/collect-runtime-notices.py" "$DEST/Contents/Resources/runtime"
IDENTITY="${SIGNING_IDENTITY:--}"
python3 "$APP_DIR/scripts/sign-bundle.py" "$DEST" --identity "$IDENTITY"
echo "$DEST"
