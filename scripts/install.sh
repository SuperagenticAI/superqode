#!/bin/bash
set -e

# Configuration
VERSION="0.1.5"
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

# --- UI Helpers ---

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Spinner helper
show_spinner() {
  local pid=$!
  local delay=0.1
  local spinstr='|/-\'
  while kill -0 $pid 2>/dev/null; do
    local temp=${spinstr#?}
    printf " [%c]  " "$spinstr"
    spinstr=$temp${spinstr%"$temp"}
    sleep $delay
    printf "\b\b\b\b\b\b"
  done
  # Wait for the background process to finish and get its exit code
  wait $pid
  return $?
}

echo -e "${BLUE}🚀 Starting SuperQode Installation...${NC}"
echo -e "Detected platform: ${YELLOW}${PLATFORM}-${ARCH_TAG}${NC}"

# Create temp directory
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

# --- Installation Logic ---

# Check if archive exists locally (for testing) or download it
if [ -f "release_builds/${ARCHIVE_NAME}" ]; then
    echo -e "Using local archive for installation..."
    cp "release_builds/${ARCHIVE_NAME}" "${TMP_DIR}/"
else
    printf "Downloading SuperQode v${VERSION}..."
    curl -fsSL "$DOWNLOAD_URL" -o "${TMP_DIR}/${ARCHIVE_NAME}" &
    if show_spinner; then
        echo -e " ${GREEN}Done!${NC}"
    else
        echo -e " ${RED}Failed! (HTTP 404 or connection issue)${NC}"
        echo -e "Please verify that the file exists at: ${DOWNLOAD_URL}"
        exit 1
    fi
fi

# Extract
printf "Extracting application files..."
tar -xzf "${TMP_DIR}/${ARCHIVE_NAME}" -C "$TMP_DIR" &
if show_spinner; then
    echo -e " ${GREEN}Done!${NC}"
else
    echo -e " ${RED}Failed!${NC}"
    exit 1
fi

# Install
printf "Installing to ${INSTALL_LIB_DIR}...";
rm -rf "$INSTALL_LIB_DIR"
mkdir -p "$(dirname "$INSTALL_LIB_DIR")"
mv "${TMP_DIR}/${APP_NAME}" "$INSTALL_LIB_DIR"
echo -e " ${GREEN}Done!${NC}"

# Create symlink
printf "Creating binary symlink..."
mkdir -p "$INSTALL_BIN_DIR"
ln -sf "${INSTALL_LIB_DIR}/${APP_NAME}" "${INSTALL_BIN_DIR}/${APP_NAME}"
echo -e " ${GREEN}Done!${NC}"

# Verify PATH
if [[ ":$PATH:" != *":${INSTALL_BIN_DIR}:"* ]]; then
    echo -e ""
    echo -e "${YELLOW}⚠️  Warning: ${INSTALL_BIN_DIR} is not in your PATH.${NC}"
    echo -e "Add it to your shell config (e.g., ~/.zshrc):"
    echo -e "  ${BLUE}export PATH=\"${INSTALL_BIN_DIR}:\$PATH\"${NC}"
    echo -e ""
fi

# Verify installation
# Temporarily add to path for verification
export PATH="${INSTALL_BIN_DIR}:$PATH"
VERSION_OUT=$($APP_NAME --version 2>/dev/null || echo "")

if [ -n "$VERSION_OUT" ]; then
    echo -e "${GREEN}✅ Successfully installed $VERSION_OUT${NC}"
    echo -e "Run '${BLUE}${APP_NAME}${NC}' to get started!"
else
    if [ -x "${INSTALL_BIN_DIR}/${APP_NAME}" ]; then
        echo -e "${GREEN}✅ Successfully installed to ${INSTALL_BIN_DIR}/${APP_NAME}${NC}"
        echo -e "Note: You may need to restart your terminal or add ${INSTALL_BIN_DIR} to your PATH."
    else
        echo -e "${RED}❌ Installation failed.${NC}"
        exit 1
    fi
fi
