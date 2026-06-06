"""Tests for plugin manifest loading."""

import json

from superqode.plugins import (
    disable_plugin,
    enable_plugin,
    install_plugin,
    load_plugins,
    validate_plugin_manifest,
)


def test_load_project_plugin_manifest(tmp_path):
    plugin_dir = tmp_path / ".superqode" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    manifest = plugin_dir / "plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "tools": [{"name": "demo_tool"}],
                "commands": [{"name": "demo"}],
                "skills": ["skills/review.md"],
            }
        ),
        encoding="utf-8",
    )

    plugins = load_plugins(tmp_path)

    assert len(plugins) == 1
    assert plugins[0].id == "demo"
    assert plugins[0].tools[0]["name"] == "demo_tool"


def test_validate_plugin_manifest_reports_invalid_json(tmp_path):
    manifest = tmp_path / "plugin.json"
    manifest.write_text("{bad", encoding="utf-8")

    issues = validate_plugin_manifest(manifest)

    assert issues


def test_install_plugin_and_enable_disable_state(tmp_path):
    source = tmp_path / "source-plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo Plugin", "version": "1.0.0"}),
        encoding="utf-8",
    )

    installed = install_plugin(source, tmp_path)
    assert installed.id == "demo"
    assert (tmp_path / ".superqode" / "plugins" / "demo" / "plugin.json").exists()
    assert [plugin.id for plugin in load_plugins(tmp_path)] == ["demo"]

    assert disable_plugin("demo", tmp_path) is True
    assert load_plugins(tmp_path) == []
    assert [plugin.id for plugin in load_plugins(tmp_path, include_disabled=True)] == ["demo"]

    assert enable_plugin("demo", tmp_path) is True
    assert [plugin.id for plugin in load_plugins(tmp_path)] == ["demo"]


def test_validate_plugin_manifest_reports_missing_referenced_file(tmp_path):
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo Plugin",
                "commands": [{"name": "demo", "path": "missing.py"}],
            }
        ),
        encoding="utf-8",
    )

    issues = validate_plugin_manifest(manifest)

    assert "commands[0].path points to a missing file: missing.py" in issues
