#!/bin/bash
set -euo pipefail

echo "🐳 Building Docker image for Linux build..."
# Dockerfile is now in scripts/
docker build -f scripts/Dockerfile.linux_build -t superqode-builder .

echo "📦 Running Linux build in container..."
# Run container, mapping the current directory to /app/output (or similar) to extract artifacts?
# Actually, better to map the whole repo so we can write the output file back to host.
# But Dockerfile copies files in. So we need to map a volume to get the artifact out.

# We'll map the current directory to /app/dist_host so the script can copy the final tarball there.
# Modifying build_linux_binary.sh to support an output directory argument would be cleaner,
# but for now we'll just run the script and then copy the artifact out.

# Let's create a dist directory on host if it doesn't exist
mkdir -p dist

echo "Starting build container..."
# Run the build script
# We mount the current directory to /output to retrieve the artifact
docker run --rm -v "$(pwd):/output" superqode-builder bash -c "./scripts/build_linux_binary.sh && cp *.tar.gz /output/"

echo "✅ Linux build complete. Artifacts in current directory."
ls -lh superqode-linux-*.tar.gz
