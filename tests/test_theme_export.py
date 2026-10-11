"""Exports can be consumed independently and preserve existing files."""

from dataclasses import replace
import json
from pathlib import Path

from click.testing import CliRunner
from jsonschema import Draft202012Validator
import pytest

from superqode import design_system as ds
from superqode.app.appearance import AppearancePreferences, appearance_document
from superqode.main import cli_main
from superqode.theming import load_theme_file, native_document, palette_tokens, theme_from_document
from superqode.theming.export import native_export_document, pi_document, pi_compatibility


@pytest.mark.parametrize("name", ["superqode", "light", "nord", "system"])
def test_native_and_pi_exports_round_trip_semantic_roles(name):
    theme = ds.get_theme(name)
    native = native_export_document(theme)
    assert native["$schema"].endswith("/schema.json")
    assert palette_tokens(theme_from_document(native)) == palette_tokens(theme)
    pi = pi_document(theme)
    restored = palette_tokens(theme_from_document(pi))
    for role in (
        "purple",
        "text",
        "user_text",
        "diff_add",
        "syntax_keyword",
        "thinking_max",
        "scrollbar_thumb",
        "export_bg",
    ):
        assert restored[role] == palette_tokens(theme)[role]
    assert pi["name"] != "system"


def test_pi_compatibility_reports_omitted_extensions():
    theme = replace(ds.get_theme("superqode"), extensions={"plugin_custom": "#123456"})
    report = pi_compatibility(theme)
    assert report["valid"] and report["omitted_extension_colors"] == ["plugin_custom"]
    assert "plugin_custom" not in pi_document(theme)["colors"]
    assert native_document(theme)["extensions"] == {"plugin_custom": "#123456"}


def test_appearance_export_validates_against_bundled_schema():
    path = Path(__file__).parents[1] / "src/superqode/data/themes/appearance.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    document = appearance_document(
        AppearancePreferences(cursor="steady", mouse="off"), "light/nord"
    )
    Draft202012Validator(schema).validate(document)
    assert AppearancePreferences.from_dict(document["appearance"]).cursor == "steady"
    assert AppearancePreferences.from_dict(document["appearance"]).mouse == "off"


@pytest.mark.parametrize("format_name", ["superqode", "pi"])
def test_cli_theme_export_and_compatibility_never_overwrite(tmp_path, format_name):
    path = tmp_path / "portable.json"
    result = CliRunner().invoke(
        cli_main, ["theme", "export", "superqode", str(path), "--format", format_name]
    )
    assert result.exit_code == 0, result.output
    exported = load_theme_file(path)
    assert palette_tokens(exported)["purple"] == palette_tokens(ds.get_theme("superqode"))["purple"]
    previous = path.read_bytes()
    result = CliRunner().invoke(
        cli_main, ["theme", "export", "light", str(path), "--format", format_name]
    )
    assert result.exit_code != 0
    assert path.read_bytes() == previous
    result = CliRunner().invoke(cli_main, ["theme", "compatibility", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["valid"]


def test_schema_files_are_not_discovered_as_theme_palettes():
    from superqode.app.theme_bridge import discover_themes

    assert not any("appearance.schema" in error for error in discover_themes())
