"""Sign all embedded native code inside out, including code under Resources.

No credentials are read by this script. The identity's private key stays in Keychain.
No sandbox, library-validation or executable-memory exceptions are granted.
"""

import argparse
import hashlib
from pathlib import Path
import plistlib
import subprocess


MACH_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def native_files(app):
    result = []
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) in MACH_MAGICS:
                    result.append(path)
    return sorted(result, key=lambda p: (-len(p.parts), str(p)))


def sign(app, identity):
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    identifier = info["CFBundleIdentifier"]
    options = ["--force", "--sign", identity]
    if identity != "-":
        if not identity.startswith("Developer ID Application:"):
            raise ValueError("Use a Developer ID Application identity, or '-' for a local preview")
        options += ["--options", "runtime", "--timestamp"]
    native = native_files(app)
    # Give loose Python executables/libraries stable identifiers rather than their
    # basename alone. Bundle containers are subsequently sealed inside out.
    for path in native:
        suffix = hashlib.sha256(str(path.relative_to(app)).encode()).hexdigest()[:24]
        subprocess.run(
            ["codesign", *options, "--identifier", f"{identifier}.code.{suffix}", str(path)],
            check=True,
        )
    bundles = [
        p
        for p in app.rglob("*")
        if p.is_dir()
        and not p.is_symlink()
        and p.suffix in {".app", ".framework", ".xpc", ".appex", ".bundle"}
        and any(p in n.parents for n in native)
    ]
    for path in sorted(bundles, key=lambda p: (-len(p.parts), str(p))):
        subprocess.run(["codesign", *options, str(path)], check=True)
    subprocess.run(["codesign", *options, str(app)], check=True)
    for path in [*native, app]:
        subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    print(f"Verified {len(native)} native files and the outer bundle")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--identity", default="-")
    args = parser.parse_args()
    sign(args.app.resolve(), args.identity)
