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
cp "$BINARY_DIR/SuperQodeAppleModel" "$DEST/Contents/MacOS/SuperQodeAppleModel.next"
mv -f "$DEST/Contents/MacOS/SuperQodeAppleModel.next" "$DEST/Contents/MacOS/SuperQodeAppleModel"
cp "$APP_DIR/resources/Info.plist" "$DEST/Contents/Info.plist"
# SwiftPM dependency resources (including the native terminal renderer).
for RESOURCE_BUNDLE in "$BINARY_DIR"/*.bundle; do
    [ -d "$RESOURCE_BUNDLE" ] || continue
    ditto "$RESOURCE_BUNDLE" "$DEST/Contents/Resources/$(basename "$RESOURCE_BUNDLE")"
done
if [ -f "$APP_DIR/THIRD-PARTY-NOTICES.txt" ]; then cp "$APP_DIR/THIRD-PARTY-NOTICES.txt" "$DEST/Contents/Resources/"; fi
cp "$APP_DIR/resources/ACP-REGISTRY-LICENSE.txt" "$DEST/Contents/Resources/"
cp "$APP_DIR/resources/agent-icons-provenance.json" "$DEST/Contents/Resources/"
cp "$APP_DIR/resources/PROVIDER-ICONS-LICENSE.txt" "$DEST/Contents/Resources/"
cp "$APP_DIR/resources/provider-icons-provenance.json" "$DEST/Contents/Resources/"
if [ -f "$APP_DIR/resources/icon.icns" ]; then cp "$APP_DIR/resources/icon.icns" "$DEST/Contents/Resources/icon.icns"; fi
rm -rf "$DEST/Contents/Resources/swift-mlx"
if [ "${SUPERQODE_INCLUDE_SWIFT_MLX:-0}" = "1" ]; then
    MLX_SCRATCH="${SUPERQODE_SWIFT_MLX_SCRATCH:-$APP_DIR/.build/swift-mlx}"
    MLX_HELPER="$(bash "$APP_DIR/SwiftMLX/build.sh" "$MLX_SCRATCH" "$CONFIGURATION")"
    MLX_DEST="$DEST/Contents/Resources/swift-mlx"
    mkdir -p "$MLX_DEST"
    cp "$MLX_HELPER" "$(dirname "$MLX_HELPER")/mlx.metallib" "$MLX_DEST/"
    for checkout in "$MLX_SCRATCH"/checkouts/*; do
        for notice in "$checkout"/LICENSE* "$checkout"/NOTICE*; do
            [ -f "$notice" ] || continue
            cp "$notice" "$MLX_DEST/$(basename "$checkout")-$(basename "$notice")"
        done
    done
    for dependency in mlx mlx-c metal-cpp fmt json; do
        for notice in "$MLX_SCRATCH"/checkouts/mlx-swift/Source/Cmlx/"$dependency"/LICENSE*; do
            [ -f "$notice" ] || continue
            cp "$notice" "$MLX_DEST/$dependency-$(basename "$notice")"
        done
    done
fi
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
# uv --target installs wheel scripts under site-packages/bin. Monty searches
# the bundled interpreter's scripts directory for its signed worker.
"$RUNTIME_PYTHON" - <<'PY'
import os
from pathlib import Path
import sysconfig

worker = Path(sysconfig.get_path("purelib")) / "bin" / "monty"
launcher = Path(sysconfig.get_path("scripts")) / "monty"
if not worker.is_file():
    raise SystemExit("The bundled Monty worker is missing.")
launcher.unlink(missing_ok=True)
launcher.symlink_to(os.path.relpath(worker, launcher.parent))
PY
"$RUNTIME_PYTHON" "$APP_DIR/scripts/check-runtime-dependencies.py"
# Source and distribution metadata must agree even with an older base payload.
python3 "$APP_DIR/scripts/refresh-engine-metadata.py" "$DEST/Contents/Resources/runtime"
python3 "$APP_DIR/scripts/stamp-runtime.py" "$DEST/Contents/Resources/runtime"
python3 "$APP_DIR/scripts/collect-runtime-notices.py" "$DEST/Contents/Resources/runtime"
IDENTITY="${SIGNING_IDENTITY:--}"
python3 "$APP_DIR/scripts/sign-bundle.py" "$DEST" --identity "$IDENTITY"
"$RUNTIME_PYTHON" - <<'PY'
from pydantic_monty import Monty

with Monty() as pool, pool.checkout() as session:
    if session.feed_run("20 + 22") != 42:
        raise SystemExit("The bundled Monty worker did not execute the smoke check.")
PY
echo "$DEST"
