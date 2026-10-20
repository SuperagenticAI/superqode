"""Generate native Mac branding from the existing repository SVG."""

from pathlib import Path
import os
import subprocess

app = Path(__file__).resolve().parents[1]
env = dict(os.environ)
if Path("/Applications/Xcode.app").exists():
    env.setdefault("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")
env["CLANG_MODULE_CACHE_PATH"] = str(app / ".build/ModuleCache")
subprocess.run(
    ["xcrun", "swift", str(app / "scripts/export-brand-assets.swift"), str(app)],
    env=env,
    check=True,
)
subprocess.run(
    [
        "iconutil",
        "-c",
        "icns",
        str(app / "resources/icon.iconset"),
        "-o",
        str(app / "resources/icon.icns"),
    ],
    check=True,
)
