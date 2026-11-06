#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Build a local signed iOS archive. This does not upload or publish an app.

Usage: archive.sh --team APPLETEAMID [--bundle-id dev.superqode.companion]
                  [--output /path/to/SuperQode.xcarchive] [--allow-provisioning]

Add your Apple Developer account in Xcode Settings > Accounts first.
Team ID is a non-secret 10-character identifier. Never pass passwords or private keys.
--allow-provisioning explicitly lets Xcode contact Apple to create/update signing profiles.
Without it, configure the profile once in Xcode Signing & Capabilities.
HELP
}

team=""
bundle="dev.superqode.companion"
root=$(cd "$(dirname "$0")/.." && pwd)
output="$root/build/SuperQode.xcarchive"
provisioning=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --team) team="${2:?Provide a Team ID}"; shift 2 ;;
    --bundle-id) bundle="${2:?Provide a bundle identifier}"; shift 2 ;;
    --output) output="${2:?Provide an archive path}"; shift 2 ;;
    --allow-provisioning) provisioning=(-allowProvisioningUpdates); shift ;;
    *) usage; exit 2 ;;
  esac
done
if [[ ! "$team" =~ ^[A-Z0-9]{10}$ ]]; then
  usage
  exit 2
fi
if [[ ! "$bundle" =~ ^[A-Za-z][A-Za-z0-9.-]+$ || "$output" != *.xcarchive ]]; then
  echo "Choose a valid bundle identifier and an output ending in .xcarchive." >&2
  exit 2
fi
if ! command -v xcodebuild >/dev/null; then
  echo "Install Xcode on your Mac and select its command-line tools before archiving." >&2
  exit 2
fi
if [[ -e "$output" ]]; then
  echo "The archive already exists. Choose another --output path; existing archives are preserved." >&2
  exit 2
fi
mkdir -p "$(dirname "$output")"
xcodebuild archive -project "$root/SuperQodeCompanion.xcodeproj" \
  -scheme SuperQodeCompanion -configuration Release -destination 'generic/platform=iOS' \
  -archivePath "$output" DEVELOPMENT_TEAM="$team" PRODUCT_BUNDLE_IDENTIFIER="$bundle" \
  CODE_SIGN_STYLE=Automatic "${provisioning[@]}"
echo "Archive created: $output"
echo "Open it in Xcode Organizer to validate and choose distribution when you are ready."
