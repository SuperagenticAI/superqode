"""Portable exports contain editable declared sources, never live runtime state."""
# ruff: noqa: F401, F811

import hashlib
import json
from pathlib import Path
import zipfile

from click.testing import CliRunner
import pytest

from test_factory_definition import project, rewrite
from test_factory_studio import studio
from superqode.commands.factory import factory
from superqode.factory import portable
from superqode.factory.definition import load_factory
from superqode.factory.snapshot import resolve_factory


def test_export_reproduces_snapshot_from_plain_files_on_another_root(project, tmp_path):
    private = project / ".superqode/workorders/private-session.json"
    private.parent.mkdir()
    private.write_text('{"secret": "must-not-export-runtime"}')
    review = portable.preview(project)
    assert not (project / ".superqode/factory-operations").exists()
    package = portable.create(project, expected=review["snapshot_digest"])
    content = Path(package["path"]).read_bytes()
    assert package["sha256"] == "sha256:" + hashlib.sha256(content).hexdigest()
    target = tmp_path / "moved-project"
    target.mkdir()
    with zipfile.ZipFile(package["path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert not manifest["requires_desktop_app"]
        assert manifest["external_platforms"] == {
            "adapter_required": True,
            "execution_verified": False,
        }
        for name, record in manifest["entries"].items():
            raw = archive.read(name)
            assert hashlib.sha256(raw).hexdigest() == record["sha256"][7:]
            if name.startswith("factory/"):
                path = target / name.removeprefix("factory/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        assert b"must-not-export-runtime" not in content
        assert "application" in archive.read("README.md").decode()
    assert resolve_factory(load_factory(root=target)).digest == review["snapshot_digest"]
    assert not package["execution_started"] and not package["release_authorized"]


def test_export_rejects_stale_sources_and_sensitive_components(project):
    review = portable.preview(project)
    rewrite(project, lambda d: d["metadata"].update(name="changed"))
    with pytest.raises(ValueError, match="changed"):
        portable.create(project, expected=review["snapshot_digest"])
    secret = project / "private.key"
    secret.write_text("secret")
    rewrite(
        project,
        lambda d: d["data_context"].update(
            files={"bad": {"path": "private.key", "purpose": "context"}}
        ),
    )
    with pytest.raises(ValueError, match="Sensitive"):
        portable.preview(project)


def test_cli_and_native_export_require_review_and_never_start_jobs(studio):
    rpc, root, service = studio
    before = service._all("select id from jobs")
    review = rpc("export.preview")
    with pytest.raises(ValueError, match="Confirm"):
        rpc("export.create", digest=review["snapshot_digest"])
    result = rpc("export.create", digest=review["snapshot_digest"], confirmed=True)
    assert Path(result["path"]).is_file()
    assert service._all("select id from jobs") == before
    cli = CliRunner().invoke(factory, ["export", "--project", str(root)])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.output)["manifest"]["snapshot_digest"] == review["snapshot_digest"]
