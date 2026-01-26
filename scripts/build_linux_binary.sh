#!/usr/bin/env bash
set -euo pipefail

# This script is intended to be run on a Linux machine (e.g., via CI/CD or Docker)
# to build the Linux binary of SuperQode.

echo "Building SuperQode Linux Binary..."

# Ensure dependencies
python -m pip install --upgrade pip
python -m pip install -e . pyinstaller pyinstaller-hooks-contrib

# Build with PyInstaller
# Note: --clean helps avoid cache issues across OS builds
pyinstaller --clean -y superqode.spec

echo "Build complete."
echo "Binary location: dist/superqode"

# Package for distribution
ARCH="$(uname -m)"
PLATFORM="linux-${ARCH}"
ARCHIVE_NAME="superqode-${PLATFORM}.tar.gz"

echo "Packaging ${ARCHIVE_NAME}..."
tar -C dist -czf "${ARCHIVE_NAME}" superqode

echo "Artifact ready: ${ARCHIVE_NAME}"
