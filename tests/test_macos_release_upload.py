import importlib.util
import io
from pathlib import Path
import plistlib

import pytest


SCRIPT = Path(__file__).parents[1] / "apps/macos/scripts/upload-release.py"
SPEC = importlib.util.spec_from_file_location("macos_upload", SCRIPT)
upload = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upload)


def test_credentials_are_literal_and_private(tmp_path):
    config = tmp_path / ".env"
    config.write_text(
        'FTP_HOST=example.com\nFTP_USER=user\nFTP_PASSWORD="a$#=b"\n'
        "FTP_REMOTE_DIR=/downloads/macos\n"
    )
    config.chmod(0o644)
    with pytest.raises(ValueError, match="chmod 600"):
        upload.load_config(config)
    config.chmod(0o600)
    assert upload.load_config(config)["FTP_PASSWORD"] == "a$#=b"


@pytest.mark.parametrize("directory", ["/downloads/macos/latest", "/", "/public_html"])
def test_wrong_release_root_is_rejected(tmp_path, directory):
    config = tmp_path / ".env"
    config.write_text(
        f"FTP_HOST=example.com\nFTP_USER=user\nFTP_PASSWORD=password\nFTP_REMOTE_DIR={directory}\n"
    )
    config.chmod(0o600)
    with pytest.raises(ValueError, match="macos folder"):
        upload.load_config(config)


class FakeFTP:
    def __init__(self, corrupt=False):
        self.files = {"SuperQode-arm64.dmg": b"previous release"}
        self.corrupt = corrupt
        self.events = []

    def storbinary(self, command, stream, **kwargs):
        name = command.removeprefix("STOR ")
        self.files[name] = stream.read()
        self.events.append(("store", name))

    def retrbinary(self, command, callback, **kwargs):
        name = command.removeprefix("RETR ")
        callback(b"corrupt" if self.corrupt else self.files[name])

    def rename(self, source, target):
        self.files[target] = self.files.pop(source)
        self.events.append(("rename", target))

    def delete(self, name):
        if name in self.files:
            del self.files[name]
        else:
            raise upload.ftplib.error_perm("550 missing")


def test_corrupt_transfer_does_not_replace_live_release(tmp_path):
    dmg = tmp_path / "release.dmg"
    dmg.write_bytes(b"release")
    ftp = FakeFTP(corrupt=True)
    with pytest.raises(ValueError, match="hash mismatch"):
        upload.stage_and_promote(ftp, dmg, "SuperQode-arm64.dmg", upload.file_digest(dmg))
    assert ftp.files == {"SuperQode-arm64.dmg": b"previous release"}
    assert not any(event[0] == "rename" for event in ftp.events)


def test_both_files_are_staged_before_live_names_change(tmp_path):
    dmg = tmp_path / "release.dmg"
    dmg.write_bytes(b"release")
    digest = upload.file_digest(dmg)
    ftp = FakeFTP()
    upload.stage_and_promote(ftp, dmg, "SuperQode-arm64.dmg", digest)
    assert [kind for kind, _ in ftp.events] == ["store", "store", "rename", "rename"]
    assert ftp.files == {
        "SuperQode-arm64.dmg": b"release",
        "SuperQode-arm64.dmg.sha256": upload.checksum_line(digest, "SuperQode-arm64.dmg"),
    }


def test_oversized_remote_checksum_is_rejected():
    class FTP:
        def retrbinary(self, command, callback):
            callback(io.BytesIO(b"x" * 16385).read())

    with pytest.raises(ValueError, match="16 KB"):
        upload.read_remote(FTP(), "checksum")


def test_environment_only_credentials_do_not_need_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(upload, "DEFAULT_CONFIG", tmp_path / "missing")
    env = {
        "FTP_HOST": "example.com",
        "FTP_USER": "user",
        "FTP_PASSWORD": "a$#=b",
        "FTP_REMOTE_DIR": "/downloads/macos",
    }
    assert upload.load_config(environ=env) == env


def test_environment_overrides_private_file(tmp_path):
    config = tmp_path / ".env"
    config.write_text(
        "FTP_HOST=example.com\nFTP_USER=user\nFTP_PASSWORD=old\nFTP_REMOTE_DIR=/downloads/macos\n"
    )
    config.chmod(0o600)
    assert upload.load_config(config, environ={"FTP_PASSWORD": "new"})["FTP_PASSWORD"] == "new"


def test_repository_credentials_are_not_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(upload, "DEFAULT_CONFIG", tmp_path / "home-config-missing")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.macos-release").write_text("FTP_PASSWORD=must-not-load\n")
    with pytest.raises(ValueError, match="Missing configuration field"):
        upload.load_config(environ={})


def test_automatic_version_uses_source_metadata_not_newer_archive(tmp_path):
    app = tmp_path / "apps/macos"
    (app / "resources").mkdir(parents=True)
    (app / "release").mkdir()
    info = {"CFBundleShortVersionString": "0.1.11", "CFBundleVersion": "12"}
    (app / "resources/Info.plist").write_bytes(plistlib.dumps(info))
    expected = app / "release/SuperQode-0.1.11-arm64.dmg"
    expected.write_bytes(b"current")
    (app / "release/SuperQode-9.0.0-arm64.dmg").write_bytes(b"unrelated")
    assert upload.automatic_dmg(tmp_path) == expected
    expected.unlink()
    with pytest.raises(ValueError, match="No DMG for source version"):
        upload.automatic_dmg(tmp_path)


def test_automatic_version_rejects_stale_packaged_app(tmp_path):
    app = tmp_path / "apps/macos"
    (app / "resources").mkdir(parents=True)
    contents = app / "release/SuperQode.app/Contents"
    contents.mkdir(parents=True)
    (app / "resources/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleShortVersionString": "0.1.11",
                "CFBundleVersion": "12",
            }
        )
    )
    (app / "release/SuperQode-0.1.11-arm64.dmg").write_bytes(b"current")
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleShortVersionString": "0.1.11",
                "CFBundleVersion": "11",
            }
        )
    )
    with pytest.raises(ValueError, match="Packaged app metadata differs"):
        upload.automatic_dmg(tmp_path)
