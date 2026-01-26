#!/usr/bin/env bash
set -euo pipefail

# This script is intended to be run on a Linux machine (e.g., via CI/CD or Docker)
# to build the Linux binary of SuperQode in One-Dir mode.

echo "Building SuperQode Linux Binary..."

# 1. Get the project root directory
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 2. Ensure dependencies
python -m pip install --upgrade pip
python -m pip install -e . pyinstaller pyinstaller-hooks-contrib toml

# 3. Build with PyInstaller (using the updated .spec which is now One-Dir)
pyinstaller --clean -y superqode.spec

# 4. Package for distribution
BINARY_NAME="superqode"
VERSION=$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])")
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) ARCH_TAG="x86_64" ;;
    aarch64|arm64) ARCH_TAG="arm64" ;;
    *) ARCH_TAG="$ARCH" ;;
esac

ARCHIVE_NAME="${BINARY_NAME}-${VERSION}-linux-${ARCH_TAG}.tar.gz"
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

echo "✅ Linux build complete."
echo "Artifact ready: $RELEASE_DIR/$ARCHIVE_NAME"
