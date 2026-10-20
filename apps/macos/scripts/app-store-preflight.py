"""Validate brand assets; report real App Store blockers without asserting readiness."""

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--assets-only", action="store_true")
args = parser.parse_args()
errors = []


def png(path, expected, opaque=False):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != expected:
        errors.append("Invalid PNG dimensions: " + str(path.relative_to(APP)))
    if opaque and data[25] != 2:
        errors.append("App icon is not opaque RGB: " + str(path.relative_to(APP)))


catalog = APP / "resources/Assets.xcassets/AppIcon.appiconset"
images = json.loads((catalog / "Contents.json").read_text())["images"]
if len(images) != 10:
    errors.append("Expected ten macOS icon slots")
for item in images:
    logical = int(item["size"].split("x")[0])
    scale = int(item["scale"][0])
    png(catalog / item["filename"], (logical * scale,) * 2)
png(APP / "app-store/branding/SuperQode-1024.png", (1024, 1024), opaque=True)
manifest = json.loads((APP / "app-store/branding/manifest.json").read_text())
if (
    hashlib.sha256((ROOT / manifest["source"]).read_bytes()).hexdigest()
    != manifest["source_sha256"]
):
    errors.append("Brand asset source changed; regenerate the icons")
report = {
    "brand_assets": "passed" if not errors else "failed",
    "icon_slots": len(images),
    "source": manifest["source"],
    "errors": errors,
}
if not args.assets_only:
    bundle = APP / "release/SuperQode.app"
    entitlements = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(bundle)], capture_output=True
    ).stdout
    try:
        sandbox = plistlib.loads(entitlements).get("com.apple.security.app-sandbox") is True
    except (ValueError, plistlib.InvalidFileException):
        sandbox = False
    report.update(
        {
            "submission_ready": False,
            "sandbox_enabled": sandbox,
            "blockers": [
                "Sandboxed repository access, bookmarks, Python/helper inheritance and agent process behavior have not been validated.",
                "App Store distribution/installer identities, provisioning, a signed archive and upload validation are missing.",
                "Real reviewed screenshots at Apple-supported Mac dimensions are not prepared; diagnostic renders are not submission screenshots.",
                "App privacy, third-party SDK disclosures, export compliance, age rating, support/privacy URLs and App Review instructions require owner review.",
                "Terminal feature coverage and real-vendor ACP connection validation remain incomplete.",
            ],
            "screenshot_sizes": [[1280, 800], [1440, 900], [2560, 1600], [2880, 1800]],
        }
    )
print(json.dumps(report, indent=2))
raise SystemExit(1 if errors or not args.assets_only else 0)
