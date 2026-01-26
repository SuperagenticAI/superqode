#!/bin/bash
set -e

# Configuration
VERSION="0.1.4"
APP_NAME="superqode"
INSTALL_LIB_DIR="$HOME/.local/lib/${APP_NAME}"
INSTALL_BIN_DIR="$HOME/.local/bin"

# Detect OS and Architecture
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

ARCHIVE_NAME="${APP_NAME}-${VERSION}-${PLATFORM}-${ARCH_TAG}.tar.gz"
DOWNLOAD_URL="https://github.com/SuperagenticAI/superqode/releases/download/v${VERSION}/${ARCHIVE_NAME}"

# --- Installation Logic ---

echo "Detected platform: ${PLATFORM}-${ARCH_TAG}"

# Create temp directory
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

# Check if archive exists locally (for testing) or download it
if [ -f "release_builds/${ARCHIVE_NAME}" ]; then
    echo "Using local archive for installation..."
    cp "release_builds/${ARCHIVE_NAME}" "${TMP_DIR}/"
else
    echo "Downloading from: ${DOWNLOAD_URL}"
    curl -fsSL "$DOWNLOAD_URL" -o "${TMP_DIR}/${ARCHIVE_NAME}"
fi

# Extract
echo "Extracting..."
tar -xzf "${TMP_DIR}/${ARCHIVE_NAME}" -C "$TMP_DIR"

# Install
echo "Installing to ${INSTALL_LIB_DIR}..."
rm -rf "$INSTALL_LIB_DIR"
mkdir -p "$(dirname "$INSTALL_LIB_DIR")"
mv "${TMP_DIR}/${APP_NAME}" "$INSTALL_LIB_DIR"

# Create symlink
echo "Creating symlink in ${INSTALL_BIN_DIR}..."
mkdir -p "$INSTALL_BIN_DIR"
ln -sf "${INSTALL_LIB_DIR}/${APP_NAME}" "${INSTALL_BIN_DIR}/${APP_NAME}"

# Verify PATH
if [[ ":$PATH:" != ".*:${INSTALL_BIN_DIR}:"* ]]; then
    echo ""
    echo "⚠️  Warning: ${INSTALL_BIN_DIR} is not in your PATH."
    echo "Add it to your shell config (e.g., ~/.bashrc or ~/.zshrc):"
    echo "  export PATH=\"
.local/bin:$PATH\""
    echo ""
fi

# Verify installation
if command -v "$APP_NAME" >/dev/null; then
    echo "✅ Successfully installed $($APP_NAME --version)"
    echo "Run '$APP_NAME' to get started!"
else
    # Check if we can run it via absolute path
    if [ -x "${INSTALL_BIN_DIR}/${APP_NAME}" ]; then
        echo "✅ Successfully installed to ${INSTALL_BIN_DIR}/${APP_NAME}"
        echo "Note: You need to add ${INSTALL_BIN_DIR} to your PATH."
    else
        echo "❌ Installation failed."
        exit 1
    fi
fi
