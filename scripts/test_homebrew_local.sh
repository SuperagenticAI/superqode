#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script currently supports macOS only."
  exit 1
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  arm64) PLATFORM="macos-arm64" ;;
  x86_64) PLATFORM="macos-x86_64" ;;
  *)
    echo "Unsupported architecture: ${ARCH}"
    exit 1
    ;;
esac

# 1. Build Binary
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "Building binary..."
  "${ROOT_DIR}/scripts/build_binary.sh"
fi

# 2. Package
ARCHIVE_NAME="superqode-${PLATFORM}.tar.gz"
ARCHIVE_PATH="${ROOT_DIR}/${ARCHIVE_NAME}"

echo "Packaging ${ARCHIVE_NAME}..."
tar -C "${ROOT_DIR}/dist" -czf "${ARCHIVE_PATH}" superqode

SHA256="$(shasum -a 256 "${ARCHIVE_PATH}" | awk '{print $1}')"
ARCHIVE_URL="file://${ARCHIVE_PATH}"

# 3. Create Local Tap
TAP_NAME="superqode-local/test"
echo "Creating local tap ${TAP_NAME}..."
brew tap-new "${TAP_NAME}" --no-git || true

TAP_DIR="$(brew --repo "${TAP_NAME}")"
FORMULA_PATH="${TAP_DIR}/Formula/superqode.rb"

# 4. Generate Formula
echo "Generating formula at ${FORMULA_PATH}..."
cat > "${FORMULA_PATH}" <<EOF
class Superqode < Formula
  desc "SuperQode CLI (Local Test)"
  homepage "https://github.com/SuperagenticAI/superqode"
  version "0.0.0-local"
  url "${ARCHIVE_URL}"
  sha256 "${SHA256}"

  def install
    bin.install "superqode"
  end

  test do
    system "\#{bin}/superqode", "--version"
  end
end
EOF

# 5. Install & Test
echo "Installing superqode from local tap..."
# Uninstall if exists to ensure clean install
brew uninstall superqode || true
brew install "${TAP_NAME}/superqode"

echo "Running brew test..."
brew test "${TAP_NAME}/superqode"

echo "Verifying installation..."
if command -v superqode >/dev/null; then
    VERSION=$(superqode --version)
    echo "✅ Successfully installed: ${VERSION}"
else
    echo "❌ Installation failed: superqode command not found"
    exit 1
fi

# 6. Cleanup
echo "Cleaning up..."
brew uninstall superqode
brew untap "${TAP_NAME}"
rm "${ARCHIVE_PATH}"

echo "🎉 Local Homebrew test passed!"