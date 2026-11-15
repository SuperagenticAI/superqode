#!/bin/bash
set -euo pipefail

package="$(cd "$(dirname "$0")" && pwd)"
scratch="${1:-"$package/.build"}"
mkdir -p "$scratch"
scratch="$(cd "$scratch" && pwd)"
metal="$(xcrun --find metal)"
metallib="$(xcrun --find metallib)"
sdk="$(xcrun --sdk macosx --show-sdk-path)"
args=(--package-path "$package" --scratch-path "$scratch" --build-system native --force-resolved-versions -c "${2:-debug}")
swift build "${args[@]}" >&2
binary_dir="$(swift build "${args[@]}" --show-bin-path)"

# The native SwiftPM build compiles MLX's C++ but skips its Metal resources.
# Use the Xcode-selected compiler, including an installed Metal component.
sources="$scratch/checkouts/mlx-swift/Source/Cmlx/mlx-generated/metal"
stage="$(mktemp -d "$scratch/metal.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
objects=()
while IFS= read -r -d '' source; do
    object="$stage/${#objects[@]}.air"
    "$metal" -c -target air64-apple-macos14.0 -isysroot "$sdk" \
        -fmetal-math-mode=fast -fmetal-math-fp32-functions=fast -Wno-c++17-extensions \
        "$source" -o "$object"
    objects+=("$object")
done < <(find "$sources" -type f -name '*.metal' -print0)

if [ "${#objects[@]}" -eq 0 ]; then
    echo "No generated Metal shaders found in the pinned MLX checkout." >&2
    exit 1
fi
"$metallib" "${objects[@]}" -o "$stage/mlx.metallib"
mv -f "$stage/mlx.metallib" "$binary_dir/mlx.metallib"
printf '%s\n' "$binary_dir/SuperQodeSwiftMLX"
