#!/usr/bin/env bash
set -euo pipefail

# 1. Get the project root directory
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 2. Determine platform and arch
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux) PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    *) echo "Unsupported OS: $OS"; exit 1 ;;
esac

case "$ARCH" in
    x86_64) ARCH_TAG="x86_64" ;;
    aarch64|arm64) ARCH_TAG="arm64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

# 3. Build the binary (One-Dir mode via updated spec)
echo "Building binary in One-Dir mode..."
scripts/build_binary.sh

# 4. Package the result
BINARY_NAME="superqode"
VERSION=$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])")
ARCHIVE_NAME="${BINARY_NAME}-${VERSION}-${PLATFORM}-${ARCH_TAG}.tar.gz"
RELEASE_DIR="release_builds"

echo "Packaging release: ${ARCHIVE_NAME}..."
mkdir -p "$RELEASE_DIR"

# Create a clean staging directory
STAGING_DIR=$(mktemp -d)
trap 'rm -rf -- "$STAGING_DIR"' EXIT

# Copy the application directory (from dist/superqode)
cp -r "dist/${BINARY_NAME}" "$STAGING_DIR/"

# Copy the scripts directory
cp -r "scripts" "$STAGING_DIR/${BINARY_NAME}/"

# Create the final archive
(
  cd "$STAGING_DIR"
  tar -czf "$ROOT_DIR/$RELEASE_DIR/$ARCHIVE_NAME" "${BINARY_NAME}"
)

echo "✅ Successfully packaged release build:"
echo "   $RELEASE_DIR/$ARCHIVE_NAME"
