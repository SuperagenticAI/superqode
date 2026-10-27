"""Check GoDaddy FTPS access, or publish an already notarized macOS DMG.

Default operation is read-only. Credentials come from outside the repository or
environment variables; they are never interpreted as shell commands or printed.
"""

import argparse
import ftplib
import hashlib
import io
import os
from pathlib import Path
import plistlib
import re
import ssl
import subprocess
import sys
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[3]
PUBLIC = "https://superqode.dev/downloads/macos"
DEFAULT_CONFIG = Path.home() / ".env.macos-release"
CONFIG_FIELDS = (
    "FTP_HOST",
    "FTP_USER",
    "FTP_PASSWORD",
    "FTP_REMOTE_DIR",
    "FTP_PORT",
    "MACOS_SIGNING_IDENTITY",
    "MACOS_NOTARY_PROFILE",
)


def load_config(path=None, *, environ=None):
    environ = os.environ if environ is None else environ
    config = {}
    selected = path or environ.get("SUPERQODE_MACOS_RELEASE_CONFIG")
    path = Path(selected).expanduser() if selected else DEFAULT_CONFIG
    if selected or path.exists():
        if path.stat().st_mode & 0o077:
            raise ValueError(f"Restrict credential file access first: chmod 600 {path}")
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator:
                raise ValueError("Each configuration line must use KEY=value")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            config[key.strip()] = value
    for key in CONFIG_FIELDS:
        if key in environ:
            config[key] = environ[key]
    for key in ("FTP_HOST", "FTP_USER", "FTP_PASSWORD", "FTP_REMOTE_DIR"):
        if not config.get(key):
            raise ValueError(f"Missing configuration field: {key}")
        if "\r" in config[key] or "\n" in config[key]:
            raise ValueError(f"Invalid newline in {key}")
    if "://" in config["FTP_HOST"]:
        raise ValueError("FTP_HOST must be a hostname, without ftp:// or a path")
    if config["FTP_REMOTE_DIR"].rstrip("/").split("/")[-1] != "macos":
        raise ValueError("FTP_REMOTE_DIR must point to the macos folder, not latest")
    return config


def automatic_dmg(root=ROOT):
    """Use the source release metadata, never file modification times."""
    app_dir = root / "apps/macos"
    info = plistlib.loads((app_dir / "resources/Info.plist").read_bytes())
    version = info["CFBundleShortVersionString"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Source app version must use X.Y.Z")
    dmg = app_dir / "release" / f"SuperQode-{version}-arm64.dmg"
    if not dmg.is_file():
        raise ValueError(f"No DMG for source version {version}; build and notarize it first")
    packaged = app_dir / "release/SuperQode.app/Contents/Info.plist"
    if packaged.exists():
        actual = plistlib.loads(packaged.read_bytes())
        for field in ("CFBundleShortVersionString", "CFBundleVersion"):
            if actual.get(field) != info.get(field):
                raise ValueError(
                    "Packaged app metadata differs from source; rebuild before uploading"
                )
    return dmg


def validate_dmg(dmg):
    env = dict(os.environ)
    env.setdefault("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")
    for command in (
        ["codesign", "--verify", "--strict", str(dmg)],
        ["xcrun", "stapler", "validate", str(dmg)],
        ["spctl", "--assess", "--type", "open", "--context", "context:primary-signature", str(dmg)],
    ):
        subprocess.run(command, check=True, env=env)


def connect(config):
    ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=60)
    try:
        ftp.connect(config["FTP_HOST"], int(config.get("FTP_PORT", "21")))
        ftp.login(config["FTP_USER"], config["FTP_PASSWORD"])
        ftp.prot_p()
        ftp.cwd(config["FTP_REMOTE_DIR"])
        return ftp
    except BaseException:
        ftp.close()
        raise


def read_remote(ftp, name):
    output = io.BytesIO()

    def append(chunk):
        if output.tell() + len(chunk) > 16384:
            raise ValueError("Remote checksum file unexpectedly exceeds 16 KB")
        output.write(chunk)

    ftp.retrbinary(f"RETR {name}", append)
    return output.getvalue()


def checksum_line(digest, filename):
    return f"{digest}  {filename}\n".encode()


def check_destination(ftp):
    base = ftp.pwd()
    print(f"Connected using encrypted FTPS. Remote directory: {base}")
    ftp.cwd("latest")
    names = {name.rsplit("/", 1)[-1] for name in ftp.nlst()}
    required = {"SuperQode-arm64.dmg", "SuperQode-arm64.dmg.sha256"}
    if not required.issubset(names):
        raise ValueError("Destination does not contain the expected latest release files")
    checksum = read_remote(ftp, "SuperQode-arm64.dmg.sha256").decode().strip()
    if not re.fullmatch(r"[a-fA-F0-9]{64}\s+\*?SuperQode-arm64\.dmg", checksum):
        raise ValueError("Existing latest checksum has an unexpected format or filename")
    print(f"Found latest DMG and checksum: {checksum}")
    ftp.cwd(base)


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_and_promote(ftp, dmg, filename, digest):
    """Finish both transfers and verify remote bytes before replacing live names."""
    token = uuid.uuid4().hex
    temporary = f".{filename}.{token}.upload"
    checksum_name = f"{filename}.sha256"
    temporary_checksum = f".{checksum_name}.{token}.upload"
    try:
        with dmg.open("rb") as stream:
            ftp.storbinary(f"STOR {temporary}", stream, blocksize=1024 * 1024)
        remote_digest = hashlib.sha256()
        ftp.retrbinary(f"RETR {temporary}", remote_digest.update, blocksize=1024 * 1024)
        if remote_digest.hexdigest() != digest:
            raise ValueError("Uploaded DMG hash mismatch; live release files were not replaced")
        ftp.storbinary(f"STOR {temporary_checksum}", io.BytesIO(checksum_line(digest, filename)))
        if read_remote(ftp, temporary_checksum) != checksum_line(digest, filename):
            raise ValueError("Uploaded checksum mismatch; live release files were not replaced")
        ftp.rename(temporary, filename)
        ftp.rename(temporary_checksum, checksum_name)
    finally:
        for name in (temporary, temporary_checksum):
            try:
                ftp.delete(name)
            except ftplib.error_perm:
                pass


def publish(ftp, dmg, version, digest):
    base = ftp.pwd()
    filename = dmg.name
    names = {name.rsplit("/", 1)[-1] for name in ftp.nlst()}
    if version not in names:
        ftp.mkd(version)
    ftp.cwd(version)
    names = {name.rsplit("/", 1)[-1] for name in ftp.nlst()}
    if filename in names or f"{filename}.sha256" in names:
        actual = hashlib.sha256()
        ftp.retrbinary(f"RETR {filename}", actual.update, blocksize=1024 * 1024)
        if actual.hexdigest() != digest or read_remote(ftp, f"{filename}.sha256") != checksum_line(
            digest, filename
        ):
            raise ValueError(
                "Versioned release already exists with different content; refusing overwrite"
            )
        print(f"Versioned release {version} already matches; preserving it")
    else:
        stage_and_promote(ftp, dmg, filename, digest)
        print(f"Uploaded versioned release {version}")
    ftp.cwd(base)
    ftp.cwd("latest")
    stage_and_promote(ftp, dmg, "SuperQode-arm64.dmg", digest)
    print("Published latest DMG and checksum")
    ftp.cwd(base)


def verify_public(version, digest):
    for directory, filename in (
        (version, f"SuperQode-{version}-arm64.dmg"),
        ("latest", "SuperQode-arm64.dmg"),
    ):
        url = f"{PUBLIC}/{directory}/{filename}"
        for suffix in (".sha256", ""):
            request = urllib.request.Request(
                f"{url}{suffix}?verify={uuid.uuid4().hex}",
                headers={"Cache-Control": "no-cache"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                if suffix:
                    if response.read(16385).strip() != checksum_line(digest, filename).strip():
                        raise ValueError(f"Public checksum mismatch: {url}.sha256")
                else:
                    actual = hashlib.sha256()
                    while chunk := response.read(1024 * 1024):
                        actual.update(chunk)
                    if actual.hexdigest() != digest:
                        raise ValueError(f"Public DMG mismatch: {url}")
        print(f"Verified public DMG and checksum: {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="External credentials file (environment overrides file)"
    )
    parser.add_argument(
        "--upload",
        nargs="?",
        const="auto",
        metavar="NOTARIZED_DMG",
        help="Upload the current app version automatically, or specify a DMG explicitly",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    version = digest = None
    if args.upload:
        dmg = automatic_dmg() if args.upload == "auto" else Path(args.upload).expanduser().resolve()
        match = re.fullmatch(r"SuperQode-(\d+\.\d+\.\d+)-arm64\.dmg", dmg.name)
        if not match:
            raise ValueError("Expected SuperQode-X.Y.Z-arm64.dmg")
        version = match.group(1)
        print(f"Selected release: {dmg.name}")
        validate_dmg(dmg)
        digest = file_digest(dmg)
    with connect(config) as ftp:
        check_destination(ftp)
        if args.upload:
            publish(ftp, dmg, version, digest)
    if args.upload:
        verify_public(version, digest)
    else:
        print("Read-only connection check passed. No files changed on the server.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Server messages can echo account details. Keep credentials out of logs.
        if isinstance(error, ValueError):
            print(f"Error: {error}", file=sys.stderr)
        else:
            print(
                f"Release operation failed ({type(error).__name__}). No credentials logged.",
                file=sys.stderr,
            )
        sys.exit(1)
