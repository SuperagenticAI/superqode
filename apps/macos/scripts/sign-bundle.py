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


def prune_framework_build_inputs(app):
    # Standalone Python includes Tcl/Tk stub archives and linker configuration
    # scripts for building extensions. They are build inputs, not runtime code,
    # and codesign rejects them outside a framework's Resources. Keep runtime
    # executables, shared libraries and resources, including their notices.
    frameworks = app / "Contents/Resources/runtime/python/Frameworks"
    for framework in frameworks.glob("*.framework"):
        if framework.is_symlink():
            continue
        for pattern in ("*.a", "*Config.sh"):
            for path in framework.rglob(pattern):
                if path.is_symlink() or path.is_file():
                    path.unlink()


def framework_executables(framework):
    result = set()
    manifests = [framework / "Resources/Info.plist"]
    manifests.extend(framework.glob("Versions/*/Resources/Info.plist"))
    for manifest in manifests:
        if manifest.is_file():
            info = plistlib.loads(manifest.read_bytes())
            executable = info.get("CFBundleExecutable")
            if executable:
                result.add((manifest.parent.parent / executable).resolve())
    return result


def sign(app, identity):
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    identifier = info["CFBundleIdentifier"]
    options = ["--force", "--sign", identity]
    if identity != "-":
        if not identity.startswith("Developer ID Application:"):
            raise ValueError("Use a Developer ID Application identity, or '-' for a local preview")
        options += ["--options", "runtime", "--timestamp"]
    prune_framework_build_inputs(app)
    native = native_files(app)
    bundles = [
        p
        for p in app.rglob("*")
        if p.is_dir()
        and not p.is_symlink()
        and p.suffix in {".app", ".framework", ".xpc", ".appex", ".bundle"}
        and any(p in n.parents for n in native)
    ]
    # python-build-standalone also ships a framework-style Python prefix whose
    # directory is named "python", not "Python.framework". Signing its Python
    # library seals that prefix. Seal it after its embedded Tcl/Tk frameworks.
    runtime_python = app / "Contents/Resources/runtime/python"
    if (runtime_python / "Resources/Info.plist").is_file():
        bundles.append(runtime_python)
    framework_mains = set()
    for bundle in bundles:
        if bundle.suffix == ".framework" or bundle == runtime_python:
            framework_mains.update(framework_executables(bundle))
    # Give loose Python executables/libraries stable identifiers rather than their
    # basename alone. Bundle containers are subsequently sealed inside out.
    for path in native:
        # Signing a framework's executable seals its enclosing framework too.
        # Defer it until all nested code has been signed.
        if path.resolve() in framework_mains:
            continue
        suffix = hashlib.sha256(str(path.relative_to(app)).encode()).hexdigest()[:24]
        subprocess.run(
            ["codesign", *options, "--identifier", f"{identifier}.code.{suffix}", str(path)],
            check=True,
        )
    for path in sorted(bundles, key=lambda p: (-len(p.parts), str(p))):
        subprocess.run(["codesign", *options, str(path)], check=True)
    subprocess.run(["codesign", *options, str(app)], check=True)
    for path in [*native, app]:
        subprocess.run(["codesign", "--verify", "--strict", "--verbose=4", str(path)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    print(f"Verified {len(native)} native files and the outer bundle")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--identity", default="-")
    args = parser.parse_args()
    sign(args.app.resolve(), args.identity)
