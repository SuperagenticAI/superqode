#!/bin/bash
set -e

# Configuration
# Binaries are hosted on GitHub Releases
VERSION="v0.1.3"
BASE_URL="https://github.com/SuperagenticAI/superqode/releases/download/${VERSION}"
BINARY_NAME="superqode"
INSTALL_DIR="/usr/local/bin"

# Detect OS and Architecture
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        PLATFORM="linux"
        ;;
    Darwin)
        PLATFORM="macos"
        ;;
    *)
        echo "Unsupported operating system: $OS"
        exit 1
        ;;
esac

case "$ARCH" in
    x86_64)
        ARCH_TAG="x86_64"
        ;;
    aarch64|arm64)
        ARCH_TAG="arm64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

ASSET_NAME="${BINARY_NAME}-${PLATFORM}-${ARCH_TAG}.tar.gz"
DOWNLOAD_URL="${BASE_URL}/${ASSET_NAME}"

echo "Detected platform: ${PLATFORM}-${ARCH_TAG}"
echo "Downloading from: ${DOWNLOAD_URL}"

# Create temp directory
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

# Download
curl -fsSL "$DOWNLOAD_URL" -o "${TMP_DIR}/${ASSET_NAME}"

# Extract
echo "Extracting..."
tar -xzf "${TMP_DIR}/${ASSET_NAME}" -C "$TMP_DIR"

# Install
echo "Installing to ${INSTALL_DIR}..."
if [ -w "$INSTALL_DIR" ]; then
    mv "${TMP_DIR}/${BINARY_NAME}" "${INSTALL_DIR}/${BINARY_NAME}"
else
    echo "Sudo required to install to ${INSTALL_DIR}"
    sudo mv "${TMP_DIR}/${BINARY_NAME}" "${INSTALL_DIR}/${BINARY_NAME}"
fi

# Verify
if command -v "$BINARY_NAME" >/dev/null; then
    echo "✅ Successfully installed $("$BINARY_NAME" --version)"
    echo "Run '$BINARY_NAME' to get started!"
else
    echo "❌ Installation failed."
    exit 1
fi
