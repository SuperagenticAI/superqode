#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAP_DIR="${TAP_DIR:-/tmp/homebrew-superqode}"
FORMULA_PATH="${TAP_DIR}/Formula/superqode.rb"

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

if [[ ! -d "${TAP_DIR}" ]]; then
  echo "Tap repo not found at ${TAP_DIR}."
  echo "Clone it first, e.g.:"
  echo "  git clone https://github.com/SuperagenticAI/homebrew-superqode ${TAP_DIR}"
  exit 1
fi

if [[ ! -f "${FORMULA_PATH}" ]]; then
  echo "Formula not found at ${FORMULA_PATH}."
  exit 1
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "Building binary..."
  "${ROOT_DIR}/scripts/build_binary.sh"
fi

ARCHIVE_NAME="superqode-${PLATFORM}.tar.gz"
ARCHIVE_PATH="${ROOT_DIR}/${ARCHIVE_NAME}"

echo "Packaging ${ARCHIVE_NAME}..."
tar -C "${ROOT_DIR}/dist" -czf "${ARCHIVE_PATH}" superqode

SHA256="$(shasum -a 256 "${ARCHIVE_PATH}" | awk '{print $1}')"
ARCHIVE_URL="file://${ARCHIVE_PATH}"

TMP_FORMULA="/tmp/superqode-local.rb"
cat > "${TMP_FORMULA}" <<EOF
class Superqode < Formula
  desc "SuperQode CLI"
  homepage "https://github.com/SuperagenticAI/superqode"
  version "0.0.0-local"
  url "${ARCHIVE_URL}"
  sha256 "${SHA256}"

  def install
    bin.install "superqode"
  end

  test do
    system "\#{bin}/superqode", "--help"
  end
end
EOF

echo "Installing from local formula..."
brew install --formula "${TMP_FORMULA}"

echo "Running brew test..."
brew test superqode

echo "Checking version..."
superqode --version || true

echo "Uninstalling..."
brew uninstall superqode

echo "Local Homebrew test complete."
