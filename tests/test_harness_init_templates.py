"""`superqode harness init --template` accepts every registry template."""

import pytest
import yaml
from click.testing import CliRunner

from superqode.commands.harness import HARNESS_TEMPLATE_CHOICES, harness
from superqode.harness.templates import BUILTIN_TEMPLATES


def test_cli_choices_cover_every_registry_template():
    public = {name for name in BUILTIN_TEMPLATES if "_" not in name}
    assert set(HARNESS_TEMPLATE_CHOICES) == public
    assert "codegem" in HARNESS_TEMPLATE_CHOICES


@pytest.mark.parametrize("template", sorted(BUILTIN_TEMPLATES))
def test_init_accepts_registry_template(template, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        harness, ["init", "demo", "--template", template, "--output", "h.yaml", "--minimal"]
    )
    if "_" in template:
        assert result.exit_code != 0
        return
    assert result.exit_code == 0, result.output
    assert yaml.safe_load((tmp_path / "h.yaml").read_text())["inherits"] == template


def test_init_codegem_writes_a_full_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        harness, ["init", "my-codegem", "--template", "codegem", "--output", "codegem.yaml"]
    )
    assert result.exit_code == 0, result.output
    spec = yaml.safe_load((tmp_path / "codegem.yaml").read_text())
    assert spec["name"] == "my-codegem"
    assert spec["runtime"]["backend"] == "codegem"
