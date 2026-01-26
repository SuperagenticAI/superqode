#!/bin/bash
set -euo pipefail

echo "🐳 Building Docker image for Linux build..."
docker build -f scripts/Dockerfile.linux_build -t superqode-builder .

echo "📦 Running Linux build in container..."
# Ensure release_builds exists on host
mkdir -p release_builds

# Run the build.
# We mount the release_builds directory to the container's release_builds directory
# so the final artifact is written directly to the host.
docker run --rm \
    -v "$(pwd)/release_builds:/app/release_builds" \
    superqode-builder

echo "✅ Linux build complete. Artifacts in release_builds/ directory."
ls -lh release_builds/superqode-*-linux-*.tar.gz
