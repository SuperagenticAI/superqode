"""Tests for plugin manifest loading."""

import json

from superqode.plugins import load_plugins, validate_plugin_manifest


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
